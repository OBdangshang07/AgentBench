"""Public definition for the BACKEND ULTRA financial-ledger challenge.

This opt-in module contains only public contract material.  The PostgreSQL 16
validator and reference implementation are shipped separately as a digest-pinned
local private bundle and are resolved through ``private_validator_ref`` at score
time.  The catalog owner must provide that reference when opting this case in.
"""

from __future__ import annotations

import textwrap
from typing import Any


def _validator(kind: str, weight: float, **config: Any) -> dict[str, Any]:
    return {"type": kind, "weight": weight, "config": config}


LEDGER_SPEC = textwrap.dedent(
    r'''
    # BACKEND ULTRA · Strongly Consistent Financial Ledger v1

    Implement `ledger.py` and `app.py` with Python 3.12, FastAPI-compatible application code,
    `psycopg` 3.2, and PostgreSQL 16.  The evaluator provisions an isolated
    PostgreSQL 16 database and exposes its DSN through `DATABASE_URL`.  Do not use
    SQLite, an in-memory substitute, a process-local lock, network services, or a
    second persistence engine.  The validator opens several independent
    connections and processes against the same database.

    ## Public API

    Keep these exception names and method signatures.  `Ledger(dsn)` receives a
    PostgreSQL DSN; when omitted it may read `DATABASE_URL`.

    ```python
    Ledger(dsn=None)
    create_tenant(tenant_id, currency="USD")
    create_account(tenant_id, account_id, kind="customer", currency="USD")
    deposit(tenant_id, account_id, amount_minor, request_id, metadata=None)
    transfer(tenant_id, source_account_id, destination_account_id,
             amount_minor, request_id, metadata=None)
    refund(tenant_id, account_id, amount_minor, request_id,
           original_transaction_id=None, metadata=None)
    get_balance(tenant_id, account_id)
    list_entries(tenant_id, account_id=None)
    list_outbox(tenant_id, limit=100)
    claim_outbox(tenant_id, worker_id, limit=100, lease_seconds=30)
    ack_outbox(tenant_id, event_id, worker_id)
    audit_head(tenant_id)
    verify_audit_chain(tenant_id)
    close()
    ```

    `app.py` must expose a FastAPI `app` object (and may expose `create_app`).
    The HTTP adapter must provide these JSON routes and delegate to the same
    transactional Ledger implementation; it must not maintain a second state:

    ```text
    GET  /healthz
    POST /v1/tenants
    POST /v1/tenants/{tenant_id}/accounts
    POST /v1/tenants/{tenant_id}/deposit
    POST /v1/tenants/{tenant_id}/transfer
    POST /v1/tenants/{tenant_id}/refund
    GET  /v1/tenants/{tenant_id}/accounts/{account_id}/balance
    GET  /v1/tenants/{tenant_id}/entries
    GET  /v1/tenants/{tenant_id}/outbox
    POST /v1/tenants/{tenant_id}/outbox/claim
    POST /v1/tenants/{tenant_id}/outbox/{event_id}/ack
    GET  /v1/tenants/{tenant_id}/audit/head
    GET  /v1/tenants/{tenant_id}/audit/verify
    ```

    `DATABASE_URL` is the only default connection source.  Map invalid input to
    4xx responses, `InsufficientFunds` to 409, and tenant/idempotency/integrity
    errors to stable JSON error objects without leaking another tenant's data.

    Amounts are positive integers in the smallest currency unit (for example,
    cents).  Reject booleans, floats, strings, zero, and negative values.  IDs and
    request IDs are non-empty strings.  Metadata must be finite, JSON-serializable
    data; canonical JSON uses UTF-8, sorted keys, compact separators, and rejects
    NaN/Infinity.

    Each successful money operation returns a JSON-compatible dict containing at
    least `transaction_id`, `request_id`, `kind`, `amount_minor`, and
    `status="posted"`.  A replay with the same `(tenant_id, request_id)` and the
    same canonical request returns the original result and creates no additional
    transaction, posting, outbox event, or audit row.  A different request under
    that key raises `IdempotencyConflict`.  The same key in another tenant is
    independent.  Failed operations consume no request key and leave no partial
    rows.

    ## Accounting and isolation invariants

    Use integer double-entry postings.  Every transaction has at least two
    postings, debit and credit totals are equal, and a customer account's balance
    is `credits - debits`.  `deposit` and `refund` credit the requested customer
    account against the reserved per-tenant `__settlement__` system account.
    `transfer` debits the source customer and credits the destination customer.
    Customer sources may never go below zero; an unsuccessful transfer raises
    `InsufficientFunds`.  Accounts, transactions, requests, postings, outbox
    events, and audit rows are always tenant-qualified.  An account ID belonging
    to another tenant must not be usable or observable through a different tenant
    and raises `TenantViolation` (or another documented LedgerError without
    disclosing data).

    ## Atomicity, concurrency, and transactional outbox

    A money operation is one PostgreSQL transaction at an isolation level that
    prevents lost updates: idempotency decision, transaction row, all postings,
    account balances, exactly one outbox row, request result, and audit row commit
    together or not at all.  Use row locks (`SELECT ... FOR UPDATE`), a unique
    `(tenant_id, request_id)` constraint, and retry serialization/deadlock errors
    only when the operation can be retried without duplicating a committed request.
    Schema setup/migration must be serialized with a PostgreSQL advisory lock.

    The outbox row has a stable `event_id`, tenant and transaction IDs, canonical
    JSON `payload`, and publication state.  `claim_outbox` leases unpublished rows
    with `FOR UPDATE SKIP LOCKED`; an expired lease is reclaimable.  `ack_outbox`
    requires the tenant and current worker lease, is idempotent after publication,
    and never deletes the event.  Outbox state changes must not alter balances.

    ## Crash recovery and schema

    The required tables are `schema_meta`, `tenants`, `accounts`,
    `ledger_transactions`, `postings`, `idempotency_keys`, `outbox`, and
    `audit_log`.  A fresh database must create them automatically.  A process may
    be terminated before or during COMMIT; after reopening, every visible
    transaction is complete with all dependent rows, and every invisible one is
    absent.  Never repair a partial transaction by silently inventing money.

    A legacy database may contain these tables (and no new tables):

    ```sql
    legacy_accounts(
      tenant_id TEXT, account_id TEXT, kind TEXT, currency TEXT,
      balance_minor BIGINT
    )
    legacy_transactions(
      tx_id TEXT, tenant_id TEXT, kind TEXT, request_id TEXT,
      amount_minor BIGINT, metadata_json TEXT, created_at TIMESTAMPTZ
    )
    legacy_postings(
      tx_id TEXT, tenant_id TEXT, account_id TEXT,
      direction TEXT, amount_minor BIGINT, position INTEGER
    )
    ```

    On first open, migrate all legacy rows losslessly into the required schema,
    preserve transaction IDs and balances, generate one outbox/audit row per
    imported transaction, validate debit/credit totals and legacy balances, and
    make migration atomic and repeat-safe.  Do not drop legacy tables; a second
    open must not duplicate anything.

    ## Hash audit chain

    `audit_log` is a per-tenant sequence starting at zero.  Each row stores the
    canonical event payload, `previous_hash`, and SHA-256 `hash`; the hash covers
    tenant ID, sequence, previous hash, event type, and canonical payload.  Every
    successful money operation adds exactly one row.  `verify_audit_chain` returns
    true only when every row recomputes and links, and raises `IntegrityError` on
    tampering, gaps, or invalid JSON.  `audit_head` returns the latest hash or
    `None` for a tenant with no transactions.

    Run `python public_smoke.py` locally after setting `DATABASE_URL`.  Private
    checks add PostgreSQL multiprocess contention, duplicate-charge races,
    cross-tenant attacks, migration fixtures, outbox leasing, hash tampering,
    and crash/reopen checks.  The private checks are deterministic; hidden data
    and interleavings are not part of the public contract.
    '''
).strip() + "\n"


