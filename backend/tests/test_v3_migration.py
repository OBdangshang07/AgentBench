from __future__ import annotations

import hashlib
import json
import sqlite3

from agentbench.catalog import (
    MOCK_MODEL_ID,
    SMOKE_SUITE_ID,
    UNIFIED_RUNNER_ID,
    build_catalog,
)
from agentbench.db import Database
from agentbench.execution import DockerExecutor, Workspace
from agentbench.schemas import ExperimentCreate, Participant
from agentbench.scoring import ScoringEngine, ValidationResult
from agentbench.service import EvaluationService


def test_ncre_office_catalog_is_frozen_for_v3() -> None:
    office_cases = [case for case in build_catalog() if case.get("category") == "office-exam"]
    canonical = json.dumps(
        office_cases, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    assert len(office_cases) == 12
    assert hashlib.sha256(canonical).hexdigest() == (
        "494efc69335bb6659ad00f297656a33a29488e9dc7cf631e7ff25e117070a412"
    )


def test_v3_runs_keep_immutable_test_definition_revisions(settings) -> None:
    service = EvaluationService(settings)
    try:
        experiment = service.create_experiment(
            ExperimentCreate(
                name="V3 revision snapshot",
                suite_id=SMOKE_SUITE_ID,
                participants=[
                    Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)
                ],
            )
        )
        run = service.database.fetch_one(
            "SELECT * FROM runs WHERE experiment_id=? ORDER BY created_at LIMIT 1",
            (experiment["id"],),
        )
        assert run is not None
        assert run["test_revision_id"]
        assert run["scoring_profile"] == "balanced-v3"
        assert experiment["benchmark_generation"] == "v3"

        original_definition, original_revision = service._definition_for_run(run)
        replacement = {**original_definition, "instruction": "V3 replacement sentinel"}
        service.database.execute(
            "UPDATE test_cases SET definition_json=? WHERE id=?",
            (json.dumps(replacement, ensure_ascii=False), run["test_case_id"]),
        )
        service.database.sync_test_case_revisions(run["test_case_id"])

        refreshed = service.database.fetch_one("SELECT * FROM runs WHERE id=?", (run["id"],))
        assert refreshed is not None
        preserved_definition, preserved_revision = service._definition_for_run(refreshed)
        assert preserved_revision["id"] == original_revision["id"]
        assert preserved_definition["instruction"] == original_definition["instruction"]
        assert service.database.fetch_one("SELECT version FROM schema_meta") == {"version": 4}
    finally:
        service.close()


