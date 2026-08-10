from __future__ import annotations

import difflib
import hashlib
import json
import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import Any

from .config import Settings
from .db import Database, new_id, utc_now
from .schemas import (
    ApprovalDecision,
    FileChangeReview,
    McpServerCreate,
    ProjectCreate,
    ProjectRootCreate,
    SessionAttachmentImport,
    SessionCreate,
    SessionTurnCreate,
    TaskGraphCreate,
    TaskItemCreate,
)
from .secrets import SecretStore

ACTIVE_SESSION_STATUSES = {"queued", "preparing", "running", "waiting_approval"}
TERMINAL_TURN_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
SKIPPED_TREE_DIRECTORIES = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "dist",
    "node_modules",
    "target",
    "tmp",
}


def _json(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _git_branch(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    try:
        value = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    prefix = "ref: refs/heads/"
    return value[len(prefix) :] if value.startswith(prefix) else value[:12]


class StudioService:
    """Project and interactive Agent session domain.

    Benchmark runs intentionally remain owned by EvaluationService.  This service only
    stores long-lived user projects and interactive sessions so V4 can evolve without
    changing the immutable evaluation history model.
    """

    def __init__(self, database: Database, settings: Settings, secrets: SecretStore):
        self.database = database
        self.settings = settings
        self.secrets = secrets
        self.recover_interrupted_sessions()

    def recover_interrupted_sessions(self) -> None:
        now = utc_now()
        active = self.database.fetch_all(
            "SELECT id FROM agent_sessions WHERE status IN "
            "('queued','preparing','running','waiting_approval')"
        )
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE session_turns SET status='interrupted',error_code='app_restarted',"
                "error_message='AgentBench exited while this turn was active',completed_at=? "
                "WHERE status IN ('queued','preparing','running','waiting_approval')",
                (now,),
            )
            connection.execute(
                "UPDATE agent_sessions SET status='interrupted',updated_at=?,completed_at=? "
                "WHERE status IN ('queued','preparing','running','waiting_approval')",
                (now, now),
            )
        for row in active:
            self.append_event(
                row["id"],
                "session.interrupted",
                {"reason": "app_restarted"},
                visibility="user",
            )

    # Projects
    def _resolve_project_root(self, raw_path: str) -> Path:
        try:
            root = Path(raw_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("project_root_not_found") from exc
        if not root.is_dir():
            raise ValueError("project_root_must_be_directory")
        anchor = Path(root.anchor).resolve() if root.anchor else None
        if anchor and root == anchor:
            raise ValueError("project_root_too_broad")
        return root

    def _enabled_entity(self, table: str, entity_id: str | None) -> dict[str, Any] | None:
        if not entity_id:
            return None
        if table not in {"models", "agent_runners"}:
            raise ValueError("invalid_entity_table")
        row = self.database.fetch_one(f"SELECT * FROM {table} WHERE id=?", (entity_id,))
        if not row:
            raise KeyError(f"{table[:-1]}_not_found")
        if not row["enabled"]:
            raise ValueError(f"{table[:-1]}_disabled")
        return row

    def _default_entity_id(self, table: str) -> str:
        if table not in {"models", "agent_runners"}:
            raise ValueError("invalid_entity_table")
        row = self.database.fetch_one(
            f"SELECT id FROM {table} WHERE enabled=1 ORDER BY builtin DESC,name LIMIT 1"
        )
        if not row:
            raise ValueError(f"no_enabled_{table}")
        return str(row["id"])

    def create_project(self, value: ProjectCreate) -> dict[str, Any]:
        root = self._resolve_project_root(value.root_path)
        existing = self.database.fetch_one(
            "SELECT p.id FROM projects p JOIN project_roots pr ON pr.project_id=p.id "
            "WHERE pr.root_path=? AND p.archived=0",
            (str(root),),
        )
        if existing:
            raise ValueError("project_root_already_registered")
        runner_id = value.default_runner_id or self._default_entity_id("agent_runners")
        model_id = value.default_model_id or self._default_entity_id("models")
        self._enabled_entity("agent_runners", runner_id)
        self._enabled_entity("models", model_id)
        project_id = new_id()
        root_id = new_id()
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO projects(id,name,description,default_runner_id,default_model_id,"
                "permission_profile,settings_json,pinned,archived,created_at,updated_at,last_opened_at) "
                "VALUES (?,?,?,?,?,?,'{}',?,0,?,?,?)",
                (
                    project_id,
                    value.name.strip(),
                    value.description.strip(),
                    runner_id,
                    model_id,
                    value.permission_profile,
                    int(value.pinned),
                    now,
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO project_roots(id,project_id,root_path,label,access_mode,is_primary,created_at) "
                "VALUES (?,?,?,?,?,1,?)",
                (root_id, project_id, str(root), root.name, value.permission_profile, now),
            )
        self.database.insert_audit(
            "project.created",
            "project",
            project_id,
            {"root_path": str(root), "permission_profile": value.permission_profile},
        )
        return self.get_project(project_id)

    def _project_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        root_path = row.get("root_path")
        branch = _git_branch(Path(root_path)) if root_path else None
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "default_runner_id": row.get("default_runner_id"),
            "default_model_id": row.get("default_model_id"),
            "permission_profile": row["permission_profile"],
            "settings": _json(row.get("settings_json"), {}),
            "pinned": bool(row["pinned"]),
            "archived": bool(row["archived"]),
            "root_path": root_path,
            "branch": branch,
            "session_count": int(row.get("session_count") or 0),
            "active_sessions": int(row.get("active_sessions") or 0),
            "pending_approvals": int(row.get("pending_approvals") or 0),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_opened_at": row.get("last_opened_at"),
        }

    def list_projects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE p.archived=0"
        rows = self.database.fetch_all(
            "SELECT p.*,pr.root_path,"
            "(SELECT COUNT(*) FROM agent_sessions s WHERE s.project_id=p.id AND s.archived=0) "
            "session_count,"
            "(SELECT COUNT(*) FROM agent_sessions s WHERE s.project_id=p.id AND s.archived=0 "
            "AND s.status IN ('queued','preparing','running','waiting_approval')) active_sessions,"
            "(SELECT COUNT(*) FROM approval_requests a JOIN agent_sessions s ON s.id=a.session_id "
            "WHERE s.project_id=p.id AND a.status='pending') pending_approvals "
            "FROM projects p LEFT JOIN project_roots pr ON pr.project_id=p.id AND pr.is_primary=1 "
            f"{where} ORDER BY p.pinned DESC,COALESCE(p.last_opened_at,p.updated_at) DESC"
        )
        return [self._project_summary(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT p.*,pr.root_path,"
            "(SELECT COUNT(*) FROM agent_sessions s WHERE s.project_id=p.id AND s.archived=0) "
            "session_count,"
            "(SELECT COUNT(*) FROM agent_sessions s WHERE s.project_id=p.id AND s.archived=0 "
            "AND s.status IN ('queued','preparing','running','waiting_approval')) active_sessions,"
            "(SELECT COUNT(*) FROM approval_requests a JOIN agent_sessions s ON s.id=a.session_id "
            "WHERE s.project_id=p.id AND a.status='pending') pending_approvals "
            "FROM projects p LEFT JOIN project_roots pr ON pr.project_id=p.id AND pr.is_primary=1 "
            "WHERE p.id=?",
            (project_id,),
        )
        if not row:
            raise KeyError("project_not_found")
        output = self._project_summary(row)
        output["roots"] = [
            {
                **root,
                "is_primary": bool(root["is_primary"]),
            }
            for root in self.database.fetch_all(
                "SELECT id,root_path,label,access_mode,is_primary,created_at FROM project_roots "
                "WHERE project_id=? ORDER BY is_primary DESC,created_at",
                (project_id,),
            )
        ]
        return output

    def update_project(self, project_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        self.get_project(project_id)
        allowed = {
            "name",
            "description",
            "default_runner_id",
            "default_model_id",
            "permission_profile",
            "pinned",
            "archived",
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        if "default_runner_id" in values and values["default_runner_id"] is not None:
            self._enabled_entity("agent_runners", values["default_runner_id"])
        if "default_model_id" in values and values["default_model_id"] is not None:
            self._enabled_entity("models", values["default_model_id"])
        for key in ("pinned", "archived"):
            if key in values:
                values[key] = int(bool(values[key]))
        if not values:
            return self.get_project(project_id)
        values["updated_at"] = utc_now()
        assignments = ",".join(f"{key}=?" for key in values)
        self.database.execute(
            f"UPDATE projects SET {assignments} WHERE id=?",
            (*values.values(), project_id),
        )
        self.database.insert_audit("project.updated", "project", project_id, changes)
        return self.get_project(project_id)

    def add_project_root(self, project_id: str, value: ProjectRootCreate) -> dict[str, Any]:
        project = self.get_project(project_id)
        if project["archived"]:
            raise ValueError("project_archived")
        root = self._resolve_project_root(value.root_path)
        root_id = new_id()
        try:
            self.database.execute(
                "INSERT INTO project_roots(id,project_id,root_path,label,access_mode,is_primary,created_at) "
                "VALUES (?,?,?,?,?,0,?)",
                (
                    root_id,
                    project_id,
                    str(root),
                    value.label.strip() or root.name,
                    value.access_mode,
                    utc_now(),
                ),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError("project_root_already_registered") from exc
            raise
        self.database.insert_audit(
            "project.root_added", "project", project_id, {"root_path": str(root)}
        )
        return self.get_project(project_id)

    def archive_project(self, project_id: str) -> dict[str, Any]:
        active = self.database.fetch_one(
            "SELECT COUNT(*) count FROM agent_sessions WHERE project_id=? "
            "AND status IN ('queued','preparing','running','waiting_approval')",
            (project_id,),
        )
        if not active:
            self.get_project(project_id)
        elif int(active["count"]):
            raise ValueError("project_has_active_sessions")
        return self.update_project(project_id, {"archived": True})

    def _primary_root(self, project_id: str) -> Path:
        row = self.database.fetch_one(
            "SELECT root_path FROM project_roots WHERE project_id=? AND is_primary=1",
            (project_id,),
        )
        if not row:
            raise ValueError("project_primary_root_missing")
        return self._resolve_project_root(str(row["root_path"]))

    def list_project_files(
        self, project_id: str, relative_path: str = ".", max_items: int = 500
    ) -> dict[str, Any]:
        root = self._primary_root(project_id)
        target = (root / relative_path).resolve()
        if not target.is_relative_to(root):
            raise ValueError("project_path_escape")
        if not target.exists():
            raise KeyError("project_path_not_found")
        if not target.is_dir():
            raise ValueError("project_path_not_directory")
        entries: list[dict[str, Any]] = []
        for child in sorted(target.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower())):
            if len(entries) >= max(1, min(max_items, 2000)):
                break
            if child.is_dir() and child.name in SKIPPED_TREE_DIRECTORIES:
                continue
            try:
                resolved = child.resolve()
                stat = child.stat()
            except OSError:
                continue
            if not resolved.is_relative_to(root):
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": str(resolved.relative_to(root)).replace(os.sep, "/"),
                    "kind": "directory" if child.is_dir() else "file",
                    "size": 0 if child.is_dir() else int(stat.st_size),
                    "modified_ns": int(stat.st_mtime_ns),
                }
            )
        return {
            "project_id": project_id,
            "root_path": str(root),
            "path": str(target.relative_to(root)).replace(os.sep, "/") or ".",
            "entries": entries,
        }

    def search_project_files(
        self, project_id: str, query: str, max_items: int = 120
    ) -> dict[str, Any]:
        root = self._primary_root(project_id)
        needle = query.strip().casefold()
        if len(needle) < 2:
            raise ValueError("project_search_query_too_short")
        limit = max(1, min(max_items, 200))
        scan_limit = 50_000
        scanned = 0
        truncated = False
        entries: list[dict[str, Any]] = []

        for directory, directory_names, file_names in os.walk(
            root, topdown=True, followlinks=False
        ):
            directory_names[:] = sorted(
                [name for name in directory_names if name not in SKIPPED_TREE_DIRECTORIES],
                key=str.casefold,
            )
            candidates = [
                *((name, "directory") for name in directory_names),
                *((name, "file") for name in sorted(file_names, key=str.casefold)),
            ]
            for name, kind in candidates:
                scanned += 1
                if scanned > scan_limit:
                    truncated = True
                    break
                path = Path(directory) / name
                relative = str(path.relative_to(root)).replace(os.sep, "/")
                if needle not in relative.casefold():
                    continue
                try:
                    resolved = path.resolve()
                    stat = path.stat()
                except OSError:
                    continue
                if not resolved.is_relative_to(root):
                    continue
                entries.append(
                    {
                        "name": name,
                        "path": relative,
                        "kind": kind,
                        "size": 0 if kind == "directory" else int(stat.st_size),
                        "modified_ns": int(stat.st_mtime_ns),
                    }
                )
                if len(entries) >= limit:
                    truncated = True
                    break
            if truncated:
                break

        return {
            "project_id": project_id,
            "root_path": str(root),
            "query": query.strip(),
            "entries": entries,
            "scanned": min(scanned, scan_limit),
            "truncated": truncated,
        }

    def read_project_file(self, project_id: str, relative_path: str) -> dict[str, Any]:
        root = self._primary_root(project_id)
        target = (root / relative_path).resolve()
        if not target.is_relative_to(root):
            raise ValueError("project_path_escape")
        if not target.is_file():
            raise KeyError("project_file_not_found")
        if target.stat().st_size > 2_000_000:
            raise ValueError("project_file_too_large")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("project_file_not_text") from exc
        return {
            "project_id": project_id,
            "path": str(target.relative_to(root)).replace(os.sep, "/"),
            "content": content,
            "size": target.stat().st_size,
        }

    # Sessions
    def _session_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "project_name": row.get("project_name"),
            "title": row["title"],
            "runner_id": row["runner_id"],
            "runner_name": row.get("runner_name"),
            "runner_type": row.get("runner_type"),
            "model_id": row["model_id"],
            "model_name": row.get("model_name"),
            "status": row["status"],
            "permission_profile": row["permission_profile"],
            "reasoning_effort": row.get("reasoning_effort") or "medium",
            "native_session_id": row.get("native_session_id"),
            "workspace_path": row["workspace_path"],
            "summary": row["summary"],
            "tokens_input": int(row["tokens_input"]),
            "tokens_output": int(row["tokens_output"]),
            "cost_usd": float(row["cost_usd"]),
            "duration_ms": int(row["duration_ms"]),
            "turn_count": int(row.get("turn_count") or 0),
            "pending_approvals": int(row.get("pending_approvals") or 0),
            "archived": bool(row["archived"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
        }

    def _session_query(self, where: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            "SELECT s.*,p.name project_name,r.name runner_name,r.runner_type,m.name model_name,"
            "(SELECT COUNT(*) FROM session_turns t WHERE t.session_id=s.id) turn_count,"
            "(SELECT COUNT(*) FROM approval_requests a WHERE a.session_id=s.id "
            "AND a.status='pending') pending_approvals "
            "FROM agent_sessions s JOIN projects p ON p.id=s.project_id "
            "JOIN agent_runners r ON r.id=s.runner_id JOIN models m ON m.id=s.model_id "
            f"{where} ORDER BY s.updated_at DESC",
            params,
        )

    def create_session(self, value: SessionCreate) -> dict[str, Any]:
        project = self.get_project(value.project_id)
        if project["archived"]:
            raise ValueError("project_archived")
        runner_id = value.runner_id or project.get("default_runner_id")
        model_id = value.model_id or project.get("default_model_id")
        if not runner_id:
            runner_id = self._default_entity_id("agent_runners")
        if not model_id:
            model_id = self._default_entity_id("models")
        self._enabled_entity("agent_runners", runner_id)
        self._enabled_entity("models", model_id)
        root = self._primary_root(value.project_id)
        session_id = new_id()
        now = utc_now()
        permission_profile = value.permission_profile or project["permission_profile"]
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO agent_sessions(id,project_id,title,runner_id,model_id,status,"
                "permission_profile,reasoning_effort,workspace_path,created_at,updated_at) "
                "VALUES (?,?,?,?,?,'idle',?,?,?,?,?)",
                (
                    session_id,
                    value.project_id,
                    value.title.strip(),
                    runner_id,
                    model_id,
                    permission_profile,
                    value.reasoning_effort,
                    str(root),
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE projects SET last_opened_at=?,updated_at=? WHERE id=?",
                (now, now, value.project_id),
            )
        self.append_event(
            session_id,
            "session.created",
            {
                "runner_id": runner_id,
                "model_id": model_id,
                "permission_profile": permission_profile,
                "reasoning_effort": value.reasoning_effort,
            },
        )
        self.database.insert_audit("session.created", "session", session_id)
        return self.get_session(session_id)

    def list_sessions(
        self,
        project_id: str | None = None,
        include_archived: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("s.project_id=?")
            params.append(project_id)
        if not include_archived:
            clauses.append("s.archived=0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._session_query(where, tuple(params))[: max(1, min(limit, 1000))]
        return [self._session_summary(row) for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any]:
        rows = self._session_query("WHERE s.id=?", (session_id,))
        if not rows:
            raise KeyError("session_not_found")
        output = self._session_summary(rows[0])
        messages = self.database.fetch_all(
            "SELECT id,turn_id,role,content,metadata_json,created_at FROM session_messages "
            "WHERE session_id=? ORDER BY created_at,id",
            (session_id,),
        )
        for message in messages:
            message["metadata"] = _json(message.pop("metadata_json"), {})
        output["messages"] = messages
        output["events"] = self.get_events(session_id, max(0, self._latest_seq(session_id) - 300))
        output["approvals"] = self.list_approvals(session_id=session_id)
        output["turns"] = self.database.fetch_all(
            "SELECT * FROM session_turns WHERE session_id=? ORDER BY turn_no",
            (session_id,),
        )
        output["file_changes"] = self.database.fetch_all(
            "SELECT id,turn_id,path,change_type,before_sha256,after_sha256,size_delta,"
            "status,created_at FROM session_file_changes WHERE session_id=? "
            "ORDER BY created_at,id",
            (session_id,),
        )
        output["artifacts"] = self.database.fetch_all(
            "SELECT id,turn_id,kind,name,path,size,sha256,created_at "
            "FROM session_artifacts WHERE session_id=? ORDER BY created_at,id",
            (session_id,),
        )
        return output

    def update_session(self, session_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        session = self.get_session(session_id)
        allowed = {
            "title",
            "runner_id",
            "model_id",
            "permission_profile",
            "reasoning_effort",
            "archived",
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        if session["status"] in ACTIVE_SESSION_STATUSES and any(
            key in values for key in ("runner_id", "model_id")
        ):
            raise ValueError("active_session_configuration_locked")
        if "runner_id" in values and values["runner_id"] is not None:
            self._enabled_entity("agent_runners", values["runner_id"])
        if "model_id" in values and values["model_id"] is not None:
            self._enabled_entity("models", values["model_id"])
        if "archived" in values:
            values["archived"] = int(bool(values["archived"]))
        if not values:
            return session
        values["updated_at"] = utc_now()
        assignments = ",".join(f"{key}=?" for key in values)
        self.database.execute(
            f"UPDATE agent_sessions SET {assignments} WHERE id=?",
            (*values.values(), session_id),
        )
        self.database.insert_audit("session.updated", "session", session_id, changes)
        if values.get("permission_profile") == "full":
            for approval in self.list_approvals(session_id=session_id, status="pending"):
                self.decide_approval(
                    approval["id"],
                    ApprovalDecision(
                        decision="allow_session",
                        reason="会话已切换为完全访问",
                    ),
                )
        return self.get_session(session_id)

    def import_session_attachments(
        self, session_id: str, value: SessionAttachmentImport
    ) -> list[dict[str, Any]]:
        self.get_session(session_id)
        sources: list[Path] = []
        total_size = 0
        for raw_path in value.paths:
            source = Path(raw_path).expanduser().resolve()
            if not source.is_file():
                raise ValueError("attachment_file_not_found")
            size = source.stat().st_size
            if size > 50 * 1024 * 1024:
                raise ValueError("attachment_file_too_large")
            total_size += size
            if total_size > 100 * 1024 * 1024:
                raise ValueError("attachment_total_too_large")
            sources.append(source)

        target_root = (self.settings.data_dir / "studio-attachments" / session_id).resolve()
        target_root.mkdir(parents=True, exist_ok=True)
        created_at = utc_now()
        imported: list[dict[str, Any]] = []
        try:
            for source in sources:
                attachment_id = new_id()
                safe_name = re.sub(r"[^\w.()\[\] -]+", "_", source.name, flags=re.UNICODE)
                safe_name = safe_name.strip(" .")[:180] or "attachment"
                target = (target_root / f"{attachment_id}-{safe_name}").resolve()
                if target_root not in target.parents:
                    raise ValueError("attachment_path_invalid")
                shutil.copy2(source, target)
                size = target.stat().st_size
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                self.database.execute(
                    "INSERT INTO session_artifacts(id,session_id,turn_id,kind,name,path,size,"
                    "sha256,created_at) VALUES (?,?,NULL,'attachment',?,?,?,?,?)",
                    (
                        attachment_id,
                        session_id,
                        safe_name,
                        str(target),
                        size,
                        digest,
                        created_at,
                    ),
                )
                imported.append(
                    {
                        "id": attachment_id,
                        "kind": "attachment",
                        "name": safe_name,
                        "size": size,
                        "media_type": mimetypes.guess_type(safe_name)[0]
                        or "application/octet-stream",
                        "created_at": created_at,
                    }
                )
        except Exception:
            for item in imported:
                row = self.database.fetch_one(
                    "SELECT path FROM session_artifacts WHERE id=?", (item["id"],)
                )
                if row:
                    Path(str(row["path"])).unlink(missing_ok=True)
                    self.database.execute("DELETE FROM session_artifacts WHERE id=?", (item["id"],))
            raise
        self.database.insert_audit(
            "session.attachments_imported",
            "session",
            session_id,
            {"count": len(imported), "total_size": total_size},
        )
        return imported

    def delete_session_attachment(self, session_id: str, attachment_id: str) -> None:
        row = self.database.fetch_one(
            "SELECT id,path,turn_id,kind FROM session_artifacts WHERE id=? AND session_id=?",
            (attachment_id, session_id),
        )
        if not row or row["kind"] != "attachment":
            raise KeyError("attachment_not_found")
        if row.get("turn_id"):
            raise ValueError("attachment_already_sent")
        target = Path(str(row["path"])).resolve()
        attachment_root = (self.settings.data_dir / "studio-attachments" / session_id).resolve()
        if attachment_root not in target.parents:
            raise ValueError("attachment_path_invalid")
        target.unlink(missing_ok=True)
        self.database.execute("DELETE FROM session_artifacts WHERE id=?", (attachment_id,))

    def _normalize_turn_context(
        self, session_id: str, context: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in context:
            if item.get("type") != "attachment":
                normalized.append(item)
                continue
            attachment_id = str(item.get("artifact_id") or "")
            row = self.database.fetch_one(
                "SELECT id,name,size,path,turn_id FROM session_artifacts "
                "WHERE id=? AND session_id=? AND kind='attachment'",
                (attachment_id, session_id),
            )
            if not row or row.get("turn_id"):
                raise ValueError("attachment_not_available")
            normalized.append(
                {
                    "type": "attachment",
                    "artifact_id": row["id"],
                    "name": row["name"],
                    "size": int(row["size"]),
                    "media_type": mimetypes.guess_type(str(row["name"]))[0]
                    or "application/octet-stream",
                }
            )
        return normalized

    def queue_turn(self, session_id: str, value: SessionTurnCreate) -> dict[str, Any]:
        session = self.get_session(session_id)
        if session["archived"]:
            raise ValueError("session_archived")
        if session["status"] in ACTIVE_SESSION_STATUSES:
            raise ValueError("session_already_active")
        turn_id = new_id()
        message_id = new_id()
        context = self._normalize_turn_context(session_id, value.context)
        now = utc_now()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(turn_no),0)+1 turn_no FROM session_turns WHERE session_id=?",
                (session_id,),
            ).fetchone()
            turn_no = int(row["turn_no"])
            connection.execute(
                "INSERT INTO session_turns(id,session_id,turn_no,status,user_message,created_at) "
                "VALUES (?,?,?,'queued',?,?)",
                (turn_id, session_id, turn_no, value.message.strip(), now),
            )
            connection.execute(
                "INSERT INTO session_messages(id,session_id,turn_id,role,content,metadata_json,created_at) "
                "VALUES (?,?,?,'user',?,?,?)",
                (
                    message_id,
                    session_id,
                    turn_id,
                    value.message.strip(),
                    json.dumps({"context": context}, ensure_ascii=False),
                    now,
                ),
            )
            attachment_ids = [
                str(item["artifact_id"])
                for item in context
                if item.get("type") == "attachment"
            ]
            if attachment_ids:
                placeholders = ",".join("?" for _ in attachment_ids)
                connection.execute(
                    f"UPDATE session_artifacts SET turn_id=? WHERE session_id=? "
                    f"AND kind='attachment' AND turn_id IS NULL AND id IN ({placeholders})",
                    (turn_id, session_id, *attachment_ids),
                )
            connection.execute(
                "UPDATE agent_sessions SET status='queued',updated_at=?,started_at=COALESCE(started_at,?) "
                "WHERE id=?",
                (now, now, session_id),
            )
        self.append_event(
            session_id,
            "turn.queued",
            {"turn_id": turn_id, "turn_no": turn_no, "context_items": len(context)},
            turn_id=turn_id,
        )
        self.database.insert_audit(
            "session.turn_queued", "session", session_id, {"turn_id": turn_id}
        )
        return self.database.fetch_one("SELECT * FROM session_turns WHERE id=?", (turn_id,)) or {}

    def _latest_seq(self, session_id: str) -> int:
        row = self.database.fetch_one(
            "SELECT COALESCE(MAX(seq),0) seq FROM session_events WHERE session_id=?",
            (session_id,),
        )
        return int(row["seq"]) if row else 0

    def append_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        turn_id: str | None = None,
        visibility: str = "user",
        _connection: Any | None = None,
    ) -> dict[str, Any]:
        if visibility not in {"user", "recording_safe", "sensitive", "internal"}:
            raise ValueError("invalid_event_visibility")

        def insert(connection: Any) -> tuple[Any, int, str]:
            session = connection.execute(
                "SELECT 1 FROM agent_sessions WHERE id=?", (session_id,)
            ).fetchone()
            if not session:
                raise KeyError("session_not_found")
            row = connection.execute(
                "SELECT COALESCE(MAX(seq),0)+1 seq FROM session_events WHERE session_id=?",
                (session_id,),
            ).fetchone()
            seq = int(row["seq"])
            created_at = utc_now()
            cursor = connection.execute(
                "INSERT INTO session_events(session_id,turn_id,seq,event_type,visibility,"
                "payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    session_id,
                    turn_id,
                    seq,
                    event_type,
                    visibility,
                    json.dumps(payload, ensure_ascii=False),
                    created_at,
                ),
            )
            return cursor, seq, created_at

        if _connection is None:
            with self.database.transaction() as connection:
                cursor, seq, created_at = insert(connection)
        else:
            cursor, seq, created_at = insert(_connection)
        return {
            "id": int(cursor.lastrowid),
            "session_id": session_id,
            "turn_id": turn_id,
            "seq": seq,
            "event_type": event_type,
            "visibility": visibility,
            "payload": payload,
            "created_at": created_at,
        }

    def get_events(
        self, session_id: str, after: int = 0, include_sensitive: bool = False
    ) -> list[dict[str, Any]]:
        session = self.database.fetch_one(
            "SELECT id FROM agent_sessions WHERE id=?", (session_id,)
        )
        if not session:
            raise KeyError("session_not_found")
        visibility = "" if include_sensitive else "AND visibility IN ('user','recording_safe')"
        rows = self.database.fetch_all(
            "SELECT id,session_id,turn_id,seq,event_type,visibility,payload_json,created_at "
            "FROM session_events WHERE session_id=? AND seq>? "
            f"{visibility} ORDER BY seq",
            (session_id, after),
        )
        for row in rows:
            row["payload"] = _json(row.pop("payload_json"), {})
        return rows

    # File change review. Snapshot files live under AgentBench's private data directory.
    def _change_snapshot_path(self, raw_path: str | None) -> Path | None:
        if not raw_path:
            return None
        base = (self.settings.data_dir / "studio-snapshots").resolve()
        path = Path(raw_path).resolve()
        if not path.is_relative_to(base):
            raise ValueError("invalid_change_snapshot")
        return path

    def _file_change_row(self, change_id: str) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT c.*,s.workspace_path,s.project_id FROM session_file_changes c "
            "JOIN agent_sessions s ON s.id=c.session_id WHERE c.id=?",
            (change_id,),
        )
        if not row:
            raise KeyError("file_change_not_found")
        return row

    @staticmethod
    def _change_target(row: dict[str, Any]) -> Path:
        root = Path(str(row["workspace_path"])).resolve()
        target = (root / str(row["path"])).resolve()
        if not target.is_relative_to(root):
            raise ValueError("project_path_escape")
        return target

    @staticmethod
    def _sha256(path: Path) -> str | None:
        if not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def file_change_diff(self, session_id: str, change_id: str) -> dict[str, Any]:
        row = self._file_change_row(change_id)
        if row["session_id"] != session_id:
            raise KeyError("file_change_not_found")
        before_path = self._change_snapshot_path(row.get("before_snapshot_path"))
        after_path = self._change_snapshot_path(row.get("after_snapshot_path"))

        def text_from(path: Path | None) -> str:
            if path is None or not path.is_file():
                return ""
            return path.read_text(encoding="utf-8", errors="replace")[:2_000_000]

        before = text_from(before_path)
        after = text_from(after_path)
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{row['path']}",
                tofile=f"b/{row['path']}",
            )
        )
        target = self._change_target(row)
        current = ""
        if target.is_file() and target.stat().st_size <= 2_000_000:
            current = target.read_text(encoding="utf-8", errors="replace")
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "path": row["path"],
            "change_type": row["change_type"],
            "status": row["status"],
            "diff": diff[:4_000_000],
            "current_content": current,
            "can_restore": before_path is not None or row["change_type"] == "created",
        }

    def review_file_change(
        self, change_id: str, value: FileChangeReview
    ) -> dict[str, Any]:
        row = self._file_change_row(change_id)
        target = self._change_target(row)
        current_sha = self._sha256(target)
        if row.get("after_sha256") and current_sha != row["after_sha256"]:
            raise ValueError("file_changed_since_agent_turn")
        if value.action == "accept":
            status = "accepted"
        elif value.action == "apply_content":
            if value.content is None:
                raise ValueError("file_change_content_required")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value.content, encoding="utf-8")
            status = "partially_applied"
        else:
            before_path = self._change_snapshot_path(row.get("before_snapshot_path"))
            if row["change_type"] == "created":
                if target.exists():
                    target.unlink()
            elif before_path is not None and before_path.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(before_path.read_bytes())
            else:
                raise ValueError("file_change_snapshot_unavailable")
            status = "rejected"
        self.database.execute(
            "UPDATE session_file_changes SET status=? WHERE id=?", (status, change_id)
        )
        self.append_event(
            row["session_id"],
            "file.reviewed",
            {"change_id": change_id, "path": row["path"], "status": status},
            turn_id=row.get("turn_id"),
            visibility="recording_safe",
        )
        self.database.insert_audit(
            "file_change.reviewed",
            "file_change",
            change_id,
            {"action": value.action, "path": row["path"]},
        )
        return self.file_change_diff(row["session_id"], change_id)

    # Approval center
    def create_approval(
        self,
        session_id: str,
        *,
        request_type: str,
        title: str,
        description: str,
        request: dict[str, Any],
        risk_level: str = "medium",
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        self.get_session(session_id)
        approval_id = new_id()
        now = utc_now()
        self.database.execute(
            "INSERT INTO approval_requests(id,session_id,turn_id,request_type,status,title,"
            "description,risk_level,request_json,decision_json,created_at) "
            "VALUES (?,?,?,?,'pending',?,?,? ,?,'{}',?)",
            (
                approval_id,
                session_id,
                turn_id,
                request_type,
                title,
                description,
                risk_level,
                json.dumps(request, ensure_ascii=False),
                now,
            ),
        )
        self.database.execute(
            "UPDATE agent_sessions SET status='waiting_approval',updated_at=? WHERE id=?",
            (now, session_id),
        )
        if turn_id:
            self.database.execute(
                "UPDATE session_turns SET status='waiting_approval' WHERE id=? "
                "AND status IN ('preparing','running')",
                (turn_id,),
            )
        self.append_event(
            session_id,
            "approval.requested",
            {
                "approval_id": approval_id,
                "request_type": request_type,
                "title": title,
                "risk_level": risk_level,
            },
            turn_id=turn_id,
        )
        return self.get_approval(approval_id)

    def _public_approval(self, row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row["request"] = _json(row.pop("request_json"), {})
        row["decision"] = _json(row.pop("decision_json"), {})
        return row

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        row = self.database.fetch_one("SELECT * FROM approval_requests WHERE id=?", (approval_id,))
        if not row:
            raise KeyError("approval_not_found")
        return self._public_approval(row)

    def list_approvals(
        self, session_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id=?")
            params.append(session_id)
        if status:
            clauses.append("status=?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return [
            self._public_approval(row)
            for row in self.database.fetch_all(
                f"SELECT * FROM approval_requests {where} ORDER BY created_at DESC",
                tuple(params),
            )
        ]

    def decide_approval(
        self, approval_id: str, value: ApprovalDecision
    ) -> dict[str, Any]:
        approval = self.get_approval(approval_id)
        if approval["status"] != "pending":
            raise ValueError("approval_already_resolved")
        status = "denied" if value.decision == "deny" else "approved"
        now = utc_now()
        decision = {"decision": value.decision, "reason": value.reason}
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE approval_requests SET status=?,decision_json=?,resolved_at=? WHERE id=?",
                (status, json.dumps(decision, ensure_ascii=False), now, approval_id),
            )
            remaining = connection.execute(
                "SELECT COUNT(*) count FROM approval_requests WHERE session_id=? "
                "AND status='pending' AND id<>?",
                (approval["session_id"], approval_id),
            ).fetchone()
            if not int(remaining["count"]):
                active_turn = connection.execute(
                    "SELECT id FROM session_turns WHERE id=? AND status='waiting_approval'",
                    (approval.get("turn_id"),),
                ).fetchone() if approval.get("turn_id") else None
                if active_turn:
                    connection.execute(
                        "UPDATE session_turns SET status='running' WHERE id=?",
                        (active_turn["id"],),
                    )
                    connection.execute(
                        "UPDATE agent_sessions SET status='running',updated_at=? WHERE id=? "
                        "AND status='waiting_approval'",
                        (now, approval["session_id"]),
                    )
                else:
                    connection.execute(
                        "UPDATE agent_sessions SET status='idle',updated_at=? WHERE id=? "
                        "AND status='waiting_approval'",
                        (now, approval["session_id"]),
                    )
            if value.decision == "allow_project":
                session = connection.execute(
                    "SELECT project_id,runner_id FROM agent_sessions WHERE id=?",
                    (approval["session_id"],),
                ).fetchone()
                request = approval["request"]
                pattern = str(request.get("command") or request.get("path") or "*")
                connection.execute(
                    "INSERT OR REPLACE INTO permission_rules(id,project_id,runner_id,scope,pattern,"
                    "decision,created_at) VALUES (?,?,?,?,?,'allow',?)",
                    (
                        new_id(),
                        session["project_id"],
                        session["runner_id"],
                        approval["request_type"],
                        pattern,
                        now,
                    ),
                )
        self.append_event(
            approval["session_id"],
            "approval.resolved",
            {"approval_id": approval_id, "status": status, **decision},
            turn_id=approval.get("turn_id"),
        )
        self.database.insert_audit(
            "approval.resolved", "approval", approval_id, {"status": status, **decision}
        )
        return self.get_approval(approval_id)

    # Tasks and flow definitions
    def create_task(self, value: TaskItemCreate) -> dict[str, Any]:
        if value.project_id:
            self.get_project(value.project_id)
        if value.runner_id:
            self._enabled_entity("agent_runners", value.runner_id)
        if value.model_id:
            self._enabled_entity("models", value.model_id)
        task_id = new_id()
        now = utc_now()
        self.database.execute(
            "INSERT INTO task_items(id,project_id,title,description,status,priority,runner_id,"
            "model_id,created_at,updated_at) VALUES (?,?,?,?,'backlog',?,?,?,?,?)",
            (
                task_id,
                value.project_id,
                value.title.strip(),
                value.description.strip(),
                value.priority,
                value.runner_id,
                value.model_id,
                now,
                now,
            ),
        )
        self.database.insert_audit("task.created", "task", task_id)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT t.*,p.name project_name,r.name runner_name,m.name model_name "
            "FROM task_items t LEFT JOIN projects p ON p.id=t.project_id "
            "LEFT JOIN agent_runners r ON r.id=t.runner_id LEFT JOIN models m ON m.id=t.model_id "
            "WHERE t.id=?",
            (task_id,),
        )
        if not row:
            raise KeyError("task_not_found")
        return row

    def list_tasks(self, project_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE t.project_id=?" if project_id else ""
        params: tuple[Any, ...] = (project_id,) if project_id else ()
        return self.database.fetch_all(
            "SELECT t.*,p.name project_name,r.name runner_name,m.name model_name "
            "FROM task_items t LEFT JOIN projects p ON p.id=t.project_id "
            "LEFT JOIN agent_runners r ON r.id=t.runner_id LEFT JOIN models m ON m.id=t.model_id "
            f"{where} ORDER BY CASE t.status WHEN 'running' THEN 0 WHEN 'approval' THEN 1 "
            "WHEN 'queued' THEN 2 WHEN 'backlog' THEN 3 ELSE 4 END,t.updated_at DESC",
            params,
        )

    def update_task(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        self.get_task(task_id)
        allowed = {"title", "description", "status", "priority", "runner_id", "model_id"}
        values = {key: value for key, value in changes.items() if key in allowed}
        if "runner_id" in values and values["runner_id"]:
            self._enabled_entity("agent_runners", values["runner_id"])
        if "model_id" in values and values["model_id"]:
            self._enabled_entity("models", values["model_id"])
        if not values:
            return self.get_task(task_id)
        now = utc_now()
        values["updated_at"] = now
        if values.get("status") == "completed":
            values["completed_at"] = now
        assignments = ",".join(f"{key}=?" for key in values)
        self.database.execute(
            f"UPDATE task_items SET {assignments} WHERE id=?", (*values.values(), task_id)
        )
        self.database.insert_audit("task.updated", "task", task_id, changes)
        return self.get_task(task_id)

    def create_graph(self, value: TaskGraphCreate) -> dict[str, Any]:
        if value.project_id:
            self.get_project(value.project_id)
        graph_id = new_id()
        now = utc_now()
        node_ids: dict[str, str] = {}
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO task_graphs(id,project_id,name,description,status,settings_json,"
                "created_at,updated_at) VALUES (?,?,?,?,'draft',?,?,?)",
                (
                    graph_id,
                    value.project_id,
                    value.name.strip(),
                    value.description.strip(),
                    json.dumps(value.settings, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            for index, node in enumerate(value.nodes):
                alias = str(node.get("id") or f"node-{index + 1}")
                if alias in node_ids:
                    raise ValueError("duplicate_graph_node_id")
                node_id = new_id()
                node_ids[alias] = node_id
                connection.execute(
                    "INSERT INTO task_nodes(id,graph_id,node_type,name,position_x,position_y,"
                    "config_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'pending',?,?)",
                    (
                        node_id,
                        graph_id,
                        str(node.get("type") or "agent"),
                        str(node.get("name") or alias)[:180],
                        float(node.get("x") or 0),
                        float(node.get("y") or 0),
                        json.dumps(node.get("config") or {}, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            for edge in value.edges:
                source = node_ids.get(str(edge.get("source")))
                target = node_ids.get(str(edge.get("target")))
                if not source or not target or source == target:
                    raise ValueError("invalid_graph_edge")
                connection.execute(
                    "INSERT INTO task_edges(id,graph_id,source_node_id,target_node_id,"
                    "condition_json,created_at) VALUES (?,?,?,?,?,?)",
                    (
                        new_id(),
                        graph_id,
                        source,
                        target,
                        json.dumps(edge.get("condition") or {}, ensure_ascii=False),
                        now,
                    ),
                )
        self.database.insert_audit("task_graph.created", "task_graph", graph_id)
        return self.get_graph(graph_id)

    def get_graph(self, graph_id: str) -> dict[str, Any]:
        graph = self.database.fetch_one("SELECT * FROM task_graphs WHERE id=?", (graph_id,))
        if not graph:
            raise KeyError("task_graph_not_found")
        graph["settings"] = _json(graph.pop("settings_json"), {})
        graph["nodes"] = self.database.fetch_all(
            "SELECT * FROM task_nodes WHERE graph_id=? ORDER BY created_at", (graph_id,)
        )
        for node in graph["nodes"]:
            node["config"] = _json(node.pop("config_json"), {})
            node["output"] = _json(node.pop("output_json", None), {})
        graph["edges"] = self.database.fetch_all(
            "SELECT * FROM task_edges WHERE graph_id=? ORDER BY created_at", (graph_id,)
        )
        for edge in graph["edges"]:
            edge["condition"] = _json(edge.pop("condition_json"), {})
        return graph

    def list_graphs(self, project_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE g.project_id=?" if project_id else ""
        params: tuple[Any, ...] = (project_id,) if project_id else ()
        return self.database.fetch_all(
            "SELECT g.*,p.name project_name,"
            "(SELECT COUNT(*) FROM task_nodes n WHERE n.graph_id=g.id) node_count "
            "FROM task_graphs g LEFT JOIN projects p ON p.id=g.project_id "
            f"{where} ORDER BY g.updated_at DESC",
            params,
        )

    # MCP definitions. Secret values are stored in the platform keyring, never SQLite.
    def create_mcp_server(self, value: McpServerCreate) -> dict[str, Any]:
        if value.transport == "stdio" and not value.command:
            raise ValueError("mcp_stdio_command_required")
        if value.transport != "stdio" and not value.url:
            raise ValueError("mcp_url_required")
        server_id = new_id()
        now = utc_now()
        env_refs: dict[str, str] = {}
        try:
            for key, secret in value.env.items():
                if not key or not key.replace("_", "").isalnum():
                    raise ValueError("invalid_mcp_env_key")
                credential_ref = f"mcp-{server_id}-{key}"
                self.secrets.set(credential_ref, secret)
                env_refs[key] = credential_ref
            self.database.execute(
                "INSERT INTO mcp_servers(id,name,transport,command,args_json,url,env_json,enabled,"
                "builtin,created_at,updated_at) VALUES (?,?,?,?,?,?,?,1,0,?,?)",
                (
                    server_id,
                    value.name.strip(),
                    value.transport,
                    value.command,
                    json.dumps(value.args, ensure_ascii=False),
                    str(value.url) if value.url else None,
                    json.dumps(env_refs, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        except Exception:
            for credential_ref in env_refs.values():
                self.secrets.delete(credential_ref)
            raise
        self.database.insert_audit("mcp_server.created", "mcp_server", server_id)
        return self.get_mcp_server(server_id)

    def _public_mcp(self, row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row["args"] = _json(row.pop("args_json"), [])
        row["env_keys"] = sorted(_json(row.pop("env_json"), {}).keys())
        row["tools"] = _json(row.pop("tools_json", None), [])
        row["enabled"] = bool(row["enabled"])
        row["builtin"] = bool(row["builtin"])
        return row

    def get_mcp_server_internal(self, server_id: str) -> dict[str, Any]:
        row = self.database.fetch_one("SELECT * FROM mcp_servers WHERE id=?", (server_id,))
        if not row:
            raise KeyError("mcp_server_not_found")
        row["args"] = _json(row.get("args_json"), [])
        row["env_refs"] = _json(row.get("env_json"), {})
        return row

    def update_mcp_health(
        self,
        server_id: str,
        *,
        status: str,
        tools: list[dict[str, Any]],
        error: str | None,
    ) -> dict[str, Any]:
        self.get_mcp_server_internal(server_id)
        now = utc_now()
        self.database.execute(
            "UPDATE mcp_servers SET health_status=?,tools_json=?,last_error=?,"
            "last_checked_at=?,updated_at=? WHERE id=?",
            (
                status,
                json.dumps(tools, ensure_ascii=False),
                error,
                now,
                now,
                server_id,
            ),
        )
        return self.get_mcp_server(server_id)

    def get_mcp_server(self, server_id: str) -> dict[str, Any]:
        row = self.database.fetch_one("SELECT * FROM mcp_servers WHERE id=?", (server_id,))
        if not row:
            raise KeyError("mcp_server_not_found")
        return self._public_mcp(row)

    def list_mcp_servers(self) -> list[dict[str, Any]]:
        return [
            self._public_mcp(row)
            for row in self.database.fetch_all(
                "SELECT * FROM mcp_servers ORDER BY builtin DESC,name"
            )
        ]

    def dashboard(self) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT "
            "(SELECT COUNT(*) FROM projects WHERE archived=0) project_count,"
            "(SELECT COUNT(*) FROM agent_sessions WHERE archived=0) session_count,"
            "(SELECT COUNT(*) FROM agent_sessions WHERE status IN "
            "('queued','preparing','running','waiting_approval')) active_sessions,"
            "(SELECT COUNT(*) FROM approval_requests WHERE status='pending') pending_approvals,"
            "(SELECT COUNT(*) FROM task_items WHERE status='completed') completed_tasks,"
            "(SELECT COUNT(*) FROM task_items WHERE status IN ('backlog','queued','running','approval')) "
            "open_tasks,"
            "(SELECT COALESCE(SUM(tokens_input+tokens_output),0) FROM agent_sessions) total_tokens,"
            "(SELECT COALESCE(SUM(cost_usd),0) FROM agent_sessions) total_cost"
        ) or {}
        return {
            **row,
            "active_sessions_list": self.list_sessions(limit=5),
            "pending_approvals_list": self.list_approvals(status="pending")[:5],
            "recent_projects": self.list_projects()[:6],
        }