LEDGER_SCAFFOLD = textwrap.dedent(
    r'''
    """Scaffold for BACKEND ULTRA · PostgreSQL 16 financial ledger."""

    from __future__ import annotations

    from pathlib import Path


    class LedgerError(RuntimeError):
        pass


    class AccountNotFound(LedgerError):
        pass


    class TenantNotFound(LedgerError):
        pass


    class TenantViolation(LedgerError):
        pass


    class IdempotencyConflict(LedgerError):
        pass


    class InsufficientFunds(LedgerError):
        pass


    class ConcurrencyError(LedgerError):
        pass


    class IntegrityError(LedgerError):
        pass


    class LeaseError(LedgerError):
        pass


    class Ledger:
        """Implement the PostgreSQL 16 contract described in SPEC.md."""

        SETTLEMENT_ACCOUNT = "__settlement__"

        def __init__(self, dsn: str | None = None):
            raise NotImplementedError

        def close(self) -> None:
            return None

        def create_tenant(self, tenant_id: str, currency: str = "USD") -> dict:
            raise NotImplementedError

        def create_account(
            self,
            tenant_id: str,
            account_id: str,
            kind: str = "customer",
            currency: str = "USD",
        ) -> dict:
            raise NotImplementedError

        def deposit(
            self,
            tenant_id: str,
            account_id: str,
            amount_minor: int,
            request_id: str,
            metadata: dict | None = None,
        ) -> dict:
            raise NotImplementedError

        def transfer(
            self,
            tenant_id: str,
            source_account_id: str,
            destination_account_id: str,
            amount_minor: int,
            request_id: str,
            metadata: dict | None = None,
        ) -> dict:
            raise NotImplementedError

        def refund(
            self,
            tenant_id: str,
            account_id: str,
            amount_minor: int,
            request_id: str,
            original_transaction_id: str | None = None,
            metadata: dict | None = None,
        ) -> dict:
            raise NotImplementedError

        def get_balance(self, tenant_id: str, account_id: str) -> int:
            raise NotImplementedError

        def list_entries(self, tenant_id: str, account_id: str | None = None) -> list[dict]:
            raise NotImplementedError

        def list_outbox(self, tenant_id: str, limit: int = 100) -> list[dict]:
            raise NotImplementedError

        def claim_outbox(
            self, tenant_id: str, worker_id: str, limit: int = 100, lease_seconds: int = 30
        ) -> list[dict]:
            raise NotImplementedError

        def ack_outbox(self, tenant_id: str, event_id: str, worker_id: str) -> bool:
            raise NotImplementedError

        def audit_head(self, tenant_id: str) -> str | None:
            raise NotImplementedError

        def verify_audit_chain(self, tenant_id: str) -> bool:
            raise NotImplementedError


    __all__ = [
        "AccountNotFound",
        "ConcurrencyError",
        "IdempotencyConflict",
        "InsufficientFunds",
        "IntegrityError",
        "LeaseError",
        "Ledger",
        "LedgerError",
        "TenantNotFound",
        "TenantViolation",
    ]
    '''
).strip() + "\n"


