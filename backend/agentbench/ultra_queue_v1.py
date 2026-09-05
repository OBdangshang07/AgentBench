"""Public definition for the BACKEND ULTRA distributed queue challenge.

The production definition intentionally contains no answer key, reference
implementation, or private validator source.  Those materials belong in the
signed private-validator bundle resolved by ``private_validator_ref`` at run
time.  The module is not imported by the shared catalog until the catalog owner
explicitly opts the case in.
"""

from __future__ import annotations

import textwrap
from typing import Any


def _validator(kind: str, weight: float, **config: Any) -> dict[str, Any]:
    return {"type": kind, "weight": weight, "config": config}


# The signed bundle is installed into the local private-validator store by the
# runtime.  Keeping this unset forces explicit catalog integration instead of
# accidentally shipping an unverifiable hidden-validator reference.
QUEUE_PRIVATE_VALIDATOR_REF: dict[str, str] | None = None


def _private_validator_ref(value: dict[str, Any] | None) -> dict[str, Any]:
    reference = value if value is not None else QUEUE_PRIVATE_VALIDATOR_REF
    if not isinstance(reference, dict):
        raise ValueError(
            "distributed queue case requires the digest-pinned private_validator_ref "
            "from the local PostgreSQL validator bundle"
        )
    return dict(reference)


