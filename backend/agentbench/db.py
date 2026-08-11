from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 10


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    base_url TEXT,
    api_style TEXT NOT NULL DEFAULT 'openai',
    credential_ref TEXT,
    settings_json TEXT NOT NULL DEFAULT '{}',
    input_price REAL NOT NULL DEFAULT 0,
    output_price REAL NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runners (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    runner_type TEXT NOT NULL,
    executable TEXT,
    args_json TEXT NOT NULL DEFAULT '[]',
    env_json TEXT NOT NULL DEFAULT '{}',
    system_prompt TEXT NOT NULL DEFAULT '',
    tools_json TEXT NOT NULL DEFAULT '[]',
    limits_json TEXT NOT NULL DEFAULT '{}',
    model_override_supported INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS test_cases (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    version TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    definition_json TEXT NOT NULL,
    definition_hash TEXT,
    builtin INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(slug, version)
);

CREATE TABLE IF NOT EXISTS test_case_revisions (
    id TEXT PRIMARY KEY,
    test_case_id TEXT NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    version TEXT NOT NULL,
    definition_hash TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(test_case_id, definition_hash)
);

CREATE TABLE IF NOT EXISTS test_suites (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suite_cases (
    suite_id TEXT NOT NULL REFERENCES test_suites(id) ON DELETE CASCADE,
    test_case_id TEXT NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(suite_id, test_case_id)
);

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    suite_id TEXT NOT NULL REFERENCES test_suites(id),
    participants_json TEXT NOT NULL,
    repetitions INTEGER NOT NULL DEFAULT 1,
    concurrency INTEGER NOT NULL DEFAULT 1,
    benchmark_generation TEXT NOT NULL DEFAULT 'v2',
    scoring_profile TEXT NOT NULL DEFAULT 'balanced-v2',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    test_case_id TEXT NOT NULL REFERENCES test_cases(id),
    test_revision_id TEXT REFERENCES test_case_revisions(id),
    model_id TEXT NOT NULL REFERENCES models(id),
    runner_id TEXT NOT NULL REFERENCES agent_runners(id),
    repetition INTEGER NOT NULL DEFAULT 1,
    lane TEXT NOT NULL,
    scoring_profile TEXT NOT NULL DEFAULT 'balanced-v2',
    status TEXT NOT NULL DEFAULT 'queued',
    final_answer TEXT,
    score REAL,
    tokens_input INTEGER NOT NULL DEFAULT 0,
    tokens_output INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    cost_source TEXT NOT NULL DEFAULT 'unavailable',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    steps INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    passed INTEGER,
    workspace_path TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS run_attempts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    prompt TEXT NOT NULL,
    multiplier REAL NOT NULL DEFAULT 1,
    raw_score REAL,
    adjusted_score REAL,
    passed INTEGER NOT NULL DEFAULT 0,
    tokens_input INTEGER NOT NULL DEFAULT 0,
    tokens_output INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    steps INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(run_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, seq)
);

CREATE TABLE IF NOT EXISTS validator_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    validator_type TEXT NOT NULL,
    weight REAL NOT NULL,
    score REAL NOT NULL,
    status TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judge_reviews (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    judge_model_id TEXT,
    judge_runner_id TEXT,
    score REAL,
    status TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS score_components (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    dimension TEXT NOT NULL,
    score REAL NOT NULL,
    weight REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    subject_type TEXT,
    subject_id TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    default_runner_id TEXT REFERENCES agent_runners(id) ON DELETE SET NULL,
    default_model_id TEXT REFERENCES models(id) ON DELETE SET NULL,
    permission_profile TEXT NOT NULL DEFAULT 'workspace',
    settings_json TEXT NOT NULL DEFAULT '{}',
    pinned INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_opened_at TEXT
);

CREATE TABLE IF NOT EXISTS project_roots (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    root_path TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    access_mode TEXT NOT NULL DEFAULT 'workspace',
    is_primary INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, root_path)
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    runner_id TEXT NOT NULL REFERENCES agent_runners(id),
    model_id TEXT NOT NULL REFERENCES models(id),
    status TEXT NOT NULL DEFAULT 'idle',
    permission_profile TEXT NOT NULL DEFAULT 'workspace',
    reasoning_effort TEXT NOT NULL DEFAULT 'medium',
    skill_pack_id TEXT REFERENCES prompt_templates(id) ON DELETE SET NULL,
    native_session_id TEXT,
    workspace_path TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    tokens_input INTEGER NOT NULL DEFAULT 0,
    tokens_output INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS session_turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    turn_no INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    user_message TEXT NOT NULL,
    final_answer TEXT,
    tokens_input INTEGER NOT NULL DEFAULT 0,
    tokens_output INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    steps INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(session_id, turn_no)
);

CREATE TABLE IF NOT EXISTS session_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES session_turns(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES session_turns(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'user',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(session_id, seq)
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES session_turns(id) ON DELETE CASCADE,
    request_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    request_json TEXT NOT NULL DEFAULT '{}',
    decision_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS permission_rules (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    runner_id TEXT REFERENCES agent_runners(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    pattern TEXT NOT NULL,
    decision TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, runner_id, scope, pattern)
);

CREATE TABLE IF NOT EXISTS session_file_changes (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES session_turns(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    change_type TEXT NOT NULL,
    before_sha256 TEXT,
    after_sha256 TEXT,
    size_delta INTEGER NOT NULL DEFAULT 0,
    before_snapshot_path TEXT,
    after_snapshot_path TEXT,
    status TEXT NOT NULL DEFAULT 'observed',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES session_turns(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_graphs (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS task_nodes (
    id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL REFERENCES task_graphs(id) ON DELETE CASCADE,
    node_type TEXT NOT NULL,
    name TEXT NOT NULL,
    position_x REAL NOT NULL DEFAULT 0,
    position_y REAL NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    output_json TEXT NOT NULL DEFAULT '{}',
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_edges (
    id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL REFERENCES task_graphs(id) ON DELETE CASCADE,
    source_node_id TEXT NOT NULL REFERENCES task_nodes(id) ON DELETE CASCADE,
    target_node_id TEXT NOT NULL REFERENCES task_nodes(id) ON DELETE CASCADE,
    condition_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(graph_id, source_node_id, target_node_id)
);

CREATE TABLE IF NOT EXISTS task_graph_versions (
    id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL REFERENCES task_graphs(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    settings_json TEXT NOT NULL DEFAULT '{}',
    definition_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(graph_id, version_no)
);

CREATE TABLE IF NOT EXISTS task_graph_runs (
    id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL REFERENCES task_graphs(id) ON DELETE CASCADE,
    version_no INTEGER,
    status TEXT NOT NULL,
    dry_run INTEGER NOT NULL DEFAULT 0,
    retry_node_id TEXT,
    error_message TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    usage_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_items (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    graph_id TEXT REFERENCES task_graphs(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'backlog',
    priority TEXT NOT NULL DEFAULT 'normal',
    runner_id TEXT REFERENCES agent_runners(id) ON DELETE SET NULL,
    model_id TEXT REFERENCES models(id) ON DELETE SET NULL,
    session_id TEXT REFERENCES agent_sessions(id) ON DELETE SET NULL,
    due_at TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    depends_on_json TEXT NOT NULL DEFAULT '[]',
    result_summary TEXT NOT NULL DEFAULT '',
    retry_of TEXT REFERENCES task_items(id) ON DELETE SET NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    cancelled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS mcp_servers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    transport TEXT NOT NULL DEFAULT 'stdio',
    command TEXT,
    args_json TEXT NOT NULL DEFAULT '[]',
    url TEXT,
    env_json TEXT NOT NULL DEFAULT '{}',
    tools_json TEXT NOT NULL DEFAULT '[]',
    health_status TEXT NOT NULL DEFAULT 'unknown',
    last_error TEXT,
    last_checked_at TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    tools_json TEXT NOT NULL DEFAULT '[]',
    permission_profile TEXT,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

"""

# Indexes must be installed after column migrations. SQLite evaluates CREATE INDEX
# immediately even when the table came from an older schema, so keeping these in
# SCHEMA would make a V4 database fail before V5 could add task_items.archived.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_runs_experiment ON runs(experiment_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_attempts_run ON run_attempts(run_id, attempt_no);
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_tests_category ON test_cases(category);
CREATE INDEX IF NOT EXISTS idx_revisions_case ON test_case_revisions(test_case_id, created_at);
CREATE INDEX IF NOT EXISTS idx_projects_archived ON projects(archived, updated_at);
CREATE INDEX IF NOT EXISTS idx_project_roots_project ON project_roots(project_id, is_primary);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON agent_sessions(project_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON agent_sessions(status);
CREATE INDEX IF NOT EXISTS idx_session_turns_session ON session_turns(session_id, turn_no);
CREATE INDEX IF NOT EXISTS idx_session_messages_session ON session_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approval_requests(status, created_at);
CREATE INDEX IF NOT EXISTS idx_file_changes_session ON session_file_changes(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_task_nodes_graph ON task_nodes(graph_id, status);
CREATE INDEX IF NOT EXISTS idx_task_items_status ON task_items(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_task_items_project ON task_items(project_id, archived, updated_at);
CREATE INDEX IF NOT EXISTS idx_task_graphs_project ON task_graphs(project_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_task_graph_versions_graph ON task_graph_versions(graph_id, version_no DESC);
CREATE INDEX IF NOT EXISTS idx_task_graph_runs_graph ON task_graph_runs(graph_id, created_at DESC);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _backup_before_migration(self, target_version: int) -> Path | None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        try:
            with sqlite3.connect(self.path) as probe:
                has_meta = probe.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
                ).fetchone()
                if not has_meta:
                    return None
                row = probe.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
                current_version = int(row[0]) if row else 0
        except (OSError, sqlite3.DatabaseError, TypeError, ValueError):
            return None
        if current_version >= target_version:
            return None
        backup_dir = self.path.parent / "migration-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / (
            f"{self.path.stem}-pre-schema-v{target_version}-{timestamp}{self.path.suffix}"
        )
        with sqlite3.connect(self.path) as source, sqlite3.connect(backup_path) as target:
            source.backup(target)
        return backup_path

    def initialize(self) -> None:
        self._backup_before_migration(SCHEMA_VERSION)
        with self._write_lock, self.connect() as connection:
            connection.executescript(SCHEMA)
            run_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
            }
            for name, declaration in (
                ("cost_source", "TEXT NOT NULL DEFAULT 'unavailable'"),
                ("attempt_count", "INTEGER NOT NULL DEFAULT 1"),
                ("passed", "INTEGER"),
                ("test_revision_id", "TEXT"),
                ("scoring_profile", "TEXT NOT NULL DEFAULT 'balanced-v2'"),
            ):
                if name not in run_columns:
                    connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {declaration}")
            experiment_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(experiments)").fetchall()
            }
            for name, declaration in (
                ("benchmark_generation", "TEXT NOT NULL DEFAULT 'v2'"),
                ("scoring_profile", "TEXT NOT NULL DEFAULT 'balanced-v2'"),
            ):
                if name not in experiment_columns:
                    connection.execute(
                        f"ALTER TABLE experiments ADD COLUMN {name} {declaration}"
                    )
            test_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(test_cases)").fetchall()
            }
            if "definition_hash" not in test_columns:
                connection.execute("ALTER TABLE test_cases ADD COLUMN definition_hash TEXT")
            change_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(session_file_changes)"
                ).fetchall()
            }
            for name in ("before_snapshot_path", "after_snapshot_path"):
                if name not in change_columns:
                    connection.execute(
                        f"ALTER TABLE session_file_changes ADD COLUMN {name} TEXT"
                    )
            mcp_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(mcp_servers)").fetchall()
            }
            for name, declaration in (
                ("tools_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("health_status", "TEXT NOT NULL DEFAULT 'unknown'"),
                ("last_error", "TEXT"),
                ("last_checked_at", "TEXT"),
            ):
                if name not in mcp_columns:
                    connection.execute(
                        f"ALTER TABLE mcp_servers ADD COLUMN {name} {declaration}"
                    )
            node_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(task_nodes)").fetchall()
            }
            for name, declaration in (
                ("attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("error_message", "TEXT"),
                ("output_json", "TEXT NOT NULL DEFAULT '{}'"),
            ):
                if name not in node_columns:
                    connection.execute(
                        f"ALTER TABLE task_nodes ADD COLUMN {name} {declaration}"
                    )
            session_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(agent_sessions)").fetchall()
            }
            if "reasoning_effort" not in session_columns:
                connection.execute(
                    "ALTER TABLE agent_sessions ADD COLUMN reasoning_effort "
                    "TEXT NOT NULL DEFAULT 'medium'"
                )
            if "skill_pack_id" not in session_columns:
                connection.execute("ALTER TABLE agent_sessions ADD COLUMN skill_pack_id TEXT")
            task_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(task_items)").fetchall()
            }
            for name, declaration in (
                ("tags_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("depends_on_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("result_summary", "TEXT NOT NULL DEFAULT ''"),
                ("retry_of", "TEXT"),
                ("archived", "INTEGER NOT NULL DEFAULT 0"),
                ("cancelled_at", "TEXT"),
            ):
                if name not in task_columns:
                    connection.execute(
                        f"ALTER TABLE task_items ADD COLUMN {name} {declaration}"
                    )
            connection.executescript(INDEXES)
            row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
            elif int(row["version"]) < SCHEMA_VERSION:
                connection.execute("UPDATE schema_meta SET version=?", (SCHEMA_VERSION,))

    @staticmethod
    def _definition_digest(definition_json: str) -> str:
        try:
            value = json.loads(definition_json)
            canonical = json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        except (TypeError, json.JSONDecodeError):
            canonical = definition_json
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def sync_test_case_revisions(self, test_case_id: str | None = None) -> None:
        """Archive immutable test definitions and bind legacy runs to the best known revision.

        Built-in catalog rows are refreshed during application upgrades.  A run must keep
        using the exact definition that existed when the experiment was created, so revisions
        are append-only even when a catalog row keeps the same public version string.
        """
        where = " WHERE id=?" if test_case_id else ""
        params: tuple[str, ...] = (test_case_id,) if test_case_id else ()
        with self.transaction() as connection:
            rows = connection.execute(
                f"SELECT id,slug,version,definition_json FROM test_cases{where}", params
            ).fetchall()
            for row in rows:
                digest = self._definition_digest(row["definition_json"])
                revision_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"agentbench:test-revision:{row['id']}:{digest}",
                    )
                )
                connection.execute(
                    "INSERT OR IGNORE INTO test_case_revisions("
                    "id,test_case_id,slug,version,definition_hash,definition_json,created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        revision_id,
                        row["id"],
                        row["slug"],
                        row["version"],
                        digest,
                        row["definition_json"],
                        utc_now(),
                    ),
                )
                connection.execute(
                    "UPDATE test_cases SET definition_hash=? WHERE id=?",
                    (digest, row["id"]),
                )
                connection.execute(
                    "UPDATE runs SET test_revision_id=? "
                    "WHERE test_case_id=? AND test_revision_id IS NULL",
                    (revision_id, row["id"]),
                )

    @contextmanager
    def transaction(self):
        with self._write_lock, self.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.transaction() as connection:
            connection.execute(sql, tuple(params))

    def executemany(self, sql: str, values: Iterable[Iterable[Any]]) -> None:
        with self.transaction() as connection:
            connection.executemany(sql, [tuple(row) for row in values])

    def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, tuple(params)).fetchall()]

    def insert_audit(
        self,
        action: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.execute(
            "INSERT INTO audit_logs(action, subject_type, subject_id, detail_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (action, subject_type, subject_id, json.dumps(detail or {}), utc_now()),
        )
