from __future__ import annotations

import base64
import json
import urllib.parse

import pytest
from fastapi.testclient import TestClient
from test_ncre_office import judge_answers

from agentbench.api import create_app
from agentbench.catalog import (
    GAUNTLET_SUITE_ID,
    MOCK_MODEL_ID,
    NCRE_OFFICE_SUITE_ID,
    QODER_RUNNER_ID,
    SMOKE_SUITE_ID,
    UNIFIED_RUNNER_ID,
    build_catalog,
    stable_id,
)
from agentbench.ncre_assets import blobs
from agentbench.service import EvaluationService

SUITE_CASE_PREVIEW_KEYS = {
    "id",
    "slug",
    "title",
    "description",
    "category",
    "difficulty",
    "estimated_minutes",
    "requires_docker",
    "instruction",
}


def test_health_and_catalog_api(settings):
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["version"] == "4.1.1"
        cases = client.get("/api/v1/test-cases").json()
        # 214 existing cases plus the two built-in 2025 Math I tracks
        # (22 questions each). The API must expose the bundled paper without
        # requiring a user-side PDF import.
        assert len(cases) == 258
        assert {item["difficulty"] for item in cases} == {1, 2, 3, 4, 5, 6}
        assert any(item["requires_docker"] for item in cases)
        assert any(item["requires_judge"] for item in cases)
        status = client.get("/api/v1/system/status").json()
        assert status["database"]["ready"] is True
        assert isinstance(status["docker"]["available"], bool)


def test_private_ultra_validator_is_not_exposed_by_api(settings):
    with TestClient(create_app(settings)) as client:
        ultra = next(
            item
            for item in client.get("/api/v1/test-cases").json()
            if item["slug"] == "ultra.event-store-crash-consistency-003"
        )
        definition = client.get(f"/api/v1/test-cases/{ultra['id']}").json()["definition"]
        command = next(
            item for item in definition["validators"] if item["type"] == "command_metrics"
        )
        assert command["config"]["private"] is True
        assert command["config"]["command"] == "<AgentBench private validator>"
        assert "private_files" not in command["config"]
        assert "demo_actions" not in definition["metadata"]


def test_qoder_runner_supports_verified_quick_install(settings):
    with TestClient(create_app(settings)) as client:
        runners = client.get("/api/v1/runners").json()
        qoder = next(item for item in runners if item["id"] == QODER_RUNNER_ID)
        assert qoder["executable"] == "qoderclicn"
        assert "--print" in qoder["args"]
        assert "--dangerously-skip-permissions" in qoder["args"]
        assert "{prompt}" in qoder["args"]
        assert qoder["install"]["supported"] is True
        assert qoder["install"]["command"] == "npm install -g @qodercn-ai/qoderclicn"


def test_windows_tauri_origin_is_allowed(settings):
    with TestClient(create_app(settings)) as client:
        response = client.options(
            "/api/v1/dashboard",
            headers={
                "Origin": "http://tauri.localhost",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_yaml_test_dsl_import(settings):
    document = """
slug: custom.yaml-001
version: 1.0.0
category: instruction-following
title: YAML import
instruction: Return OK
validators:
  - type: exact_match
    weight: 90
    config:
      expected: OK
"""
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/test-cases/import",
            content=document.encode("utf-8"),
            headers={"Content-Type": "text/yaml"},
        )
        assert response.status_code == 201
        assert response.json()["slug"] == "custom.yaml-001"


def test_model_delete_archives_referenced_models_and_restore(settings):
    payload = {
        "name": "Disposable model",
        "provider": "codex-cli",
        "model_name": "gpt-test",
        "api_style": "openai",
    }
    with TestClient(create_app(settings)) as client:
        unused = client.post("/api/v1/models", json=payload).json()
        deleted = client.delete(f"/api/v1/models/{unused['id']}")
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True, "action": "deleted", "run_references": 0}

        referenced = client.post(
            "/api/v1/models", json={**payload, "name": "Historical model"}
        ).json()
        client.patch(
            "/api/v1/settings",
            json={"judge_model_id": referenced["id"], "judge_runner_id": UNIFIED_RUNNER_ID},
        )
        experiment = client.post(
            "/api/v1/experiments",
            json={
                "name": "Reference holder",
                "suite_id": SMOKE_SUITE_ID,
                "participants": [
                    {"model_id": referenced["id"], "runner_id": UNIFIED_RUNNER_ID}
                ],
                "repetitions": 1,
                "concurrency": 1,
            },
        )
        assert experiment.status_code == 201

        archived = client.delete(f"/api/v1/models/{referenced['id']}")
        assert archived.status_code == 200
        assert archived.json()["action"] == "archived"
        assert archived.json()["run_references"] == 12
        assert referenced["id"] not in {
            model["id"] for model in client.get("/api/v1/models").json()
        }
        archived_models = client.get(
            "/api/v1/models", params={"include_archived": True}
        ).json()
        archived_model = next(model for model in archived_models if model["id"] == referenced["id"])
        assert archived_model["enabled"] is False
        assert client.get("/api/v1/system/status").json()["settings"]["judge_model_id"] is None

        restored = client.patch(
            f"/api/v1/models/{referenced['id']}", json={"enabled": True}
        )
        assert restored.status_code == 200
        assert restored.json()["enabled"] is True
        assert referenced["id"] in {
            model["id"] for model in client.get("/api/v1/models").json()
        }