QUEUE_SPEC = textwrap.dedent(
    r'''
    # BACKEND ULTRA · Distributed Task Queue and Lease Recovery v1

    Build a small production-style task-queue service in the supplied workspace.
    The authoritative state store is **PostgreSQL 16**.  **Redis 7 is only a
    best-effort notification/wakeup layer**: Redis data may be flushed or lost
    and the queue must still recover every task from PostgreSQL.  The service
    must run with Python 3.12, FastAPI, `psycopg` 3, and `redis-py`; do not add
    dependencies, call the network, or replace PostgreSQL with SQLite/in-memory
    state.

    Keep the files and public names below.  You may add helpers, migrations,
    tests, and SQL indexes, but the supplied `public_smoke.py` and this SPEC
    are read-only evaluation material.

    ## Runtime and files

    - `task_queue.py` contains `TaskQueue` and the exception classes.
    - `app.py` exposes a FastAPI object named `app` and the HTTP routes below.
    - `schema.sql` is an optional idempotent migration source; startup must also
      be safe when two app processes initialize concurrently.
    - `DATABASE_URL` points to PostgreSQL 16 and `REDIS_URL` points to Redis 7.
      Optional `QUEUE_LEASE_SECONDS`, `QUEUE_MAX_PENDING`,
      `QUEUE_MAX_PENDING_PER_TENANT`, and `QUEUE_RETRY_BASE_SECONDS` settings
      may configure the service without changing method signatures.  A Redis
      outage must not make a committed task disappear or make a worker unable
      to recover it through PostgreSQL polling.

    Required exceptions: `QueueError`, `DuplicateTask`, `IdempotencyConflict`,
    `Backpressure`, `LeaseLost`, `InvalidTransition`, `TenantForbidden`, and
    `TenantRequired`.

    `TaskQueue` must provide these methods (keyword names are part of the
    contract; return values are JSON-serializable task envelopes):

    ```python
    TaskQueue(database_url=None, redis_url=None, *, lease_seconds=30.0,
              max_pending=10000, max_pending_per_tenant=1000,
              max_attempts=3, retry_base_seconds=1.0)
    submit(tenant_id, task_id, payload, *, idempotency_key=None,
           queue="default", priority=0, run_after=None, depends_on=(),
           max_attempts=None)
    claim(worker_id, *, tenant_id=None, queue="default", now=None)
    claim_many(worker_id, *, limit=1, tenant_id=None, queue="default", now=None)
    heartbeat(task_id, worker_id, fencing_token, *, tenant_id=None,
              extend_by=None, now=None)
    complete(task_id, worker_id, fencing_token, result=None, *, tenant_id=None,
             now=None)
    fail(task_id, worker_id, fencing_token, error, *, retryable=True,
         retry_delay=None, tenant_id=None, now=None)
    cancel(tenant_id, task_id, *, reason=None, now=None)
    expire_leases(*, now=None)
    reconcile(*, tenant_id=None, now=None)
    get(task_id, *, tenant_id=None)
    list_tasks(tenant_id, *, status=None, limit=100)
    stats(*, tenant_id=None)
    events(tenant_id, *, task_id=None, limit=100)
    close()
    ```

    Every `run_after` and `now` argument accepts a `datetime`, an ISO-8601 string
    (including a trailing `Z`), or a Unix timestamp as an `int`/`float`; booleans
    and non-finite numbers are invalid.  Naive datetimes are interpreted as UTC
    and task envelopes serialize timestamps as ISO-8601 strings.  `expire_leases`
    returns the non-negative integer count of leases transitioned by that call.

    ## HTTP contract

    `app.py` must expose `app`.  Use JSON responses and map `TenantForbidden`,
    `TenantRequired`, `LeaseLost`, `InvalidTransition`, and `Backpressure` to
    safe 4xx responses without leaking another tenant's payload.  The following
    routes are mandatory:

    ```text
    GET  /healthz
    POST /v1/tenants/{tenant_id}/tasks
    GET  /v1/tenants/{tenant_id}/tasks/{task_id}
    POST /v1/claim
    POST /v1/tenants/{tenant_id}/tasks/{task_id}/heartbeat
    POST /v1/tenants/{tenant_id}/tasks/{task_id}/complete
    POST /v1/tenants/{tenant_id}/tasks/{task_id}/fail
    POST /v1/tenants/{tenant_id}/tasks/{task_id}/cancel
    POST /v1/maintenance/expire
    GET  /v1/tenants/{tenant_id}/stats
    GET  /v1/tenants/{tenant_id}/events
    ```

    Submit accepts `{task_id, payload, queue?, priority?, run_after?,
    depends_on?, max_attempts?}` and the `Idempotency-Key` header.  Claim accepts
    `{worker_id, tenant_id?, queue?, limit?}` and returns
    `{"tasks": [...]}` (single-claim callers may use the first item).  Heartbeat
    accepts `{worker_id, fencing_token, extend_by?}`.  Complete accepts
    `{worker_id, fencing_token, result}`.  Fail accepts
    `{worker_id, fencing_token, error, retryable?, retry_delay?}`.  Cancel accepts
    `{reason?}`.  Every task envelope includes `tenant_id`, `task_id`, `status`,
    `queue`, `priority`, `payload`, `dependencies`, `attempt`, `max_attempts`,
    `lease_owner`, `lease_until`, `fencing_token`, `result`, `error`,
    `created_at`, and `updated_at`.

    ## 任务状态机、State machine and PostgreSQL schema

    A task starts `pending`, becomes `leased` only inside the claim transaction,
    and may finish as `succeeded`, `cancelled`, or `dead_letter`; a retryable
    failure or expired lease enters `retry_wait` before it can be claimed again.
    Terminal states never become runnable.  Store payload/result/error as
    `jsonb`, timestamps as `timestamptz`, and identifiers as bound parameters.
    The `tasks` table must have a tenant/task key, a unique
    `(tenant_id,idempotency_key)` constraint (for non-null keys), indexes for
    due work and tenant/state, and a monotonic `fencing_token`.

    Dependencies refer to existing tasks in the same tenant.  Reject missing,
    duplicate, self, cross-tenant, or cyclic dependencies.  Missing/cross-tenant
    dependencies raise either `KeyError` or `InvalidTransition`; callers must not
    receive the other tenant's payload or status.  A task is eligible
    only when all dependencies are `succeeded`; if one becomes `cancelled` or
    `dead_letter`, atomically propagate the dependent to `dead_letter` with a
    machine-readable error.  A dependency check must not be implemented by a
    stale cache.

    ## Lease、Fencing Token 与 exactly-once state transitions

    Claim uses a PostgreSQL write transaction and row locks (`FOR UPDATE SKIP
    LOCKED` or an equally safe scheme).  It increments `attempt` and the
    per-task `fencing_token` in the same commit that stores `lease_owner` and
    the absolute `lease_until`.  Heartbeat extends only the current owner and
    token.  Complete/fail after expiry, after another worker claims the task,
    or with an old token must raise `LeaseLost` and must not change the result,
    status, attempt, or event log.  A successful complete replay by the same
    worker and token is idempotent; a different token/owner is rejected.

    Retry uses deterministic exponential backoff (`retry_base_seconds * 2**(n-1)`)
    unless an explicit non-negative delay is supplied.  Once `attempt` reaches
    `max_attempts`, a failure or lease expiry goes to the DLQ.  Each committed
    transition writes exactly one `events` row in the same PostgreSQL
    transaction.  Event payloads must not contain another tenant's task data.
    The stable event names are `submitted`, `claimed`, `heartbeat`, `completed`,
    `failed_retry`, `failed_dlq`, `lease_expired_retry`, `lease_expired_dlq`,
    `dependency_failed`, and `cancelled`.  Implementations need emit only the
    events reached by an operation, but must use these names for those transitions.

    ## 幂等、安全、公平与背压（Idempotency, security, fairness, and backpressure）

    Canonical JSON uses UTF-8, sorted keys, compact separators, and rejects
    NaN/Infinity.  Replaying an equivalent request with the same tenant-scoped
    idempotency key returns the original envelope; changing task id, payload,
    dependencies, queue, priority, scheduling, or attempt policy raises
    `IdempotencyConflict`.  Task ids and tenant ids are bounded and validated.

    Tenant-scoped routes and methods must enforce the path/header tenant before
    reading or mutating task data.  An unscoped lookup is permitted only when a
    task id is unambiguous; otherwise raise `TenantRequired`.  Never use a
    client-provided tenant in a SQL identifier or interpolate SQL strings.

    With no tenant filter, choose eligible tenants using a persistent
    PostgreSQL fair cursor/served sequence, then choose highest priority and
    FIFO order within that tenant.  A continuously refilled tenant must not
    starve a tenant with an eligible task.  Atomically enforce global
    `max_pending` and per-tenant `max_pending_per_tenant`; pending, retry-wait,
    and leased tasks count, terminal tasks do not.  Raise `Backpressure` without
    inserting when either limit is reached.  Redis `PUBLISH`/streams may wake
    workers but cannot be used as the source of truth for claim or recovery.

    ## 崩溃、强杀、迁移与性能（Crash, migration, and performance requirements）

    Use a connection pool or short-lived connections with `READ COMMITTED`,
    `statement_timeout`, and retryable serialization/lock handling.  Run
    migrations transactionally and make startup idempotent.  A process kill
    before commit may lose that one uncommitted request, but may never expose a
    half task, a lease without its token, an event without its state change, or
    a task missing from PostgreSQL.  After killing a worker, another process
    must expire and reclaim its lease without Redis state.

    `stats` reports every state and active/total counts.  `events` exposes an
    ordered audit trail for the requested tenant.  The validator runs concurrent
    HTTP clients, deliberately drops/flushed Redis, kills workers at lease
    boundaries, races stale completions, tests dependency cascades and fairness,
    and submits a bounded 1,000-task workload.  Full performance credit requires
    submitting all 1,000 tasks within 60 seconds and completing the full workload
    within 120 seconds; a slower correct workload receives partial credit.  Run
    `python public_smoke.py` before handing in the service.  The smoke rejects an
    untouched `NotImplemented` scaffold.  With `DATABASE_URL` configured it also
    runs a real submit/claim/complete/reopen flow; otherwise it reports
    `PUBLIC_QUEUE_SMOKE_STATIC_ONLY` rather than claiming a database pass.
    '''
).strip() + "\n"


