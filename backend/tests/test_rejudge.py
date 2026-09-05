from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agentbench.agent import AgentResult
from agentbench.api import create_app
from agentbench.catalog import MOCK_MODEL_ID, QODER_RUNNER_ID, UNIFIED_RUNNER_ID
from agentbench.db import new_id, utc_now
from agentbench.execution import CommandResult, Workspace
from agentbench.math_rubric import RUBRIC_SCHEMA, structured_rubric_config
from agentbench.model_clients import ModelDecision, ModelUsage
from agentbench.schemas import (
    ExperimentCreate,
    ModelCreate,
    Participant,
    RunnerCreate,
    TestCaseImport,
)
from agentbench.scoring import ScoreResult, ValidationResult
from agentbench.service import EvaluationService, _materialize_private_frontier_variant

JUDGE_JSON = json.dumps(
    {
        "score": 87,
        "summary": "solid",
        "strengths": ["complete"],
        "weaknesses": [],
        "evidence": ["final answer matches"],
    },
    ensure_ascii=False,
)


class SequencedClient:
    def __init__(self, answers: list[str]):
        self.answers = answers
        self.index = 0

    def complete(self, _history, _tools):
        answer = self.answers[min(self.index, len(self.answers) - 1)]
        self.index += 1
        return ModelDecision(
            kind="final", content=answer, usage=ModelUsage(input_tokens=50, output_tokens=10)
        )


def _create_rubric_run(service: EvaluationService) -> str:
    case = service.import_test_case(
        TestCaseImport(
            slug=f"test.rejudge-{new_id()}",
            version="1.0.0",
            category="judge-flow",
            title="Rejudge flow",
            instruction="Return exactly OK.",
            validators=[{"type": "ai_rubric", "weight": 100, "config": {"rubric": "quality"}}],
            limits={"max_steps": 4, "time_target_seconds": 60, "token_budget": 1000},
            attempt_policy={"max_attempts": 1, "pass_threshold": 60},
        )
    )
    suite_id = new_id()
    service.database.execute(
        "INSERT INTO test_suites(id,name,description,version,builtin,created_at) "
        "VALUES (?,?,?,'1.0.0',0,?)",
        (suite_id, "Rejudge Suite", "test", utc_now()),
    )
    service.database.execute(
        "INSERT INTO suite_cases(suite_id,test_case_id,position) VALUES (?,?,0)",
        (suite_id, case["id"]),
    )
    experiment = service.create_experiment(
        ExperimentCreate(
            name="Rejudge test",
            suite_id=suite_id,
            participants=[Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)],
        )
    )
    # ``_execute_run`` now enforces the same running-experiment guard as the
    # scheduler so a queued run cannot slip through after a pause request.
    # These focused tests drive the private executor synchronously, therefore
    # put their fixture experiment into the lifecycle state the scheduler uses.
    service.database.execute(
        "UPDATE experiments SET status='running',started_at=? WHERE id=?",
        (utc_now(), experiment["id"]),
    )
    return service.list_runs(experiment["id"])[0]["id"]


def _enable_native_judge(service: EvaluationService) -> str:
    judge_model = service.create_model(
        ModelCreate(name="Judge model", model_name="judge-model", api_style="mock")
    )
    service.update_settings(
        {
            "allow_native_cli": True,
            "judge_model_id": judge_model["id"],
            "judge_runner_id": QODER_RUNNER_ID,
        }
    )
    return judge_model["id"]


def test_long_judge_prompt_travels_via_stdin_not_argv(settings, monkeypatch):
    service = EvaluationService(settings)
    try:
        _enable_native_judge(service)
        long_instruction = ("请逐条检查以下需求并打分。\n" * 400)
        long_answer = "FINAL ANSWER LINE\n" * 500
        run = {"id": _create_rubric_run(service), "model_id": MOCK_MODEL_ID,
               "final_answer": long_answer}
        definition = {
            "instruction": long_instruction,
            "validators": [
                {"type": "ai_rubric", "weight": 100, "config": {"rubric": "quality"}}
            ],
        }
        workspace = Workspace(settings.workspaces_dir / "run-long")
        workspace.write_file("output.txt", "artifact")

        captured: dict[str, object] = {}

        def fake_run_native_cli(**kwargs):
            captured.update(kwargs)
            judge_workspace: Workspace = kwargs["workspace"]
            captured["judge_workspace_files"] = judge_workspace.list_files()
            captured["judge_prompt_file"] = judge_workspace.read_file("judge_prompt.md")
            stdout_line = json.dumps({"type": "result", "result": JUDGE_JSON})
            return CommandResult(True, 0, stdout_line + "\n", "", 12, None)

        monkeypatch.setattr("agentbench.service.run_native_cli", fake_run_native_cli)

        callback = service._judge_callback(run, definition, workspace, lambda *_args: None)
        assert callback is not None
        result = callback({"rubric": "quality"}, 100.0)

        assert result.status == "passed"
        assert result.score == 87.0
        # Full long prompt goes through stdin and the mirrored workspace file.
        stdin_text = captured["stdin_text"]
        assert isinstance(stdin_text, str)
        assert stdin_text.startswith("You are an anonymous evaluator")
        assert long_instruction in stdin_text
        assert long_answer in stdin_text
        assert "\n" in stdin_text
        assert len(stdin_text) > 8191
        assert captured["judge_prompt_file"] == stdin_text
        assert "judge_prompt.md" in captured["judge_workspace_files"]
        assert captured["extra_env"]["GIT_CEILING_DIRECTORIES"] == str(
            settings.workspaces_dir.resolve()
        )
        # argv only carries the short guidance text, never the long prompt.
        placeholders = captured["placeholders"]
        assert placeholders["prompt"] == EvaluationService.JUDGE_STDIN_GUIDANCE
        assert len(placeholders["prompt"]) < 500
        rendered = [
            part.replace("{prompt}", placeholders["prompt"])
            .replace("{model_name}", placeholders["model_name"])
            .replace("{workspace}", placeholders["workspace"])
            for part in captured["args"]
        ]
        assert all(long_answer not in part for part in rendered)
        assert len(" ".join(rendered)) < 8191
    finally:
        service.close()


