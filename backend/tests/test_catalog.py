from __future__ import annotations

import json
import subprocess
import sys

from agentbench.catalog import (
    AIDER_RUNNER_ID,
    CODEX_RUNNER_ID,
    CODING_SUITE_ID,
    FRONTIER_SUITE_ID,
    FULL_SUITE_ID,
    GAUNTLET_LITE_SUITE_ID,
    GAUNTLET_SUITE_ID,
    NCRE_OFFICE_PAPER02_SUITE_ID,
    NCRE_OFFICE_PAPER03_SUITE_ID,
    NCRE_OFFICE_SUITE_ID,
    PLANNING_SUITE_ID,
    PRACTICAL_SUITE_ID,
    REASONING_SUITE_ID,
    SMOKE_SUITE_ID,
    ULTRA_SUITE_ID,
    V2_FULL_SUITE_ID,
    V2_QUICK_SUITE_ID,
    build_catalog,
    build_ultra_catalog,
    seed_builtin_data,
)
from agentbench.execution import DockerExecutor, Workspace
from agentbench.scoring import ScoringEngine, ValidationResult
from agentbench.service import EvaluationService, public_definition


def test_builtin_catalog_contains_two_hundred_twelve_tiered_cases():
    cases = build_catalog()
    assert len(cases) == 212
    assert {case["category"] for case in cases} == {
        "instruction-following",
        "reasoning",
        "tool-use",
        "software-engineering",
        "knowledge-work",
        "data-analysis",
        "agentic-workflow",
        "security",
        "planning",
        "office-exam",
    }
    assert len({case["slug"] for case in cases}) == 212
    assert {case["metadata"]["difficulty"] for case in cases} == {1, 2, 3, 4, 5}
    assert sum(case["metadata"]["difficulty"] == 5 for case in cases) >= 30


def test_data_analysis_cases_use_partial_credit_json_validation():
    data_cases = [case for case in build_catalog() if case["category"] == "data-analysis"]

    assert len(data_cases) == 20
    legacy_cases = [case for case in data_cases if case["version"] == "2.0.0"]
    v3_cases = [case for case in data_cases if case["version"] == "3.0.0"]
    assert len(legacy_cases) == 8
    assert len(v3_cases) == 12
    for case in legacy_cases:
        json_validators = [
            validator for validator in case["validators"] if validator["type"] == "json_file"
        ]
        assert len(json_validators) == 1
        assert json_validators[0]["config"]["path"] == "deliverables/report.json"
        assert set(json_validators[0]["config"]["expected"]) == {
            "total_net",
            "top_region",
            "refunds",
            "high_value_orders",
        }
    assert all(
        any(validator["type"] == "command_metrics" for validator in case["validators"])
        for case in v3_cases
    )
    assert all(case["metadata"]["quality_revision"] == "v3-p1" for case in v3_cases)


def test_reasoning_catalog_covers_advanced_mathematics():
    reasoning = [case for case in build_catalog() if case["category"] == "reasoning"]
    advanced = [
        case
        for case in reasoning
        if str(case["slug"]).startswith("math.") and case["version"] == "3.0.0"
    ]
    upgraded_ode = next(case for case in reasoning if case["slug"] == "math.ode-second-order-ivp")

    assert len(reasoning) == 25
    assert len(advanced) == 20
    assert {case["metadata"]["capability"] for case in advanced} == {
        "integral",
        "differential-calculus",
        "differential-equation",
        "infinite-series",
        "linear-algebra",
    }
    assert sum(case["metadata"]["difficulty"] == 5 for case in advanced) == 16
    assert all(case["validators"][0]["type"] == "symbolic_json" for case in advanced)
    assert all(not any(item["type"] == "exact_match" for item in case["validators"]) for case in advanced)
    assert upgraded_ode["version"] == "3.0.0"
    assert upgraded_ode["validators"][0]["type"] == "symbolic_json"
    assert upgraded_ode["metadata"]["difficulty"] == 5


def test_v3_cross_document_cases_require_evidence_reconciliation():
    cases = [
        case
        for case in build_catalog()
        if case["slug"].startswith("knowledge.cross-document-")
    ]

    assert len(cases) == 15
    assert all(case["version"] == "3.0.0" for case in cases)
    assert all({"changes.jsonl", "signatures.json", "source-policy.json", "RULES.md"} <= set(case["initial_files"]) for case in cases)
    assert all(any(item["type"] == "json_file" for item in case["validators"]) for case in cases)
    assert all(not any(item["type"] == "exact_match" for item in case["validators"]) for case in cases)
    assert all(case["metadata"]["quality_revision"] == "v3-p0" for case in cases)