LEDGER_PUBLIC_SMOKE = textwrap.dedent(
    r'''
    import os
    import tempfile
    from pathlib import Path

    from ledger import IdempotencyConflict, Ledger


    # The local public smoke is also useful before a database is provisioned.  The
    # real assertions run whenever the runner supplies PostgreSQL 16's DSN.
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("PUBLIC_FINANCIAL_LEDGER_SMOKE_OK (DATABASE_URL not configured)")
        raise SystemExit(0)

    ledger = Ledger(dsn)
    suffix = next(tempfile._get_candidate_names())
    tenant = "public-" + suffix
    ledger.create_tenant(tenant)
    ledger.create_account(tenant, "alice")
    ledger.create_account(tenant, "bob")

    first = ledger.deposit(tenant, "alice", 1_000, "deposit-1", {"source": "bank"})
    assert first["status"] == "posted"
    assert ledger.deposit(tenant, "alice", 1_000, "deposit-1", {"source": "bank"}) == first
    assert ledger.get_balance(tenant, "alice") == 1_000

    try:
        ledger.deposit(tenant, "alice", 999, "deposit-1")
        raise AssertionError("conflicting idempotency key was accepted")
    except IdempotencyConflict:
        pass

    moved = ledger.transfer(tenant, "alice", "bob", 250, "transfer-1")
    assert moved["amount_minor"] == 250
    assert ledger.get_balance(tenant, "alice") == 750
    assert ledger.get_balance(tenant, "bob") == 250

    pending = ledger.list_outbox(tenant)
    assert len(pending) == 2
    assert all(item["published_at"] is None for item in pending)
    claimed = ledger.claim_outbox(tenant, "smoke-worker", limit=1, lease_seconds=30)
    assert len(claimed) == 1
    assert ledger.ack_outbox(tenant, claimed[0]["event_id"], "smoke-worker") is True
    assert ledger.verify_audit_chain(tenant) is True
    print("PUBLIC_FINANCIAL_LEDGER_SMOKE_OK")
    '''
).strip() + "\n"


