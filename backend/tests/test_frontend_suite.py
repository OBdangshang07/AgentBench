from __future__ import annotations

import io
import json
import stat
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from agentbench.catalog import FRONTEND_FULL_SUITE_ID
from agentbench.config import Settings
from agentbench.frontend_suite import SOURCE_COMMIT, build_frontend_cases
from agentbench.schemas import ExperimentCreate, Participant
from agentbench.service import EvaluationService


@pytest.fixture
def service(settings: Settings) -> Iterator[EvaluationService]:
    value = EvaluationService(settings)
    try:
        yield value
    finally:
        value.close()


def test_frontend_suite_is_fixed_and_manual_only(service: EvaluationService) -> None:
    suite = service.get_suite(FRONTEND_FULL_SUITE_ID)
    assert len(suite["cases"]) == 24
    cases = service.list_suite_cases(FRONTEND_FULL_SUITE_ID)
    assert min(item["difficulty"] for item in cases) == 3
    assert max(item["difficulty"] for item in cases) == 6
    definitions = build_frontend_cases()
    assert {item["metadata"]["source_commit"] for item in definitions} == {SOURCE_COMMIT}
    assert all(item["validators"] == [{"type": "manual_rubric", "weight": 100, "config": {"rubric_version": "1.0"}}] for item in definitions)
    assert all("历史参测作品" in item["instruction"] for item in definitions)
    assert all("不要克隆仓库或下载大型代码库" in item["instruction"] for item in definitions)
    assert all("与最终作品无关的调试" in item["instruction"] for item in definitions)


def _frontend_run(service: EvaluationService) -> dict:
    created = service.create_experiment(
        ExperimentCreate(
            name="frontend-manual-test",
            suite_id=FRONTEND_FULL_SUITE_ID,
            participants=[Participant(model_id=service.list_models()[0]["id"], runner_id=service.list_runners()[0]["id"])],
            repetitions=1,
            concurrency=1,
        )
    )
    run = service.list_runs(created["id"], limit=1)[0]
    workspace = service._frontend_workspace_root(created["id"]) / "test" / "r01" / "01-project"
    workspace.mkdir(parents=True)
    (workspace / "index.html").write_text("<!doctype html><title>work</title>", encoding="utf-8")
    service.database.execute(
        "UPDATE runs SET status='needs_review',workspace_path=?,completed_at=? WHERE id=?",
        (str(workspace), run["created_at"], run["id"]),
    )
    return service.get_run(run["id"])


def test_manual_frontend_review_draft_and_submit(service: EvaluationService) -> None:
    run = _frontend_run(service)
    assert run["frontend"]["source_commit"] == SOURCE_COMMIT
    rubric = run["frontend"]["rubric"]
    draft = service.save_manual_review(
        run["id"],
        {"reviewer": "QA", "dimension_scores": {rubric["dimensions"][0]["key"]: 10}},
        submit=False,
    )
    assert draft["frontend"]["review"]["status"] == "draft"
    scores = {item["key"]: item["max_score"] - 1 for item in rubric["dimensions"]}
    submitted = service.save_manual_review(
        run["id"],
        {"reviewer": "QA", "dimension_scores": scores, "checklist": {}, "critical_defects": [], "comment": "verified"},
        submit=True,
    )
    assert submitted["status"] == "completed"
    assert submitted["score"] == sum(scores.values())
    assert submitted["frontend"]["review"]["status"] == "submitted"


def test_manual_frontend_review_preserves_efficiency_dimensions(service: EvaluationService) -> None:
    run = _frontend_run(service)
    rubric = run["frontend"]["rubric"]
    now = run["created_at"]
    validator_rows = [
        ("manual", "manual_rubric", 94, 0, "needs_review"),
        ("time", "time_efficiency", 3, 100, "passed"),
        ("step", "step_efficiency", 2, 50, "passed"),
        ("token", "token_efficiency", 1, 0, "passed"),
    ]
    dimension_rows = [
        ("manual-d", "manual_quality", 0, 94),
        ("time-d", "time_efficiency", 100, 3),
        ("step-d", "step_efficiency", 50, 2),
        ("token-d", "token_efficiency", 0, 1),
    ]
    for row_id, kind, weight, score, status in validator_rows:
        service.database.execute(
            "INSERT INTO validator_results(id,run_id,validator_type,weight,score,status,evidence_json,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (row_id, run["id"], kind, weight, score, status, "{}", now),
        )
    for row_id, dimension, score, weight in dimension_rows:
        service.database.execute(
            "INSERT INTO score_components(id,run_id,dimension,score,weight,evidence_json,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (row_id, run["id"], dimension, score, weight, "{}", now),
        )
    scores = {item["key"]: item["max_score"] * 0.8 for item in rubric["dimensions"]}

    submitted = service.save_manual_review(
        run["id"],
        {"reviewer": "QA", "dimension_scores": scores, "critical_defects": []},
        submit=True,
    )

    assert submitted["score"] == 79.2
    assert {item["dimension"] for item in submitted["score_dimensions"]} == {
        "manual_quality", "time_efficiency", "step_efficiency", "token_efficiency"
    }
    manual = next(item for item in submitted["validators"] if item["validator_type"] == "manual_rubric")
    assert manual["score"] == 80
    assert manual["weight"] == 94