QUEUE_SCHEMA_SQL = textwrap.dedent(
    r'''
    -- Public schema contract.  Candidates may split this into migrations.
    CREATE TABLE IF NOT EXISTS tasks (
        tenant_id text NOT NULL,
        task_id text NOT NULL,
        payload jsonb NOT NULL,
        queue_name text NOT NULL DEFAULT 'default',
        priority integer NOT NULL DEFAULT 0,
        status text NOT NULL CHECK (status IN
            ('pending','leased','retry_wait','succeeded','dead_letter','cancelled')),
        created_at timestamptz NOT NULL DEFAULT now(),
        run_after timestamptz NOT NULL DEFAULT now(),
        attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
        max_attempts integer NOT NULL CHECK (max_attempts > 0),
        lease_owner text,
        lease_until timestamptz,
        fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
        completion_owner text,
        completion_token bigint,
        result jsonb,
        error jsonb,
        idempotency_key text,
        request_hash text NOT NULL,
        dependencies jsonb NOT NULL DEFAULT '[]'::jsonb,
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id, task_id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS tasks_tenant_idempotency_idx
        ON tasks (tenant_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL;
    CREATE INDEX IF NOT EXISTS tasks_due_idx
        ON tasks (queue_name, status, run_after, priority DESC, created_at);
    CREATE INDEX IF NOT EXISTS tasks_tenant_state_idx
        ON tasks (tenant_id, status, run_after);
    CREATE TABLE IF NOT EXISTS queue_tenant_cursor (
        queue_name text NOT NULL,
        tenant_id text NOT NULL,
        last_served bigint NOT NULL DEFAULT 0,
        served_count bigint NOT NULL DEFAULT 0,
        PRIMARY KEY (queue_name, tenant_id)
    );
    CREATE TABLE IF NOT EXISTS queue_dispatch_sequence (
        singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
        value bigint NOT NULL DEFAULT 0
    );
    INSERT INTO queue_dispatch_sequence(singleton, value)
        VALUES (true, 0) ON CONFLICT (singleton) DO NOTHING;
    CREATE TABLE IF NOT EXISTS events (
        seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id text NOT NULL,
        task_id text NOT NULL,
        event_type text NOT NULL,
        payload jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (tenant_id, task_id)
            REFERENCES tasks(tenant_id, task_id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS events_tenant_task_idx
        ON events (tenant_id, task_id, seq);
    '''
).strip() + "\n"