def test_suite_cases_endpoint_returns_whitelisted_preview_only(settings):
    with TestClient(create_app(settings)) as client:
        suite = client.get(f"/api/v1/suites/{GAUNTLET_SUITE_ID}").json()
        response = client.get(f"/api/v1/suites/{GAUNTLET_SUITE_ID}/cases")
        assert response.status_code == 200
        cases = response.json()
        assert len(cases) == len(suite["cases"])
        for item in cases:
            assert set(item) == SUITE_CASE_PREVIEW_KEYS
            assert item["instruction"]
            assert isinstance(item["difficulty"], int)
            assert isinstance(item["requires_docker"], bool)
        # 防泄漏负断言：窄端点响应文本不得包含任何敏感键
        for secret in ("private_files", "demo_response", "demo_actions", "initial_files"):
            assert secret not in response.text
        missing = client.get("/api/v1/suites/suite-missing/cases")
        assert missing.status_code == 404


def test_suite_cases_endpoint_does_not_leak_ncre_choice_answers(settings):
    answers = judge_answers("paper01")
    assert len(answers) == 20
    with TestClient(create_app(settings)) as client:
        response = client.get(f"/api/v1/suites/{NCRE_OFFICE_SUITE_ID}/cases")
        assert response.status_code == 200
        text = response.text
        for secret in ("private_files", "demo_response", "demo_actions", "initial_files"):
            assert secret not in text
        # 20 个选择题答案串（含常见序列化形态）不得出现在响应中
        for qid, letter in answers.items():
            assert f'"{qid}": "{letter}"' not in text
            assert f'"{qid}":"{letter}"' not in text
        assert json.dumps(answers) not in text
        assert json.dumps(answers, separators=(",", ":")) not in text
        assert "".join(answers[key] for key in sorted(answers)) not in text


def test_test_case_detail_strips_demo_response_for_d5_case(settings):
    target = next(
        definition
        for definition in build_catalog()
        if int((definition.get("metadata") or {}).get("difficulty", 0)) == 5
        and isinstance((definition.get("metadata") or {}).get("demo_response"), str)
        # 跳过数学题：其 demo_response 与 validator expected 同值，属合法可见
        and "。" in (definition.get("metadata") or {}).get("demo_response", "")
    )
    case_id = stable_id("case", f"{target['slug']}@{target['version']}")
    expected_answer = str(target["metadata"]["demo_response"])
    with TestClient(create_app(settings)) as client:
        response = client.get(f"/api/v1/test-cases/{case_id}")
        assert response.status_code == 200
        assert "demo_response" not in response.text
        assert expected_answer not in response.text


def test_system_status_reports_workspaces_dir(settings):
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/v1/system/status").json()
        assert status["workspaces_dir"] == str(settings.data_dir / "workspaces")