def test_three_judge_consensus_uses_scored_low_confidence_tiebreaker(
    settings, tmp_path, monkeypatch
):
    service = EvaluationService(settings)
    try:
        service.update_settings(
            {
                "judge_model_id_secondary": "secondary-model",
                "judge_runner_id_secondary": "secondary-runner",
                "judge_model_id_tiebreaker": "tiebreaker-model",
                "judge_runner_id_tiebreaker": "tiebreaker-runner",
                "judge_disagreement_threshold": 4,
            }
        )

        def review(score, status="passed", reasons=None):
            return ValidationResult(
                "ai_rubric",
                100,
                score,
                status,
                {
                    "point_awards": [
                        {
                            "point_id": "p1",
                            "awarded_points": score / 10,
                            "max_points": 10,
                        }
                    ],
                    "review_reasons": reasons or [],
                },
            )

        by_slot = {
            "primary": review(100),
            "secondary": review(90),
            "tiebreaker": review(
                85, status="needs_review", reasons=["low_point_confidence"]
            ),
        }

        def fake_single(*_args, anonymous_slot="primary", **_kwargs):
            return lambda _config, _weight: by_slot[anonymous_slot]

        monkeypatch.setattr(service, "_single_judge_callback", fake_single)
        callback = service._judge_callback(
            {"id": "run-consensus", "model_id": "candidate-model"},
            {},
            Workspace(tmp_path / "consensus"),
            lambda *_args: None,
        )
        result = callback(
            {
                "required_judges": 2,
                "judge_disagreement_threshold": 4,
                "marking_mode": "strict_exam",
                "scoring_points": [
                    {"point_id": "p1", "description": "proof", "max_points": 10}
                ],
            },
            100,
        )

        assert result.status == "passed"
        assert result.score == 90
        assert result.evidence["scores"] == [100, 90, 85]
        assert result.evidence["advisory_review_reasons"] == ["low_point_confidence"]

        stored_reviews = []
        for slot, item in by_slot.items():
            stored_reviews.append(
                {
                    "score": item.score,
                    "status": "completed" if item.status == "passed" else item.status,
                    "evidence_json": json.dumps(
                        {**item.evidence, "anonymous_slot": slot}, ensure_ascii=False
                    ),
                }
            )
        monkeypatch.setattr(
            service,
            "_single_judge_callback",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("stored reviews must not invoke a judge")
            ),
        )
        reused_callback = service._judge_callback(
            {"id": "run-consensus", "model_id": "candidate-model"},
            {},
            Workspace(tmp_path / "stored-consensus"),
            lambda *_args: None,
            stored_reviews=stored_reviews,
        )
        reused = reused_callback(
            {
                "required_judges": 2,
                "judge_disagreement_threshold": 4,
                "marking_mode": "strict_exam",
                "scoring_points": [
                    {"point_id": "p1", "description": "proof", "max_points": 10}
                ],
            },
            100,
        )
        assert reused.status == "passed"
        assert reused.score == 90
    finally:
        service.close()


def test_required_three_judges_always_runs_third_without_disagreement(
    settings, tmp_path, monkeypatch
):
    service = EvaluationService(settings)
    try:
        service.update_settings(
            {
                "judge_model_id_secondary": "secondary-model",
                "judge_runner_id_secondary": "secondary-runner",
                "judge_model_id_tiebreaker": "third-model",
                "judge_runner_id_tiebreaker": "third-runner",
                "judge_disagreement_threshold": 4,
            }
        )
        calls: list[str] = []
        scores = {"primary": 92, "secondary": 93, "tiebreaker": 91}

        def fake_single(*_args, anonymous_slot="primary", **_kwargs):
            def review(_config, weight):
                calls.append(anonymous_slot)
                score = scores[anonymous_slot]
                return ValidationResult(
                    "ai_rubric",
                    weight,
                    score,
                    "passed",
                    {
                        "point_awards": [
                            {
                                "point_id": "p1",
                                "awarded_points": score / 10,
                                "max_points": 10,
                            }
                        ],
                        "review_reasons": [],
                    },
                )

            return review

        monkeypatch.setattr(service, "_single_judge_callback", fake_single)
        callback = service._judge_callback(
            {"id": "run-required-three", "model_id": "candidate-model"},
            {},
            Workspace(tmp_path / "required-three"),
            lambda *_args: None,
        )
        result = callback(
            {
                "required_judges": 3,
                "judge_disagreement_threshold": 4,
                "marking_mode": "strict_exam",
                "scoring_points": [
                    {"point_id": "p1", "description": "proof", "max_points": 10}
                ],
            },
            100,
        )

        assert calls == ["primary", "secondary", "tiebreaker"]
        assert result.status == "passed"
        assert result.score == 92
        assert result.evidence["judge_count"] == 3
        assert result.evidence["scores"] == [92, 93, 91]
    finally:
        service.close()