QUEUE_TASK_QUEUE_SCAFFOLD = textwrap.dedent(
    r'''
    """PostgreSQL-backed task queue starter for BACKEND ULTRA."""

    from __future__ import annotations

    # The validator image provides psycopg 3 and redis-py.  Keep PostgreSQL as
    # the source of truth; Redis is only a best-effort notification client.
    import psycopg
    import redis
    from typing import Any


    class QueueError(RuntimeError):
        pass


    class DuplicateTask(QueueError):
        pass


    class IdempotencyConflict(QueueError):
        pass


    class Backpressure(QueueError):
        pass


    class LeaseLost(QueueError):
        pass


    class InvalidTransition(QueueError):
        pass


    class TenantForbidden(QueueError):
        pass


    class TenantRequired(QueueError):
        pass


    class TaskQueue:
        """Implement the SPEC with PostgreSQL as the source of truth.

        Redis is a notification hint only.  Do not put task state in process
        globals or make correctness depend on a Redis key/stream surviving.
        """

        def __init__(self, database_url=None, redis_url=None, *, lease_seconds=30.0,
                     max_pending=10000, max_pending_per_tenant=1000,
                     max_attempts=3, retry_base_seconds=1.0):
            raise NotImplementedError

        def submit(self, tenant_id, task_id, payload, *, idempotency_key=None,
                   queue="default", priority=0, run_after=None, depends_on=(),
                   max_attempts=None):
            raise NotImplementedError

        def claim(self, worker_id, *, tenant_id=None, queue="default", now=None):
            raise NotImplementedError

        def claim_many(self, worker_id, *, limit=1, tenant_id=None,
                       queue="default", now=None):
            raise NotImplementedError

        def heartbeat(self, task_id, worker_id, fencing_token, *, tenant_id=None,
                      extend_by=None, now=None):
            raise NotImplementedError

        def complete(self, task_id, worker_id, fencing_token, result=None, *,
                     tenant_id=None, now=None):
            raise NotImplementedError

        def fail(self, task_id, worker_id, fencing_token, error, *, retryable=True,
                 retry_delay=None, tenant_id=None, now=None):
            raise NotImplementedError

        def cancel(self, tenant_id, task_id, *, reason=None, now=None):
            raise NotImplementedError

        def expire_leases(self, *, now=None):
            raise NotImplementedError

        def reconcile(self, *, tenant_id=None, now=None):
            raise NotImplementedError

        def get(self, task_id, *, tenant_id=None):
            raise NotImplementedError

        def list_tasks(self, tenant_id, *, status=None, limit=100):
            raise NotImplementedError

        def stats(self, *, tenant_id=None):
            raise NotImplementedError

        def events(self, tenant_id, *, task_id=None, limit=100):
            raise NotImplementedError

        def close(self):
            raise NotImplementedError


    # Optional compatibility alias; the class above remains authoritative.
    DurableTaskQueue = TaskQueue
    '''
).strip() + "\n"


