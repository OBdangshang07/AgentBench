from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from agentbench.ultra_queue_v1 import (
    QUEUE_APP_SCAFFOLD,
    QUEUE_HARD_CAPS,
    QUEUE_METRICS,
    QUEUE_PRIVATE_VALIDATOR_REF,
    QUEUE_PUBLIC_SMOKE,
    QUEUE_SCHEMA_SQL,
    QUEUE_SPEC,
    QUEUE_TASK_QUEUE_SCAFFOLD,
    build_queue_ultra_case,
    build_queue_ultra_catalog,
)

TEST_PRIVATE_REF = {
    "bundle_id": "backend-ultra-extreme",
    "version": "1.3.0",
    "validator_id": "distributed-task-queue",
    "manifest_sha256": "a" * 64,
}


def test_queue_builder_contains_only_public_material_and_external_validator_ref():
    case = build_queue_ultra_case(TEST_PRIVATE_REF)
    assert build_queue_ultra_catalog(TEST_PRIVATE_REF) == [case]
    assert case["slug"] == "ultra.distributed-task-queue-001"
    assert case["version"] == "1.3.0"
    assert case["category"] == "ultra-backend"
    assert case["metadata"]["estimated_minutes"] == 40
    assert case["metadata"]["score_basis"] == "backend_quality_time"
    assert case["metadata"]["quality_weight"] == 95
    assert case["metadata"]["time_weight"] == 5
    assert case["metadata"]["frontier_profile"] == "backend-mastery-gates-v3"
    assert case["metadata"]["mastery_curve"] == "frontier_v1"
    assert case["attempt_policy"]["max_attempts"] == 1
    assert "multipliers" not in case["attempt_policy"]
    assert "hints" not in case["attempt_policy"]
    assert case["limits"]["time_target_seconds"] == 2400
    assert case["limits"]["max_runtime_seconds"] == 7200
    assert case["limits"]["token_budget"] == 60000
    assert case["limits"]["validator_cpus"] == 4
    assert case["limits"]["validator_memory"] == "8g"
    assert set(case["initial_files"]) == {
        "task_queue.py",
        "app.py",
        "schema.sql",
        "public_smoke.py",
        "SPEC.md",
    }
    assert len(case["validators"]) == 1
    assert case["initial_files"]["task_queue.py"] == QUEUE_TASK_QUEUE_SCAFFOLD
    assert case["initial_files"]["app.py"] == QUEUE_APP_SCAFFOLD
    assert case["initial_files"]["schema.sql"] == QUEUE_SCHEMA_SQL
    assert case["initial_files"]["public_smoke.py"] == QUEUE_PUBLIC_SMOKE
    assert case["initial_files"]["SPEC.md"] == QUEUE_SPEC
    assert "可以修改 schema.sql" in case["instruction"]
    assert "不得修改 SPEC.md 或 public_smoke.py" in case["instruction"]
    protected_reason = next(
        item["reason"] for item in QUEUE_HARD_CAPS if item["key"] == "protected_files"
    )
    assert "schema.sql" not in protected_reason

    command = next(item for item in case["validators"] if item["type"] == "command_metrics")
    config = command["config"]
    assert "private_files" not in config
    assert "private_validator_ref" in config
    assert config["private_validator_ref"] == TEST_PRIVATE_REF
    assert QUEUE_PRIVATE_VALIDATOR_REF is None
    assert len(TEST_PRIVATE_REF["manifest_sha256"]) == 64
    assert all(set(item) == {"key", "max_score", "reason"} for item in config["hard_caps"])
    assert {item["key"] for item in config["hard_caps"]} == {
        "task_loss",
        "stale_lease_overwrite",
        "tenant_escape",
        "protected_files",
    }
    assert config["critical"] is True
    assert config["critical_min_score"] == 80
    assert {item["metric_key"] for item in config["metric_caps"]} == {
        "api_persistence_state_machine",
        "lease_fencing",
        "adversarial_semantics",
        "concurrency_crash_recovery",
        "postgres_restart_recovery",
    }
    assert command["weight"] == 100
    assert "demo_actions" not in case["metadata"]
    assert "demo_response" not in case["metadata"]
    # No reference answer or private validator source is allowed in the public
    # Python module.  The builder carries only the signed bundle coordinates.
    public_text = QUEUE_SPEC + QUEUE_TASK_QUEUE_SCAFFOLD + QUEUE_APP_SCAFFOLD + QUEUE_PUBLIC_SMOKE
    assert "private_files" not in public_text
    assert "AGENTBENCH_METRICS=" not in public_text
    assert "reference implementation" not in public_text.lower()