def test_required_three_judges_continue_after_scored_dependency_violation(
    settings, tmp_path, monkeypatch
):
    service = EvaluationService(settings)
    try:
        service.update_settings(
            {
                "judge_model_id_secondary": "secondary-model",
                "judge_runner_id_secondary": "secondary-runner",
                "judge_model_id_tiebreaker": "third-model",
                "judge_runner_id_tiebreaker": "third-runner",
                "judge_disagreement_threshold": 20,
            }
        )
        calls: list[str] = []
        scores = {"primary": 50, "secondary": 55, "tiebreaker": 45}

        def fake_single(*_args, anonymous_slot="primary", **_kwargs):
            def review(_config, weight):
                calls.append(anonymous_slot)
                score = scores[anonymous_slot]
                return ValidationResult(
                    "ai_rubric",
                    weight,
                    score,
                    "needs_review" if anonymous_slot == "primary" else "passed",
                    {
                        "point_awards": [
                            {
                                "point_id": "p1",
                                "awarded_points": score / 10,
                                "max_points": 10,
                            }
                        ],
                        "review_reasons": (
                            ["dependency_violation"]
                            if anonymous_slot == "primary"
                            else []
                        ),
                    },
                )

            return review

        monkeypatch.setattr(service, "_single_judge_callback", fake_single)
        callback = service._judge_callback(
            {"id": "run-dependency-consensus", "model_id": "candidate-model"},
            {},
            Workspace(tmp_path / "dependency-consensus"),
            lambda *_args: None,
        )
        result = callback(
            {
                "required_judges": 3,
                "judge_disagreement_threshold": 20,
                "marking_mode": "strict_exam",
                "scoring_points": [
                    {"point_id": "p1", "description": "proof", "max_points": 10}
                ],
            },
            100,
        )

        assert calls == ["primary", "secondary", "tiebreaker"]
        assert result.status == "passed"
        assert result.score == 50
        assert result.evidence["judge_count"] == 3
        assert result.evidence["advisory_review_reasons"] == [
            "dependency_violation"
        ]
    finally:
        service.close()


def test_defect_aware_consensus_preserves_one_judges_real_mathematical_defect(
    settings, tmp_path, monkeypatch
):
    service = EvaluationService(settings)
    try:
        service.update_settings(
            {
                "judge_model_id_secondary": "secondary-model",
                "judge_runner_id_secondary": "secondary-runner",
                "judge_model_id_tiebreaker": "third-model",
                "judge_runner_id_tiebreaker": "third-runner",
                "judge_disagreement_threshold": 30,
            }
        )
        reviews = {
            "primary": (10.0, "none"),
            "secondary": (10.0, "none"),
            # The old per-point median erased this unique, valid defect report.
            "tiebreaker": (8.0, "major"),
        }

        def fake_single(*_args, anonymous_slot="primary", **_kwargs):
            def review(_config, weight):
                award, severity = reviews[anonymous_slot]
                return ValidationResult(
                    "ai_rubric",
                    weight,
                    award * 10,
                    "passed",
                    {
                        "point_awards": [
                            {
                                "point_id": "p1",
                                "awarded_points": award,
                                "max_points": 10,
                                "status": "met" if award == 10 else "partial",
                                "confidence": 0.99,
                                "defect_severity": severity,
                            }
                        ],
                        "review_reasons": [],
                    },
                )

            return review

        monkeypatch.setattr(service, "_single_judge_callback", fake_single)
        callback = service._judge_callback(
            {"id": "run-defect-aware", "model_id": "candidate-model"},
            {},
            Workspace(tmp_path / "defect-aware"),
            lambda *_args: None,
        )
        result = callback(
            {
                "required_judges": 3,
                "judge_disagreement_threshold": 30,
                "marking_mode": "strict_exam",
                "consensus_mode": "defect_aware",
                "critical_defect_score_cap": 95,
                "scoring_points": [
                    {
                        "point_id": "p1",
                        "description": "关键证明",
                        "max_points": 10,
                        "critical": True,
                    }
                ],
            },
            100,
        )

        assert result.status == "passed"
        assert result.score == 80
        assert result.evidence["consensus_method"] == (
            "per_point_defect_aware_then_deterministic_sum_and_caps"
        )
        assert result.evidence["critical_defects"] == ["p1"]
        point = result.evidence["point_awards"][0]
        assert point["judge_awards"] == [10, 10, 8]
        assert point["judge_defect_severities"] == ["none", "none", "major"]
        assert point["defect_aware_minimum_applied"] is True
    finally:
        service.close()


def test_rejudge_reuses_committed_seed_for_same_private_math_variant(
    settings, monkeypatch
):
    service = EvaluationService(settings)
    try:
        case = service.database.fetch_one(
            "SELECT id,definition_json FROM test_cases "
            "WHERE slug='sixdim.math.frontier.q20'"
        )
        assert case is not None
        definition = json.loads(case["definition_json"])
        suite_id = new_id()
        service.database.execute(
            "INSERT INTO test_suites(id,name,description,version,builtin,created_at) "
            "VALUES (?,?,?,'3.0.0',0,?)",
            (suite_id, "Variant replay suite", "test", utc_now()),
        )
        service.database.execute(
            "INSERT INTO suite_cases(suite_id,test_case_id,position) VALUES (?,?,0)",
            (suite_id, case["id"]),
        )
        experiment = service.create_experiment(
            ExperimentCreate(
                name="Variant replay experiment",
                suite_id=suite_id,
                participants=[
                    Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)
                ],
            )
        )
        run_id = service.list_runs(experiment["id"])[0]["id"]
        seed = service._validation_seed_for_run(run_id, definition)
        assert seed is not None
        expected_definition, expected_selection = _materialize_private_frontier_variant(
            definition, seed["seed_hex"]
        )
        service.database.execute(
            "UPDATE runs SET status='completed',final_answer='{}',score=0,steps=1,"
            "duration_ms=1,tokens_input=1,tokens_output=1,completed_at=? WHERE id=?",
            (utc_now(), run_id),
        )
        captured: dict[str, object] = {}

        def fake_score(**kwargs):
            captured["definition"] = kwargs["definition"]
            return ScoreResult(score=80, status="scored", components=[], dimensions=[])

        monkeypatch.setattr(service.scoring, "score", fake_score)

        service.rejudge_run(run_id)

        replayed = captured["definition"]
        assert replayed["instruction"] == expected_definition["instruction"]
        assert "_private_frontier_variants" not in replayed
        variant_events = [
            event
            for event in service.get_run_events(run_id, viewer_safe=False)
            if event["event_type"] == "math.variant_selected"
        ]
        assert variant_events[-1]["payload"]["variant_id"] == expected_selection[
            "variant_id"
        ]
        assert variant_events[-1]["payload"]["rejudge"] is True
    finally:
        service.close()