QUEUE_APP_SCAFFOLD = textwrap.dedent(
    r'''
    """FastAPI transport starter for BACKEND ULTRA."""

    from fastapi import FastAPI

    from task_queue import TaskQueue


    app = FastAPI(title="Durable Task Queue")
    queue = TaskQueue()


    @app.get("/healthz")
    def healthz():
        raise NotImplementedError


    # Implement the remaining routes and request validation from SPEC.md:
    # /v1/tenants/{tenant_id}/tasks, /v1/claim,
    # /v1/tenants/{tenant_id}/tasks/{task_id}/heartbeat,
    # /v1/tenants/{tenant_id}/tasks/{task_id}/complete,
    # /v1/tenants/{tenant_id}/tasks/{task_id}/fail,
    # /v1/tenants/{tenant_id}/tasks/{task_id}/cancel,
    # /v1/maintenance/expire, /v1/tenants/{tenant_id}/stats, and
    # /v1/tenants/{tenant_id}/events.
    '''
).strip() + "\n"


QUEUE_PUBLIC_SMOKE = textwrap.dedent(
    r'''
    """Public contract smoke with an optional live PostgreSQL/Redis flow."""

    import ast
    import os
    import tempfile
    from pathlib import Path


    def source(path):
        return Path(path).read_text(encoding="utf-8")


    task_source = source("task_queue.py")
    task_tree = ast.parse(task_source)
    classes = {node.name: node for node in task_tree.body if isinstance(node, ast.ClassDef)}
    assert "TaskQueue" in classes
    task_methods = {
        node.name
        for node in classes["TaskQueue"].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {
        "submit", "claim", "claim_many", "heartbeat", "complete", "fail",
        "cancel", "expire_leases", "reconcile", "get", "list_tasks", "stats",
        "events", "close",
    } <= task_methods

    def is_unimplemented(method):
        return any(
            isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Name)
            and node.exc.id == "NotImplementedError"
            for node in ast.walk(method)
        )

    required_methods = {
        "submit", "claim", "claim_many", "heartbeat", "complete", "fail",
        "cancel", "expire_leases", "reconcile", "get", "list_tasks", "stats",
        "events", "close",
    }
    implementations = {
        node.name: node
        for node in classes["TaskQueue"].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not [name for name in required_methods if is_unimplemented(implementations[name])]
    assert "psycopg" in task_source.lower()
    assert "redis" in task_source.lower()
    assert "sqlite3" not in task_source.lower()

    app_source = source("app.py")
    app_tree = ast.parse(app_source)
    assert any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "app" for target in node.targets)
        for node in app_tree.body
    )
    route_literals = set()
    for node in ast.walk(app_tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in {"get", "post", "put", "delete", "patch"}
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                route_literals.add(decorator.args[0].value)
    for route in (
        "/healthz",
        "/v1/claim",
        "/v1/maintenance/expire",
        "/v1/tenants/{tenant_id}/tasks",
        "/v1/tenants/{tenant_id}/tasks/{task_id}/heartbeat",
        "/v1/tenants/{tenant_id}/tasks/{task_id}/complete",
        "/v1/tenants/{tenant_id}/tasks/{task_id}/fail",
        "/v1/tenants/{tenant_id}/tasks/{task_id}/cancel",
    ):
        assert route in route_literals

    schema = source("schema.sql").lower()
    assert "create table if not exists tasks" in schema
    assert "jsonb" in schema and "fencing_token" in schema
    assert "create table if not exists events" in schema
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("PUBLIC_QUEUE_SMOKE_STATIC_ONLY: set DATABASE_URL for the live flow")
        raise SystemExit(0)

    from task_queue import TaskQueue

    redis_url = os.environ.get("REDIS_URL")
    suffix = next(tempfile._get_candidate_names())
    tenant = "public-" + suffix
    task_id = "task-" + suffix
    queue = TaskQueue(database_url, redis_url, lease_seconds=5)
    first = queue.submit(tenant, task_id, {"smoke": True}, run_after=0)
    replay = queue.get(task_id, tenant_id=tenant)
    assert replay["task_id"] == first["task_id"] and replay["status"] == "pending"
    claimed = queue.claim("public-worker", tenant_id=tenant)
    assert claimed and claimed["task_id"] == task_id and claimed["status"] == "leased"
    completed = queue.complete(
        task_id, "public-worker", claimed["fencing_token"], {"ok": True}, tenant_id=tenant
    )
    assert completed["status"] == "succeeded"
    queue.close()
    reopened = TaskQueue(database_url, redis_url)
    assert reopened.get(task_id, tenant_id=tenant)["status"] == "succeeded"
    reopened.close()
    print("PUBLIC_QUEUE_SMOKE_OK")
    '''
).strip() + "\n"