def test_v3_business_rules_reference_passes_private_metrics(tmp_path):
    cases = [
        case
        for case in build_catalog()
        if case["slug"].startswith("coding.business-rules-")
    ]

    assert len(cases) == 20
    assert all(case["version"] == "3.0.0" for case in cases)
    assert all(case["metadata"]["quality_revision"] == "v3-p0" for case in cases)
    for position, case in enumerate(cases[:2], start=1):
        workspace = tmp_path / f"business-{position}"
        workspace.mkdir()
        for path, content in case["initial_files"].items():
            target = workspace / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        demo = case["metadata"]["demo_actions"][0]["arguments"]
        solution = workspace / demo["path"]
        solution.parent.mkdir(parents=True, exist_ok=True)
        solution.write_text(demo["content"], encoding="utf-8")
        command = next(
            item for item in case["validators"] if item["type"] == "command_metrics"
        )
        assert [item["key"] for item in command["config"]["metrics"]] == [
            "state_machine",
            "idempotency",
            "atomic_sequence",
            "money",
            "concurrency",
            "snapshot_restore",
        ]
        private_root = workspace / ".agentbench-private-test"
        private_root.mkdir()
        validator = private_root / "validate_order_engine.py"
        validator.write_text(
            command["config"]["private_files"]["validate_order_engine.py"],
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(validator)],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        protocol = next(
            line.removeprefix("AGENTBENCH_METRICS=")
            for line in result.stdout.splitlines()
            if line.startswith("AGENTBENCH_METRICS=")
        )
        assert json.loads(protocol)["metrics"] == {
            "state_machine": 100,
            "idempotency": 100,
            "atomic_sequence": 100,
            "money": 100,
            "concurrency": 100,
            "snapshot_restore": 100,
        }