def test_private_file_validator_receives_committed_seed(settings):
    service = EvaluationService(settings)
    try:
        definition = {
            "validators": [
                {
                    "type": "command_metrics",
                    "config": {
                        "command": ["python", "verify.py"],
                        "private_files": {"verify.py": "print('{}')\n"},
                    },
                }
            ]
        }
        run_id = _create_rubric_run(service)

        seed = service._validation_seed_for_run(run_id, definition)

        assert seed is not None
        assert len(seed["seed_hex"]) == 64
        assert len(seed["commitment_sha256"]) == 64
    finally:
        service.close()


def test_judge_failure_retries_once_and_keeps_cli_output_in_evidence(settings, monkeypatch):
    service = EvaluationService(settings)
    try:
        _enable_native_judge(service)
        run = {"id": _create_rubric_run(service), "model_id": MOCK_MODEL_ID,
               "final_answer": "OK"}
        definition = {
            "instruction": "Return OK.",
            "validators": [
                {"type": "ai_rubric", "weight": 100, "config": {"rubric": "quality"}}
            ],
        }
        workspace = Workspace(settings.workspaces_dir / "run-retry")
        calls: list[dict[str, object]] = []

        def failing_twice(**kwargs):
            calls.append(kwargs)
            return CommandResult(False, 1, "", "The command line is too long", 9, "cli_failed")

        monkeypatch.setattr("agentbench.service.run_native_cli", failing_twice)
        callback = service._judge_callback(run, definition, workspace, lambda *_args: None)
        result = callback({}, 100.0)

        assert len(calls) == 2  # retried exactly once
        assert result.status == "needs_review"
        assert "The command line is too long" in result.evidence["reason"]
        assert result.evidence["judge_cli_stderr"].endswith("The command line is too long")
        assert result.evidence["judge_attempts"] == 2

        # Garbled (non-JSON) judge output: raw stdout must survive into evidence.
        calls.clear()

        def garbled(**kwargs):
            calls.append(kwargs)
            return CommandResult(True, 0, "Sorry, I cannot output JSON.", "", 9, None)

        monkeypatch.setattr("agentbench.service.run_native_cli", garbled)
        callback = service._judge_callback(run, definition, workspace, lambda *_args: None)
        result = callback({}, 100.0)

        assert len(calls) == 2
        assert result.status == "needs_review"
        assert result.evidence["judge_cli_stdout"] == "Sorry, I cannot output JSON."

        # Recovery on the retry must score normally.
        calls.clear()
        sequence = [
            CommandResult(False, 1, "", "transient failure", 5, "cli_failed"),
            CommandResult(True, 0, json.dumps({"type": "result", "result": JUDGE_JSON}), "", 8, None),
        ]

        def flaky(**kwargs):
            calls.append(kwargs)
            return sequence.pop(0)

        monkeypatch.setattr("agentbench.service.run_native_cli", flaky)
        callback = service._judge_callback(run, definition, workspace, lambda *_args: None)
        result = callback({}, 100.0)

        assert len(calls) == 2
        assert result.status == "passed"
        assert result.score == 87.0
    finally:
        service.close()


def test_research_judge_receives_complete_priority_deliverables(settings, monkeypatch):
    service = EvaluationService(settings)
    try:
        _enable_native_judge(service)
        run = {
            "id": _create_rubric_run(service),
            "model_id": MOCK_MODEL_ID,
            "final_answer": "Research deliverables completed.",
        }
        definition = {
            "instruction": "Write an evidence-backed decision memo.",
            "metadata": {"capability_dimension": "research_writing"},
            "validators": [
                {"type": "ai_rubric", "weight": 100, "config": {"rubric": "quality"}}
            ],
        }
        workspace = Workspace(settings.workspaces_dir / "research-judge-complete")
        report_tail = "REPORT_END_MARKER"
        claims_tail = "CLAIMS_END_MARKER"
        workspace.write_file("S1_source.md", "source evidence\n" * 800)
        workspace.write_file("report.md", ("decision analysis\n" * 1200) + report_tail)
        workspace.write_file(
            "claims.json", '{"claims":["' + ("supported claim " * 700) + claims_tail + '"]}'
        )

        captured: dict[str, object] = {}

        def fake_run_native_cli(**kwargs):
            captured.update(kwargs)
            return CommandResult(
                True,
                0,
                json.dumps({"type": "result", "result": JUDGE_JSON}) + "\n",
                "",
                12,
                None,
            )

        monkeypatch.setattr("agentbench.service.run_native_cli", fake_run_native_cli)
        callback = service._judge_callback(run, definition, workspace, lambda *_args: None)
        assert callback is not None
        result = callback({"rubric": "quality"}, 100.0)

        assert result.status == "passed"
        judge_prompt = str(captured["stdin_text"])
        assert report_tail in judge_prompt
        assert claims_tail in judge_prompt
        assert judge_prompt.index('"report.md"') < judge_prompt.index('"S1_source.md"')
    finally:
        service.close()