QUEUE_METRICS = [
    {
        "key": "api_persistence_state_machine",
        "name": "API、持久化与任务状态机",
        "weight": 10,
    },
    {"key": "lease_fencing", "name": "Lease、心跳与 Fencing Token", "weight": 16},
    {
        "key": "idempotency_retry_dlq",
        "name": "幂等、重试与 DLQ",
        "weight": 10,
    },
    {
        "key": "adversarial_semantics",
        "name": "逻辑时钟、边界输入与优先级语义",
        "weight": 10,
    },
    {
        "key": "concurrency_crash_recovery",
        "name": "并发安全与强杀恢复",
        "weight": 16,
    },
    {"key": "postgres_restart_recovery", "name": "PostgreSQL 强制重启恢复", "weight": 14},
    {
        "key": "dependencies_fairness_backpressure",
        "name": "依赖、公平调度与背压",
        "weight": 10,
    },
    {"key": "tenant_security", "name": "租户隔离与安全", "weight": 5},
    {"key": "performance_resources", "name": "性能与资源约束", "weight": 4},
    {
        "key": "migration_audit_observability",
        "name": "迁移、审计与可观测性",
        "weight": 5,
    },
]


QUEUE_HARD_CAPS = [
    {
        "key": "task_loss",
        "max_score": 50,
        "reason": "任务丢失或 PostgreSQL 核心状态损坏，综合分最高 50",
    },
    {
        "key": "stale_lease_overwrite",
        "max_score": 40,
        "reason": "旧租约/旧 fencing token 覆盖新结果，综合分最高 40",
    },
    {
        "key": "tenant_escape",
        "max_score": 30,
        "reason": "跨租户读取或变更成功，综合分最高 30",
    },
    {
        "key": "protected_files",
        "max_score": 0,
        "reason": "修改 SPEC.md 或 public_smoke.py，综合分为 0",
    },
]