def test_queue_builder_requires_explicit_private_bundle_pin():
    with pytest.raises(ValueError, match="private_validator_ref"):
        build_queue_ultra_case()


def test_queue_public_contract_mentions_all_required_backend_properties():
    required = [
        "PostgreSQL 16",
        "Redis 7",
        "任务状态机",
        "Fencing Token",
        "IdempotencyConflict",
        "dead_letter",
        "公平",
        "背压",
        "强杀",
        "tenant_id",
        "FOR UPDATE SKIP",
        "1,000-task",
    ]
    assert all(token in QUEUE_SPEC for token in required), [
        token for token in required if token not in QUEUE_SPEC
    ]
    assert [item["key"] for item in QUEUE_METRICS] == [
        "api_persistence_state_machine",
        "lease_fencing",
        "idempotency_retry_dlq",
        "adversarial_semantics",
        "concurrency_crash_recovery",
        "postgres_restart_recovery",
        "dependencies_fairness_backpressure",
        "tenant_security",
        "performance_resources",
        "migration_audit_observability",
    ]
    assert sum(float(item["weight"]) for item in QUEUE_METRICS) == 100
    assert [item["max_score"] for item in QUEUE_HARD_CAPS] == [50, 40, 30, 0]


def test_scaffolds_and_schema_parse_without_private_runtime_material():
    task_tree = ast.parse(QUEUE_TASK_QUEUE_SCAFFOLD)
    app_tree = ast.parse(QUEUE_APP_SCAFFOLD)
    smoke_tree = ast.parse(QUEUE_PUBLIC_SMOKE)
    assert any(isinstance(node, ast.ClassDef) and node.name == "TaskQueue" for node in task_tree.body)
    assert any(isinstance(node, ast.Assign) for node in app_tree.body)
    assert any(isinstance(node, ast.FunctionDef) and node.name == "source" for node in smoke_tree.body)
    assert "CREATE TABLE IF NOT EXISTS tasks" in QUEUE_SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS events" in QUEUE_SCHEMA_SQL
    assert "jsonb" in QUEUE_SCHEMA_SQL
    assert "sqlite" not in QUEUE_SCHEMA_SQL.lower()


def test_private_protection_matches_the_public_edit_contract():
    validator_path = (
        Path(__file__).parents[1]
        / "agentbench"
        / "private_validator_sources"
        / "backend-ultra-extreme"
        / "queue"
        / "validate_queue.py"
    )
    tree = ast.parse(validator_path.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "PROTECTED_FILE_HASHES"
            for target in node.targets
        )
    )
    protected = ast.literal_eval(assignment.value)
    assert set(protected) == {"SPEC.md", "public_smoke.py"}
    assert protected["SPEC.md"] == hashlib.sha256(QUEUE_SPEC.encode()).hexdigest()
    assert protected["public_smoke.py"] == hashlib.sha256(
        QUEUE_PUBLIC_SMOKE.encode()
    ).hexdigest()


def test_public_smoke_rejects_the_unimplemented_scaffold(tmp_path: Path):
    (tmp_path / "task_queue.py").write_text(QUEUE_TASK_QUEUE_SCAFFOLD, encoding="utf-8")
    (tmp_path / "app.py").write_text(QUEUE_APP_SCAFFOLD, encoding="utf-8")
    (tmp_path / "schema.sql").write_text(QUEUE_SCHEMA_SQL, encoding="utf-8")
    smoke = tmp_path / "public_smoke.py"
    smoke.write_text(QUEUE_PUBLIC_SMOKE, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(smoke)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "AssertionError" in result.stderr