def test_manual_frontend_critical_defect_caps_final_weighted_score(service: EvaluationService) -> None:
    run = _frontend_run(service)
    rubric = run["frontend"]["rubric"]
    now = run["created_at"]
    for row_id, dimension, score, weight in (
        ("manual-d", "manual_quality", 0, 94),
        ("time-d", "time_efficiency", 100, 3),
        ("step-d", "step_efficiency", 100, 2),
        ("token-d", "token_efficiency", 100, 1),
    ):
        service.database.execute(
            "INSERT INTO score_components(id,run_id,dimension,score,weight,evidence_json,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (row_id, run["id"], dimension, score, weight, "{}", now),
        )
    scores = {item["key"]: item["max_score"] for item in rubric["dimensions"]}

    submitted = service.save_manual_review(
        run["id"],
        {"reviewer": "QA", "dimension_scores": scores, "critical_defects": ["static_fake"]},
        submit=True,
    )

    assert submitted["score"] == 59
    assert submitted["passed"] is False


def test_frontend_preview_and_manifest_stay_inside_portfolio(service: EvaluationService) -> None:
    run = _frontend_run(service)
    preview = service.frontend_preview_status(run["id"])
    assert preview == {"available": True, "kind": "static", "entry": "index.html"}
    result = service.start_frontend_preview(run["id"])
    assert result["url"].startswith("http://127.0.0.1:")
    try:
        service._write_frontend_portfolio_manifest(run["experiment_id"])
        manifest = service._frontend_workspace_root(run["experiment_id"]) / "portfolio.json"
        value = json.loads(manifest.read_text(encoding="utf-8"))
        assert value["source"]["source_commit"] == SOURCE_COMMIT
        assert Path(value["runs"][0]["workspace_path"]).is_relative_to(service.settings.data_dir)
    finally:
        assert service.stop_frontend_preview(run["id"]) == {"stopped": True}


def test_manual_review_evidence_is_scoped_to_review(service: EvaluationService) -> None:
    run = _frontend_run(service)
    review = service.add_manual_review_evidence(run["id"], "proof.png", b"\x89PNG\r\n\x1a\n")
    item = review["evidence"][0]
    path = service.manual_review_evidence_path(run["id"], item["path"])
    assert path.read_bytes() == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(KeyError, match="manual_review_evidence_not_found"):
        service.manual_review_evidence_path(run["id"], "../outside.png")


