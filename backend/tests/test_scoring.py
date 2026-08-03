from __future__ import annotations

from agentbench.execution import CommandResult, DockerExecutor, Workspace
from agentbench.scoring import ScoringEngine


def test_deterministic_scoring_and_efficiency(tmp_path):
    workspace = Workspace(tmp_path / "run")
    definition = {
        "limits": {"max_steps": 10, "token_budget": 1000},
        "validators": [{"type": "exact_match", "weight": 90, "config": {"expected": "OK"}}],
    }
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="OK\n",
        workspace=workspace,
        steps=2,
        duration_ms=9_000,
        tokens_input=200,
        tokens_output=50,
    )
    assert score.status == "scored"
    assert score.score == 99.84
    assert score.components[0].evidence["actual"] == "OK"
    assert [item.validator_type for item in score.components[-3:]] == [
        "time_efficiency",
        "step_efficiency",
        "token_efficiency",
    ]
    assert sum(item.weight for item in score.components) == 100


def test_file_validator(tmp_path):
    workspace = Workspace(tmp_path / "run")
    workspace.write_file("result.txt", "done")
    definition = {
        "limits": {"max_steps": 4, "token_budget": 1000},
        "validators": [
            {"type": "file_exists", "weight": 40, "config": {"path": "result.txt"}},
            {
                "type": "file_content",
                "weight": 50,
                "config": {"path": "result.txt", "expected": "done"},
            },
        ],
    }
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=2,
        duration_ms=20_000,
        tokens_input=200,
        tokens_output=50,
    )
    assert score.score == 99.6


def test_private_command_validator_is_injected_then_removed(tmp_path):
    workspace = Workspace(tmp_path / "private-run")

    class FakeDocker:
        def run(self, target, command, _image, **_kwargs):
            private_path = command.split()[-1]
            assert private_path.startswith(".agentbench-private-")
            assert target.read_file(private_path) == "print('private')\n"
            return CommandResult(True, 0, "ok", "", 5)

    definition = {
        "limits": {"max_steps": 4, "token_budget": 1000},
        "validators": [
            {
                "type": "command",
                "weight": 90,
                "config": {
                    "command": "python {private_root}/verify.py",
                    "private_files": {"verify.py": "print('private')\n"},
                },
            }
        ],
    }
    score = ScoringEngine(FakeDocker()).score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
    )

    assert score.status == "scored"
    assert not any(path.startswith(".agentbench-private-") for path in workspace.list_files())


def test_private_metric_validator_returns_continuous_components(tmp_path):
    workspace = Workspace(tmp_path / "metric-run")

    class FakeDocker:
        def run(self, _target, _command, _image, **_kwargs):
            return CommandResult(
                True,
                0,
                'AGENTBENCH_METRICS={"metrics":{"correctness":72.5,"quality":91},"evidence":{"correctness":"partial"}}\n',
                "",
                5,
            )

    definition = {
        "limits": {"max_steps": 4, "token_budget": 1000},
        "validators": [
            {
                "type": "command_metrics",
                "weight": 100,
                "config": {
                    "command": "python {private_root}/verify.py",
                    "private_files": {"verify.py": "print('unused')\n"},
                    "metrics": [
                        {"key": "correctness", "name": "约束正确性", "weight": 70},
                        {"key": "quality", "name": "解质量", "weight": 30},
                    ],
                },
            }
        ],
    }
    score = ScoringEngine(FakeDocker()).score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
    )

    assert score.status == "scored"
    assert [item.validator_type for item in score.components[:2]] == ["约束正确性", "解质量"]
    assert [item.score for item in score.components[:2]] == [72.5, 91.0]
    assert not any(path.startswith(".agentbench-private-") for path in workspace.list_files())


def test_missing_private_metric_protocol_is_platform_failure(tmp_path):
    workspace = Workspace(tmp_path / "metric-platform-run")

    class FakeDocker:
        def run(self, _target, _command, _image, **_kwargs):
            return CommandResult(False, 1, "", "validator bootstrap failed", 5)

    definition = {
        "limits": {"max_steps": 4, "token_budget": 1000},
        "validators": [
            {
                "type": "command_metrics",
                "weight": 100,
                "config": {
                    "command": "python {private_root}/verify.py",
                    "private_files": {"verify.py": "broken"},
                    "metrics": [{"key": "quality", "weight": 100}],
                },
            }
        ],
    }
    score = ScoringEngine(FakeDocker()).score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=1,
        duration_ms=100,
        tokens_input=1,
        tokens_output=1,
    )

    assert score.status == "environment_unavailable"
    assert score.components[0].evidence["error_code"] == "validator_platform_error"