def build_queue_ultra_case(
    private_validator_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a public definition with an explicit private-validator reference."""

    reference = _private_validator_ref(private_validator_ref)

    return {
        "slug": "ultra.distributed-task-queue-001",
        "version": "1.3.0",
        "category": "ultra-backend",
        "title": "BACKEND ULTRA · 分布式任务队列与租约恢复",
        "description": (
            "以 PostgreSQL 16 为权威状态存储、Redis 7 为可丢失通知层，"
            "在 FastAPI 服务中实现 Lease/Fencing Token、幂等、重试/DLQ、依赖、公平调度、背压、租户隔离和多进程强杀恢复。"
        ),
        "instruction": (
            "阅读 SPEC.md，在 task_queue.py 和 app.py 中完成 PostgreSQL 16 + Redis 7 任务队列。"
            "运行 python public_smoke.py 检查公开契约；私有验证器会在统一 Docker 服务中启动 FastAPI、PostgreSQL 和 Redis，"
            "执行并发、强杀、旧租约、依赖、公平性、背压、安全和性能测试。"
            "可以修改 schema.sql 或添加迁移与索引；不得修改 SPEC.md 或 public_smoke.py。"
        ),
        "tools": ["filesystem", "search", "shell"],
        "limits": {
            "max_steps": 160,
            "time_target_seconds": 2400,
            "max_runtime_seconds": 7200,
            "validator_timeout_seconds": 900,
            "validator_cpus": 4,
            "validator_memory": "8g",
            "validator_pids_limit": 256,
            "validator_tmpfs": "512m",
            "token_budget": 60000,
            "network": "disabled",
            "docker_image": "agentbench/backend-ultra:1.0.0",
        },
        "validators": [
            _validator(
                "command_metrics",
                100,
                private_validator_ref=reference,
                metrics=QUEUE_METRICS,
                hard_caps=QUEUE_HARD_CAPS,
                metric_caps=[
                    {
                        "metric_key": "api_persistence_state_machine",
                        "min_score": 100,
                        "max_score": 75,
                        "reason": "API、持久化或状态机任一不完整时最高 75 分",
                    },
                    {
                        "metric_key": "lease_fencing",
                        "min_score": 100,
                        "max_score": 70,
                        "reason": "Lease 或 Fencing Token 语义不完整时最高 70 分",
                    },
                    {
                        "metric_key": "adversarial_semantics",
                        "min_score": 100,
                        "max_score": 85,
                        "reason": "逻辑时间、非有限输入、规范 JSON 或优先级语义存在缺口",
                    },
                    {
                        "metric_key": "concurrency_crash_recovery",
                        "min_score": 100,
                        "max_score": 75,
                        "reason": "并发、强杀或 Redis 丢失恢复未全部成立",
                    },
                    {
                        "metric_key": "postgres_restart_recovery",
                        "min_score": 100,
                        "max_score": 65,
                        "reason": "PostgreSQL 强制重启后任务、租约、幂等或事件记录未完整恢复",
                    },
                ],
                critical=True,
                critical_min_score=80,
            ),
        ],
        "tags": [
            "ultra",
            "backend",
            "fastapi",
            "postgresql-16",
            "redis-7",
            "distributed-systems",
            "lease",
            "fencing-token",
            "idempotency",
            "retry",
            "dead-letter",
            "dependencies",
            "fairness",
            "backpressure",
            "multiprocessing",
            "tenant-isolation",
        ],
        "initial_files": {
            "task_queue.py": QUEUE_TASK_QUEUE_SCAFFOLD,
            "app.py": QUEUE_APP_SCAFFOLD,
            "schema.sql": QUEUE_SCHEMA_SQL,
            "public_smoke.py": QUEUE_PUBLIC_SMOKE,
            "SPEC.md": QUEUE_SPEC,
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
            "capability": "postgresql-redis-distributed-queue-recovery",
            "capability_dimension": "systems_backend",
            "private_validation": True,
            "score_basis": "backend_quality_time",
            "mastery_curve": "frontier_v1",
            "quality_weight": 95,
            "time_weight": 5,
            "frontier_profile": "backend-mastery-gates-v3",
            "runtime_policy": "40-minute-soft-target-120-minute-safety-cap",
            "deterministic_validation": True,
            "validation_protocol": "seed-committed-ready-kill",
            "scoring_breakdown": QUEUE_METRICS,
            "hard_gates": [
                "task_loss",
                "stale_lease_overwrite",
                "tenant_escape",
                "protected_files",
            ],
        },
    }


def build_queue_ultra_catalog(
    private_validator_ref: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return a one-case catalog fragment for explicit parent integration."""

    return [build_queue_ultra_case(private_validator_ref)]


__all__ = [
    "QUEUE_APP_SCAFFOLD",
    "QUEUE_HARD_CAPS",
    "QUEUE_METRICS",
    "QUEUE_PRIVATE_VALIDATOR_REF",
    "QUEUE_PUBLIC_SMOKE",
    "QUEUE_SCHEMA_SQL",
    "QUEUE_SPEC",
    "QUEUE_TASK_QUEUE_SCAFFOLD",
    "build_queue_ultra_catalog",
    "build_queue_ultra_case",
]
