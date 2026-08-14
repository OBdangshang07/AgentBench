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
    RuntimeProfileCreate,
    SessionAttachmentImport,
    SessionCreate,
    SessionForkCreate,
    SessionTurnCreate,
    SkillPackCreate,
    TaskGraphCreate,
    TaskItemCreate,
)
from .secrets import SecretStore

ACTIVE_SESSION_STATUSES = {"queued", "preparing", "running", "waiting_approval"}
TERMINAL_TURN_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
CHAT_PROJECT_ID = "__agentbench_chat__"
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
        self.seed_skill_packs()
        self.seed_runtime_profiles()
        self._ensure_chat_project()
        self.recover_interrupted_sessions()

    def _ensure_chat_project(self) -> None:
        """Maintain an internal root for isolated, workspace-free conversations."""
        root = (self.settings.data_dir / "chat-sessions").resolve()
        root.mkdir(parents=True, exist_ok=True)
        now = utc_now()
        if not self.database.fetch_one("SELECT id FROM projects WHERE id=?", (CHAT_PROJECT_ID,)):
            self.database.execute(
                "INSERT INTO projects(id,name,description,permission_profile,settings_json,pinned,"
                "archived,created_at,updated_at,last_opened_at) VALUES (?,?,?,'readonly',?,0,0,?,?,?)",
                (
                    CHAT_PROJECT_ID,
                    "纯对话",
                    "AgentBench internal isolated conversation root",
                    json.dumps({"builtin_chat": True}),
                    now,
                    now,
                    now,
                ),
            )
        existing_root = self.database.fetch_one(
            "SELECT id FROM project_roots WHERE project_id=? AND is_primary=1",
            (CHAT_PROJECT_ID,),
        )
        if existing_root:
            self.database.execute(
                "UPDATE project_roots SET root_path=?,label='纯对话',access_mode='readonly' "
                "WHERE id=?",
                (str(root), existing_root["id"]),
            )
        else:
            self.database.execute(
                "INSERT INTO project_roots(id,project_id,root_path,label,access_mode,is_primary,created_at) "
                "VALUES (?,?,?,'纯对话','readonly',1,?)",
                (new_id(), CHAT_PROJECT_ID, str(root), now),
            )

    def seed_skill_packs(self) -> None:
        if self.database.fetch_one("SELECT id FROM prompt_templates LIMIT 1"):
            return
        now = utc_now()
        defaults = [
            (
                "代码审查",
                "聚焦安全、正确性与可测试性",
                "审查相关实现，优先报告可复现的问题、风险等级与最小修复建议。",
                ["filesystem_read", "search", "shell"],
                "standard",
            ),
            (
                "前端实现",
                "实现并验证可用的交互界面",
                "先理解现有设计语言，再完成真实交互、响应式状态和相关前端测试。",
                ["filesystem_read", "filesystem_write", "search", "shell"],
                "standard",
            ),
            (
                "发布前验证",
                "执行发布前的回归与风险检查",
                "检查版本、变更范围、测试、生产构建和发布产物，不改动无关文件。",
                ["filesystem_read", "search", "shell"],
                "standard",
            ),
        ]
        with self.database.transaction() as connection:
            connection.executemany(
                "INSERT INTO prompt_templates(id,name,description,content,tools_json,"
                "permission_profile,builtin,created_at,updated_at) VALUES (?,?,?,?,?,?,1,?,?)",
                [
                    (new_id(), name, description, content, json.dumps(tools), permission, now, now)
                    for name, description, content, tools, permission in defaults
                ],
            )

    def seed_runtime_profiles(self) -> None:
        if self.database.fetch_one("SELECT id FROM runtime_profiles LIMIT 1"):
            return
        now = utc_now()
        skill_rows = {
            row["name"]: row["id"]
            for row in self.database.fetch_all("SELECT id,name FROM prompt_templates")
        }
        defaults = [
            (
                "日常开发",
                "适合常规实现、调试和测试，保留逐项审批保护。",
                "standard",
                "medium",
                skill_rows.get("前端实现"),
            ),
            (
                "深度实现",
                "为复杂工程任务提供更高思考强度与完整开发工具。",
                "standard",
                "high",
                None,
            ),
            (
                "只读审查",
                "只分析项目并给出有证据的结论，不写入文件。",
                "readonly",
                "high",
                skill_rows.get("代码审查"),
            ),
        ]
        with self.database.transaction() as connection:
            connection.executemany(
                "INSERT INTO runtime_profiles(id,name,description,permission_profile,"
                "reasoning_effort,skill_pack_id,builtin,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,1,?,?)",
                [
                    (new_id(), name, description, permission, effort, skill_id, now, now)
                    for name, description, permission, effort, skill_id in defaults
                ],
            )

    def recover_interrupted_sessions(self) -> None:
        now = utc_now()
        active = self.database.fetch_all(
            "SELECT id FROM agent_sessions WHERE status IN "
            "('queued','preparing','running','waiting_approval')"
        )
        active_tasks = self.database.fetch_all(
            "SELECT id,session_id,status FROM task_items "
            "WHERE status IN ('queued','running','approval')"
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
            connection.execute(
                "UPDATE task_nodes SET status='failed',error_message='AgentBench exited while this flow was active',"
                "updated_at=? WHERE status IN ('running','retrying','waiting_approval')",
                (now,),
            )
            connection.execute(
                "UPDATE task_graphs SET status='interrupted',updated_at=?,completed_at=? "
                "WHERE status IN ('running','waiting_approval','testing','cancelling')",
                (now, now),
            )
            connection.execute(
                "UPDATE task_graph_runs SET status='interrupted',"
                "error_message='AgentBench exited while this flow was active',completed_at=? "
                "WHERE status='running'",
                (now,),
            )
            connection.execute(
                "UPDATE task_items SET status='failed',"
                "result_summary='AgentBench exited while this task was active',updated_at=? "
                "WHERE status IN ('queued','running','approval')",
                (now,),
            )
        for row in active:
            self.append_event(
                row["id"],
                "session.interrupted",
                {"reason": "app_restarted"},
                visibility="user",
            )
        for row in active_tasks:
            self.append_task_event(
                str(row["id"]),
                "task.interrupted",
                {
                    "reason": "app_restarted",
                    "previous_status": row["status"],
                    "session_id": row.get("session_id"),
                },
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
        where = "WHERE p.id<>?" if include_archived else "WHERE p.id<>? AND p.archived=0"
        rows = self.database.fetch_all(
            "SELECT p.*,pr.root_path,"
            "(SELECT COUNT(*) FROM agent_sessions s WHERE s.project_id=p.id AND s.archived=0) "
            "session_count,"
            "(SELECT COUNT(*) FROM agent_sessions s WHERE s.project_id=p.id AND s.archived=0 "
            "AND s.status IN ('queued','preparing','running','waiting_approval')) active_sessions,"
            "(SELECT COUNT(*) FROM approval_requests a JOIN agent_sessions s ON s.id=a.session_id "
            "WHERE s.project_id=p.id AND a.status='pending') pending_approvals "
            "FROM projects p LEFT JOIN project_roots pr ON pr.project_id=p.id AND pr.is_primary=1 "
            f"{where} ORDER BY p.pinned DESC,COALESCE(p.last_opened_at,p.updated_at) DESC",
            (CHAT_PROJECT_ID,),
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

    def project_health(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        root = Path(project["root_path"])
        runner = self.database.fetch_one(
            "SELECT id,name,enabled FROM agent_runners WHERE id=?",
            (project.get("default_runner_id"),),
        )
        model = self.database.fetch_one(
            "SELECT id,name,enabled FROM models WHERE id=?",
            (project.get("default_model_id"),),
        )
        checks = [
            {
                "id": "root",
                "label": "项目目录",
                "ok": root.is_dir(),
                "detail": str(root),
            },
            {
                "id": "read",
                "label": "读取权限",
                "ok": root.is_dir() and os.access(root, os.R_OK),
                "detail": "目录可读取" if root.is_dir() and os.access(root, os.R_OK) else "目录不可读取",
            },
            {
                "id": "write",
                "label": "写入权限",
                "ok": project["permission_profile"] == "readonly" or (root.is_dir() and os.access(root, os.W_OK)),
                "detail": "只读配置" if project["permission_profile"] == "readonly" else "目录可写" if root.is_dir() and os.access(root, os.W_OK) else "目录不可写",
            },
            {
                "id": "runner",
                "label": "默认 Agent",
                "ok": bool(runner and runner["enabled"]),
                "detail": runner["name"] if runner else "未配置",
            },
            {
                "id": "model",
                "label": "默认模型",
                "ok": bool(model and model["enabled"]),
                "detail": model["name"] if model else "未配置",
            },
            {
                "id": "git",
                "label": "Git 工作区",
                "ok": bool(project.get("branch")) or shutil.which("git") is not None,
                "detail": project.get("branch") or ("Git 可用，当前目录未初始化仓库" if shutil.which("git") else "未检测到 Git"),
            },
        ]
        return {
            "project_id": project_id,
            "ready": all(item["ok"] for item in checks if item["id"] != "git"),
            "checks": checks,
            "checked_at": utc_now(),
        }

    def search_workspace(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        """Search the operational workspace without mixing in benchmark history."""
        needle = query.strip()
        if not needle:
            return []
        pattern = f"%{needle}%"
        per_kind = max(3, min(20, limit))
        results: list[dict[str, Any]] = []

        for row in self.database.fetch_all(
            "SELECT p.id,p.name title,p.description subtitle,p.updated_at,NULL status,"
            "pr.root_path extra FROM projects p "
            "LEFT JOIN project_roots pr ON pr.project_id=p.id AND pr.is_primary=1 "
            "WHERE p.archived=0 AND (p.name LIKE ? OR p.description LIKE ? OR pr.root_path LIKE ?) "
            "ORDER BY p.pinned DESC,COALESCE(p.last_opened_at,p.updated_at) DESC LIMIT ?",
            (pattern, pattern, pattern, per_kind),
        ):
            results.append({**row, "kind": "project", "path": f"/projects/{row['id']}"})

        for row in self.database.fetch_all(
            "SELECT s.id,s.title,COALESCE(s.summary,'') subtitle,s.updated_at,s.status,p.name extra "
            "FROM agent_sessions s JOIN projects p ON p.id=s.project_id "
            "WHERE s.archived=0 AND (s.title LIKE ? OR s.summary LIKE ? OR p.name LIKE ?) "
            "ORDER BY s.updated_at DESC LIMIT ?",
            (pattern, pattern, pattern, per_kind),
        ):
            results.append({**row, "kind": "session", "path": f"/studio/{row['id']}"})

        for row in self.database.fetch_all(
            "SELECT t.id,t.title,t.description subtitle,t.updated_at,t.status,p.name extra "
            "FROM task_items t LEFT JOIN projects p ON p.id=t.project_id "
            "WHERE t.title LIKE ? OR t.description LIKE ? OR p.name LIKE ? "
            "ORDER BY t.updated_at DESC LIMIT ?",
            (pattern, pattern, pattern, per_kind),
        ):
            results.append({**row, "kind": "task", "path": f"/tasks?task={row['id']}"})

        for row in self.database.fetch_all(
            "SELECT g.id,g.name title,g.description subtitle,g.updated_at,g.status,p.name extra "
            "FROM task_graphs g LEFT JOIN projects p ON p.id=g.project_id "
            "WHERE g.name LIKE ? OR g.description LIKE ? OR p.name LIKE ? "
            "ORDER BY g.updated_at DESC LIMIT ?",
            (pattern, pattern, pattern, per_kind),
        ):
            results.append({**row, "kind": "flow", "path": f"/flows?flow={row['id']}"})

        results.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return results[: max(1, min(limit, 80))]

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
        if project_id == CHAT_PROJECT_ID:
            raise ValueError("chat_session_has_no_project_files")
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
        if project_id == CHAT_PROJECT_ID:
            raise ValueError("chat_session_has_no_project_files")
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
        session_mode = str(row.get("session_mode") or "workspace")
        return {
            "id": row["id"],
            "project_id": None if session_mode == "chat" else row["project_id"],
            "project_name": "纯对话" if session_mode == "chat" else row.get("project_name"),
            "session_mode": session_mode,
            "title": row["title"],
            "runner_id": row["runner_id"],
            "runner_name": row.get("runner_name"),
            "runner_type": row.get("runner_type"),
            "model_id": row["model_id"],
            "model_name": row.get("model_name"),
            "status": row["status"],
            "permission_profile": row["permission_profile"],
            "reasoning_effort": row.get("reasoning_effort") or "medium",
            "profile_id": row.get("profile_id"),
            "profile_name": row.get("profile_name"),
            "skill_pack_id": row.get("skill_pack_id"),
            "skill_pack_name": row.get("skill_pack_name"),
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
            "pt.name skill_pack_name,rp.name profile_name,"
            "(SELECT COUNT(*) FROM session_turns t WHERE t.session_id=s.id) turn_count,"
            "(SELECT COUNT(*) FROM approval_requests a WHERE a.session_id=s.id "
            "AND a.status='pending') pending_approvals "
            "FROM agent_sessions s JOIN projects p ON p.id=s.project_id "
            "JOIN agent_runners r ON r.id=s.runner_id JOIN models m ON m.id=s.model_id "
            "LEFT JOIN prompt_templates pt ON pt.id=s.skill_pack_id "
            "LEFT JOIN runtime_profiles rp ON rp.id=s.profile_id "
            f"{where} ORDER BY s.updated_at DESC",
            params,
        )

    @staticmethod
    def _runtime_profile(row: dict[str, Any]) -> dict[str, Any]:
        output = dict(row)
        output["mcp_server_ids"] = _json(output.pop("mcp_server_ids_json", "[]"), [])
        output["builtin"] = bool(output.get("builtin"))
        return output

    def get_runtime_profile(self, profile_id: str) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT rp.*,r.name runner_name,m.name model_name,pt.name skill_pack_name "
            "FROM runtime_profiles rp LEFT JOIN agent_runners r ON r.id=rp.runner_id "
            "LEFT JOIN models m ON m.id=rp.model_id "
            "LEFT JOIN prompt_templates pt ON pt.id=rp.skill_pack_id WHERE rp.id=?",
            (profile_id,),
        )
        if not row:
            raise KeyError("runtime_profile_not_found")
        return self._runtime_profile(row)

    def list_runtime_profiles(self) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            "SELECT rp.*,r.name runner_name,m.name model_name,pt.name skill_pack_name "
            "FROM runtime_profiles rp LEFT JOIN agent_runners r ON r.id=rp.runner_id "
            "LEFT JOIN models m ON m.id=rp.model_id "
            "LEFT JOIN prompt_templates pt ON pt.id=rp.skill_pack_id "
            "ORDER BY rp.builtin DESC,rp.name"
        )
        return [self._runtime_profile(row) for row in rows]

    def _validate_runtime_profile_links(self, values: dict[str, Any]) -> None:
        if values.get("runner_id"):
            self._enabled_entity("agent_runners", str(values["runner_id"]))
        if values.get("model_id"):
            self._enabled_entity("models", str(values["model_id"]))
        if values.get("skill_pack_id"):
            self.get_skill_pack(str(values["skill_pack_id"]))
        for server_id in values.get("mcp_server_ids") or []:
            self.get_mcp_server(str(server_id))

    def create_runtime_profile(self, value: RuntimeProfileCreate) -> dict[str, Any]:
        values = value.model_dump()
        self._validate_runtime_profile_links(values)
        profile_id = new_id()
        now = utc_now()
        self.database.execute(
            "INSERT INTO runtime_profiles(id,name,description,runner_id,model_id,"
            "permission_profile,reasoning_effort,skill_pack_id,mcp_server_ids_json,builtin,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,0,?,?)",
            (
                profile_id,
                value.name.strip(),
                value.description.strip(),
                value.runner_id,
                value.model_id,
                value.permission_profile,
                value.reasoning_effort,
                value.skill_pack_id,
                json.dumps(list(dict.fromkeys(value.mcp_server_ids))),
                now,
                now,
            ),
        )
        self.database.insert_audit("runtime_profile.created", "runtime_profile", profile_id)
        return self.get_runtime_profile(profile_id)

    def update_runtime_profile(self, profile_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        current = self.get_runtime_profile(profile_id)
        self._validate_runtime_profile_links(changes)
        values = dict(changes)
        if "name" in values:
            values["name"] = str(values["name"]).strip()
        if "description" in values:
            values["description"] = str(values["description"] or "").strip()
        if "mcp_server_ids" in values:
            values["mcp_server_ids_json"] = json.dumps(
                list(dict.fromkeys(values.pop("mcp_server_ids") or []))
            )
        if not values:
            return current
        values["updated_at"] = utc_now()
        assignments = ",".join(f"{key}=?" for key in values)
        self.database.execute(
            f"UPDATE runtime_profiles SET {assignments} WHERE id=?",
            (*values.values(), profile_id),
        )
        self.database.insert_audit(
            "runtime_profile.updated", "runtime_profile", profile_id, changes
        )
        return self.get_runtime_profile(profile_id)

    def delete_runtime_profile(self, profile_id: str) -> None:
        profile = self.get_runtime_profile(profile_id)
        if profile["builtin"]:
            raise ValueError("builtin_runtime_profile_cannot_be_deleted")
        with self.database.transaction() as connection:
            connection.execute("UPDATE agent_sessions SET profile_id=NULL WHERE profile_id=?", (profile_id,))
            connection.execute("DELETE FROM runtime_profiles WHERE id=?", (profile_id,))
        self.database.insert_audit("runtime_profile.deleted", "runtime_profile", profile_id)

    def create_session(self, value: SessionCreate) -> dict[str, Any]:
        session_mode = value.session_mode
        if session_mode == "workspace" and not value.project_id:
            raise ValueError("workspace_session_requires_project")
        project_id = CHAT_PROJECT_ID if session_mode == "chat" else str(value.project_id)
        project = self.get_project(project_id)
        if project["archived"]:
            raise ValueError("project_archived")
        profile_id = None if session_mode == "chat" else value.profile_id
        profile = self.get_runtime_profile(profile_id) if profile_id else None
        runner_id = value.runner_id or (profile or {}).get("runner_id") or project.get("default_runner_id")
        model_id = value.model_id or (profile or {}).get("model_id") or project.get("default_model_id")
        if not runner_id:
            runner_id = self._default_entity_id("agent_runners")
        if not model_id:
            model_id = self._default_entity_id("models")
        self._enabled_entity("agent_runners", runner_id)
        self._enabled_entity("models", model_id)
        skill_pack_id = None if session_mode == "chat" else (
            value.skill_pack_id or (profile or {}).get("skill_pack_id")
        )
        skill_pack = self.get_skill_pack(skill_pack_id) if skill_pack_id else None
        session_id = new_id()
        root = self._primary_root(project_id)
        if session_mode == "chat":
            root = (root / session_id).resolve()
            expected = (self.settings.data_dir / "chat-sessions").resolve()
            if not root.is_relative_to(expected):
                raise RuntimeError("invalid_chat_session_workspace")
            root.mkdir(parents=True, exist_ok=False)
        now = utc_now()
        permission_profile = "readonly" if session_mode == "chat" else (
            value.permission_profile
            or (profile or {}).get("permission_profile")
            or (skill_pack or {}).get("permission_profile")
            or project["permission_profile"]
        )
        reasoning_effort = value.reasoning_effort or (profile or {}).get("reasoning_effort") or "medium"
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO agent_sessions(id,project_id,session_mode,title,runner_id,model_id,status,"
                "permission_profile,reasoning_effort,profile_id,skill_pack_id,workspace_path,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,'idle',?,?,?,?,?,?,?)",
                (
                    session_id,
                    project_id,
                    session_mode,
                    value.title.strip(),
                    runner_id,
                    model_id,
                    permission_profile,
                    reasoning_effort,
                    profile_id,
                    skill_pack_id,
                    str(root),
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE projects SET last_opened_at=?,updated_at=? WHERE id=?",
                (now, now, project_id),
            )
        self.append_event(
            session_id,
            "session.created",
            {
                "runner_id": runner_id,
                "model_id": model_id,
                "permission_profile": permission_profile,
                "reasoning_effort": reasoning_effort,
                "profile_id": value.profile_id,
                "session_mode": session_mode,
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

    def get_session(self, session_id: str, message_limit: int | None = None) -> dict[str, Any]:
        rows = self._session_query("WHERE s.id=?", (session_id,))
        if not rows:
            raise KeyError("session_not_found")
        output = self._session_summary(rows[0])
        message_count = int(
            (
                self.database.fetch_one(
                    "SELECT COUNT(*) count FROM session_messages WHERE session_id=?",
                    (session_id,),
                )
                or {}
            ).get("count", 0)
        )
        if message_limit is None:
            messages = self.database.fetch_all(
                "SELECT id,turn_id,role,content,metadata_json,created_at FROM session_messages "
                "WHERE session_id=? ORDER BY created_at,id",
                (session_id,),
            )
        else:
            limit = max(20, min(int(message_limit), 2000))
            messages = self.database.fetch_all(
                "SELECT * FROM (SELECT id,turn_id,role,content,metadata_json,created_at "
                "FROM session_messages WHERE session_id=? ORDER BY created_at DESC,id DESC LIMIT ?) "
                "ORDER BY created_at,id",
                (session_id, limit),
            )
        for message in messages:
            message["metadata"] = _json(message.pop("metadata_json"), {})
        output["messages"] = messages
        output["message_count"] = message_count
        output["messages_truncated"] = len(messages) < message_count
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
            "profile_id",
            "runner_id",
            "model_id",
            "permission_profile",
            "reasoning_effort",
            "skill_pack_id",
            "archived",
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        if session.get("session_mode") == "chat":
            if any(key in values for key in ("profile_id", "skill_pack_id")):
                raise ValueError("chat_session_does_not_support_project_profiles")
            if "permission_profile" in values and values["permission_profile"] != "readonly":
                raise ValueError("chat_session_is_always_readonly")
            values["permission_profile"] = "readonly"
        if "profile_id" in values and values["profile_id"]:
            profile = self.get_runtime_profile(str(values["profile_id"]))
            profile_values = {
                "profile_id": profile["id"],
                "permission_profile": profile["permission_profile"],
                "reasoning_effort": profile["reasoning_effort"],
                "skill_pack_id": profile.get("skill_pack_id"),
            }
            if profile.get("runner_id"):
                profile_values["runner_id"] = profile["runner_id"]
            if profile.get("model_id"):
                profile_values["model_id"] = profile["model_id"]
            values = {**profile_values, **values}
        if session["status"] in ACTIVE_SESSION_STATUSES and any(
            key in values for key in ("runner_id", "model_id", "profile_id")
        ):
            raise ValueError("active_session_configuration_locked")
        if "runner_id" in values and values["runner_id"] is not None:
            self._enabled_entity("agent_runners", values["runner_id"])
        if "model_id" in values and values["model_id"] is not None:
            self._enabled_entity("models", values["model_id"])
        if "skill_pack_id" in values and values["skill_pack_id"] is not None:
            self.get_skill_pack(values["skill_pack_id"])
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

    def fork_session(self, session_id: str, value: SessionForkCreate) -> dict[str, Any]:
        source = self.get_session(session_id)
        selected: list[dict[str, Any]] = []
        found_boundary = value.through_message_id is None
        for message in source["messages"]:
            selected.append(message)
            if value.through_message_id and message["id"] == value.through_message_id:
                found_boundary = True
                break
        if not found_boundary:
            raise KeyError("session_message_not_found")
        created = self.create_session(
            SessionCreate(
                project_id=source["project_id"] if source.get("session_mode") != "chat" else None,
                session_mode=source.get("session_mode") or "workspace",
                profile_id=source.get("profile_id"),
                runner_id=source["runner_id"],
                model_id=source["model_id"],
                title=value.title or f"{source['title']} · 分支",
                permission_profile=source["permission_profile"],
                reasoning_effort=source["reasoning_effort"],
                skill_pack_id=source.get("skill_pack_id"),
            )
        )
        now = utc_now()
        with self.database.transaction() as connection:
            for message in selected:
                metadata = dict(message.get("metadata") or {})
                metadata["forked_from"] = {"session_id": session_id, "message_id": message["id"]}
                connection.execute(
                    "INSERT INTO session_messages(id,session_id,turn_id,role,content,metadata_json,created_at) "
                    "VALUES (?,?,NULL,?,?,?,?)",
                    (
                        new_id(),
                        created["id"],
                        message["role"],
                        message["content"],
                        json.dumps(metadata, ensure_ascii=False),
                        now,
                    ),
                )
        self.append_event(
            created["id"],
            "session.forked",
            {"source_session_id": session_id, "message_count": len(selected)},
        )
        self.database.insert_audit(
            "session.forked",
            "session",
            created["id"],
            {"source_session_id": session_id, "message_count": len(selected)},
        )
        return self.get_session(created["id"])

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
        queued_behind_active = session["status"] in ACTIVE_SESSION_STATUSES
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
            if not queued_behind_active:
                connection.execute(
                    "UPDATE agent_sessions SET status='queued',updated_at=?,"
                    "started_at=COALESCE(started_at,?) WHERE id=?",
                    (now, now, session_id),
                )
        self.append_event(
            session_id,
            "turn.enqueued" if queued_behind_active else "turn.queued",
            {
                "turn_id": turn_id,
                "turn_no": turn_no,
                "context_items": len(context),
                "queued_behind_active": queued_behind_active,
            },
            turn_id=turn_id,
        )
        self.database.insert_audit(
            "session.turn_queued", "session", session_id, {"turn_id": turn_id}
        )
        output = self.database.fetch_one(
            "SELECT * FROM session_turns WHERE id=?", (turn_id,)
        ) or {}
        output["queued_behind_active"] = queued_behind_active
        return output

    def cancel_queued_turn(self, session_id: str, turn_id: str) -> dict[str, Any]:
        """Cancel one not-yet-started instruction without disturbing the active turn."""
        self.get_session(session_id)
        turn = self.database.fetch_one(
            "SELECT id,turn_no,status FROM session_turns WHERE id=? AND session_id=?",
            (turn_id, session_id),
        )
        if not turn:
            raise KeyError("session_turn_not_found")
        if turn["status"] != "queued":
            raise ValueError("session_turn_not_queued")
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE session_turns SET status='cancelled',error_code='queue_removed',"
                "error_message='Removed from the pending instruction queue',completed_at=? "
                "WHERE id=? AND status='queued'",
                (now, turn_id),
            )
            connection.execute(
                "DELETE FROM session_messages WHERE session_id=? AND turn_id=? AND role='user'",
                (session_id, turn_id),
            )
            connection.execute(
                "UPDATE session_artifacts SET turn_id=NULL WHERE session_id=? AND turn_id=? "
                "AND kind='attachment'",
                (session_id, turn_id),
            )
        self.append_event(
            session_id,
            "turn.queue_removed",
            {"turn_id": turn_id, "turn_no": turn["turn_no"]},
            turn_id=turn_id,
        )
        self.database.insert_audit(
            "session.turn_queue_removed", "session", session_id, {"turn_id": turn_id}
        )
        return {**self.get_session(session_id), "removed_turn_id": turn_id}

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
        task = self.database.fetch_one(
            "SELECT id,status FROM task_items WHERE session_id=? AND archived=0",
            (session_id,),
        )
        if task and task["status"] in {"queued", "running"}:
            self.database.execute(
                "UPDATE task_items SET status='approval',updated_at=? WHERE id=?",
                (now, task["id"]),
            )
            self.append_task_event(
                str(task["id"]),
                "task.awaiting_approval",
                {
                    "approval_id": approval_id,
                    "request_type": request_type,
                    "title": title,
                    "risk_level": risk_level,
                },
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
        task = self.database.fetch_one(
            "SELECT id,status FROM task_items WHERE session_id=? AND archived=0",
            (approval["session_id"],),
        )
        if task and task["status"] == "approval":
            self.database.execute(
                "UPDATE task_items SET status='running',updated_at=? WHERE id=?",
                (now, task["id"]),
            )
            self.append_task_event(
                str(task["id"]),
                "task.approval_resolved",
                {"approval_id": approval_id, "status": status, **decision},
            )
        self.database.insert_audit(
            "approval.resolved", "approval", approval_id, {"status": status, **decision}
        )
        return self.get_approval(approval_id)

    # Tasks and flow definitions
    def append_task_event(
        self, task_id: str, event_type: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.get_task(task_id)
        created_at = utc_now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO task_events(task_id,event_type,payload_json,created_at) "
                "VALUES (?,?,?,?)",
                (
                    task_id,
                    event_type,
                    json.dumps(payload or {}, ensure_ascii=False),
                    created_at,
                ),
            )
        return {
            "id": int(cursor.lastrowid),
            "task_id": task_id,
            "event_type": event_type,
            "payload": payload or {},
            "created_at": created_at,
        }

    def list_task_events(self, task_id: str, limit: int = 300) -> list[dict[str, Any]]:
        self.get_task(task_id)
        rows = self.database.fetch_all(
            "SELECT id,task_id,event_type,payload_json,created_at FROM task_events "
            "WHERE task_id=? ORDER BY id DESC LIMIT ?",
            (task_id, max(1, min(limit, 1000))),
        )
        rows.reverse()
        for row in rows:
            row["payload"] = _json(row.pop("payload_json"), {})
        return rows

    def create_task(self, value: TaskItemCreate) -> dict[str, Any]:
        if value.project_id:
            self.get_project(value.project_id)
        if value.runner_id:
            self._enabled_entity("agent_runners", value.runner_id)
        if value.model_id:
            self._enabled_entity("models", value.model_id)
        for dependency_id in value.depends_on:
            self.get_task(dependency_id)
        task_id = new_id()
        now = utc_now()
        self.database.execute(
            "INSERT INTO task_items(id,project_id,title,description,status,priority,runner_id,"
            "model_id,due_at,tags_json,depends_on_json,acceptance_json,created_at,updated_at) "
            "VALUES (?,?,?,?,'backlog',?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                value.project_id,
                value.title.strip(),
                value.description.strip(),
                value.priority,
                value.runner_id,
                value.model_id,
                value.due_at,
                json.dumps(sorted({item.strip() for item in value.tags if item.strip()}), ensure_ascii=False),
                json.dumps(list(dict.fromkeys(value.depends_on)), ensure_ascii=False),
                json.dumps(
                    [item.model_dump() for item in value.acceptance_criteria],
                    ensure_ascii=False,
                ),
                now,
                now,
            ),
        )
        self.append_task_event(
            task_id,
            "task.created",
            {"title": value.title.strip(), "priority": value.priority},
        )
        self.database.insert_audit("task.created", "task", task_id)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT t.*,p.name project_name,r.name runner_name,m.name model_name,s.status session_status "
            "FROM task_items t LEFT JOIN projects p ON p.id=t.project_id "
            "LEFT JOIN agent_runners r ON r.id=t.runner_id LEFT JOIN models m ON m.id=t.model_id "
            "LEFT JOIN agent_sessions s ON s.id=t.session_id "
            "WHERE t.id=?",
            (task_id,),
        )
        if not row:
            raise KeyError("task_not_found")
        return self._task_summary(row)

    def get_task_detail(self, task_id: str) -> dict[str, Any]:
        output = self.get_task(task_id)
        output["events"] = self.list_task_events(task_id)
        output["dependencies"] = [
            self.get_task(str(item)) for item in output.get("depends_on") or []
        ]
        return output

    @staticmethod
    def _task_summary(row: dict[str, Any]) -> dict[str, Any]:
        output = dict(row)
        session_status = output.pop("session_status", None)
        if output.get("status") == "running" and session_status == "waiting_approval":
            output["status"] = "approval"
        output["tags"] = _json(output.pop("tags_json", "[]"), [])
        output["depends_on"] = _json(output.pop("depends_on_json", "[]"), [])
        output["acceptance_criteria"] = _json(output.pop("acceptance_json", "[]"), [])
        output["archived"] = bool(output.get("archived"))
        return output

    def _validate_task_dependencies(self, task_id: str, dependencies: list[str]) -> None:
        if task_id in dependencies:
            raise ValueError("task_cannot_depend_on_itself")
        queue = list(dependencies)
        visited: set[str] = set()
        while queue:
            dependency_id = queue.pop(0)
            if dependency_id == task_id:
                raise ValueError("task_dependency_cycle")
            if dependency_id in visited:
                continue
            visited.add(dependency_id)
            dependency = self.get_task(dependency_id)
            queue.extend(str(item) for item in dependency.get("depends_on") or [])

    def list_tasks(self, project_id: str | None = None, include_archived: bool = False) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("t.project_id=?")
            params.append(project_id)
        if not include_archived:
            clauses.append("t.archived=0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.database.fetch_all(
            "SELECT t.*,p.name project_name,r.name runner_name,m.name model_name,s.status session_status "
            "FROM task_items t LEFT JOIN projects p ON p.id=t.project_id "
            "LEFT JOIN agent_runners r ON r.id=t.runner_id LEFT JOIN models m ON m.id=t.model_id "
            "LEFT JOIN agent_sessions s ON s.id=t.session_id "
            f"{where} ORDER BY CASE t.status WHEN 'running' THEN 0 WHEN 'approval' THEN 1 "
            "WHEN 'queued' THEN 2 WHEN 'backlog' THEN 3 ELSE 4 END,t.updated_at DESC",
            tuple(params),
        )
        return [self._task_summary(row) for row in rows]

    def update_task(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        self.get_task(task_id)
        allowed = {"project_id", "title", "description", "status", "priority", "runner_id", "model_id", "due_at", "tags", "depends_on", "acceptance_criteria", "archived"}
        values = {key: value for key, value in changes.items() if key in allowed}
        previous_status = self.get_task(task_id)["status"]
        if "project_id" in values and values["project_id"]:
            self.get_project(values["project_id"])
        if "runner_id" in values and values["runner_id"]:
            self._enabled_entity("agent_runners", values["runner_id"])
        if "model_id" in values and values["model_id"]:
            self._enabled_entity("models", values["model_id"])
        if "tags" in values:
            values["tags_json"] = json.dumps(
                sorted({str(item).strip() for item in values.pop("tags") if str(item).strip()}),
                ensure_ascii=False,
            )
        if "depends_on" in values:
            dependencies = list(dict.fromkeys(str(item) for item in values.pop("depends_on")))
            self._validate_task_dependencies(task_id, dependencies)
            values["depends_on_json"] = json.dumps(dependencies, ensure_ascii=False)
        if "acceptance_criteria" in values:
            criteria = []
            seen: set[str] = set()
            for item in values.pop("acceptance_criteria"):
                raw = item.model_dump() if hasattr(item, "model_dump") else dict(item)
                text = str(raw.get("text") or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                criteria.append({"text": text, "completed": bool(raw.get("completed"))})
            values["acceptance_json"] = json.dumps(criteria, ensure_ascii=False)
        if "archived" in values:
            values["archived"] = int(bool(values["archived"]))
        if not values:
            return self.get_task(task_id)
        now = utc_now()
        values["updated_at"] = now
        if values.get("status") == "completed":
            values["completed_at"] = now
            values["cancelled_at"] = None
        elif values.get("status") == "cancelled":
            values["cancelled_at"] = now
            values["completed_at"] = None
        assignments = ",".join(f"{key}=?" for key in values)
        self.database.execute(
            f"UPDATE task_items SET {assignments} WHERE id=?", (*values.values(), task_id)
        )
        updated = self.get_task(task_id)
        if updated["status"] != previous_status:
            self.append_task_event(
                task_id,
                "task.status_changed",
                {"from": previous_status, "to": updated["status"]},
            )
        else:
            self.append_task_event(
                task_id,
                "task.updated",
                {"fields": sorted(key for key in changes if key in allowed)},
            )
        self.database.insert_audit("task.updated", "task", task_id, changes)
        return updated

    def duplicate_task(self, task_id: str) -> dict[str, Any]:
        source = self.get_task(task_id)
        created = self.create_task(
            TaskItemCreate(
                project_id=source.get("project_id"),
                title=f"{source['title']} · 副本",
                description=source.get("description") or "",
                priority=source.get("priority") or "normal",
                runner_id=source.get("runner_id"),
                model_id=source.get("model_id"),
                due_at=source.get("due_at"),
                tags=source.get("tags") or [],
                depends_on=source.get("depends_on") or [],
                acceptance_criteria=source.get("acceptance_criteria") or [],
            )
        )
        self.database.execute(
            "UPDATE task_items SET retry_of=? WHERE id=?", (task_id, created["id"])
        )
        self.database.insert_audit("task.duplicated", "task", created["id"], {"source": task_id})
        self.append_task_event(created["id"], "task.duplicated", {"source": task_id})
        return self.get_task(created["id"])

    def bulk_update_tasks(
        self, task_ids: list[str], action: str, value: str | None = None
    ) -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(task_ids))
        updated: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for task_id in unique_ids:
            try:
                task = self.get_task(task_id)
                if action == "archive":
                    if task["status"] in ACTIVE_SESSION_STATUSES or task["status"] == "approval":
                        raise ValueError("active_task_cannot_be_archived")
                    updated.append(self.update_task(task_id, {"archived": True}))
                elif action == "duplicate":
                    updated.append(self.duplicate_task(task_id))
                elif action == "set_priority":
                    if value not in {"low", "normal", "high", "urgent"}:
                        raise ValueError("invalid_task_priority")
                    updated.append(self.update_task(task_id, {"priority": value}))
                elif action == "set_status":
                    if task["status"] in {"queued", "running", "approval"}:
                        raise ValueError("active_task_status_locked")
                    if value not in {"backlog", "completed"}:
                        raise ValueError("invalid_manual_task_status")
                    updated.append(self.update_task(task_id, {"status": value}))
                else:
                    raise ValueError("invalid_task_bulk_action")
            except (KeyError, ValueError) as exc:
                errors.append({"task_id": task_id, "error": str(exc)})
        self.database.insert_audit(
            "task.bulk_updated",
            "task",
            "bulk",
            {"action": action, "requested": len(unique_ids), "updated": len(updated)},
        )
        return {"requested": len(unique_ids), "updated": updated, "errors": errors}

    def create_graph(self, value: TaskGraphCreate) -> dict[str, Any]:
        if value.project_id:
            self.get_project(value.project_id)
        graph_id = new_id()
        now = utc_now()
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
            self._insert_graph_definition(connection, graph_id, value.nodes, value.edges, now)
        self.database.insert_audit("task_graph.created", "task_graph", graph_id)
        self.create_graph_version(graph_id, "初始版本")
        return self.get_graph(graph_id)

    @staticmethod
    def list_graph_templates() -> list[dict[str, Any]]:
        """Return curated local templates that remain editable after creation."""
        defaults = {
            "max_retries": 1,
            "max_concurrency": 2,
            "max_runtime_seconds": 2700,
            "max_cost_usd": 3,
            "max_tokens": 500_000,
            "parallel_worktrees": True,
        }
        return [
            {
                "id": "single-delivery",
                "name": "单 Agent 交付",
                "description": "一个 Agent 完成实施，再由人工确认结果。",
                "category": "STARTER",
                "settings": defaults,
                "nodes": [
                    {
                        "id": "implement",
                        "type": "agent",
                        "name": "实施任务",
                        "x": 90,
                        "y": 170,
                        "config": {
                            "prompt": "理解目标，在项目中完成实施与验证，并汇报可检查的结果。",
                            "error_strategy": "fail_flow",
                            "retry_count": 1,
                        },
                    },
                    {
                        "id": "approve",
                        "type": "approval",
                        "name": "确认结果",
                        "x": 410,
                        "y": 170,
                        "config": {
                            "description": "检查 Agent 的结果、测试和文件变更后决定是否接受。",
                            "error_strategy": "fail_flow",
                            "retry_count": 0,
                            "input_bindings": [
                                {
                                    "source_node_id": "implement",
                                    "path": "summary",
                                    "target": "result",
                                }
                            ],
                        },
                    },
                ],
                "edges": [{"source": "implement", "target": "approve"}],
            },
            {
                "id": "parallel-review",
                "name": "双路并行评审",
                "description": "两个 Agent 并行分析，由第三个 Agent 汇总并交给人工审批。",
                "category": "MULTI AGENT",
                "settings": {**defaults, "max_concurrency": 3},
                "nodes": [
                    {
                        "id": "quality",
                        "type": "agent",
                        "name": "质量评审",
                        "x": 70,
                        "y": 80,
                        "config": {
                            "prompt": "检查正确性、可维护性和测试覆盖，给出有证据的结论。",
                            "error_strategy": "continue",
                            "retry_count": 1,
                        },
                    },
                    {
                        "id": "risk",
                        "type": "agent",
                        "name": "风险评审",
                        "x": 70,
                        "y": 280,
                        "config": {
                            "prompt": "检查安全、权限、兼容性和发布风险，给出有证据的结论。",
                            "error_strategy": "continue",
                            "retry_count": 1,
                        },
                    },
                    {
                        "id": "synthesis",
                        "type": "agent",
                        "name": "汇总结论",
                        "x": 410,
                        "y": 180,
                        "config": {
                            "prompt": "合并两路评审，消除重复并输出按优先级排列的最终结论。",
                            "error_strategy": "fail_flow",
                            "retry_count": 1,
                            "input_bindings": [
                                {"source_node_id": "quality", "path": "summary", "target": "quality_review"},
                                {"source_node_id": "risk", "path": "summary", "target": "risk_review"},
                            ],
                        },
                    },
                    {
                        "id": "approve",
                        "type": "approval",
                        "name": "人工决策",
                        "x": 740,
                        "y": 180,
                        "config": {
                            "description": "审阅汇总结论并决定是否继续。",
                            "error_strategy": "fail_flow",
                            "retry_count": 0,
                        },
                    },
                ],
                "edges": [
                    {"source": "quality", "target": "synthesis"},
                    {"source": "risk", "target": "synthesis"},
                    {"source": "synthesis", "target": "approve"},
                ],
            },
            {
                "id": "conditional-recovery",
                "name": "条件分支与恢复",
                "description": "先检查项目，再按结构化结果选择修复或直接复核。",
                "category": "CONTROL FLOW",
                "settings": defaults,
                "nodes": [
                    {
                        "id": "inspect",
                        "type": "agent",
                        "name": "项目检查",
                        "x": 70,
                        "y": 180,
                        "config": {
                            "prompt": "检查项目并在结论中明确写出 NEEDS_FIX 或 READY。",
                            "error_strategy": "fail_flow",
                            "retry_count": 1,
                        },
                    },
                    {
                        "id": "gate",
                        "type": "condition",
                        "name": "是否需要修复",
                        "x": 380,
                        "y": 180,
                        "config": {
                            "operator": "contains",
                            "value": "NEEDS_FIX",
                            "error_strategy": "fail_flow",
                            "retry_count": 0,
                        },
                    },
                    {
                        "id": "fix",
                        "type": "agent",
                        "name": "实施修复",
                        "x": 700,
                        "y": 90,
                        "config": {
                            "prompt": "依据检查结论实施修复，并运行相关验证。",
                            "error_strategy": "skip_branch",
                            "retry_count": 2,
                        },
                    },
                    {
                        "id": "review",
                        "type": "approval",
                        "name": "最终复核",
                        "x": 700,
                        "y": 290,
                        "config": {
                            "description": "复核检查结论或修复结果。",
                            "error_strategy": "fail_flow",
                            "retry_count": 0,
                        },
                    },
                ],
                "edges": [
                    {"source": "inspect", "target": "gate"},
                    {"source": "gate", "target": "fix", "condition": {"when": True}},
                    {"source": "gate", "target": "review", "condition": {"when": False}},
                ],
            },
        ]

    @staticmethod
    def _graph_definition(graph: dict[str, Any]) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": node["id"],
                    "type": node["node_type"],
                    "name": node["name"],
                    "x": node["position_x"],
                    "y": node["position_y"],
                    "config": node.get("config") or {},
                }
                for node in graph["nodes"]
            ],
            "edges": [
                {
                    "source": edge["source_node_id"],
                    "target": edge["target_node_id"],
                    "condition": edge.get("condition") or {},
                }
                for edge in graph["edges"]
            ],
        }

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def create_graph_version(self, graph_id: str, label: str = "自动保存") -> dict[str, Any]:
        graph = self.get_graph(graph_id)
        definition = self._graph_definition(graph)
        settings_json = self._canonical_json(graph.get("settings") or {})
        definition_json = self._canonical_json(definition)
        latest = self.database.fetch_one(
            "SELECT * FROM task_graph_versions WHERE graph_id=? ORDER BY version_no DESC LIMIT 1",
            (graph_id,),
        )
        if (
            latest
            and latest["name"] == graph["name"]
            and latest["description"] == graph["description"]
            and latest["settings_json"] == settings_json
            and latest["definition_json"] == definition_json
        ):
            return self.get_graph_version(graph_id, int(latest["version_no"]))
        version_no = int(latest["version_no"]) + 1 if latest else 1
        version_id = new_id()
        self.database.execute(
            "INSERT INTO task_graph_versions(id,graph_id,version_no,label,name,description,"
            "settings_json,definition_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                version_id,
                graph_id,
                version_no,
                label[:180],
                graph["name"],
                graph["description"],
                settings_json,
                definition_json,
                utc_now(),
            ),
        )
        self.database.insert_audit(
            "task_graph.version_created",
            "task_graph",
            graph_id,
            {"version_no": version_no, "label": label[:180]},
        )
        return self.get_graph_version(graph_id, version_no)

    @staticmethod
    def _graph_version_summary(row: dict[str, Any]) -> dict[str, Any]:
        value = dict(row)
        value["settings"] = _json(value.pop("settings_json", "{}"), {})
        value["definition"] = _json(value.pop("definition_json", "{}"), {})
        return value

    def get_graph_version(self, graph_id: str, version_no: int) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM task_graph_versions WHERE graph_id=? AND version_no=?",
            (graph_id, version_no),
        )
        if not row:
            raise KeyError("task_graph_version_not_found")
        return self._graph_version_summary(row)

    def list_graph_versions(self, graph_id: str) -> list[dict[str, Any]]:
        self.get_graph(graph_id)
        rows = self.database.fetch_all(
            "SELECT * FROM task_graph_versions WHERE graph_id=? ORDER BY version_no DESC",
            (graph_id,),
        )
        return [self._graph_version_summary(row) for row in rows]

    def restore_graph_version(self, graph_id: str, version_no: int) -> dict[str, Any]:
        graph = self.get_graph(graph_id)
        if graph["status"] in {"running", "waiting_approval", "testing", "cancelling"}:
            raise ValueError("active_flow_locked")
        version = self.get_graph_version(graph_id, version_no)
        definition = version["definition"]
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM task_edges WHERE graph_id=?", (graph_id,))
            connection.execute("DELETE FROM task_nodes WHERE graph_id=?", (graph_id,))
            self._insert_graph_definition(
                connection,
                graph_id,
                definition.get("nodes") or [],
                definition.get("edges") or [],
                now,
            )
            connection.execute(
                "UPDATE task_graphs SET name=?,description=?,settings_json=?,status='draft',"
                "updated_at=?,completed_at=NULL WHERE id=?",
                (
                    version["name"],
                    version["description"],
                    self._canonical_json(version["settings"]),
                    now,
                    graph_id,
                ),
            )
        restored = self.create_graph_version(graph_id, f"恢复自 V{version_no}")
        self.database.insert_audit(
            "task_graph.version_restored",
            "task_graph",
            graph_id,
            {"source_version": version_no, "new_version": restored["version_no"]},
        )
        return self.get_graph(graph_id)

    def validate_graph_definition(
        self,
        *,
        project_id: str | None,
        settings: dict[str, Any],
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        def issue(collection: list[dict[str, Any]], code: str, message: str, node_id: str | None = None) -> None:
            item: dict[str, Any] = {"code": code, "message": message}
            if node_id:
                item["node_id"] = node_id
            collection.append(item)

        if not nodes:
            issue(errors, "flow_requires_node", "工作流至少需要一个节点")
            return {
                "valid": False,
                "errors": errors,
                "warnings": warnings,
                "roots": [],
                "topological_order": [],
                "levels": [],
                "node_count": 0,
                "edge_count": len(edges),
            }

        allowed_types = {"agent", "approval", "condition", "tool"}
        aliases: list[str] = []
        node_map: dict[str, dict[str, Any]] = {}
        for index, node in enumerate(nodes):
            alias = str(node.get("id") or f"node-{index + 1}")
            if alias in node_map:
                issue(errors, "duplicate_graph_node_id", f"节点标识重复：{alias}", alias)
                continue
            aliases.append(alias)
            node_map[alias] = node
            node_type = str(node.get("type") or node.get("node_type") or "agent")
            name = str(node.get("name") or "").strip()
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            if node_type not in allowed_types:
                issue(errors, "invalid_graph_node_type", f"节点类型无效：{node_type}", alias)
            if not name:
                issue(errors, "flow_node_name_required", "节点名称不能为空", alias)
            error_strategy = str(config.get("error_strategy") or "fail_flow")
            if error_strategy not in {"fail_flow", "continue", "skip_branch"}:
                issue(errors, "invalid_node_error_strategy", "节点失败策略无效", alias)
            try:
                retry_count = int(config.get("retry_count", settings.get("max_retries", 1)))
            except (TypeError, ValueError):
                retry_count = -1
            if retry_count < 0 or retry_count > 3:
                issue(errors, "invalid_node_retry_count", "节点重试次数必须在 0 到 3 之间", alias)
            bindings = config.get("input_bindings") or []
            if not isinstance(bindings, list):
                issue(errors, "invalid_flow_input_bindings", "节点输入绑定必须是列表", alias)
            else:
                for binding in bindings:
                    if not isinstance(binding, dict):
                        issue(errors, "invalid_flow_input_binding", "节点包含无效的输入绑定", alias)
                        continue
                    if not str(binding.get("source_node_id") or ""):
                        issue(errors, "flow_binding_source_required", "输入绑定必须选择来源节点", alias)
                    if not str(binding.get("target") or "").strip():
                        issue(errors, "flow_binding_target_required", "输入绑定必须填写目标字段", alias)
            if node_type == "agent" and not str(config.get("prompt") or "").strip():
                issue(warnings, "agent_prompt_empty", "Agent 节点尚未填写任务提示词", alias)
            elif node_type == "approval" and not str(config.get("description") or "").strip():
                issue(warnings, "approval_description_empty", "审批节点没有说明需要检查的内容", alias)
            elif node_type == "condition" and not str(config.get("value") or "").strip():
                issue(warnings, "condition_value_empty", "条件节点的比较值为空", alias)
            elif node_type == "tool":
                server_id = str(config.get("server_id") or "")
                tool_name = str(config.get("tool_name") or "")
                if not server_id:
                    issue(errors, "tool_server_required", "MCP 工具节点必须选择 Server", alias)
                if not tool_name:
                    issue(errors, "tool_name_required", "MCP 工具节点必须选择工具", alias)
                if server_id:
                    try:
                        server = self.get_mcp_server(server_id)
                        if not server["enabled"]:
                            issue(errors, "tool_server_disabled", f"MCP Server“{server['name']}”已禁用", alias)
                        elif server["health_status"] == "offline":
                            issue(warnings, "tool_server_offline", f"MCP Server“{server['name']}”当前离线", alias)
                        if tool_name and server.get("tools") and tool_name not in {
                            str(tool.get("name") or "") for tool in server["tools"]
                        }:
                            issue(warnings, "tool_not_discovered", f"尚未在 Server 中发现工具“{tool_name}”", alias)
                    except KeyError:
                        issue(errors, "tool_server_missing", "所选 MCP Server 已不存在", alias)

        incoming: dict[str, list[str]] = {alias: [] for alias in aliases}
        outgoing: dict[str, list[str]] = {alias: [] for alias in aliases}
        seen_edges: set[tuple[str, str]] = set()
        for edge in edges:
            source = str(edge.get("source") or edge.get("source_node_id") or "")
            target = str(edge.get("target") or edge.get("target_node_id") or "")
            if source not in node_map or target not in node_map or source == target:
                issue(errors, "invalid_graph_edge", "连线包含不存在的节点或指向节点自身")
                continue
            if (source, target) in seen_edges:
                issue(errors, "duplicate_graph_edge", f"存在重复连线：{source} → {target}")
                continue
            seen_edges.add((source, target))
            incoming[target].append(source)
            outgoing[source].append(target)

        for alias, node in node_map.items():
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            bindings = config.get("input_bindings") or []
            if not isinstance(bindings, list):
                continue
            for binding in bindings:
                if not isinstance(binding, dict):
                    continue
                source = str(binding.get("source_node_id") or "")
                if source and source not in node_map:
                    issue(errors, "flow_binding_source_missing", "输入绑定引用的来源节点不存在", alias)
                elif source and source not in incoming.get(alias, []):
                    issue(
                        errors,
                        "flow_binding_source_not_upstream",
                        "输入绑定来源必须通过连线直接连接到当前节点",
                        alias,
                    )

        indegree = {alias: len(incoming[alias]) for alias in aliases}
        queue = [alias for alias in aliases if indegree[alias] == 0]
        roots = list(queue)
        topological: list[str] = []
        levels: list[list[str]] = []
        current = list(queue)
        while current:
            levels.append(current)
            following: list[str] = []
            for alias in current:
                topological.append(alias)
                for target in outgoing[alias]:
                    indegree[target] -= 1
                    if indegree[target] == 0:
                        following.append(target)
            current = following
        if len(topological) != len(aliases):
            issue(errors, "graph_cycle_not_allowed", "工作流存在循环依赖")
        if len(roots) > 1:
            issue(warnings, "multiple_flow_roots", f"工作流包含 {len(roots)} 个并行起点")
        if len(nodes) > 1:
            for alias in aliases:
                if not incoming[alias] and not outgoing[alias]:
                    issue(warnings, "isolated_flow_node", "节点未与工作流其他部分连接", alias)
                node_type = str(node_map[alias].get("type") or node_map[alias].get("node_type") or "agent")
                if node_type == "condition" and not outgoing[alias]:
                    issue(warnings, "condition_has_no_branch", "条件节点没有下游分支", alias)

        if any(str(node.get("type") or node.get("node_type") or "agent") in {"agent", "approval"} for node in nodes):
            if not project_id:
                issue(errors, "flow_project_required", "包含 Agent 或审批节点的工作流必须绑定项目")
            else:
                try:
                    project = self.get_project(project_id)
                    if not project.get("default_runner_id"):
                        issue(errors, "flow_runner_required", "项目没有默认 Agent")
                    if not project.get("default_model_id"):
                        issue(errors, "flow_model_required", "项目没有默认模型")
                except KeyError:
                    issue(errors, "project_not_found", "工作流绑定的项目已不存在")

        max_concurrency = int(settings.get("max_concurrency", 4) or 0)
        if max_concurrency < 1 or max_concurrency > 8:
            issue(errors, "invalid_flow_concurrency", "并发 Agent 必须在 1 到 8 之间")
        if int(settings.get("max_retries", 1) or 0) < 0:
            issue(errors, "invalid_flow_retries", "失败重试次数不能为负数")

        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "roots": roots,
            "topological_order": topological,
            "levels": levels,
            "node_count": len(nodes),
            "edge_count": len(seen_edges),
        }

    def validate_graph(self, graph_id: str) -> dict[str, Any]:
        graph = self.get_graph(graph_id)
        definition = self._graph_definition(graph)
        return self.validate_graph_definition(
            project_id=graph.get("project_id"),
            settings=graph.get("settings") or {},
            nodes=definition["nodes"],
            edges=definition["edges"],
        )

    @staticmethod
    def _graph_run_summary(row: dict[str, Any]) -> dict[str, Any]:
        value = dict(row)
        value["dry_run"] = bool(value.get("dry_run"))
        value["result"] = _json(value.pop("result_json", "{}"), {})
        value["usage"] = _json(value.pop("usage_json", "{}"), {})
        return value

    def create_graph_run(
        self,
        graph_id: str,
        *,
        status: str = "running",
        dry_run: bool = False,
        retry_node_id: str | None = None,
        result: dict[str, Any] | None = None,
        error_message: str = "",
    ) -> dict[str, Any]:
        self.get_graph(graph_id)
        version = self.database.fetch_one(
            "SELECT version_no FROM task_graph_versions WHERE graph_id=? ORDER BY version_no DESC LIMIT 1",
            (graph_id,),
        )
        run_id = new_id()
        now = utc_now()
        completed_at = now if status in {"completed", "failed", "cancelled"} else None
        self.database.execute(
            "INSERT INTO task_graph_runs(id,graph_id,version_no,status,dry_run,retry_node_id,"
            "error_message,result_json,usage_json,started_at,completed_at,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                graph_id,
                version.get("version_no") if version else None,
                status,
                int(dry_run),
                retry_node_id,
                error_message,
                json.dumps(result or {}, ensure_ascii=False),
                "{}",
                now,
                completed_at,
                now,
            ),
        )
        return self.get_graph_run(graph_id, run_id)

    def get_graph_run(self, graph_id: str, run_id: str) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM task_graph_runs WHERE graph_id=? AND id=?",
            (graph_id, run_id),
        )
        if not row:
            raise KeyError("task_graph_run_not_found")
        return self._graph_run_summary(row)

    def list_graph_runs(self, graph_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.get_graph(graph_id)
        rows = self.database.fetch_all(
            "SELECT * FROM task_graph_runs WHERE graph_id=? ORDER BY created_at DESC LIMIT ?",
            (graph_id, max(1, min(limit, 200))),
        )
        return [self._graph_run_summary(row) for row in rows]

    def finish_graph_run(
        self,
        graph_id: str,
        run_id: str,
        *,
        status: str,
        error_message: str,
        result: dict[str, Any],
        usage: dict[str, Any],
    ) -> dict[str, Any]:
        self.get_graph_run(graph_id, run_id)
        self.database.execute(
            "UPDATE task_graph_runs SET status=?,error_message=?,result_json=?,usage_json=?,"
            "completed_at=? WHERE id=? AND graph_id=?",
            (
                status,
                error_message,
                json.dumps(result, ensure_ascii=False),
                json.dumps(usage, ensure_ascii=False),
                utc_now(),
                run_id,
                graph_id,
            ),
        )
        return self.get_graph_run(graph_id, run_id)

    def dry_run_graph(self, graph_id: str) -> dict[str, Any]:
        graph = self.get_graph(graph_id)
        validation = self.validate_graph(graph_id)
        node_map = {node["id"]: node for node in graph["nodes"]}
        steps = [
            {
                "wave": wave + 1,
                "nodes": [
                    {
                        "id": node_id,
                        "name": node_map[node_id]["name"],
                        "type": node_map[node_id]["node_type"],
                    }
                    for node_id in node_ids
                    if node_id in node_map
                ],
            }
            for wave, node_ids in enumerate(validation["levels"])
        ]
        result = {"validation": validation, "steps": steps}
        return self.create_graph_run(
            graph_id,
            status="completed" if validation["valid"] else "failed",
            dry_run=True,
            result=result,
            error_message="" if validation["valid"] else "工作流静态验证未通过",
        )

    @staticmethod
    def _insert_graph_definition(connection, graph_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], now: str) -> None:
        if not nodes:
            raise ValueError("flow_requires_node")
        allowed_types = {"agent", "approval", "condition", "tool"}
        node_ids: dict[str, str] = {}
        normalized_edges: list[tuple[str, str, dict[str, Any]]] = []
        normalized_nodes: list[tuple[str, str, str, dict[str, Any]]] = []
        for index, node in enumerate(nodes):
            alias = str(node.get("id") or f"node-{index + 1}")
            if alias in node_ids:
                raise ValueError("duplicate_graph_node_id")
            node_type = str(node.get("type") or node.get("node_type") or "agent")
            if node_type not in allowed_types:
                raise ValueError("invalid_graph_node_type")
            node_id = new_id()
            node_ids[alias] = node_id
            normalized_nodes.append((alias, node_id, node_type, node))
        for alias, node_id, node_type, node in normalized_nodes:
            config = json.loads(json.dumps(node.get("config") or {}, ensure_ascii=False))
            bindings = config.get("input_bindings") or []
            if not isinstance(bindings, list):
                raise ValueError("invalid_flow_input_bindings")
            for binding in bindings:
                if not isinstance(binding, dict):
                    raise ValueError("invalid_flow_input_binding")
                source_alias = str(binding.get("source_node_id") or "")
                if not source_alias or source_alias not in node_ids:
                    raise ValueError("flow_binding_source_missing")
                binding["source_node_id"] = node_ids[source_alias]
            connection.execute(
                "INSERT INTO task_nodes(id,graph_id,node_type,name,position_x,position_y,"
                "config_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'pending',?,?)",
                (
                    node_id,
                    graph_id,
                    node_type,
                    str(node.get("name") or alias)[:180],
                    float(node.get("x", node.get("position_x", 0)) or 0),
                    float(node.get("y", node.get("position_y", 0)) or 0),
                    json.dumps(config, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        seen_edges: set[tuple[str, str]] = set()
        adjacency: dict[str, list[str]] = {alias: [] for alias in node_ids}
        for edge in edges:
            source_alias = str(edge.get("source") or edge.get("source_node_id") or "")
            target_alias = str(edge.get("target") or edge.get("target_node_id") or "")
            source = node_ids.get(source_alias)
            target = node_ids.get(target_alias)
            if not source or not target or source == target:
                raise ValueError("invalid_graph_edge")
            pair = (source_alias, target_alias)
            if pair in seen_edges:
                raise ValueError("duplicate_graph_edge")
            seen_edges.add(pair)
            adjacency[source_alias].append(target_alias)
            normalized_edges.append((source, target, edge.get("condition") or {}))
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(alias: str) -> None:
            if alias in visiting:
                raise ValueError("graph_cycle_not_allowed")
            if alias in visited:
                return
            visiting.add(alias)
            for target_alias in adjacency[alias]:
                visit(target_alias)
            visiting.remove(alias)
            visited.add(alias)

        for alias in node_ids:
            visit(alias)
        for source, target, condition in normalized_edges:
            connection.execute(
                "INSERT INTO task_edges(id,graph_id,source_node_id,target_node_id,"
                "condition_json,created_at) VALUES (?,?,?,?,?,?)",
                (new_id(), graph_id, source, target, json.dumps(condition, ensure_ascii=False), now),
            )

    def update_graph(self, graph_id: str, value) -> dict[str, Any]:
        graph = self.get_graph(graph_id)
        if graph["status"] in {"running", "waiting_approval", "testing", "cancelling"}:
            raise ValueError("active_flow_locked")
        changes = value.model_dump(exclude_unset=True)
        if "project_id" in changes and changes["project_id"]:
            self.get_project(str(changes["project_id"]))
        definition_changed = "nodes" in changes or "edges" in changes
        if definition_changed and not ({"nodes", "edges"} <= changes.keys()):
            raise ValueError("flow_nodes_and_edges_required")
        now = utc_now()
        with self.database.transaction() as connection:
            values: dict[str, Any] = {}
            if "project_id" in changes:
                values["project_id"] = changes["project_id"]
            if "name" in changes:
                values["name"] = str(changes["name"]).strip()
            if "description" in changes:
                values["description"] = str(changes["description"] or "").strip()
            if "settings" in changes:
                values["settings_json"] = json.dumps(changes["settings"] or {}, ensure_ascii=False)
            if definition_changed:
                connection.execute("DELETE FROM task_edges WHERE graph_id=?", (graph_id,))
                connection.execute("DELETE FROM task_nodes WHERE graph_id=?", (graph_id,))
                self._insert_graph_definition(
                    connection, graph_id, changes["nodes"], changes["edges"], now
                )
            if values or definition_changed:
                values.update({"status": "draft", "updated_at": now, "completed_at": None})
                assignments = ",".join(f"{key}=?" for key in values)
                connection.execute(
                    f"UPDATE task_graphs SET {assignments} WHERE id=?",
                    (*values.values(), graph_id),
                )
        self.database.insert_audit("task_graph.updated", "task_graph", graph_id)
        self.create_graph_version(graph_id)
        return self.get_graph(graph_id)

    def delete_graph(self, graph_id: str) -> None:
        graph = self.get_graph(graph_id)
        if graph["status"] in {"running", "waiting_approval", "testing", "cancelling"}:
            raise ValueError("active_flow_locked")
        self.database.execute("DELETE FROM task_graphs WHERE id=?", (graph_id,))
        self.database.insert_audit("task_graph.deleted", "task_graph", graph_id)

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

    def update_mcp_server(self, server_id: str, value) -> dict[str, Any]:
        current = self.get_mcp_server_internal(server_id)
        if current.get("builtin"):
            raise ValueError("builtin_mcp_server_locked")
        changes = value.model_dump(exclude_unset=True)
        remove_keys = set(changes.pop("remove_env_keys", []))
        environment = dict(current.get("env_refs") or {})
        for key in remove_keys:
            reference = environment.pop(key, None)
            if reference:
                self.secrets.delete(str(reference))
        for key, secret in (changes.pop("env", None) or {}).items():
            if not key or not key.replace("_", "").isalnum():
                raise ValueError("invalid_mcp_env_key")
            reference = environment.get(key) or f"mcp-{server_id}-{key}"
            self.secrets.set(reference, secret)
            environment[key] = reference
        transport = str(changes.get("transport") or current["transport"])
        command = changes.get("command", current.get("command"))
        url = str(changes["url"]) if changes.get("url") else changes.get("url", current.get("url"))
        if transport == "stdio" and not command:
            raise ValueError("mcp_stdio_command_required")
        if transport != "stdio" and not url:
            raise ValueError("mcp_url_required")
        values: dict[str, Any] = {
            "name": str(changes.get("name") or current["name"]).strip(),
            "transport": transport,
            "command": command if transport == "stdio" else None,
            "args_json": json.dumps(changes.get("args", current.get("args") or []), ensure_ascii=False),
            "url": url if transport != "stdio" else None,
            "env_json": json.dumps(environment, ensure_ascii=False),
            "enabled": int(bool(changes.get("enabled", current["enabled"]))),
            "health_status": "unknown",
            "tools_json": "[]",
            "last_error": None,
            "last_checked_at": None,
            "updated_at": utc_now(),
        }
        assignments = ",".join(f"{key}=?" for key in values)
        self.database.execute(
            f"UPDATE mcp_servers SET {assignments} WHERE id=?", (*values.values(), server_id)
        )
        self.database.insert_audit("mcp_server.updated", "mcp_server", server_id)
        return self.get_mcp_server(server_id)

    def delete_mcp_server(self, server_id: str) -> None:
        current = self.get_mcp_server_internal(server_id)
        if current.get("builtin"):
            raise ValueError("builtin_mcp_server_locked")
        for reference in (current.get("env_refs") or {}).values():
            self.secrets.delete(str(reference))
        self.database.execute("DELETE FROM mcp_servers WHERE id=?", (server_id,))
        self.database.insert_audit("mcp_server.deleted", "mcp_server", server_id)

    def _public_skill_pack(self, row: dict[str, Any]) -> dict[str, Any]:
        output = dict(row)
        output["tools"] = _json(output.pop("tools_json"), [])
        output["builtin"] = bool(output["builtin"])
        return output

    def list_skill_packs(self) -> list[dict[str, Any]]:
        return [
            self._public_skill_pack(row)
            for row in self.database.fetch_all(
                "SELECT * FROM prompt_templates ORDER BY builtin DESC,name"
            )
        ]

    def get_skill_pack(self, pack_id: str) -> dict[str, Any]:
        row = self.database.fetch_one("SELECT * FROM prompt_templates WHERE id=?", (pack_id,))
        if not row:
            raise KeyError("skill_pack_not_found")
        return self._public_skill_pack(row)

    def create_skill_pack(self, value: SkillPackCreate) -> dict[str, Any]:
        pack_id = new_id()
        now = utc_now()
        self.database.execute(
            "INSERT INTO prompt_templates(id,name,description,content,tools_json,"
            "permission_profile,builtin,created_at,updated_at) VALUES (?,?,?,?,?,?,0,?,?)",
            (
                pack_id,
                value.name.strip(),
                value.description.strip(),
                value.content.strip(),
                json.dumps(value.tools, ensure_ascii=False),
                value.permission_profile,
                now,
                now,
            ),
        )
        self.database.insert_audit("skill_pack.created", "skill_pack", pack_id)
        return self.get_skill_pack(pack_id)

    def update_skill_pack(self, pack_id: str, value) -> dict[str, Any]:
        current = self.get_skill_pack(pack_id)
        if current["builtin"]:
            raise ValueError("builtin_skill_pack_locked")
        changes = value.model_dump(exclude_unset=True)
        values: dict[str, Any] = {}
        for key in ("name", "description", "content", "permission_profile"):
            if key in changes:
                values[key] = changes[key].strip() if isinstance(changes[key], str) else changes[key]
        if "tools" in changes:
            values["tools_json"] = json.dumps(changes["tools"] or [], ensure_ascii=False)
        if values:
            values["updated_at"] = utc_now()
            assignments = ",".join(f"{key}=?" for key in values)
            self.database.execute(
                f"UPDATE prompt_templates SET {assignments} WHERE id=?",
                (*values.values(), pack_id),
            )
        self.database.insert_audit("skill_pack.updated", "skill_pack", pack_id)
        return self.get_skill_pack(pack_id)

    def delete_skill_pack(self, pack_id: str) -> None:
        current = self.get_skill_pack(pack_id)
        if current["builtin"]:
            raise ValueError("builtin_skill_pack_locked")
        self.database.execute("UPDATE agent_sessions SET skill_pack_id=NULL WHERE skill_pack_id=?", (pack_id,))
        self.database.execute("DELETE FROM prompt_templates WHERE id=?", (pack_id,))
        self.database.insert_audit("skill_pack.deleted", "skill_pack", pack_id)

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

    def unified_activity(self, limit: int = 30) -> list[dict[str, Any]]:
        """Return one presentation-safe activity stream across sessions, tasks and Flows."""
        per_source = max(8, min(limit, 100))
        activity: list[dict[str, Any]] = []
        session_rows = self.database.fetch_all(
            "SELECT e.id,e.session_id,e.event_type,e.payload_json,e.created_at,"
            "s.title source_title,p.id project_id,p.name project_name "
            "FROM session_events e JOIN agent_sessions s ON s.id=e.session_id "
            "JOIN projects p ON p.id=s.project_id "
            "WHERE e.visibility IN ('user','recording_safe') "
            "AND e.event_type NOT IN ('live.heartbeat','usage.updated','model.requested') "
            "ORDER BY e.created_at DESC,e.id DESC LIMIT ?",
            (per_source,),
        )
        session_labels = {
            "session.created": "会话已创建",
            "turn.started": "Agent 开始执行",
            "assistant.message": "Agent 已交付回复",
            "turn.completed": "Agent 本轮完成",
            "turn.failed": "Agent 本轮失败",
            "turn.cancelled": "Agent 本轮已取消",
            "approval.requested": "Agent 正在等待审批",
            "approval.resolved": "审批已处理",
            "file.changed": "项目文件发生变更",
        }
        for row in session_rows:
            event_type = str(row["event_type"])
            payload = _json(row.pop("payload_json"), {})
            activity.append(
                {
                    "id": f"session:{row['id']}",
                    "source_type": "session",
                    "source_id": row["session_id"],
                    "source_title": row["source_title"],
                    "project_id": row["project_id"],
                    "project_name": row["project_name"],
                    "event_type": event_type,
                    "summary": session_labels.get(event_type, event_type.replace(".", " · ")),
                    "status": (
                        "failed"
                        if "failed" in event_type
                        else "attention"
                        if "approval" in event_type
                        else "completed"
                        if event_type.endswith("completed") or event_type == "assistant.message"
                        else "running"
                        if event_type.endswith("started")
                        else "info"
                    ),
                    "payload": payload,
                    "href": f"/studio/{row['session_id']}",
                    "created_at": row["created_at"],
                }
            )

        task_rows = self.database.fetch_all(
            "SELECT e.id,e.task_id,e.event_type,e.payload_json,e.created_at,"
            "t.title source_title,t.project_id,p.name project_name "
            "FROM task_events e JOIN task_items t ON t.id=e.task_id "
            "LEFT JOIN projects p ON p.id=t.project_id "
            "ORDER BY e.created_at DESC,e.id DESC LIMIT ?",
            (per_source,),
        )
        task_labels = {
            "task.created": "任务已创建",
            "task.queued": "任务已进入队列",
            "task.running": "任务开始执行",
            "task.approval": "任务等待验收",
            "task.completed": "任务已完成",
            "task.failed": "任务执行失败",
            "task.cancelled": "任务已取消",
            "task.updated": "任务已更新",
        }
        for row in task_rows:
            event_type = str(row["event_type"])
            activity.append(
                {
                    "id": f"task:{row['id']}",
                    "source_type": "task",
                    "source_id": row["task_id"],
                    "source_title": row["source_title"],
                    "project_id": row["project_id"],
                    "project_name": row["project_name"],
                    "event_type": event_type,
                    "summary": task_labels.get(event_type, event_type.replace(".", " · ")),
                    "status": (
                        "failed"
                        if "failed" in event_type
                        else "attention"
                        if "approval" in event_type
                        else "completed"
                        if event_type.endswith("completed")
                        else "running"
                        if event_type.endswith(("queued", "running"))
                        else "info"
                    ),
                    "payload": _json(row.pop("payload_json"), {}),
                    "href": f"/tasks/{row['task_id']}",
                    "created_at": row["created_at"],
                }
            )

        flow_rows = self.database.fetch_all(
            "SELECT r.id,r.graph_id,r.status,r.dry_run,r.created_at,g.name source_title,"
            "g.project_id,p.name project_name FROM task_graph_runs r "
            "JOIN task_graphs g ON g.id=r.graph_id LEFT JOIN projects p ON p.id=g.project_id "
            "ORDER BY r.created_at DESC LIMIT ?",
            (per_source,),
        )
        for row in flow_rows:
            status = str(row["status"])
            activity.append(
                {
                    "id": f"flow:{row['id']}",
                    "source_type": "flow",
                    "source_id": row["graph_id"],
                    "source_title": row["source_title"],
                    "project_id": row["project_id"],
                    "project_name": row["project_name"],
                    "event_type": f"flow.{status}",
                    "summary": (
                        "Flow 静态试运行完成"
                        if row["dry_run"] and status == "completed"
                        else f"Flow {status}"
                    ),
                    "status": (
                        "failed"
                        if status in {"failed", "cancelled"}
                        else "completed"
                        if status == "completed"
                        else "running"
                    ),
                    "payload": {"run_id": row["id"], "dry_run": bool(row["dry_run"])},
                    "href": f"/flows?flow={row['graph_id']}",
                    "created_at": row["created_at"],
                }
            )
        return sorted(activity, key=lambda item: item["created_at"], reverse=True)[:limit]

    def dashboard(self) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT "
            "(SELECT COUNT(*) FROM projects WHERE archived=0 AND id<>?) project_count,"
            "(SELECT COUNT(*) FROM agent_sessions WHERE archived=0) session_count,"
            "(SELECT COUNT(*) FROM agent_sessions WHERE status IN "
            "('queued','preparing','running','waiting_approval')) active_sessions,"
            "(SELECT COUNT(*) FROM approval_requests WHERE status='pending') pending_approvals,"
            "(SELECT COUNT(*) FROM task_items WHERE status='completed') completed_tasks,"
            "(SELECT COUNT(*) FROM task_items WHERE status IN ('backlog','queued','running','approval')) "
            "open_tasks,"
            "(SELECT COALESCE(SUM(tokens_input+tokens_output),0) FROM agent_sessions) total_tokens,"
            "(SELECT COALESCE(SUM(cost_usd),0) FROM agent_sessions) total_cost"
            ,(CHAT_PROJECT_ID,)
        ) or {}
        active_rows = self._session_query(
            "WHERE s.archived=0 AND s.status IN "
            "('queued','preparing','running','waiting_approval')",
            (),
        )[:5]
        recent_failures = self.database.fetch_all(
            "SELECT s.id,s.title,s.status,s.updated_at,p.name project_name,"
            "r.name runner_name,m.name model_name,"
            "(SELECT st.error_message FROM session_turns st WHERE st.session_id=s.id "
            "AND st.error_message IS NOT NULL AND st.error_message<>'' "
            "ORDER BY st.turn_no DESC LIMIT 1) error_message "
            "FROM agent_sessions s JOIN projects p ON p.id=s.project_id "
            "LEFT JOIN agent_runners r ON r.id=s.runner_id "
            "LEFT JOIN models m ON m.id=s.model_id "
            "WHERE s.archived=0 AND s.status IN ('failed','interrupted') "
            "ORDER BY s.updated_at DESC LIMIT 4"
        )
        runtime_health = self.database.fetch_one(
            "SELECT "
            "(SELECT COUNT(*) FROM models WHERE enabled=1) models_enabled,"
            "(SELECT COUNT(*) FROM agent_runners WHERE enabled=1) runners_enabled,"
            "(SELECT COUNT(*) FROM mcp_servers WHERE enabled=1) mcp_enabled,"
            "(SELECT COUNT(*) FROM mcp_servers WHERE enabled=1 AND health_status='online') "
            "mcp_healthy,"
            "(SELECT COUNT(*) FROM mcp_servers WHERE enabled=1 AND health_status='offline') "
            "mcp_error"
        ) or {}
        active_tasks = self.database.fetch_all(
            "SELECT t.id,t.title,t.status,t.priority,t.session_id,t.updated_at,"
            "p.id project_id,p.name project_name FROM task_items t "
            "LEFT JOIN projects p ON p.id=t.project_id WHERE t.archived=0 "
            "AND t.status IN ('queued','running','approval') "
            "ORDER BY t.updated_at DESC LIMIT 6"
        )
        active_flows = self.database.fetch_all(
            "SELECT g.id,g.name,g.status,g.updated_at,g.project_id,p.name project_name,"
            "(SELECT COUNT(*) FROM task_nodes n WHERE n.graph_id=g.id) node_count,"
            "(SELECT COUNT(*) FROM task_nodes n WHERE n.graph_id=g.id AND n.status='completed') "
            "completed_nodes FROM task_graphs g LEFT JOIN projects p ON p.id=g.project_id "
            "WHERE g.status='running' ORDER BY g.updated_at DESC LIMIT 6"
        )
        return {
            **row,
            "active_sessions_list": [self._session_summary(item) for item in active_rows],
            "pending_approvals_list": self.list_approvals(status="pending")[:5],
            "recent_projects": self.list_projects()[:6],
            "recent_failures": recent_failures,
            "runtime_health": runtime_health,
            "active_tasks_list": active_tasks,
            "active_flows_list": active_flows,
            "activity": self.unified_activity(30),
        }