def test_private_metric_timeout_is_candidate_failure(tmp_path):
    workspace = Workspace(tmp_path / "metric-timeout-run")

    class TimeoutDocker:
        def run(self, _target, _command, _image, **_kwargs):
            return CommandResult(False, None, "", "Command timed out", 1000, "command_timeout")

    definition = {
        "limits": {"max_steps": 4, "token_budget": 1000},
        "validators": [
            {
                "type": "command_metrics",
                "weight": 100,
                "config": {
                    "command": "python {private_root}/verify.py",
                    "private_files": {"verify.py": "broken"},
                    "metrics": [{"key": "quality", "weight": 100}],
                },
            }
        ],
    }
    score = ScoringEngine(TimeoutDocker()).score(
        definition=definition,
        final_answer="",
        workspace=workspace,
        steps=1,
        duration_ms=1000,
        tokens_input=1,
        tokens_output=1,
    )

    assert score.status == "scored"
    assert score.components[0].validator_type == "quality"
    assert score.components[0].score == 0
    assert score.components[0].status == "failed"


def test_partial_text_score_is_continuous(tmp_path):
    workspace = Workspace(tmp_path / "run")
    definition = {
        "limits": {"max_steps": 10, "timeout_seconds": 100, "token_budget": 1000},
        "validators": [
            {"type": "exact_match", "weight": 90, "config": {"expected": "READY-001"}}
        ],
    }
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="READY-002",
        workspace=workspace,
        steps=3,
        duration_ms=30_000,
        tokens_input=300,
        tokens_output=50,
    )
    assert score.status == "scored"
    assert 40 < score.score < 65
    assert score.components[0].status == "partial"
    assert 0 < score.components[0].score < 100


def test_json_file_scores_fields_and_accepts_utf8_bom(tmp_path):
    workspace = Workspace(tmp_path / "run")
    workspace.write_file(
        "deliverables/report.json",
        '\ufeff{"total": 12, "region": "west", "refunds": 2}',
    )
    definition = {
        "limits": {"max_steps": 10, "timeout_seconds": 100, "token_budget": 1000},
        "validators": [
            {
                "type": "json_file",
                "weight": 95,
                "config": {
                    "path": "deliverables/report.json",
                    "expected": {
                        "total": 12,
                        "region": "west",
                        "refunds": 2,
                        "high_value": 4,
                    },
                },
            }
        ],
    }
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="done",
        workspace=workspace,
        steps=4,
        duration_ms=25_000,
        tokens_input=250,
        tokens_output=50,
    )
    objective = next(
        item for item in score.dimensions if item.validator_type == "objective_quality"
    )
    assert objective.score == 75
    assert score.components[0].evidence["field_scores"]["high_value"] == 0


def test_time_has_small_but_visible_weight(tmp_path):
    workspace = Workspace(tmp_path / "run")
    definition = {
        "limits": {"max_steps": 10, "timeout_seconds": 100, "token_budget": 1000},
        "validators": [{"type": "exact_match", "weight": 100, "config": {"expected": "OK"}}],
    }
    engine = ScoringEngine(DockerExecutor(executable="missing-docker"))
    fast = engine.score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=2,
        duration_ms=10_000,
        tokens_input=200,
        tokens_output=50,
    )
    slow = engine.score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=2,
        duration_ms=400_000,
        tokens_input=200,
        tokens_output=50,
    )
    assert 0 < fast.score - slow.score <= 3
    time_component = next(
        item for item in fast.components if item.validator_type == "time_efficiency"
    )
    assert time_component.weight == 3


def test_time_target_is_soft_and_uses_logarithmic_penalty(tmp_path):
    workspace = Workspace(tmp_path / "run")
    definition = {
        "limits": {"max_steps": 10, "time_target_seconds": 100, "token_budget": 1000},
        "validators": [{"type": "exact_match", "weight": 100, "config": {"expected": "OK"}}],
    }
    score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=2,
        duration_ms=400_000,
        tokens_input=200,
        tokens_output=50,
    )
    time_component = next(
        item for item in score.components if item.validator_type == "time_efficiency"
    )

    assert score.status == "scored"
    assert time_component.score == 75
    assert time_component.evidence["target_exceeded"] is True
    assert time_component.evidence["elapsed_multiple"] == 4
    assert score.score > 98


def test_token_efficiency_uses_small_weight_and_missing_usage_is_neutral(tmp_path):
    workspace = Workspace(tmp_path / "run")
    definition = {
        "limits": {"max_steps": 10, "timeout_seconds": 100, "token_budget": 1000},
        "validators": [{"type": "exact_match", "weight": 100, "config": {"expected": "OK"}}],
    }
    engine = ScoringEngine(DockerExecutor(executable="missing-docker"))
    efficient = engine.score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=2,
        duration_ms=10_000,
        tokens_input=200,
        tokens_output=50,
    )
    unreported = engine.score(
        definition=definition,
        final_answer="OK",
        workspace=workspace,
        steps=2,
        duration_ms=10_000,
        tokens_input=0,
        tokens_output=0,
    )
    efficient_component = next(
        item for item in efficient.components if item.validator_type == "token_efficiency"
    )
    neutral_component = next(
        item for item in unreported.components if item.validator_type == "token_efficiency"
    )
    assert efficient_component.weight == 1
    assert efficient_component.score == 100
    assert neutral_component.score == 50
    assert efficient.score - unreported.score == 0.5
