from __future__ import annotations

import copy
import json

import pytest

from agentbench.execution import DockerExecutor, Workspace
from agentbench.frontier_v5 import optimize_case
from agentbench.moment_transfer import certificates
from agentbench.research_audit import audit_claim_graph
from agentbench.scoring import ScoringEngine
from agentbench.six_dimension_suite import build_six_dimension_cases


@pytest.mark.parametrize("expression", ["2z-x-y", "-x-y+2z", "2*x3-x1-x2", "2*a3-a1-a2"])
def test_coordinate_equivalence_is_expression_order_independent(expression):
    engine = ScoringEngine(DockerExecutor(executable="missing-docker"))
    result = engine._validate_symbolic_json(
        100,
        {
            "fields": {
                "answer": {
                    "kind": "expression",
                    "expected": "2*a3-a1-a2",
                    "variables": ["a1", "a2", "a3"],
                }
            }
        },
        json.dumps({"answer": expression}),
        None,
    )
    assert result.score == 100


def test_sampling_does_not_accept_an_expression_vanishing_on_old_sample_line():
    engine = ScoringEngine(DockerExecutor(executable="missing-docker"))
    result = engine._validate_symbolic_json(
        100,
        {"fields": {"answer": {"kind": "expression", "expected": "0", "variables": ["x", "y"]}}},
        json.dumps({"answer": "100*y-100*x-31"}),
        None,
    )
    assert result.score == 0


def test_complete_json_larger_than_preview_is_graded_without_truncation(tmp_path):
    workspace = Workspace(tmp_path)
    claims = [
        {
            "id": "c1",
            "claim": "Revenue 12",
            "type": "fact",
            "confidence": "high",
            "citations": ["S1:p1"],
            "depends_on": [],
            "appendix": "x" * 150000,
        }
    ]
    workspace.write_file("report.md", "Revenue 12 [S1:p1]")
    workspace.write_file("claims.json", json.dumps(claims))
    assert len(workspace.read_file("claims.json")) == 100000
    result = ScoringEngine(DockerExecutor(executable="missing-docker"))._validate_research_claims(
        100,
        {"min_claims": 1, "require_claim_graph": True},
        workspace,
        {"initial_files": {"S1.txt": "[p1] Revenue 12"}},
    )
    assert result.score == 100
    assert result.evidence["claim_graph"]["errors"] == []


@pytest.mark.parametrize(
    "claims",
    [
        [{"id": "a", "depends_on": ["missing"]}],
        [{"id": "a", "depends_on": ["a"]}],
        [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}],
        [{"id": "a", "depends_on": []}, {"id": "a", "depends_on": []}],
        [{"id": "a", "depends_on": "b"}],
    ],
)
def test_malformed_claim_graph_cannot_pass(claims):
    assert audit_claim_graph(claims)["score"] == 0


def test_long_valid_graph_does_not_require_python_recursion():
    claims = [{"id": str(i), "depends_on": [str(i - 1)] if i else []} for i in range(2000)]
    assert audit_claim_graph(claims)["score"] == 100


def test_v5_preserves_frontend_and_equalizes_submission_protocol():
    for case in build_six_dimension_cases():
        before = copy.deepcopy(case)
        optimized = optimize_case(case)
        assert case == before
        if case["metadata"]["capability_dimension"] == "creative_frontend":
            assert optimized == case
        else:
            assert optimized["version"] == "5.0.0"
            assert optimized["attempt_policy"]["max_attempts"] == 1
            assert optimized["metadata"]["validation_pairing"] == "experiment-case-repetition/v1"
            for variant in optimized.get("_private_frontier_variants", {}).get("variants", []):
                assert "评测协议 v5" in variant["instruction"]


@pytest.mark.parametrize(
    "weights", [(1, 2, 3, 4, 4, 3, 2, 1), (3, 1, 4, 2, 5, 2, 1, 2), (2, 5, 1, 3, 1, 4, 3, 1)]
)
def test_new_math_bounds_have_exact_primal_and_dual_certificates(weights):
    moments, bounds, segments = certificates(weights)
    for name, answer in bounds.items():
        p = answer["probabilities"]
        c = answer["dual_coefficients"]
        threshold = int(name[-1])
        assert min(p) >= 0
        assert [sum(v * x**k for x, v in enumerate(p)) for k in range(4)] == moments
        assert (
            sum(p[threshold:])
            == answer["value"]
            == sum(a * b for a, b in zip(c, moments, strict=False))
        )
        delta = [sum(c[k] * x**k for k in range(4)) - int(x >= threshold) for x in range(8)]
        assert min(delta) >= 0 if name.startswith("upper") else max(delta) <= 0
    for segment in segments:
        p = segment["probabilities"]
        assert (sum(p[3:]), sum(p[5:])) == segment["line"]
    assert segments[0]["from"] == 0
    assert all(a["from"] < b["from"] for a, b in zip(segments, segments[1:], strict=False))