APP_SCAFFOLD = textwrap.dedent(
    r'''
    """FastAPI adapter scaffold for the PostgreSQL 16 ledger challenge."""

    from __future__ import annotations

    from fastapi import FastAPI

    from ledger import Ledger


    app = FastAPI(title="Backend Ultra Financial Ledger")


    def get_ledger() -> Ledger:
        """Create a request-safe Ledger facade using DATABASE_URL."""
        raise NotImplementedError


    @app.get("/healthz")
    def healthz() -> dict:
        raise NotImplementedError


    # Implement the routes listed in SPEC.md.  Keep all money mutations in Ledger;
    # do not add an in-memory balance or idempotency cache in this adapter.
    '''
).strip() + "\n"


FINANCIAL_LEDGER_METRICS = [
    {"key": "api_business", "name": "API 与业务流程", "weight": 10},
    {"key": "double_entry", "name": "双重记账与余额不变量", "weight": 18},
    {"key": "transaction_idempotency", "name": "事务幂等与规范 JSON", "weight": 20},
    {"key": "concurrency", "name": "多进程并发转账", "weight": 15},
    {"key": "crash_outbox", "name": "强杀恢复与事务发件箱", "weight": 15},
    {"key": "tenant_security", "name": "租户隔离与安全", "weight": 10},
    {"key": "migration_audit", "name": "迁移与哈希审计", "weight": 5},
    {"key": "performance", "name": "性能", "weight": 5},
    {"key": "observability", "name": "可观测性", "weight": 2},
]


FINANCIAL_LEDGER_HARD_GATES = [
    {
        "key": "data_loss",
        "name": "硬门槛：数据丢失",
        "max_score": 40,
        "reason": "任一已确认账务丢失时最高 40 分",
    },
    {
        "key": "duplicate_charge",
        "name": "硬门槛：重复扣款",
        "max_score": 40,
        "reason": "同一幂等请求产生重复扣款时最高 40 分",
    },
    {
        "key": "ledger_imbalance",
        "name": "硬门槛：账本不平",
        "max_score": 40,
        "reason": "任一交易借贷不平或余额无法由流水重建时最高 40 分",
    },
    {
        "key": "tenant_escape",
        "name": "硬门槛：跨租户越权",
        "max_score": 30,
        "reason": "跨租户读取或写入成功时最高 30 分",
    },
    {
        "key": "protected_files",
        "name": "硬门槛：保护文件被修改",
        "max_score": 0,
        "reason": "修改 SPEC.md 或 public_smoke.py 时不得获得质量分",
    },
]


# The signed bundle is installed into the local private-validator store by the
# runtime.  Keeping None here forces an explicit catalog integration instead of
# accidentally shipping an unverifiable hidden-validator reference.
FINANCIAL_LEDGER_PRIVATE_VALIDATOR_REF: dict[str, str] | None = None


def _private_validator_ref(value: dict[str, Any] | None) -> dict[str, Any]:
    reference = value if value is not None else FINANCIAL_LEDGER_PRIVATE_VALIDATOR_REF
    if not isinstance(reference, dict):
        raise ValueError(
            "financial ledger case requires the digest-pinned private_validator_ref "
            "from the local PostgreSQL validator bundle"
        )
    return dict(reference)