def test_schema_upgrade_creates_recoverable_database_backup(tmp_path) -> None:
    database_path = tmp_path / "agentbench.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE schema_meta(version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_meta(version) VALUES (3)")

    database = Database(database_path)
    database.initialize()

    backups = list((tmp_path / "migration-backups").glob("agentbench-pre-schema-v4-*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("SELECT version FROM schema_meta").fetchone() == (3,)
    assert database.fetch_one("SELECT version FROM schema_meta") == {"version": 4}


def test_test_library_health_uses_objective_scores_not_legacy_passed(settings) -> None:
    service = EvaluationService(settings)
    try:
        experiment = service.create_experiment(
            ExperimentCreate(
                name="V3 health statistics",
                suite_id=SMOKE_SUITE_ID,
                participants=[
                    Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)
                ],
                repetitions=3,
            )
        )
        runs = service.database.fetch_all(
            "SELECT * FROM runs WHERE experiment_id=? ORDER BY test_case_id,repetition",
            (experiment["id"],),
        )
        target_case_id = runs[0]["test_case_id"]
        target_runs = [row for row in runs if row["test_case_id"] == target_case_id]
        assert len(target_runs) == 3
        for row in target_runs:
            service.database.execute(
                "UPDATE runs SET status='completed',score=99.8,passed=0 WHERE id=?",
                (row["id"],),
            )
            service.database.execute(
                "INSERT INTO score_components(id,run_id,dimension,score,weight,evidence_json,created_at) "
                "VALUES (?,?,?,?,94,'{}','now')",
                (f"component-{row['id']}", row["id"], "objective_quality", 100.0),
            )
            service.database.execute(
                "INSERT INTO run_attempts(id,run_id,attempt_no,status,prompt,multiplier,raw_score,"
                "adjusted_score,passed,created_at) VALUES (?,?,1,'completed','',1,100,99.8,1,'now')",
                (f"attempt-{row['id']}", row["id"]),
            )

        case = next(item for item in service.list_test_cases() if item["id"] == target_case_id)
        assert case["health"] == {
            **case["health"],
            "sample_size": 3,
            "objective_full_rate": 100.0,
            "first_attempt_full_rate": 100.0,
            "confidence": "low",
            "low_discrimination": True,
        }
    finally:
        service.close()


def test_anonymous_multi_judge_consensus_and_disagreement(settings, monkeypatch) -> None:
    service = EvaluationService(settings)
    try:
        service.update_settings(
            {
                "judge_model_id": "judge-primary",
                "judge_runner_id": "runner-primary",
                "judge_model_id_secondary": "judge-secondary",
                "judge_runner_id_secondary": "runner-secondary",
                "judge_disagreement_threshold": 12,
            }
        )
        scores = {"primary": 82.0, "secondary": 88.0}

        def fake_single(*_args, anonymous_slot="primary", **_kwargs):
            def callback(_config, weight):
                return ValidationResult(
                    "ai_rubric",
                    weight,
                    scores[anonymous_slot],
                    "passed",
                    {"anonymous_slot": anonymous_slot, "evidence": [anonymous_slot]},
                )

            return callback

        monkeypatch.setattr(service, "_single_judge_callback", fake_single)
        events = []
        callback = service._judge_callback(
            {"id": "run", "model_id": "candidate"},
            {"validators": [{"type": "ai_rubric"}]},
            object(),
            lambda event_type, payload: events.append((event_type, payload)),
        )
        assert callback is not None
        consensus = callback({}, 25)
        assert consensus.status == "passed"
        assert consensus.score == 85.0
        assert consensus.evidence["judge_count"] == 2
        assert events[-1][0] == "judge.consensus"

        scores["secondary"] = 40.0
        disagreement = callback({}, 25)
        assert disagreement.status == "needs_review"
        assert disagreement.evidence["difference"] == 42.0
        assert events[-1][0] == "judge.disagreement"
    finally:
        service.close()


def test_symbolic_json_accepts_equivalent_math_and_awards_partial_credit(tmp_path) -> None:
    engine = ScoringEngine(DockerExecutor(executable="missing-docker"))
    workspace = Workspace(tmp_path / "workspace")
    definition = {
        "limits": {"max_steps": 10, "time_target_seconds": 600, "token_budget": 5000},
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 100,
                "config": {
                    "fields": {
                        "lambda_4.classification": {
                            "expected": "infinitely-many",
                            "weight": 1,
                        },
                        "lambda_4.family": {
                            "kind": "expression",
                            "expected": "exp(x)*(1-cos(2*x))/4+C*exp(x)*sin(2*x)",
                            "variables": ["x", "C"],
                            "weight": 3,
                        },
                    }
                },
            }
        ],
    }
    equivalent_answer = json.dumps(
        {
            "lambda_4": {
                "classification": "infinitely-many",
                "family": "E^x*(1-cos(2*x)+4*C*sin(2*x))/4",
            }
        }
    )
    full = engine.score(
        definition=definition,
        final_answer=equivalent_answer,
        workspace=workspace,
        steps=3,
        duration_ms=1000,
        tokens_input=100,
        tokens_output=100,
    )
    assert full.dimensions[0].score == 100.0

    wrong_formula = equivalent_answer.replace("sin(2*x)", "sin(3*x)")
    partial = engine.score(
        definition=definition,
        final_answer=wrong_formula,
        workspace=workspace,
        steps=3,
        duration_ms=1000,
        tokens_input=100,
        tokens_output=100,
    )
    assert partial.dimensions[0].score == 25.0


def test_all_v3_math_reference_answers_satisfy_symbolic_validators(tmp_path) -> None:
    engine = ScoringEngine(DockerExecutor(executable="missing-docker"))
    math_cases = [
        case
        for case in build_catalog()
        if str(case["slug"]).startswith("math.") and case["version"] == "3.0.0"
    ]

    assert len(math_cases) == 20
    for case in math_cases:
        workspace = Workspace(tmp_path / str(case["slug"]).replace(".", "-"))
        score = engine.score(
            definition=case,
            final_answer=str(case["metadata"]["demo_response"]),
            workspace=workspace,
            steps=3,
            duration_ms=1000,
            tokens_input=100,
            tokens_output=100,
        )
        objective = next(
            item for item in score.dimensions if item.validator_type == "objective_quality"
        )
        assert objective.score == 100.0, case["slug"]


def test_public_test_definition_hides_v3_reference_answers(settings) -> None:
    service = EvaluationService(settings)
    try:
        ode = next(
            item
            for item in service.list_test_cases()
            if item["slug"] == "math.ode-second-order-ivp"
        )
        public = service.get_test_case(ode["id"])
        serialized = json.dumps(public, ensure_ascii=False)
        assert "symbolic_json" in serialized
        assert "private" in serialized
        assert "infinitely-many" not in serialized
        assert "cos(sqrt(2)*pi)" not in serialized
    finally:
        service.close()