def _seed_profile_runs(settings):
    service = EvaluationService(settings)
    now = "2026-08-06T00:00:00+00:00"
    for model_id, name in (("model-alpha", "Alpha"), ("model-beta", "Beta")):
        service.database.execute(
            "INSERT INTO models(id,name,provider,model_name,api_style,settings_json,"
            "input_price,output_price,enabled,builtin,created_at,updated_at) "
            "VALUES (?,?,?,?,'openai','{}',0,0,1,0,?,?)",
            (model_id, name, "codex-cli", f"{name.lower()}-test", now, now),
        )
    for case_id, category in (
        ("case-r1", "reasoning"),
        ("case-r2", "reasoning"),
        ("case-p1", "planning"),
    ):
        service.database.execute(
            "INSERT INTO test_cases(id,slug,version,category,title,description,"
            "definition_json,builtin,enabled,created_at) "
            "VALUES (?,?,'1.0.0',?,?,'','{}',0,1,?)",
            (case_id, f"profile.{case_id}", category, case_id, now),
        )
    service.database.execute(
        "INSERT INTO experiments(id,name,suite_id,participants_json,benchmark_generation,"
        "scoring_profile,status,created_at) "
        "VALUES ('exp-profile','Profiles',?,'[]','v3','balanced-v3','completed',?)",
        (SMOKE_SUITE_ID, now),
    )

    def add_run(run_id, model_id, case_id, status, score, passed, lane, created_at):
        service.database.execute(
            "INSERT INTO runs(id,experiment_id,test_case_id,model_id,runner_id,repetition,"
            "lane,status,score,passed,created_at) VALUES (?,?,?,?,?,1,?,?,?,?,?)",
            (run_id, "exp-profile", case_id, model_id, UNIFIED_RUNNER_ID, lane,
             status, score, passed, created_at),
        )

    add_run("run-a1", "model-alpha", "case-r1", "completed", 90, 1, "unified",
            "2026-08-01T00:00:00+00:00")
    add_run("run-a2", "model-alpha", "case-r2", "completed", 80, 0, "unified",
            "2026-08-02T00:00:00+00:00")
    add_run("run-a3", "model-alpha", "case-p1", "completed", 70, 1, "unified",
            "2026-08-03T00:00:00+00:00")
    add_run("run-a4", "model-alpha", "case-r1", "completed", 100, 1, "native",
            "2026-08-05T00:00:00+00:00")
    # 非 completed 的 run 不得计入
    add_run("run-a5", "model-alpha", "case-r1", "failed", 50, 0, "unified",
            "2026-08-06T00:00:00+00:00")
    add_run("run-a6", "model-alpha", "case-r2", "cancelled", None, None, "unified",
            "2026-08-06T00:00:00+00:00")
    add_run("run-b1", "model-beta", "case-r1", "completed", 60, 1, "unified",
            "2026-08-04T00:00:00+00:00")
    return service


def test_model_profiles_endpoint_aggregates_completed_runs(settings):
    service = _seed_profile_runs(settings)
    try:
        with TestClient(create_app(settings)) as client:
            profiles = client.get("/api/v1/model-profiles").json()
            assert [item["model_id"] for item in profiles] == ["model-alpha", "model-beta"]
            alpha, beta = profiles
            assert alpha["model_name"] == "Alpha"
            assert alpha["provider"] == "codex-cli"
            assert alpha["total_runs"] == 4
            assert alpha["avg_score"] == 85.0  # (90+80+70+100)/4
            assert alpha["success_rate"] == 75.0  # 3 passed / 4
            assert alpha["last_run_at"] == "2026-08-05T00:00:00+00:00"
            assert [dim["category"] for dim in alpha["dimensions"]] == [
                "reasoning",
                "planning",
            ]
            assert alpha["dimensions"][0] == {
                "category": "reasoning",
                "avg_score": 90.0,  # (90+80+100)/3，含 native lane
                "runs": 3,
                "success_rate": 66.7,
            }
            assert alpha["dimensions"][1] == {
                "category": "planning",
                "avg_score": 70.0,
                "runs": 1,
                "success_rate": 100.0,
            }
            assert beta["total_runs"] == 1
            assert beta["avg_score"] == 60.0
            assert beta["success_rate"] == 100.0

            unified = client.get("/api/v1/model-profiles", params={"lane": "unified"}).json()
            alpha_unified = next(item for item in unified if item["model_id"] == "model-alpha")
            assert alpha_unified["total_runs"] == 3
            assert alpha_unified["avg_score"] == 80.0
            assert alpha_unified["success_rate"] == 66.7
            reasoning = next(
                dim for dim in alpha_unified["dimensions"] if dim["category"] == "reasoning"
            )
            assert reasoning["runs"] == 2
            assert reasoning["avg_score"] == 85.0
            assert client.get("/api/v1/model-profiles", params={"lane": "native"}).json()[0][
                "total_runs"
            ] == 1
    finally:
        service.close()