def test_frontend_suite_can_pause_skip_and_resume(
    service: EvaluationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = service.create_experiment(
        ExperimentCreate(
            name="frontend-controls-test",
            suite_id=FRONTEND_FULL_SUITE_ID,
            participants=[Participant(model_id=service.list_models()[0]["id"], runner_id=service.list_runners()[0]["id"])],
            repetitions=1,
            concurrency=1,
        )
    )
    queued = service.list_runs(created["id"])
    skipped = service.skip_run(queued[0]["id"])
    assert skipped["status"] == "cancelled"


    assert skipped["error_code"] == "suite_skipped"

    service.database.execute("UPDATE experiments SET status='running' WHERE id=?", (created["id"],))
    paused = service.pause_experiment(created["id"])
    assert paused["status"] == "paused"
    assert {item["status"] for item in service.list_runs(created["id"])[1:]} == {"queued"}

    submitted: list[str] = []
    monkeypatch.setattr(
        service.executor,
        "submit",
        lambda _callable, run_id, _semaphore: submitted.append(run_id),
    )
    monkeypatch.setattr(service, "preflight_experiment", lambda _experiment_id: {"ok": True})
    resumed = service.start_experiment(created["id"])
    assert resumed["status"] == "running"
    assert len(submitted) == 23


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_skipped_frontend_run_accepts_offline_html_import(service: EvaluationService) -> None:
    created = service.create_experiment(
        ExperimentCreate(
            name="frontend-offline-html",
            suite_id=FRONTEND_FULL_SUITE_ID,
            participants=[Participant(model_id=service.list_models()[0]["id"], runner_id=service.list_runners()[0]["id"])],
            repetitions=1,
            concurrency=1,
        )
    )
    run = service.list_runs(created["id"])[0]
    service.skip_run(run["id"])

    imported = service.import_frontend_artifact(
        run["id"], "black-hole.html", b"<!doctype html><title>Black hole</title>",
    )

    current = imported["run"]
    assert current["status"] == "needs_review"
    assert current["score"] is None
    assert current["frontend"]["review"]["status"] == "draft"
    assert imported["preview"] == {"available": True, "kind": "static", "entry": "index.html"}
    root = Path(current["workspace_path"])
    assert root.is_relative_to(service._frontend_workspace_root(created["id"]))
    assert (root / "index.html").read_bytes().startswith(b"<!doctype html>")
    manifest = json.loads((root / ".agentbench-import.json").read_text(encoding="utf-8"))
    assert manifest["scripts_executed"] is False
    assert manifest["original_name"] == "black-hole.html"
    assert {item["kind"] for item in current["artifacts"]} == {"frontend_import"}


def test_frontend_zip_import_collapses_one_wrapper_and_finds_dist(service: EvaluationService) -> None:
    created = service.create_experiment(
        ExperimentCreate(
            name="frontend-offline-zip",
            suite_id=FRONTEND_FULL_SUITE_ID,
            participants=[Participant(model_id=service.list_models()[0]["id"], runner_id=service.list_runners()[0]["id"])],
        )
    )
    run = service.list_runs(created["id"])[0]
    service.skip_run(run["id"])
    payload = _zip_bytes(
        {
            "my-project/dist/index.html": b"<!doctype html><script src='assets/app.js'></script>",
            "my-project/dist/assets/app.js": b"document.body.append('ready')",
            "my-project/package.json": b'{"scripts":{"build":"vite build"}}',
        }
    )

    imported = service.import_frontend_artifact(run["id"], "project.zip", payload)

    assert imported["preview"]["entry"] == "dist/index.html"
    root = Path(imported["run"]["workspace_path"])
    assert (root / "dist" / "assets" / "app.js").is_file()
    assert not (root / "my-project").exists()


@pytest.mark.parametrize("member_name", ["../outside.html", "C:/outside.html", "/outside.html"])
def test_frontend_zip_import_rejects_path_escape(
    service: EvaluationService, member_name: str
) -> None:
    run = _frontend_run(service)
    service.database.execute(
        "UPDATE runs SET status='cancelled',error_code='suite_skipped' WHERE id=?", (run["id"],)
    )
    payload = _zip_bytes({member_name: b"<!doctype html>"})

    with pytest.raises(ValueError, match="frontend_import_archive_path_invalid"):
        service.import_frontend_artifact(run["id"], "escape.zip", payload)


def test_frontend_zip_import_rejects_symlink(service: EvaluationService) -> None:
    run = _frontend_run(service)
    service.database.execute(
        "UPDATE runs SET status='cancelled',error_code='suite_skipped' WHERE id=?", (run["id"],)
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        link = zipfile.ZipInfo("index.html")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "../outside.html")

    with pytest.raises(ValueError, match="frontend_import_archive_link_forbidden"):
        service.import_frontend_artifact(run["id"], "link.zip", output.getvalue())


def test_experiment_dispatch_query_follows_frozen_suite_order(
    service: EvaluationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = service.create_experiment(
        ExperimentCreate(
            name="frontend-dispatch-order",
            suite_id=FRONTEND_FULL_SUITE_ID,
            participants=[Participant(model_id=service.list_models()[0]["id"], runner_id=service.list_runners()[0]["id"])],
            repetitions=1,
            concurrency=1,
        )
    )
    expected = [item["id"] for item in service.list_suite_cases(FRONTEND_FULL_SUITE_ID)]
    submitted: list[str] = []

    class RecordingExecutor:
        def submit(self, _callable, run_id, _semaphore):
            submitted.append(run_id)

        def shutdown(self, **_kwargs):
            return None

    monkeypatch.setattr(
        service,
        "preflight_experiment",
        lambda _experiment_id: {"ok": True, "errors": [], "warnings": [], "checks": {}},
    )
    monkeypatch.setattr(service, "executor", RecordingExecutor())
    service.start_experiment(created["id"])
    actual = [service.get_run(run_id)["test_case_id"] for run_id in submitted]

    assert actual == expected
