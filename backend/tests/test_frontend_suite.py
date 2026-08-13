from __future__ import annotations

import json
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
    assert paused["status"] == "interrupted"
    assert {item["status"] for item in service.list_runs(created["id"])[1:]} == {"interrupted"}

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
