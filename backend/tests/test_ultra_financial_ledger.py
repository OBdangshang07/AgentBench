from __future__ import annotations

from agentbench.ultra_financial_ledger import (
    FINANCIAL_LEDGER_HARD_GATES,
    FINANCIAL_LEDGER_METRICS,
    LEDGER_PUBLIC_SMOKE,
    LEDGER_SCAFFOLD,
    LEDGER_SPEC,
    build_financial_ledger_case,
    build_financial_ledger_catalog,
)

TEST_PRIVATE_REFERENCE = {
    "bundle_id": "backend-ultra-extreme",
    "version": "1.3.0",
    "validator_id": "financial-ledger",
    "manifest_sha256": "a" * 64,
}


def test_financial_ledger_public_definition_has_no_hidden_material():
    case = build_financial_ledger_case(TEST_PRIVATE_REFERENCE)
    assert build_financial_ledger_catalog(TEST_PRIVATE_REFERENCE) == [case]
    assert case["slug"] == "ultra.strong-consistency-financial-ledger-001"
    assert case["version"] == "1.3.0"
    assert case["category"] == "ultra-backend"
    assert set(case["initial_files"]) == {"ledger.py", "app.py", "public_smoke.py", "SPEC.md"}
    assert case["initial_files"]["ledger.py"] == LEDGER_SCAFFOLD
    assert case["initial_files"]["app.py"]
    assert case["initial_files"]["public_smoke.py"] == LEDGER_PUBLIC_SMOKE
    assert case["initial_files"]["SPEC.md"] == LEDGER_SPEC
    assert "postgresql-16" in case["tags"]
    assert case["attempt_policy"] == {
        "max_attempts": 1,
        "pass_threshold": 85,
        "preserve_workspace": True,
    }
    assert case["metadata"]["score_basis"] == "backend_quality_time"
    assert case["metadata"]["quality_weight"] == 95
    assert case["metadata"]["time_weight"] == 5
    assert case["metadata"]["frontier_profile"] == "backend-mastery-gates-v3"
    assert case["metadata"]["mastery_curve"] == "frontier_v1"
    assert case["limits"]["time_target_seconds"] == 2400
    assert case["limits"]["max_runtime_seconds"] == 7200
    assert "demo_actions" not in case["metadata"]
    assert "reference" not in repr(case).lower()
    assert "private_files" not in repr(case)

    command = next(item for item in case["validators"] if item["type"] == "command_metrics")
    assert command["weight"] == 100
    assert len(case["validators"]) == 1
    assert command["config"]["private_validator_ref"] == TEST_PRIVATE_REFERENCE
    assert "private_files" not in command["config"]
    assert command["config"]["critical"] is True
    assert command["config"]["critical_min_score"] == 80
    assert [item["key"] for item in command["config"]["metrics"]] == [
        item["key"] for item in FINANCIAL_LEDGER_METRICS
    ]
    assert command["config"]["hard_caps"] == FINANCIAL_LEDGER_HARD_GATES
    assert {item["metric_key"] for item in command["config"]["metric_caps"]} == {
        "api_business",
        "boundary_contract",
        "concurrency",
        "crash_outbox",
        "restart_recovery",
    }
    assert case["metadata"]["hard_gates"] == [
        "data_loss",
        "duplicate_charge",
        "ledger_imbalance",
        "tenant_escape",
        "protected_files",
    ]


def test_financial_ledger_requires_explicit_private_reference():
    try:
        build_financial_ledger_case()
    except ValueError as exc:
        assert "private_validator_ref" in str(exc)
    else:
        raise AssertionError("public builder must not silently create an unverifiable case")


def test_financial_ledger_public_contract_mentions_postgres_and_audit_requirements():
    spec = LEDGER_SPEC.lower()
    assert "postgresql 16" in spec
    assert "psycopg" in spec
    assert "transactional outbox" in spec
    assert "double-entry" in spec
    assert "legacy_postings" in spec
    assert "hash" in spec and "sha-256" in spec
    assert "ledger_transactions(transaction_id" in spec
    assert "original_transaction_id" in spec
    assert "at most 60 seconds" in spec
    assert "PUBLIC_FINANCIAL_LEDGER_SMOKE_OK" in LEDGER_PUBLIC_SMOKE
    assert "SMOKE_SKIPPED" in LEDGER_PUBLIC_SMOKE