def test_hidden_data_source_is_syntax_valid():
    for case in build_six_dimension_cases():
        for validator in case["validators"]:
            for filename, source in validator["config"].get("private_files", {}).items():
                compile(source, filename, "exec")


@pytest.mark.parametrize("seed", ["1" * 64, "2" * 64, "3" * 64])
def test_relabelled_scheduler_keeps_a_proven_feasible_witness(monkeypatch, tmp_path, seed):
    from agentbench.ultra_v5 import _scheduler_instance, _scheduler_private_validator

    monkeypatch.setattr("sys.argv", ["evaluate.py", "--seed", seed])
    for size, machines in ((12, 3), (22, 4), (36, 4), (60, 5), (96, 6)):
        instance, witness = _scheduler_instance(
            "test", task_count=size, machine_count=machines, seed=2203
        )
        source = _scheduler_private_validator({"instances": [instance]}).split(
            "hidden_path = private_root", 1
        )[0]
        ns = {"__file__": str(tmp_path / "private" / "evaluate.py")}
        exec(compile(source, "<scheduler-setup>", "exec"), ns)
        result = ns["analyze"](ns["hidden"]["instances"][0], ns["rename"](witness))
        assert result["feasible"], result


def test_pair_seed_shared_only_inside_experiment_case_repetition(settings):
    from fastapi.testclient import TestClient

    from agentbench.api import create_app
    from agentbench.catalog import MOCK_MODEL_ID, SIX_DIMENSION_SUITE_ID, UNIFIED_RUNNER_ID
    from agentbench.schemas import ExperimentCreate

    with TestClient(create_app(settings)) as client:
        service = client.app.state.service
        value = ExperimentCreate(
            name="paired seed regression",
            suite_id=SIX_DIMENSION_SUITE_ID,
            participants=[{"model_id": MOCK_MODEL_ID, "runner_id": UNIFIED_RUNNER_ID}],
            repetitions=2,
        )
        exp = service.create_experiment(value)
        rows = service.database.fetch_all(
            "SELECT * FROM runs WHERE experiment_id=? ORDER BY test_revision_id,repetition",
            (exp["id"],),
        )
        mathematical = [
            r
            for r in rows
            if service._definition_for_run(r)[0]["slug"] == "sixdim.math.moment-duality-transfer"
        ]
        first, second = mathematical
        definition = service._definition_for_run(first)[0]
        s1 = service._validation_seed_for_run(first["id"], definition)
        s2 = service._validation_seed_for_run(second["id"], definition)
        assert s1["seed_hex"] != s2["seed_hex"]
        service.database.execute("UPDATE runs SET repetition=1 WHERE id=?", (second["id"],))
        service.database.execute("DELETE FROM run_validation_seeds WHERE run_id=?", (second["id"],))
        assert (
            service._validation_seed_for_run(second["id"], definition)["seed_hex"] == s1["seed_hex"]
        )


@pytest.mark.parametrize("constant_answer", [False, True])
def test_seeded_experiment_grader_rejects_fixed_sample_answers(
    monkeypatch, capsys, constant_answer
):
    import types

    from agentbench.data_frontier import _experiment_validator

    monkeypatch.setattr("sys.argv", ["validate.py", "--seed", "8" * 64])
    source = _experiment_validator()
    ns = {}
    exec(compile(source.split("try: analyze=", 1)[0], "<setup>", "exec"), ns)
    reference = ns["reference"]
    baseline = reference(ns["payload"]())
    candidate = types.ModuleType("experiment_audit")
    candidate.analyze = (lambda payload: copy.deepcopy(baseline)) if constant_answer else reference
    monkeypatch.setitem(__import__("sys").modules, "experiment_audit", candidate)
    exec(compile(source, "<grader>", "exec"), {})
    payload = json.loads(capsys.readouterr().out.split("AGENTBENCH_METRICS=")[-1])
    if constant_answer:
        assert payload["metrics"]["estimands"] < 20
        assert payload["metrics"]["simpson_validation"] == 0
    else:
        assert all(value == 100 for value in payload["metrics"].values())