def test_model_profiles_endpoint_returns_empty_without_completed_runs(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/model-profiles").json() == []


NCRE_WORD_CASE_ID = stable_id("case", "ncre.office.paper01.word@1.0.0")
NCRE_CHOICE_CASE_ID = stable_id("case", "ncre.office.paper01.choice@1.0.0")


def _seed_material_runs(settings):
    """Queued runs (workspace_path NULL) bound to real NCRE paper01 cases."""
    service = EvaluationService(settings)
    now = "2026-08-06T00:00:00+00:00"
    service.database.execute(
        "INSERT INTO experiments(id,name,suite_id,participants_json,status,created_at) "
        "VALUES ('exp-material','Materials',?,'[]','draft',?)",
        (NCRE_OFFICE_SUITE_ID, now),
    )
    for run_id, case_id in (
        ("run-mat-word", NCRE_WORD_CASE_ID),
        ("run-mat-choice", NCRE_CHOICE_CASE_ID),
    ):
        service.database.execute(
            "INSERT INTO runs(id,experiment_id,test_case_id,model_id,runner_id,repetition,"
            "lane,status,created_at) VALUES (?,?,?,?,?,1,'unified','queued',?)",
            (run_id, "exp-material", case_id, MOCK_MODEL_ID, UNIFIED_RUNNER_ID, now),
        )
    return service


def test_run_material_endpoint_downloads_office_assets(settings):
    service = _seed_material_runs(settings)
    try:
        with TestClient(create_app(settings)) as client:
            # 二进制 docx：字节与原始 base64 解码一致
            docx = client.get("/api/v1/runs/run-mat-word/materials/Word.docx")
            assert docx.status_code == 200
            assert docx.content == base64.b64decode(blobs.WORD_DOCX_B64)
            assert docx.headers["content-type"].startswith(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            assert 'filename="Word.docx"' in docx.headers["content-disposition"]
            # 纯文本 csv（中文文件名）：UTF-8 字节一致 + RFC 5987 编码 + ASCII fallback
            csv = client.get(
                f"/api/v1/runs/run-mat-word/materials/{urllib.parse.quote('通讯录.csv')}"
            )
            assert csv.status_code == 200
            assert csv.content == blobs.CONTACTS_CSV.encode("utf-8")
            assert csv.headers["content-type"].startswith("text/csv")
            disposition = csv.headers["content-disposition"]
            assert "attachment" in disposition
            assert f"filename*=UTF-8''{urllib.parse.quote('通讯录.csv')}" in disposition
            assert 'filename="csv"' in disposition  # 中文主干剔除后保留 ASCII 部分作 fallback
            # 防泄漏：素材响应不含判分脚本内容
            assert b"judge_word" not in docx.content
            assert "private_files" not in docx.text
            assert "private_files" not in csv.text
    finally:
        service.close()


def test_run_material_endpoint_rejects_unknown_and_traversal(settings):
    service = _seed_material_runs(settings)
    try:
        with TestClient(create_app(settings)) as client:
            unknown = client.get("/api/v1/runs/run-mat-word/materials/NoSuch.docx")
            assert unknown.status_code == 404
            assert unknown.json()["detail"] == "material_not_found"
            # 路径穿越：HTTP 客户端可能规范化 ..，故 API 层仅断言 404，
            # 字面量穿越输入由 service 白名单拒绝
            for hostile in ("../../x", "Word.docx/../judge_word.py"):
                response = client.get(
                    f"/api/v1/runs/run-mat-word/materials/{urllib.parse.quote(hostile, safe='')}"
                )
                assert response.status_code == 404
            # 选择题空 initial_files：任意文件名均 404
            assert (
                client.get("/api/v1/runs/run-mat-choice/materials/Word.docx").status_code == 404
            )
            # run 不存在
            assert (
                client.get("/api/v1/runs/run-missing/materials/Word.docx").status_code == 404
            )
        # service 层拒绝字面量穿越输入（含 /、\、..）
        for hostile in ("../../x", "Word.docx/../judge_word.py", "..\\..\\x"):
            with pytest.raises(KeyError, match="material_not_found"):
                service.get_run_material("run-mat-word", hostile)
        with pytest.raises(KeyError, match="run_not_found"):
            service.get_run_material("run-missing", "Word.docx")
    finally:
        service.close()


def test_get_run_payload_omits_material_contents_and_lists_materials(settings):
    service = _seed_material_runs(settings)
    try:
        with TestClient(create_app(settings)) as client:
            response = client.get("/api/v1/runs/run-mat-word")
            assert response.status_code == 200
            body = response.json()
            # test_definition 不再携带 initial_files 内容，仅暴露 materials 清单
            assert "initial_files" not in body["test_definition"]
            assert body["materials"] == [
                {"name": "Word.docx", "size_bytes": len(base64.b64decode(blobs.WORD_DOCX_B64))},
                {"name": "通讯录.csv", "size_bytes": len(blobs.CONTACTS_CSV.encode("utf-8"))},
            ]
            # 瘦身生效：base64 全文与 csv 全文不再出现在轮询载荷中
            assert blobs.WORD_DOCX_B64[:64] not in response.text
            assert blobs.CONTACTS_CSV[:32] not in response.text
            # 防泄漏负断言
            for secret in ("private_files", "judge_word.py", "demo_response", "demo_actions"):
                assert secret not in response.text

            choice = client.get("/api/v1/runs/run-mat-choice")
            assert choice.status_code == 200
            choice_body = choice.json()
            assert choice_body["materials"] == []
            assert "initial_files" not in choice_body["test_definition"]
            answers = judge_answers("paper01")
            for qid, letter in answers.items():
                assert f'"{qid}": "{letter}"' not in choice.text
                assert f'"{qid}":"{letter}"' not in choice.text
            assert json.dumps(answers) not in choice.text
    finally:
        service.close()