def test_v3_security_reference_passes_combined_attack_metrics(tmp_path):
    cases = [
        case
        for case in build_catalog()
        if case["slug"].startswith("security.hardening-")
    ]

    assert len(cases) == 15
    assert all(case["version"] == "3.0.0" for case in cases)
    assert all(case["metadata"]["quality_revision"] == "v3-p0" for case in cases)
    for position, case in enumerate(cases[:3], start=1):
        workspace = tmp_path / f"security-{position}"
        workspace.mkdir()
        for path, content in case["initial_files"].items():
            target = workspace / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        demo = case["metadata"]["demo_actions"][0]["arguments"]
        solution = workspace / demo["path"]
        solution.write_text(demo["content"], encoding="utf-8")
        public = subprocess.run(
            [sys.executable, "public_smoke.py"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert public.returncode == 0, public.stderr
        assert "PUBLIC_SECURITY_SMOKE_OK" in public.stdout
        command = next(
            item for item in case["validators"] if item["type"] == "command_metrics"
        )
        private_root = workspace / ".agentbench-private-test"
        private_root.mkdir()
        validator = private_root / "validate_secure_gateway.py"
        validator.write_text(
            command["config"]["private_files"]["validate_secure_gateway.py"],
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(validator)],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        protocol = next(
            line.removeprefix("AGENTBENCH_METRICS=")
            for line in result.stdout.splitlines()
            if line.startswith("AGENTBENCH_METRICS=")
        )
        assert json.loads(protocol)["metrics"] == {
            "valid_store": 100,
            "canonicalization": 100,
            "authentication": 100,
            "symlink_containment": 100,
            "atomic_replay": 100,
            "redaction": 100,
        }


def test_v3_planning_reference_is_feasible_and_objectively_scored(tmp_path):
    cases = [
        case
        for case in build_catalog()
        if case["slug"].startswith("planning.delivery-plan-")
    ]

    assert len(cases) == 15
    assert all(case["version"] == "3.0.0" for case in cases)
    assert all(case["metadata"]["quality_revision"] == "v3-p1" for case in cases)
    for position, case in enumerate(cases[:2], start=1):
        workspace = tmp_path / f"planning-{position}"
        workspace.mkdir()
        for path, content in case["initial_files"].items():
            (workspace / path).write_text(content, encoding="utf-8")
        demo = case["metadata"]["demo_actions"][0]["arguments"]
        plan = workspace / demo["path"]
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(demo["content"], encoding="utf-8")
        score = ScoringEngine(DockerExecutor(executable="missing-docker")).score(
            definition=case,
            final_answer="计划已写入 deliverables/plan.json",
            workspace=Workspace(workspace),
            steps=5,
            duration_ms=1000,
            tokens_input=100,
            tokens_output=100,
            judge_callback=lambda _config, judge_weight: ValidationResult(
                "ai_rubric", judge_weight, 100, "passed", {"test": True}
            ),
        )
        constraint_components = [
            item
            for item in score.components
            if item.evidence.get("metric_key") is not None
        ]
        assert [item.evidence["metric_key"] for item in constraint_components] == [
            "coverage",
            "dependencies",
            "resources",
            "budget_deadline",
            "safety_controls",
            "objective_quality",
        ]
        assert all(item.score == 100 for item in constraint_components)


def test_v3_workflow_reference_is_resumable_and_idempotent(tmp_path):
    cases = [
        case
        for case in build_catalog()
        if case["slug"].startswith("workflow.ticket-triage-")
        and case["version"] == "3.0.0"
    ]

    assert [case["slug"] for case in cases] == [
        f"workflow.ticket-triage-{index:03d}" for index in range(9, 16)
    ]
    for position, case in enumerate(cases[:2], start=1):
        workspace = tmp_path / f"workflow-{position}"
        workspace.mkdir()
        for path, content in case["initial_files"].items():
            (workspace / path).write_text(content, encoding="utf-8")
        demo = case["metadata"]["demo_actions"][0]["arguments"]
        (workspace / demo["path"]).write_text(demo["content"], encoding="utf-8")
        public = subprocess.run(
            [sys.executable, "public_smoke.py"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert public.returncode == 0, public.stderr
        assert "PUBLIC_WORKFLOW_SMOKE_OK" in public.stdout
        command = next(
            item for item in case["validators"] if item["type"] == "command_metrics"
        )
        private_root = workspace / ".agentbench-private-test"
        private_root.mkdir()
        validator = private_root / "validate_workflow.py"
        validator.write_text(
            command["config"]["private_files"]["validate_workflow.py"], encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(validator)],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        protocol = next(
            line.removeprefix("AGENTBENCH_METRICS=")
            for line in result.stdout.splitlines()
            if line.startswith("AGENTBENCH_METRICS=")
        )
        assert json.loads(protocol)["metrics"] == {
            "state_transitions": 100,
            "idempotency": 100,
            "partial_failure": 100,
            "incremental_guard": 100,
            "ordering": 100,
            "atomic_outputs": 100,
        }


def test_v3_data_reference_handles_hidden_dirty_data_and_bootstrap(tmp_path):
    cases = [
        case
        for case in build_catalog()
        if case["slug"].startswith("data.orders-analysis-")
        and case["version"] == "3.0.0"
    ]

    assert [case["slug"] for case in cases] == [
        f"data.orders-analysis-{index:03d}" for index in range(9, 21)
    ]
    for position, case in enumerate(cases[:2], start=1):
        workspace = tmp_path / f"data-{position}"
        workspace.mkdir()
        for path, content in case["initial_files"].items():
            (workspace / path).write_text(content, encoding="utf-8")
        demo = case["metadata"]["demo_actions"][0]["arguments"]
        (workspace / demo["path"]).write_text(demo["content"], encoding="utf-8")
        public = subprocess.run(
            [sys.executable, "public_smoke.py"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert public.returncode == 0, public.stderr
        assert "PUBLIC_DATA_SMOKE_OK" in public.stdout
        command = next(
            item for item in case["validators"] if item["type"] == "command_metrics"
        )
        private_root = workspace / ".agentbench-private-test"
        private_root.mkdir()
        validator = private_root / "validate_analytics.py"
        validator.write_text(
            command["config"]["private_files"]["validate_analytics.py"], encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(validator)],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        protocol = next(
            line.removeprefix("AGENTBENCH_METRICS=")
            for line in result.stdout.splitlines()
            if line.startswith("AGENTBENCH_METRICS=")
        )
        assert json.loads(protocol)["metrics"] == {
            "schema_provenance": 100,
            "dedup_temporal": 100,
            "decimal_reconciliation": 100,
            "regional_metrics": 100,
            "bootstrap": 100,
            "edge_reproducibility": 100,
        }


def test_seed_disables_retired_builtin_cases(settings):
    service = EvaluationService(settings)
    try:
        service.database.execute(
            "INSERT INTO test_cases(id,slug,version,category,title,description,definition_json,"
            "builtin,enabled,created_at) VALUES ('retired','retired.case','1','reasoning',"
            "'retired','','{}',1,1,'now')"
        )
        seed_builtin_data(service.database)
        retired = service.database.fetch_one(
            "SELECT enabled FROM test_cases WHERE id='retired'"
        )
        assert retired == {"enabled": 0}
        assert service.dashboard()["test_cases"] == 214
    finally:
        service.close()


def test_ultra_catalog_contains_three_attempt_project_challenges():
    cases = build_ultra_catalog()

    assert len(cases) == 2
    assert {case["metadata"]["difficulty"] for case in cases} == {6}
    assert {case["metadata"]["tier"] for case in cases} == {"ultra"}
    for case in cases:
        assert case["attempt_policy"] == {
            **case["attempt_policy"],
            "max_attempts": 3,
            "pass_threshold": 85,
            "multipliers": [1.0, 0.85, 0.7],
            "preserve_workspace": True,
        }
        assert len(case["attempt_policy"]["hints"]) == 2
        assert any(item["type"] == "command_metrics" for item in case["validators"])
        assert case["version"] == "5.0.0"


def test_ultra_private_validators_are_hidden_and_scheduler_reference_is_feasible(tmp_path):
    event_case, scheduler_case = build_ultra_catalog()

    event_command = next(
        item for item in event_case["validators"] if item["type"] == "command_metrics"
    )
    assert event_command["config"]["private_files"]
    compile(
        event_command["config"]["private_files"]["validate_event_store.py"],
        "validate_event_store.py",
        "exec",
    )
    assert 'sys.path.insert(0, str(workspace))' in event_command["config"][
        "private_files"
    ]["validate_event_store.py"]
    assert [item["key"] for item in event_command["config"]["metrics"]] == [
        "migration_schema",
        "idempotency_json",
        "multiprocess",
        "crash_atomicity",
        "integrity_snapshot",
        "file_integrity",
    ]
    event_workspace = tmp_path / "event"
    event_workspace.mkdir()
    for path, content in event_case["initial_files"].items():
        (event_workspace / path).write_text(content, encoding="utf-8")
    event_demo = event_case["metadata"]["demo_actions"][0]["arguments"]
    (event_workspace / event_demo["path"]).write_text(
        event_demo["content"], encoding="utf-8"
    )
    event_result = subprocess.run(
        [sys.executable, "public_smoke.py"],
        cwd=event_workspace,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert event_result.returncode == 0, event_result.stderr
    assert "PUBLIC_EVENT_STORE_SMOKE_OK" in event_result.stdout

    scheduler_workspace = tmp_path / "scheduler"
    scheduler_workspace.mkdir()
    for path, content in scheduler_case["initial_files"].items():
        target = scheduler_workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    demo = scheduler_case["metadata"]["demo_actions"][0]["arguments"]
    solver = scheduler_workspace / demo["path"]
    solver.parent.mkdir(parents=True, exist_ok=True)
    solver.write_text(demo["content"], encoding="utf-8")
    scheduler_command = next(
        item for item in scheduler_case["validators"] if item["type"] == "command_metrics"
    )
    private_root = scheduler_workspace / ".agentbench-private-test"
    private_root.mkdir()
    private_validator = private_root / "evaluate_solver.py"
    private_validator.write_text(
        scheduler_command["config"]["private_files"]["evaluate_solver.py"],
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(private_validator)],
        cwd=scheduler_workspace,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    protocol = next(
        line.removeprefix("AGENTBENCH_METRICS=")
        for line in result.stdout.splitlines()
        if line.startswith("AGENTBENCH_METRICS=")
    )
    metrics = json.loads(protocol)["metrics"]
    assert metrics == {
        "interface": 100.0,
        "constraint_correctness": 100.0,
        "feasibility": 100.0,
        "optimality": 100.0,
        "stability": 100.0,
    }
    payload = json.loads(scheduler_case["initial_files"]["public_instances.json"])
    assert [len(item["tasks"]) for item in payload["instances"]] == [7, 9]


def test_seeded_suites_have_expected_sizes(settings):
    service = EvaluationService(settings)
    try:
        assert len(service.get_suite(FULL_SUITE_ID)["cases"]) == 100
        assert len(service.get_suite(SMOKE_SUITE_ID)["cases"]) == 12
        assert len(service.get_suite(V2_QUICK_SUITE_ID)["cases"]) == 20
        assert len(service.get_suite(PRACTICAL_SUITE_ID)["cases"]) == 75
        assert len(service.get_suite(FRONTIER_SUITE_ID)["cases"]) == 37
        assert len(service.get_suite(V2_FULL_SUITE_ID)["cases"]) == 212
        assert len(service.get_suite(NCRE_OFFICE_SUITE_ID)["cases"]) == 4
        assert len(service.get_suite(NCRE_OFFICE_PAPER02_SUITE_ID)["cases"]) == 4
        assert len(service.get_suite(NCRE_OFFICE_PAPER03_SUITE_ID)["cases"]) == 4
        assert len(service.get_suite(ULTRA_SUITE_ID)["cases"]) == 2
        assert len(service.get_suite(REASONING_SUITE_ID)["cases"]) == 25
        assert len(service.get_suite(PLANNING_SUITE_ID)["cases"]) == 15
        assert len(service.get_suite(CODING_SUITE_ID)["cases"]) == 20
        gauntlet_cases = service.get_suite(GAUNTLET_SUITE_ID)["cases"]
        gauntlet_lite_cases = service.get_suite(GAUNTLET_LITE_SUITE_ID)["cases"]
        assert 50 <= len(gauntlet_cases) <= 75
        assert len(gauntlet_cases) >= 55
        assert {case["category"] for case in gauntlet_cases}.isdisjoint({"office-exam"})
        assert 50 <= len(gauntlet_lite_cases) <= 75
        assert service.dashboard()["test_cases"] == 214
        suites = {item["id"]: item for item in service.list_suites()}
        assert suites[FRONTIER_SUITE_ID]["difficulty_max"] == 5
        assert suites[PRACTICAL_SUITE_ID]["docker_case_count"] > 0
        assert suites[ULTRA_SUITE_ID]["docker_case_count"] == 2
        assert suites[GAUNTLET_SUITE_ID]["difficulty_min"] >= 4
        assert suites[GAUNTLET_SUITE_ID]["category_count"] >= 5
        assert suites[GAUNTLET_SUITE_ID]["docker_case_count"] > 0
        assert suites[GAUNTLET_LITE_SUITE_ID]["difficulty_min"] >= 4
        assert suites[GAUNTLET_LITE_SUITE_ID]["docker_case_count"] == 0
        valid_ids = {
            row["id"]
            for row in service.database.fetch_all("SELECT id FROM test_cases")
        }
        for case in gauntlet_cases + gauntlet_lite_cases:
            assert case["id"] in valid_ids
        runner_types = {runner["runner_type"] for runner in service.list_runners()}
        assert {
            "opencode_cli",
            "reasonix_cli",
            "gemini_cli",
            "aider_cli",
            "kimi_code_cli",
            "qoder_cli",
        } <= runner_types
    finally:
        service.close()


def test_public_definition_strips_demo_response_reference_answers():
    case = next(
        item
        for item in build_catalog()
        if (item.get("metadata") or {}).get("demo_response")
    )

    public = public_definition(case)

    assert "demo_response" in case["metadata"]
    assert "demo_response" not in (public.get("metadata") or {})


def test_builtin_runner_upgrade_refreshes_code_owned_fields_only(settings):
    service = EvaluationService(settings)
    try:
        service.database.execute(
            "UPDATE agent_runners SET args_json='[\"exec\",\"{prompt}\"]',"
            "env_json='{\"KEEP\":\"yes\"}',limits_json='{\"timeout_seconds\":77}',enabled=0 "
            "WHERE id=?",
            (CODEX_RUNNER_ID,),
        )
        service.database.execute(
            "UPDATE agent_runners SET args_json='[\"--yes\",\"{prompt}\"]' WHERE id=?",
            (AIDER_RUNNER_ID,),
        )
    finally:
        service.close()

    upgraded = EvaluationService(settings)
    try:
        codex = upgraded.database.fetch_one(
            "SELECT * FROM agent_runners WHERE id=?", (CODEX_RUNNER_ID,)
        )
        aider = upgraded.database.fetch_one(
            "SELECT * FROM agent_runners WHERE id=?", (AIDER_RUNNER_ID,)
        )
        assert codex is not None and aider is not None
        assert "--skip-git-repo-check" in codex["args_json"]
        assert codex["env_json"] == '{"KEEP":"yes"}'
        assert codex["limits_json"] == '{"timeout_seconds":77}'
        assert codex["enabled"] == 0
        assert "--no-git" in aider["args_json"]
    finally:
        upgraded.close()