def build_financial_ledger_case(
    private_validator_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an opt-in catalog definition with no hidden source material.

    ``private_validator_ref`` is a digest-pinned reference resolved by
    ``PrivateValidatorStore`` at validation time.  The reference implementation
    and validator files are deliberately not accepted as arguments and are never
    embedded in the public definition.
    """

    reference = _private_validator_ref(private_validator_ref)
    command_validator = _validator(
        "command_metrics",
        100,
        private_validator_ref=reference,
        metrics=FINANCIAL_LEDGER_METRICS,
        hard_caps=FINANCIAL_LEDGER_HARD_GATES,
        critical=True,
        critical_min_score=80,
    )
    return {
        "slug": "ultra.strong-consistency-financial-ledger-001",
        "version": "1.0.0",
        "category": "ultra-backend",
        "title": "BACKEND ULTRA · 强一致金融账本与事务发件箱",
        "description": (
            "在 FastAPI 兼容服务与 PostgreSQL 16 上，测试多租户、双重记账、幂等、"
            "事务发件箱、崩溃恢复、迁移和哈希审计链。"
        ),
        "instruction": (
            "阅读 SPEC.md 并完成 ledger.py，保持 Ledger 的公共 API 和异常名称不变。"
            "先运行 public_smoke.py；公开 smoke 只验证基础契约，任务结束后由独立私有验证器"
            "分项测试多租户隔离、双重记账、幂等、并发、事务 Outbox、崩溃恢复、迁移和审计链。"
            "不得修改 SPEC.md、public_smoke.py，不得识别验证环境、跳过检查或依赖网络。"
        ),
        "tools": ["filesystem", "search", "shell"],
        "limits": {
            "max_steps": 80,
            "time_target_seconds": 2400,
            "max_runtime_seconds": 2400,
            "validator_timeout_seconds": 600,
            "token_budget": 60000,
            "network": "disabled",
            "docker_image": "agentbench/backend-ultra:1.0.0",
            "validator_cpus": 4,
            "validator_memory": "8g",
            "validator_pids_limit": 256,
            "validator_tmpfs": "512m",
        },
        "validators": [command_validator],
        "tags": [
            "ultra",
            "backend",
            "postgresql-16",
            "fastapi",
            "double-entry",
            "multi-tenant",
            "idempotency",
            "transactional-outbox",
            "crash-recovery",
            "migration",
            "hash-chain",
        ],
        "initial_files": {
            "ledger.py": LEDGER_SCAFFOLD,
            "app.py": APP_SCAFFOLD,
            "public_smoke.py": LEDGER_PUBLIC_SMOKE,
            "SPEC.md": LEDGER_SPEC,
        },
        "attempt_policy": {
            "max_attempts": 1,
            "pass_threshold": 85,
            "preserve_workspace": True,
        },
        "metadata": {
            "difficulty": 6,
            "tier": "ultra",
            "estimated_minutes": 40,
            "capability": "strong-consistency-financial-ledger-postgresql16",
            "private_validation": True,
            "score_basis": "backend_quality",
            "deterministic_validation": True,
            "validation_protocol": "seed-committed-ready-kill",
            "scoring_breakdown": FINANCIAL_LEDGER_METRICS,
            "hard_gates": [
                "data_loss",
                "duplicate_charge",
                "ledger_imbalance",
                "tenant_escape",
                "protected_files",
            ],
        },
    }


def build_financial_ledger_catalog(
    private_validator_ref: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return a one-case fragment for explicit parent integration."""

    return [build_financial_ledger_case(private_validator_ref)]


__all__ = [
    "FINANCIAL_LEDGER_HARD_GATES",
    "FINANCIAL_LEDGER_METRICS",
    "FINANCIAL_LEDGER_PRIVATE_VALIDATOR_REF",
    "LEDGER_PUBLIC_SMOKE",
    "LEDGER_SCAFFOLD",
    "LEDGER_SPEC",
    "build_financial_ledger_case",
    "build_financial_ledger_catalog",
]