def test_structured_judge_retries_legacy_shape_with_corrective_schema_guidance(
    settings, monkeypatch
):
    service = EvaluationService(settings)
    try:
        _enable_native_judge(service)
        run = {
            "id": _create_rubric_run(service),
            "model_id": MOCK_MODEL_ID,
            "final_answer": "完整解答",
        }
        config = structured_rubric_config(
            version="2025.math1.q17.r1",
            source={
                "source_id": "expert-q17",
                "version": "2025.math1.q17.r1",
                "source_tier": "expert_reconstructed",
            },
            scoring_points=[
                {"point_id": "q17.1", "description": "建立方法", "max_points": 3},
                {"point_id": "q17.2", "description": "完成计算", "max_points": 4},
                {"point_id": "q17.3", "description": "得到结论", "max_points": 3},
            ],
        )
        definition = {
            "instruction": "求定积分并写出过程。",
            "validators": [{"type": "ai_rubric", "weight": 100, "config": config}],
        }
        workspace = Workspace(settings.workspaces_dir / "run-structured-retry")
        valid_result = {
            "schema": RUBRIC_SCHEMA,
            "rubric_version": config["rubric_version"],
            "source_tier": config["source_tier"],
            "solution_path": "reference",
            "points": [
                {
                    "point_id": point["point_id"],
                    "awarded_points": point["max_points"],
                    "status": "met",
                    "confidence": 1,
                    "evidence": "候选答案对应步骤",
                    "rationale": "正确",
                    "propagated_error": False,
                    "independent_work": True,
                }
                for point in config["scoring_points"]
            ],
            "overall_confidence": 1,
            "summary": "逐点评分完成",
            "review_flags": [],
        }
        outputs = [JUDGE_JSON, json.dumps(valid_result, ensure_ascii=False)]
        calls: list[dict[str, object]] = []

        def legacy_then_structured(**kwargs):
            calls.append(kwargs)
            result = outputs.pop(0)
            return CommandResult(
                True,
                0,
                json.dumps({"type": "result", "result": result}, ensure_ascii=False),
                "",
                8,
                None,
            )

        monkeypatch.setattr("agentbench.service.run_native_cli", legacy_then_structured)
        callback = service._judge_callback(run, definition, workspace, lambda *_args: None)
        assert callback is not None
        result = callback(config, 100.0)

        assert len(calls) == 2
        assert result.status == "passed"
        assert result.score == 100
        assert "RUBRIC_RESPONSE_SCHEMA" in str(calls[0]["stdin_text"])
        assert "不要输出旧版 score" in str(calls[1]["stdin_text"])
        assert "不要输出旧版 score" in calls[1]["placeholders"]["prompt"]
    finally:
        service.close()


