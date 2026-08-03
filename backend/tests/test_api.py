from __future__ import annotations

from fastapi.testclient import TestClient

from agentbench.api import create_app
from agentbench.catalog import QODER_RUNNER_ID, SMOKE_SUITE_ID, UNIFIED_RUNNER_ID


def test_health_and_catalog_api(settings):
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["version"] == "2.4.1"
        cases = client.get("/api/v1/test-cases").json()
        assert len(cases) == 202
        assert {item["difficulty"] for item in cases} == {1, 2, 3, 4, 5, 6}
        assert any(item["requires_docker"] for item in cases)
        assert any(item["requires_judge"] for item in cases)
        status = client.get("/api/v1/system/status").json()
        assert status["database"]["ready"] is True
        assert status["docker"]["available"] is False


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


def test_qoder_install_endpoint_refuses_unverified_recipe(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post(f"/api/v1/runners/{QODER_RUNNER_ID}/install")
        assert response.status_code == 400
        assert "暂无已验证" in response.json()["detail"]


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