def test_rejudge_endpoint_rescores_needs_review_run(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        run_id = _create_rubric_run(service)
        service._model_client = lambda _model, _metadata: SequencedClient(["OK"])
        service._execute_run(run_id)
        before = service.get_run(run_id)
        assert before["status"] == "needs_review"
        assert before["final_answer"] == "OK"
        assert before["score"] is None

        judge_model = service.create_model(
            ModelCreate(name="Judge model", model_name="judge-model", api_style="mock")
        )
        service.update_settings(
            {"judge_model_id": judge_model["id"], "judge_runner_id": UNIFIED_RUNNER_ID}
        )
        service._model_client = lambda _model, _metadata: SequencedClient([JUDGE_JSON])

        response = client.post(f"/api/v1/runs/{run_id}/rejudge")
        assert response.status_code == 200
        after = response.json()
        assert after["status"] == "completed"
        assert after["score"] is not None and after["score"] > 0
        assert after["passed"] is True
        assert after["final_answer"] == "OK"  # reused, model not re-run

        service._model_client = lambda _model, _metadata: (_ for _ in ()).throw(
            AssertionError("reuse_judge=true must not call the judge model")
        )
        reused = client.post(f"/api/v1/runs/{run_id}/rejudge?reuse_judge=true")
        assert reused.status_code == 200
        assert reused.json()["score"] == after["score"]


def test_rejudge_recovers_candidate_answer_after_judge_phase_crash(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        run_id = _create_rubric_run(service)
        before = service.get_run(run_id)
        workspace = settings.workspaces_dir / run_id
        workspace.mkdir(parents=True)
        service.database.execute(
            "UPDATE runs SET status='failed',final_answer=NULL,workspace_path=?,"
            "error_code='internal_error',error_message='[Errno 22] Invalid argument',"
            "failure_class='runtime_environment_failure' WHERE id=?",
            (str(workspace), run_id),
        )
        service.database.execute(
            "INSERT INTO run_events(run_id,seq,event_type,payload_json,created_at) "
            "VALUES (?,?,?,?,?)",
            (
                run_id,
                1,
                "live.message",
                json.dumps(
                    {
                        "runner_type": "unified",
                        "text": "OK",
                        "status": "completed",
                    }
                ),
                utc_now(),
            ),
        )
        service.database.execute(
            "INSERT INTO run_events(run_id,seq,event_type,payload_json,created_at) "
            "VALUES (?,?,?,?,?)",
            (run_id, 2, "run.validating", "{}", utc_now()),
        )
        judge_model = service.create_model(
            ModelCreate(name="Judge model", model_name="judge-model", api_style="mock")
        )
        service.update_settings(
            {"judge_model_id": judge_model["id"], "judge_runner_id": UNIFIED_RUNNER_ID}
        )
        service._model_client = lambda _model, _metadata: SequencedClient([JUDGE_JSON])

        response = client.post(f"/api/v1/runs/{run_id}/rejudge")

        assert response.status_code == 200
        recovered = response.json()
        after = recovered
        assert recovered["status"] == "completed"
        assert recovered["final_answer"] == "OK"
        assert recovered["error_code"] is None
        assert recovered["failure_class"] is None
        assert len(after["judge_reviews"]) == 1
        assert {event["event_type"] for event in after["events"]} >= {
            "rejudge.started",
            "run.rejudged",
        }
        ai_component = next(
            item for item in after["validators"] if item["validator_type"] == "ai_rubric"
        )
        assert ai_component["status"] == "passed"
        # experiment aggregation stays consistent
        experiment = service.get_experiment(before["experiment_id"])
        assert experiment["status"] == "completed"


def test_experiment_rejudge_recovers_structured_answers_without_rerunning_model(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        case = service.import_test_case(
            TestCaseImport(
                slug=f"test.structured-rejudge-{new_id()}",
                version="1.0.0",
                category="postgraduate-math",
                title="Structured rejudge",
                instruction='Return {"answer":"B"}.',
                validators=[
                    {
                        "type": "symbolic_json",
                        "weight": 100,
                        "config": {
                            "fields": {
                                "answer": {"kind": "literal", "expected": "B"}
                            }
                        },
                    }
                ],
                limits={"max_steps": 4, "time_target_seconds": 60},
            )
        )
        suite_id = new_id()
        service.database.execute(
            "INSERT INTO test_suites(id,name,description,version,builtin,created_at) "
            "VALUES (?,?,?,'1.0.0',0,?)",
            (suite_id, "Structured Suite", "test", utc_now()),
        )
        service.database.execute(
            "INSERT INTO suite_cases(suite_id,test_case_id,position) VALUES (?,?,0)",
            (suite_id, case["id"]),
        )
        experiment = service.create_experiment(
            ExperimentCreate(
                name="Structured history repair",
                suite_id=suite_id,
                participants=[
                    Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)
                ],
            )
        )
        run_id = service.list_runs(experiment["id"])[0]["id"]
        service.database.execute(
            "UPDATE experiments SET status='running',started_at=? WHERE id=?",
            (utc_now(), experiment["id"]),
        )
        service._model_client = lambda _model, _metadata: SequencedClient(
            ['分析完成。\n```json\n{"answer":"B"}\n```']
        )
        service._execute_run(run_id)
        service.database.execute("UPDATE runs SET score=5.5,passed=0 WHERE id=?", (run_id,))

        response = client.post(f"/api/v1/experiments/{experiment['id']}/rejudge")

        assert response.status_code == 200
        payload = response.json()
        assert payload["updated"] == 1
        assert payload["failed"] == 0
        assert payload["runs"][0]["previous_score"] == 5.5
        assert payload["runs"][0]["score"] > 99
        repaired = service.get_run(run_id)
        assert repaired["passed"] is True
        assert repaired["final_answer"].startswith("分析完成")


def test_rejudge_endpoint_rejects_missing_final_answer_or_wrong_status(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        run_id = _create_rubric_run(service)
        service._model_client = lambda _model, _metadata: SequencedClient(["OK"])
        service._execute_run(run_id)

        # no final_answer -> 409
        service.database.execute(
            "UPDATE runs SET final_answer=NULL,status='completed' WHERE id=?", (run_id,)
        )
        response = client.post(f"/api/v1/runs/{run_id}/rejudge")
        assert response.status_code == 409
        assert response.json()["detail"] == "run_has_no_final_answer"

        # terminal non-reviewable status -> 409
        service.database.execute(
            "DELETE FROM run_events WHERE run_id=? AND "
            "event_type IN ('run.validating','run.judging')",
            (run_id,),
        )
        service.database.execute(
            "UPDATE runs SET final_answer='OK',status='failed' WHERE id=?", (run_id,)
        )
        response = client.post(f"/api/v1/runs/{run_id}/rejudge")
        assert response.status_code == 409
        assert response.json()["detail"] == "run_not_rejudgeable"

        # unknown run -> 404
        missing = client.post("/api/v1/runs/run-missing/rejudge")
        assert missing.status_code == 404


def test_rejudge_keeps_attempt_multiplier(settings):
    service = EvaluationService(settings)
    try:
        run_id = _create_rubric_run(service)
        service._model_client = lambda _model, _metadata: SequencedClient(["OK"])
        service._execute_run(run_id)
        service.database.execute(
            "UPDATE run_attempts SET multiplier=0.85 WHERE run_id=?", (run_id,)
        )
        judge_model = service.create_model(
            ModelCreate(name="Judge model", model_name="judge-model", api_style="mock")
        )
        service.update_settings(
            {"judge_model_id": judge_model["id"], "judge_runner_id": UNIFIED_RUNNER_ID}
        )
        service._model_client = lambda _model, _metadata: SequencedClient([JUDGE_JSON])

        after = service.rejudge_run(run_id)

        raw_attempt = service.database.fetch_one(
            "SELECT raw_score,adjusted_score FROM run_attempts WHERE run_id=?", (run_id,)
        )
        assert after["score"] == round(raw_attempt["raw_score"] * 0.85, 2)
        assert raw_attempt["adjusted_score"] == after["score"]

        service._model_client = lambda _model, _metadata: (_ for _ in ()).throw(
            AssertionError("stored structured judge evidence should be reused")
        )
        reused = service.rejudge_run(run_id, reuse_judge=True)
        assert reused["status"] == "completed"
        assert reused["score"] == after["score"]
        stored_validator = service.database.fetch_one(
            "SELECT evidence_json FROM validator_results "
            "WHERE run_id=? AND validator_type='ai_rubric'",
            (run_id,),
        )
        assert json.loads(stored_validator["evidence_json"])["reused_for_revalidation"] is True
    finally:
        service.close()


def test_rejudge_can_apply_checker_only_current_revision_without_rerunning_model(settings):
    service = EvaluationService(settings)
    try:
        case = service.import_test_case(
            TestCaseImport(
                slug=f"test.evaluator-hotfix-{new_id()}",
                version="1.0.0",
                category="checker-hotfix",
                title="Evaluator hotfix",
                instruction="Return exactly OK.",
                validators=[
                    {"type": "exact_match", "weight": 100, "config": {"expected": "WRONG"}}
                ],
                limits={"max_steps": 4, "time_target_seconds": 60, "token_budget": 1000},
                attempt_policy={"max_attempts": 1, "pass_threshold": 60},
            )
        )
        suite_id = new_id()
        service.database.execute(
            "INSERT INTO test_suites(id,name,description,version,builtin,created_at) "
            "VALUES (?,?,?,'1.0.0',0,?)",
            (suite_id, "Evaluator hotfix suite", "test", utc_now()),
        )
        service.database.execute(
            "INSERT INTO suite_cases(suite_id,test_case_id,position) VALUES (?,?,0)",
            (suite_id, case["id"]),
        )
        experiment = service.create_experiment(
            ExperimentCreate(
                name="Evaluator hotfix experiment",
                suite_id=suite_id,
                participants=[
                    Participant(model_id=MOCK_MODEL_ID, runner_id=UNIFIED_RUNNER_ID)
                ],
            )
        )
        run_id = service.list_runs(experiment["id"])[0]["id"]
        original_revision = service.database.fetch_one(
            "SELECT tr.id FROM test_cases t JOIN test_case_revisions tr "
            "ON tr.test_case_id=t.id AND tr.definition_hash=t.definition_hash WHERE t.id=?",
            (case["id"],),
        )["id"]
        service.database.execute(
            "UPDATE runs SET status='completed',final_answer='OK',score=0,tokens_input=1,"
            "tokens_output=1,duration_ms=1000,steps=1,passed=0,completed_at=? WHERE id=?",
            (utc_now(), run_id),
        )
        service.database.execute(
            "INSERT INTO run_attempts(id,run_id,attempt_no,status,prompt,multiplier,"
            "created_at) VALUES (?,?,1,'completed','Return exactly OK.',0.7,?)",
            (new_id(), run_id, utc_now()),
        )
        current_definition = service.database.fetch_one(
            "SELECT definition_json FROM test_cases WHERE id=?", (case["id"],)
        )["definition_json"]
        definition = json.loads(current_definition)
        definition["validators"][0]["config"]["expected"] = "OK"
        service.database.execute(
            "UPDATE test_cases SET definition_json=? WHERE id=?",
            (json.dumps(definition, ensure_ascii=False), case["id"]),
        )
        service.database.sync_test_case_revisions(case["id"])

        repaired = service.rejudge_run(
            run_id,
            use_current_evaluator=True,
            waive_retry_penalty=True,
        )

        assert repaired["score"] == 99.8
        exact = next(
            item for item in repaired["validators"] if item["validator_type"] == "exact_match"
        )
        assert exact["score"] == 100.0
        assert repaired["test_revision_id"] != original_revision
        events = service.get_run_events(run_id, viewer_safe=False)
        started = next(item for item in events if item["event_type"] == "rejudge.started")
        assert started["payload"]["evaluator_mode"] == "current"
        assert started["payload"]["original_revision_id"] == original_revision
        assert started["payload"]["retry_penalty_waived"] is True
        finished = next(item for item in events if item["event_type"] == "run.rejudged")
        assert finished["payload"]["stored_attempt_multiplier"] == 0.7
        assert finished["payload"]["applied_attempt_multiplier"] == 1.0
    finally:
        service.close()


def test_retry_penalty_waiver_requires_current_evaluator(settings):
    service = EvaluationService(settings)
    try:
        run_id = _create_rubric_run(service)
        with pytest.raises(
            ValueError, match="retry_penalty_waiver_requires_current_evaluator"
        ):
            service.rejudge_run(run_id, waive_retry_penalty=True)
    finally:
        service.close()


def test_current_evaluator_rejudge_rejects_changed_candidate_contract(settings):
    service = EvaluationService(settings)
    try:
        run_id = _create_rubric_run(service)
        run = service.get_run(run_id)
        service.database.execute(
            "UPDATE runs SET status='needs_review',final_answer='OK' WHERE id=?", (run_id,)
        )
        definition = json.loads(
            service.database.fetch_one(
                "SELECT definition_json FROM test_cases WHERE id=?", (run["test_case_id"],)
            )["definition_json"]
        )
        definition["instruction"] = "A materially different task."
        service.database.execute(
            "UPDATE test_cases SET definition_json=? WHERE id=?",
            (json.dumps(definition, ensure_ascii=False), run["test_case_id"]),
        )
        service.database.sync_test_case_revisions(run["test_case_id"])

        with pytest.raises(ValueError, match="current_evaluator_public_contract_changed"):
            service.rejudge_run(run_id, use_current_evaluator=True)
    finally:
        service.close()


def test_timeout_with_preserved_workspace_is_scored_automatically(settings, monkeypatch):
    """A watchdog stop must not turn an already-written coding submission into 0."""
    service = EvaluationService(settings)
    try:
        runner = service.create_runner(
            RunnerCreate(name="Timeout native runner", runner_type="command", executable="native")
        )
        expected_answer = (
            "Agent reached the runtime safety limit; score the preserved workspace "
            "as the submitted coding result."
        )
        case = service.import_test_case(
            TestCaseImport(
                slug=f"test.timeout-salvage-{new_id()}",
                version="1.0.0",
                category="ultra-backend",
                title="Timeout workspace salvage",
                instruction="Write the solution and finish the task.",
                initial_files={"starter.txt": "unchanged"},
                validators=[
                    {
                        "type": "exact_match",
                        "weight": 100,
                        "config": {"expected": expected_answer},
                    }
                ],
                limits={"max_steps": 4, "time_target_seconds": 60},
                attempt_policy={
                    "max_attempts": 1,
                    "pass_threshold": 60,
                    "preserve_workspace": True,
                },
            )
        )
        suite_id = new_id()
        service.database.execute(
            "INSERT INTO test_suites(id,name,description,version,builtin,created_at) "
            "VALUES (?,?,?,'1.0.0',0,?)",
            (suite_id, "Timeout salvage suite", "test", utc_now()),
        )
        service.database.execute(
            "INSERT INTO suite_cases(suite_id,test_case_id,position) VALUES (?,?,0)",
            (suite_id, case["id"]),
        )
        experiment = service.create_experiment(
            ExperimentCreate(
                name="Timeout salvage test",
                suite_id=suite_id,
                participants=[
                    Participant(model_id=MOCK_MODEL_ID, runner_id=runner["id"])
                ],
            )
        )
        run_id = service.list_runs(experiment["id"])[0]["id"]
        service.database.execute(
            "UPDATE experiments SET status='running',started_at=? WHERE id=?",
            (utc_now(), experiment["id"]),
        )

        def timed_out_native_agent(_runner, _model, _definition, workspace, _events, _cancel):
            workspace.write_file("solution.txt", "written before watchdog")
            return AgentResult(
                False,
                "",
                3,
                ModelUsage(input_tokens=12, output_tokens=8),
                1234,
                "runtime_safety_limit",
                "watchdog",
            )

        monkeypatch.setattr(service, "_run_native_agent", timed_out_native_agent)
        service._execute_run(run_id)

        run = service.get_run(run_id)
        assert run["status"] == "completed"
        assert run["score"] > 95.0
        objective = next(
            item for item in run["score_dimensions"] if item["dimension"] == "objective_quality"
        )
        assert objective["score"] == 100.0
        assert run["passed"] is True
        assert run["error_code"] is None
        assert run["final_answer"] == expected_answer
        event_types = {item["event_type"] for item in run["events"]}
        assert {"run.failed", "rejudge.started", "run.timeout_workspace_salvaged"} <= event_types
        # The model attempt remains auditable as a timeout even though its workspace
        # was successfully scored afterwards.
        assert run["attempts"][0]["status"] == "failed"
        assert run["attempts"][0]["raw_score"] > 95.0
        assert (settings.workspaces_dir / run_id / "solution.txt").read_text(encoding="utf-8") == (
            "written before watchdog"
        )
    finally:
        service.close()


def test_timeout_artifact_only_run_is_scored_without_legacy_preserve_flag(
    settings, monkeypatch
):
    """Older Office cases must not discard an already-written artifact at timeout."""
    service = EvaluationService(settings)
    try:
        runner = service.create_runner(
            RunnerCreate(name="Artifact timeout runner", runner_type="command", executable="native")
        )
        case = service.import_test_case(
            TestCaseImport(
                slug=f"test.timeout-artifact-salvage-{new_id()}",
                version="1.0.0",
                category="office-productivity",
                title="Artifact timeout salvage",
                instruction="Write result.docx and finish.",
                initial_files={"starter.txt": "unchanged"},
                validators=[
                    {"type": "file_exists", "weight": 100, "config": {"path": "result.docx"}}
                ],
                limits={"max_steps": 4, "time_target_seconds": 60},
                # Deliberately omit attempt_policy to represent a legacy built-in.
            )
        )
        suite_id = new_id()
        service.database.execute(
            "INSERT INTO test_suites(id,name,description,version,builtin,created_at) "
            "VALUES (?,?,?,'1.0.0',0,?)",
            (suite_id, "Artifact timeout suite", "test", utc_now()),
        )
        service.database.execute(
            "INSERT INTO suite_cases(suite_id,test_case_id,position) VALUES (?,?,0)",
            (suite_id, case["id"]),
        )
        experiment = service.create_experiment(
            ExperimentCreate(
                name="Artifact timeout test",
                suite_id=suite_id,
                participants=[Participant(model_id=MOCK_MODEL_ID, runner_id=runner["id"])],
            )
        )
        run_id = service.list_runs(experiment["id"])[0]["id"]
        service.database.execute(
            "UPDATE experiments SET status='running',started_at=? WHERE id=?",
            (utc_now(), experiment["id"]),
        )

        def timed_out_native_agent(_runner, _model, _definition, workspace, _events, _cancel):
            workspace.write_file("result.docx", "artifact bytes")
            return AgentResult(
                False,
                "",
                3,
                ModelUsage(input_tokens=12, output_tokens=8),
                1234,
                "runtime_safety_limit",
                "watchdog",
            )

        monkeypatch.setattr(service, "_run_native_agent", timed_out_native_agent)
        service._execute_run(run_id)

        run = service.get_run(run_id)
        assert run["status"] == "completed"
        assert run["score"] > 98.0
        assert next(
            item for item in run["validators"] if item["validator_type"] == "file_exists"
        )["score"] == 100.0
        assert run["passed"] is True
        assert run["final_answer"].startswith("Agent reached the runtime safety limit")
        assert "run.timeout_workspace_salvaged" in {
            item["event_type"] for item in run["events"]
        }
    finally:
        service.close()
