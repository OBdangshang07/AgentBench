from __future__ import annotations

import base64
import copy
import json
import logging
import os
import re
import shutil
import statistics
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Any

from . import __version__
from .agent import AgentHarness, AgentResult
from .catalog import seed_builtin_data
from .config import Settings
from .db import Database, new_id, utc_now
from .execution import (
    SAFE_ENV_KEYS,
    DockerExecutor,
    Workspace,
    native_cli_status,
    resolve_cli_install_plan,
    run_native_cli,
)
from .math_exam import (
    MATH_EXAM_ID,
    build_published_math_cases,
    get_math_import,
    import_math_pdf,
    list_math_imports,
    mark_math_import_published,
    update_math_question,
)
from .model_clients import (
    AnthropicClient,
    MockModelClient,
    ModelClient,
    ModelClientError,
    OpenAICompatibleClient,
)
from .model_discovery import discover_models
from .reports import create_backup, export_experiment, restore_backup
from .schemas import (
    ExperimentCreate,
    ModelCreate,
    ModelDiscoveryRequest,
    ModelUpdate,
    RunnerCreate,
    TestCaseImport,
)
from .scoring import ScoringEngine, ValidationResult
from .secrets import SecretStore

logger = logging.getLogger(__name__)


_VIEWER_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(sk|rk|pk|api)[-_][a-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\b(bearer\s+)[a-z0-9._~+/=-]{12,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)\b"
        r"\s*[:=]\s*[^\s,;]+"
    ),
)
_VIEWER_PRIVATE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credential_ref",
    "env",
    "environment",
    "password",
    "private_input",
    "private_validation",
    "secret",
    "system_prompt",
}
_VIEWER_REASONING_KEYS = {
    "chain_of_thought",
    "content",
    "prompt",
    "reasoning",
    "system",
    "thinking",
}


def _redact_viewer_text(value: str, limit: int = 1600) -> str:
    cleaned = value.replace("\x00", "")
    for pattern in _VIEWER_SECRET_PATTERNS:
        cleaned = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]", cleaned)
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def _viewer_safe_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    normalized_key = key.lower()
    if normalized_key in _VIEWER_PRIVATE_KEYS or normalized_key in _VIEWER_REASONING_KEYS:
        return "[REDACTED]"
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return _redact_viewer_text(value)
    if isinstance(value, dict):
        return {
            str(child_key): _viewer_safe_value(child_value, key=str(child_key), depth=depth + 1)
            for child_key, child_value in list(value.items())[:40]
        }
    if isinstance(value, list):
        return [_viewer_safe_value(item, depth=depth + 1) for item in value[:30]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _redact_viewer_text(str(value))


def _viewer_safe_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_type == "model.responded":
        kind = str(payload.get("kind") or "response")
        return {
            "step": payload.get("step"),
            "kind": kind,
            "summary": "模型已提交最终结果" if kind == "final" else "模型已生成下一项可验证操作",
            "usage": _viewer_safe_value(payload.get("usage") or {}),
        }
    if event_type == "tool.requested":
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        safe_arguments = {
            key: _viewer_safe_value(value, key=key)
            for key, value in arguments.items()
            if key.lower() not in {"content", "patch", "replacement", "text"}
        }
        if "content" in arguments:
            safe_arguments["content_bytes"] = len(str(arguments["content"]).encode("utf-8"))
        return {
            "step": payload.get("step"),
            "id": payload.get("id"),
            "name": payload.get("name"),
            "arguments": safe_arguments,
        }
    if event_type == "tool.completed":
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        keep = {
            key: value
            for key, value in result.items()
            if key
            in {
                "bytes",
                "duration_ms",
                "error_code",
                "exit_code",
                "matches",
                "ok",
                "path",
                "status",
            }
        }
        for name in ("stdout", "stderr"):
            if isinstance(result.get(name), str):
                keep[name] = _redact_viewer_text(result[name], 800)
        return {
            "step": payload.get("step"),
            "name": payload.get("name"),
            "result": _viewer_safe_value(keep),
        }
    if event_type == "native_cli.event":
        item = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        kind = str(item.get("type") or (item.get("item") or {}).get("type") or "activity")
        return {
            "runner_type": payload.get("runner_type"),
            "kind": kind,
            "summary": f"Agent 已产生 {kind} 可验证事件",
            "usage": _viewer_safe_value(item.get("usage") or {}),
        }
    if event_type == "validator.completed":
        return {
            key: _viewer_safe_value(value, key=key)
            for key, value in payload.items()
            if key != "evidence"
        }
    if event_type == "judge.completed":
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        return {
            "score": payload.get("score"),
            "anonymous_slot": payload.get("anonymous_slot"),
            "summary": _redact_viewer_text(str(evidence.get("summary") or "匿名裁判已完成"), 500),
        }
    if event_type == "attempt.retry_scheduled":
        return {"next_attempt": payload.get("next_attempt"), "summary": "已根据评分维度生成下一轮公开提示"}
    return _viewer_safe_value(payload)


def _json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def public_model(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output["settings"] = _json(output.pop("settings_json", "{}"), {})
    output["has_secret"] = bool(output.pop("credential_ref", None))
    output["enabled"] = bool(output["enabled"])
    output["builtin"] = bool(output["builtin"])
    return output


def public_runner(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    for source, target, fallback in (
        ("args_json", "args", []),
        ("env_json", "env", {}),
        ("tools_json", "tools", []),
        ("limits_json", "limits", {}),
    ):
        output[target] = _json(output.pop(source, None), fallback)
    output["model_override_supported"] = bool(output["model_override_supported"])
    output["enabled"] = bool(output["enabled"])
    output["builtin"] = bool(output["builtin"])
    return output


def _material_size_bytes(value: str) -> int:
    """Decoded size of an initial_files value (base64 with padding correction, else UTF-8)."""
    if isinstance(value, str) and value.startswith("base64:"):
        encoded = value[len("base64:"):]
        return len(encoded) // 4 * 3 - encoded.count("=")
    return len(str(value).encode("utf-8"))


def public_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Remove reference answers and private validator payloads from API responses."""
    output = copy.deepcopy(definition)
    metadata = output.get("metadata") or {}
    metadata.pop("demo_actions", None)
    metadata.pop("demo_response", None)
    metadata.pop("reference_schedule", None)
    for validator in output.get("validators") or []:
        config = validator.get("config") or {}
        kind = str(validator.get("type") or "")
        hidden = config.pop("private_files", None) is not None
        sensitive_keys = {
            "exact_match": {"expected"},
            "contains": {"text"},
            "regex": {"pattern"},
            "file_content": {"expected"},
            "file_contains": {"text"},
            "json_file": {"expected"},
            "symbolic_json": {"fields"},
            "ai_rubric": {"reference_answer", "accepted_answers", "solution_obligations"},
        }.get(kind, set())
        for key in sensitive_keys:
            hidden = config.pop(key, None) is not None or hidden
        if hidden and kind in {"command", "command_metrics"}:
            config["command"] = "<AgentBench private validator>"
        if hidden:
            config["private"] = True
    return output


class EvaluationService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.database = Database(settings.database_path)
        self.database.initialize()
        seed_builtin_data(self.database)
        self.database.sync_test_case_revisions()
        self.secrets = SecretStore(settings.data_dir)
        self.docker = DockerExecutor()
        self.scoring = ScoringEngine(self.docker)
        self.executor = ThreadPoolExecutor(
            max_workers=settings.max_workers, thread_name_prefix="agentbench-run"
        )
        self.install_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="agentbench-install"
        )
        self._cancel_events: dict[str, threading.Event] = {}
        self._experiment_semaphores: dict[str, threading.Semaphore] = {}
        self._install_jobs: dict[str, dict[str, Any]] = {}
        self._state_lock = threading.RLock()
        self.recover_interrupted_runs()

    def _definition_for_run(self, run: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return the immutable definition revision selected for a run.

        Legacy databases are backfilled during startup.  The current catalog row remains a
        guarded fallback so an interrupted migration is still readable instead of corrupting
        the run or silently dropping its materials.
        """
        revision = None
        revision_id = run.get("test_revision_id")
        if revision_id:
            revision = self.database.fetch_one(
                "SELECT id,version,definition_hash,definition_json FROM test_case_revisions "
                "WHERE id=?",
                (revision_id,),
            )
        if revision:
            return _json(revision["definition_json"], {}), revision
        current = self.database.fetch_one(
            "SELECT id,version,definition_hash,definition_json FROM test_cases WHERE id=?",
            (run["test_case_id"],),
        )
        if not current:
            raise ValueError("test_case_missing")
        return _json(current["definition_json"], {}), current

    def close(self) -> None:
        with self._state_lock:
            for event in self._cancel_events.values():
                event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.install_executor.shutdown(wait=False, cancel_futures=False)

    def recover_interrupted_runs(self) -> None:
        now = utc_now()
        self.database.execute(
            "UPDATE runs SET status='interrupted', error_code='app_restarted', "
            "error_message='The desktop app exited while this run was active', completed_at=? "
            "WHERE status IN ('preparing','running','validating','judging')",
            (now,),
        )
        self.database.execute(
            "UPDATE experiments SET status='interrupted', completed_at=? WHERE status='running'",
            (now,),
        )

    # Models
    def list_models(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else " WHERE enabled=1"
        return [
            public_model(row)
            for row in self.database.fetch_all(
                f"SELECT * FROM models{where} ORDER BY enabled DESC,builtin DESC,name"
            )
        ]

    def get_model(self, model_id: str) -> dict[str, Any]:
        row = self.database.fetch_one("SELECT * FROM models WHERE id=?", (model_id,))
        if not row:
            raise KeyError("model_not_found")
        return row

    def create_model(self, value: ModelCreate) -> dict[str, Any]:
        model_id = new_id()
        credential_ref = f"model-{model_id}" if value.api_key else None
        if value.api_key and credential_ref:
            self.secrets.set(credential_ref, value.api_key)
        now = utc_now()
        base_url = str(value.base_url) if value.base_url else None
        if value.api_style == "openai" and not base_url:
            base_url = "https://api.openai.com/v1"
        if value.api_style == "anthropic" and not base_url:
            base_url = "https://api.anthropic.com"
        model_settings: dict[str, Any] = {
            "temperature": value.temperature,
            "max_tokens": value.max_tokens,
        }
        if value.agent_provider:
            model_settings["agent_provider"] = value.agent_provider
        self.database.execute(
            "INSERT INTO models(id,name,provider,model_name,base_url,api_style,credential_ref,"
            "settings_json,input_price,output_price,enabled,builtin,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,1,0,?,?)",
            (
                model_id,
                value.name,
                value.provider,
                value.model_name,
                base_url,
                value.api_style,
                credential_ref,
                json.dumps(model_settings, ensure_ascii=False),
                value.input_price,
                value.output_price,
                now,
                now,
            ),
        )
        self.database.insert_audit("model.created", "model", model_id)
        return public_model(self.get_model(model_id))

    def discover_models(self, value: ModelDiscoveryRequest) -> dict[str, Any]:
        return discover_models(
            source=value.source,
            provider=value.provider,
            base_url=str(value.base_url) if value.base_url else None,
            api_style=value.api_style,
            api_key=value.api_key,
        )

    def delete_model(self, model_id: str) -> dict[str, Any]:
        row = self.get_model(model_id)
        if row["builtin"]:
            raise ValueError("builtin_model_cannot_be_deleted")
        references = self.database.fetch_one(
            "SELECT COUNT(*) count FROM runs WHERE model_id=?", (model_id,)
        ) or {"count": 0}
        run_references = int(references["count"])
        action = "archived" if run_references else "deleted"
        now = utc_now()
        with self.database.transaction() as connection:
            if run_references:
                connection.execute(
                    "UPDATE models SET enabled=0,updated_at=? WHERE id=?", (now, model_id)
                )
            else:
                connection.execute("DELETE FROM models WHERE id=?", (model_id,))
            for setting_key in (
                "judge_model_id",
                "judge_model_id_secondary",
                "judge_model_id_tiebreaker",
            ):
                judge = connection.execute(
                    "SELECT value_json FROM app_settings WHERE key=?", (setting_key,)
                ).fetchone()
                if judge and _json(judge["value_json"], None) == model_id:
                    connection.execute(
                        "INSERT INTO app_settings(key,value_json,updated_at) VALUES (?,'null',?) "
                        "ON CONFLICT(key) DO UPDATE SET value_json='null',"
                        "updated_at=excluded.updated_at",
                        (setting_key, now),
                    )
        if action == "deleted":
            self.secrets.delete(row.get("credential_ref"))
        self.database.insert_audit(
            f"model.{action}",
            "model",
            model_id,
            {"run_references": run_references},
        )
        return {"ok": True, "action": action, "run_references": run_references}

    def set_model_enabled(self, model_id: str, enabled: bool) -> dict[str, Any]:
        row = self.get_model(model_id)
        if row["builtin"] and not enabled:
            raise ValueError("builtin_model_cannot_be_archived")
        self.database.execute(
            "UPDATE models SET enabled=?,updated_at=? WHERE id=?",
            (int(enabled), utc_now(), model_id),
        )
        self.database.insert_audit(
            "model.restored" if enabled else "model.archived", "model", model_id
        )
        return public_model(self.get_model(model_id))

    def update_model(self, model_id: str, value: ModelUpdate) -> dict[str, Any]:
        row = self.get_model(model_id)
        changes = value.model_dump(exclude_unset=True)
        enabled = changes.pop("enabled", None)
        if enabled is not None:
            if row["builtin"] and not enabled:
                raise ValueError("builtin_model_cannot_be_archived")
            self.database.execute(
                "UPDATE models SET enabled=?,updated_at=? WHERE id=?",
                (int(enabled), utc_now(), model_id),
            )
        api_key = changes.pop("api_key", None)
        if api_key:
            credential_ref = row.get("credential_ref") or f"model-{model_id}"
            self.secrets.set(credential_ref, api_key)
            self.database.execute(
                "UPDATE models SET credential_ref=?,updated_at=? WHERE id=?",
                (credential_ref, utc_now(), model_id),
            )
        direct: dict[str, Any] = {}
        for key in ("name", "input_price", "output_price"):
            if key in changes:
                direct[key] = changes.pop(key)
        if "base_url" in changes:
            direct["base_url"] = str(changes.pop("base_url")) if changes["base_url"] else None
        if direct:
            assignments = ",".join(f"{key}=?" for key in direct)
            self.database.execute(
                f"UPDATE models SET {assignments},updated_at=? WHERE id=?",
                (*direct.values(), utc_now(), model_id),
            )
        settings = _json(row.get("settings_json"), {})
        settings_changed = False
        for key in ("temperature", "max_tokens"):
            if key in changes:
                settings[key] = changes[key]
                settings_changed = True
        if settings_changed:
            self.database.execute(
                "UPDATE models SET settings_json=?,updated_at=? WHERE id=?",
                (json.dumps(settings, ensure_ascii=False), utc_now(), model_id),
            )
        refreshed = self.get_model(model_id)
        self._reprice_model_runs(refreshed)
        self.database.insert_audit(
            "model.updated", "model", model_id, {"fields": sorted(value.model_fields_set)}
        )
        return public_model(refreshed)

    def _reprice_model_runs(self, model: dict[str, Any]) -> None:
        input_price = float(model.get("input_price") or 0)
        output_price = float(model.get("output_price") or 0)
        if input_price > 0 or output_price > 0:
            self.database.execute(
                "UPDATE runs SET cost_usd=(tokens_input*?+tokens_output*?)/1000000.0,"
                "cost_source=CASE WHEN tokens_input+tokens_output>0 THEN 'configured' "
                "ELSE 'unavailable' END WHERE model_id=? AND cost_source!='reported'",
                (input_price, output_price, model["id"]),
            )
        else:
            self.database.execute(
                "UPDATE runs SET cost_usd=0,cost_source=CASE WHEN tokens_input+tokens_output>0 "
                "THEN 'unpriced' ELSE 'unavailable' END WHERE model_id=? AND cost_source!='reported'",
                (model["id"],),
            )

    def test_model(self, model_id: str) -> dict[str, Any]:
        model = self.get_model(model_id)
        cli_runners = {
            "codex-cli": "codex_cli",
            "claude-code": "claude_code_cli",
            "opencode-cli": "opencode_cli",
            "reasonix-cli": "reasonix_cli",
            "gemini-cli": "gemini_cli",
            "aider-cli": "aider_cli",
            "kimi-code": "kimi_code_cli",
            "qoder-cli": "qoder_cli",
        }
        runner_type = cli_runners.get(model["provider"])
        if runner_type:
            started = time.perf_counter()
            runner = self.database.fetch_one(
                "SELECT * FROM agent_runners WHERE runner_type=? AND enabled=1 "
                "ORDER BY builtin DESC LIMIT 1",
                (runner_type,),
            )
            if not runner:
                raise ValueError(f"未找到已启用的 {runner_type} Runner")
            errors, _ = self._check_runner(runner)
            if not self._native_cli_allowed():
                errors.insert(0, "请先在本地设置中启用“允许原生 CLI Runner”")
            if errors:
                raise ValueError("；".join(errors))
            workspace_path = (self.settings.workspaces_dir / f"model-test-{new_id()}").resolve()
            if not workspace_path.is_relative_to(self.settings.workspaces_dir.resolve()):
                raise RuntimeError("Invalid model test workspace")
            workspace = Workspace(workspace_path)
            smoke_runner = dict(runner)
            smoke_runner["limits_json"] = json.dumps({"timeout_seconds": 90})
            if runner_type == "claude_code_cli":
                smoke_args = _json(smoke_runner.get("args_json"), [])
                if "--effort" in smoke_args:
                    effort_index = smoke_args.index("--effort")
                    if effort_index + 1 < len(smoke_args):
                        smoke_args[effort_index + 1] = "low"
                smoke_runner["args_json"] = json.dumps(smoke_args, ensure_ascii=False)
            try:
                result = self._run_native_agent(
                    smoke_runner,
                    model,
                    {
                        "instruction": "Return exactly AGENTBENCH-OK and nothing else.",
                        "tools": [],
                        "limits": {"timeout_seconds": 90},
                        "metadata": {"connection_test": True},
                    },
                    workspace,
                    lambda *_args: None,
                    threading.Event(),
                )
                if not result.ok:
                    raise ValueError(result.error_message or result.error_code or "CLI 冒烟测试失败")
                if "AGENTBENCH-OK" not in result.final_answer:
                    preview = result.final_answer.strip()[-500:] or "未返回文本"
                    raise ValueError(f"CLI 已启动，但未完成最小任务：{preview}")
                return {
                    "ok": True,
                    "response": "真实最小任务通过（AGENTBENCH-OK）",
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "tokens_input": result.usage.input_tokens,
                    "tokens_output": result.usage.output_tokens,
                    "runner_type": runner_type,
                }
            finally:
                shutil.rmtree(workspace_path, ignore_errors=True)
        client = self._model_client(model, {})
        started = time.perf_counter()
        decision = client.complete(
            [
                {"role": "system", "content": "Return only OK."},
                {"role": "user", "content": "Connection check. Return only OK."},
            ],
            [],
        )
        return {
            "ok": decision.kind == "final",
            "response": decision.content[:500],
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    # Runners
    def list_runners(self) -> list[dict[str, Any]]:
        rows = self.database.fetch_all("SELECT * FROM agent_runners ORDER BY builtin DESC, name")
        output = []
        for row in rows:
            item = public_runner(row)
            item["capability"] = (
                {"installed": True, "version": "built-in"}
                if item["runner_type"] == "unified"
                else native_cli_status(item.get("executable"))
            )
            install = resolve_cli_install_plan(item["runner_type"])
            install.pop("argv", None)
            install.pop("manager_executable", None)
            item["install"] = install
            output.append(item)
        return output

    def start_runner_install(self, runner_id: str) -> dict[str, Any]:
        runner = self.database.fetch_one(
            "SELECT id,name,runner_type,builtin FROM agent_runners WHERE id=?",
            (runner_id,),
        )
        if not runner:
            raise KeyError("runner_not_found")
        if not runner["builtin"]:
            raise ValueError("自定义 Runner 不允许调用内置安装器")
        plan = resolve_cli_install_plan(str(runner["runner_type"]))
        if not plan.get("supported"):
            raise ValueError(str(plan.get("manual_instructions") or "此 Runner 只能手动安装"))
        if not plan.get("available") or not plan.get("argv"):
            raise ValueError(str(plan.get("unavailable_reason") or "安装工具不可用"))
        with self._state_lock:
            if any(
                job["status"] in {"queued", "running"}
                for job in self._install_jobs.values()
            ):
                raise ValueError("已有 Agent 安装任务正在运行，请等待完成后再继续")
            job_id = new_id()
            job = {
                "id": job_id,
                "runner_id": runner_id,
                "runner_name": runner["name"],
                "runner_type": runner["runner_type"],
                "status": "queued",
                "source": plan["source"],
                "command": plan["command"],
                "manager": plan["manager"],
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "created_at": utc_now(),
                "started_at": None,
                "completed_at": None,
                "duration_ms": 0,
                "error": None,
            }
            self._install_jobs[job_id] = job
        self.install_executor.submit(self._run_install_job, job_id, list(plan["argv"]))
        self.database.insert_audit(
            "runner.install_started",
            "runner",
            runner_id,
            {"job_id": job_id, "manager": plan["manager"], "command": plan["command"]},
        )
        return copy.deepcopy(job)

    def get_runner_install(self, job_id: str) -> dict[str, Any]:
        with self._state_lock:
            job = self._install_jobs.get(job_id)
            if not job:
                raise KeyError("install_job_not_found")
            return copy.deepcopy(job)

    def _append_install_output(self, job_id: str, field: str, text: str) -> None:
        with self._state_lock:
            job = self._install_jobs.get(job_id)
            if not job:
                return
            job[field] = (str(job[field]) + text)[-120_000:]

    def _run_install_job(self, job_id: str, argv: list[str]) -> None:
        started = time.perf_counter()
        with self._state_lock:
            job = self._install_jobs[job_id]
            job["status"] = "running"
            job["started_at"] = utc_now()
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in SAFE_ENV_KEYS
        }
        try:
            process = subprocess.Popen(
                argv,
                cwd=self.settings.data_dir,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            def drain(stream: Any, field: str) -> None:
                if stream is None:
                    return
                for line in iter(stream.readline, ""):
                    self._append_install_output(job_id, field, line)
                stream.close()

            stdout_reader = threading.Thread(
                target=drain, args=(process.stdout, "stdout"), daemon=True
            )
            stderr_reader = threading.Thread(
                target=drain, args=(process.stderr, "stderr"), daemon=True
            )
            stdout_reader.start()
            stderr_reader.start()
            exit_code = process.wait()
            stdout_reader.join(timeout=2)
            stderr_reader.join(timeout=2)
            with self._state_lock:
                job = self._install_jobs[job_id]
                job["exit_code"] = exit_code
                job["status"] = "completed" if exit_code == 0 else "failed"
                job["error"] = None if exit_code == 0 else f"安装命令退出码 {exit_code}"
        except OSError as exc:
            with self._state_lock:
                job = self._install_jobs[job_id]
                job["status"] = "failed"
                job["error"] = str(exc)
        finally:
            with self._state_lock:
                job = self._install_jobs[job_id]
                job["duration_ms"] = int((time.perf_counter() - started) * 1000)
                job["completed_at"] = utc_now()
                status = job["status"]
                runner_id = job["runner_id"]
            self.database.insert_audit(
                "runner.install_completed",
                "runner",
                runner_id,
                {"job_id": job_id, "status": status},
            )

    def create_runner(self, value: RunnerCreate) -> dict[str, Any]:
        runner_id = new_id()
        now = utc_now()
        self.database.execute(
            "INSERT INTO agent_runners(id,name,runner_type,executable,args_json,env_json,"
            "system_prompt,tools_json,limits_json,model_override_supported,enabled,builtin,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,0,?,?)",
            (
                runner_id,
                value.name,
                value.runner_type,
                value.executable,
                json.dumps(value.args, ensure_ascii=False),
                json.dumps(value.env, ensure_ascii=False),
                value.system_prompt,
                json.dumps(value.tools),
                json.dumps(value.limits),
                int(value.model_override_supported),
                now,
                now,
            ),
        )
        self.database.insert_audit("runner.created", "runner", runner_id)
        row = self.database.fetch_one("SELECT * FROM agent_runners WHERE id=?", (runner_id,))
        assert row
        return public_runner(row)

    # Catalog
    def import_math_paper(self, *, filename: str, content: bytes, year: int) -> dict[str, Any]:
        return import_math_pdf(
            self.settings.data_dir,
            filename=filename,
            content=content,
            year=year,
        )

    def list_math_paper_imports(self) -> list[dict[str, Any]]:
        return list_math_imports(self.settings.data_dir)

    def get_math_paper_import(self, import_id: str) -> dict[str, Any]:
        return get_math_import(self.settings.data_dir, import_id)

    def _math_experiment_score(self, experiment_id: str) -> dict[str, float] | None:
        rows = self.database.fetch_all(
            "SELECT r.score,t.definition_json FROM runs r "
            "JOIN test_cases t ON t.id=r.test_case_id WHERE r.experiment_id=?",
            (experiment_id,),
        )
        weighted_sum = 0.0
        point_sum = 0.0
        found_math = False
        for row in rows:
            metadata = (_json(row["definition_json"], {}).get("metadata") or {})
            if metadata.get("exam") != MATH_EXAM_ID:
                continue
            found_math = True
            if row.get("score") is None:
                continue
            points = float(metadata.get("points") or 0)
            if points <= 0:
                continue
            weighted_sum += float(row["score"]) * points
            point_sum += points
        if not found_math or point_sum <= 0:
            return None
        raw_percentage = weighted_sum / point_sum
        percentage = round(raw_percentage, 2)
        return {
            "weighted_score": percentage,
            "exam_score": round(raw_percentage * 1.5, 2),
            "exam_total": 150.0,
        }

    def update_math_paper_question(
        self, import_id: str, number: int, changes: dict[str, Any]
    ) -> dict[str, Any]:
        manifest = update_math_question(self.settings.data_dir, import_id, number, changes)
        self.database.insert_audit(
            "math_paper.question_updated",
            "math_paper_import",
            import_id,
            {"question_no": number, "review_status": changes.get("review_status")},
        )
        return manifest

    def publish_math_paper(self, import_id: str) -> dict[str, Any]:
        manifest = get_math_import(self.settings.data_dir, import_id)
        if manifest.get("status") == "published":
            return manifest
        cases_by_lane = build_published_math_cases(manifest)
        year = int(manifest["year"])
        now = utc_now()
        published_suites: list[dict[str, Any]] = []
        case_ids: list[str] = []
        with self.database.transaction() as connection:
            for lane, cases in cases_by_lane.items():
                lane_name = "闭卷推理" if lane == "closed-book" else "工具增强"
                suite_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"agentbench:math-suite:{year}:{lane}",
                    )
                )
                connection.execute(
                    "INSERT INTO test_suites(id,name,description,version,builtin,created_at) "
                    "VALUES (?,?,?,?,0,?) ON CONFLICT(id) DO UPDATE SET "
                    "name=excluded.name,description=excluded.description,version=excluded.version",
                    (
                        suite_id,
                        f"{year} 考研数学一 · {lane_name}",
                        "22 道经人工校对的正式真题。"
                        + ("仅允许统一 Agent 参测，以保证工具完全禁用。" if lane == "closed-book" else "允许 Agent 使用其可用工具。"),
                        f"{year}.1",
                        now,
                    ),
                )
                connection.execute("DELETE FROM suite_cases WHERE suite_id=?", (suite_id,))
                for position, case in enumerate(cases):
                    definition = case["definition"]
                    self._validate_definition(definition)
                    definition_json = json.dumps(definition, ensure_ascii=False)
                    connection.execute(
                        "INSERT INTO test_cases(id,slug,version,category,title,description,definition_json,builtin,enabled,created_at) "
                        "VALUES (?,?,?,?,?,?,?,0,1,?) ON CONFLICT(id) DO UPDATE SET "
                        "title=excluded.title,description=excluded.description,definition_json=excluded.definition_json,enabled=1",
                        (
                            case["id"], case["slug"], case["version"], case["category"],
                            case["title"], case["description"], definition_json, now,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO suite_cases(suite_id,test_case_id,position) VALUES (?,?,?)",
                        (suite_id, case["id"], position),
                    )
                    case_ids.append(case["id"])
                published_suites.append(
                    {"id": suite_id, "lane": lane, "name": f"{year} 考研数学一 · {lane_name}", "case_count": len(cases)}
                )
        for case_id in case_ids:
            self.database.sync_test_case_revisions(case_id)
        published = mark_math_import_published(
            self.settings.data_dir, import_id, published_suites
        )
        self.database.insert_audit(
            "math_paper.published",
            "math_paper_import",
            import_id,
            {"suite_ids": [item["id"] for item in published_suites]},
        )
        return published

    def list_test_cases(
        self, category: str | None = None, query: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        clauses = ["enabled=1"]
        params: list[Any] = []
        if category:
            clauses.append("category=?")
            params.append(category)
        if query:
            clauses.append("(title LIKE ? OR slug LIKE ? OR description LIKE ?)")
            token = f"%{query}%"
            params.extend([token, token, token])
        params.append(min(max(limit, 1), 500))
        rows = self.database.fetch_all(
            f"SELECT id,slug,version,category,title,description,definition_json,builtin,created_at "
            f"FROM test_cases WHERE {' AND '.join(clauses)} ORDER BY category,title LIMIT ?",
            params,
        )
        for row in rows:
            row["builtin"] = bool(row["builtin"])
            definition = _json(row.pop("definition_json"), {})
            metadata = definition.get("metadata") or {}
            validators = definition.get("validators") or []
            row["difficulty"] = int(metadata.get("difficulty", 2))
            row["estimated_minutes"] = int(metadata.get("estimated_minutes", 5))
            row["capability"] = metadata.get("capability") or row["category"]
            row["tags"] = definition.get("tags") or []
            row["tools"] = definition.get("tools") or []
            row["requires_docker"] = any(
                item.get("type") in {"command", "command_metrics"} for item in validators
            )
            row["requires_judge"] = any(
                item.get("type") == "ai_rubric" for item in validators
            )
        self._attach_test_health(rows)
        return rows

    def _attach_test_health(self, rows: list[dict[str, Any]]) -> None:
        """Attach evidence-backed calibration health without trusting legacy passed flags."""
        if not rows:
            return
        case_ids = [str(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in case_ids)
        samples = self.database.fetch_all(
            "SELECT r.test_case_id,r.model_id,r.score,"
            "(SELECT sc.score FROM score_components sc WHERE sc.run_id=r.id "
            "AND sc.dimension='objective_quality' LIMIT 1) AS objective_score,"
            "(SELECT ra.raw_score FROM run_attempts ra WHERE ra.run_id=r.id "
            "AND ra.attempt_no=1 LIMIT 1) AS first_attempt_score "
            "FROM runs r JOIN test_cases current_case ON current_case.id=r.test_case_id "
            "LEFT JOIN test_case_revisions current_revision "
            "ON current_revision.test_case_id=current_case.id "
            "AND current_revision.definition_hash=current_case.definition_hash "
            "WHERE r.status='completed' AND r.score IS NOT NULL "
            "AND (r.test_revision_id=current_revision.id OR r.test_revision_id IS NULL) "
            f"AND r.test_case_id IN ({placeholders})",
            case_ids,
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for sample in samples:
            grouped.setdefault(str(sample["test_case_id"]), []).append(sample)
        for row in rows:
            values = grouped.get(str(row["id"]), [])
            quality_scores = [
                float(
                    item["objective_score"]
                    if item["objective_score"] is not None
                    else item["score"]
                )
                for item in values
            ]
            first_scores = [
                float(item["first_attempt_score"])
                for item in values
                if item["first_attempt_score"] is not None
            ]
            sample_size = len(quality_scores)
            full_count = sum(score >= 99.5 for score in quality_scores)
            partial_count = sum(0 < score < 99.5 for score in quality_scores)
            first_full_count = sum(score >= 99.5 for score in first_scores)
            if sample_size >= 20:
                confidence = "high"
            elif sample_size >= 9:
                confidence = "medium"
            elif sample_size >= 3:
                confidence = "low"
            else:
                confidence = "insufficient"
            full_rate = round(full_count * 100.0 / sample_size, 1) if sample_size else None
            row["health"] = {
                "sample_size": sample_size,
                "model_count": len({str(item["model_id"]) for item in values}),
                "avg_objective_score": round(statistics.fmean(quality_scores), 2)
                if quality_scores
                else None,
                "objective_full_rate": full_rate,
                "first_attempt_full_rate": round(
                    first_full_count * 100.0 / len(first_scores), 1
                )
                if first_scores
                else None,
                "partial_credit_rate": round(partial_count * 100.0 / sample_size, 1)
                if sample_size
                else None,
                "score_stddev": round(statistics.pstdev(quality_scores), 2)
                if sample_size > 1
                else None,
                "confidence": confidence,
                "low_discrimination": bool(sample_size >= 3 and (full_rate or 0) >= 80),
            }

    def get_test_case(self, case_id: str) -> dict[str, Any]:
        row = self.database.fetch_one("SELECT * FROM test_cases WHERE id=?", (case_id,))
        if not row:
            raise KeyError("test_case_not_found")
        row["definition"] = public_definition(_json(row.pop("definition_json"), {}))
        row["builtin"] = bool(row["builtin"])
        row["enabled"] = bool(row["enabled"])
        return row

    def import_test_case(self, value: TestCaseImport) -> dict[str, Any]:
        definition = value.model_dump(mode="json")
        self._validate_definition(definition)
        case_id = new_id()
        self.database.execute(
            "INSERT INTO test_cases(id,slug,version,category,title,description,definition_json,"
            "builtin,enabled,created_at) VALUES (?,?,?,?,?,?,?,0,1,?)",
            (
                case_id,
                value.slug,
                value.version,
                value.category,
                value.title,
                value.description,
                json.dumps(definition, ensure_ascii=False),
                utc_now(),
            ),
        )
        self.database.sync_test_case_revisions(case_id)
        self.database.insert_audit("test_case.imported", "test_case", case_id)
        return self.get_test_case(case_id)

    @staticmethod
    def _validate_definition(definition: dict[str, Any]) -> None:
        if not definition.get("validators"):
            raise ValueError("At least one validator is required")
        total = sum(float(item.get("weight", 0)) for item in definition["validators"])
        if total <= 0 or total > 100:
            raise ValueError("Validator weights must total between 0 and 100")
        supported = {
            "exact_match",
            "contains",
            "regex",
            "json_schema",
            "json_file",
            "symbolic_json",
            "constraint_plan",
            "file_exists",
            "file_content",
            "file_contains",
            "forbidden_paths",
            "command",
            "command_metrics",
            "ai_rubric",
        }
        unknown = [
            item["type"] for item in definition["validators"] if item.get("type") not in supported
        ]
        if unknown:
            raise ValueError(f"Unsupported validators: {', '.join(unknown)}")

    def list_suites(self) -> list[dict[str, Any]]:
        suites = self.database.fetch_all(
            "SELECT s.*, COUNT(sc.test_case_id) AS case_count FROM test_suites s "
            "LEFT JOIN suite_cases sc ON sc.suite_id=s.id GROUP BY s.id ORDER BY s.builtin DESC,s.name"
        )
        for suite in suites:
            definitions = self.database.fetch_all(
                "SELECT t.category,t.definition_json FROM suite_cases sc "
                "JOIN test_cases t ON t.id=sc.test_case_id WHERE sc.suite_id=?",
                (suite["id"],),
            )
            difficulties: list[int] = []
            categories: set[str] = set()
            docker_cases = 0
            judge_cases = 0
            for item in definitions:
                definition = _json(item["definition_json"], {})
                metadata = definition.get("metadata") or {}
                limits = definition.get("limits") or {}
                validators = definition.get("validators") or []
                difficulties.append(int(metadata.get("difficulty", 2)))
                categories.add(str(item["category"]))
                docker_cases += int(
                    bool(limits.get("docker_image"))
                    or any(v.get("type") in {"command", "command_metrics"} for v in validators)
                )
                judge_cases += int(any(v.get("type") == "ai_rubric" for v in validators))
            suite["difficulty_min"] = min(difficulties, default=1)
            suite["difficulty_max"] = max(difficulties, default=1)
            suite["category_count"] = len(categories)
            suite["docker_case_count"] = docker_cases
            suite["judge_case_count"] = judge_cases
        return suites

    def get_suite(self, suite_id: str) -> dict[str, Any]:
        suite = self.database.fetch_one("SELECT * FROM test_suites WHERE id=?", (suite_id,))
        if not suite:
            raise KeyError("suite_not_found")
        suite["cases"] = self.database.fetch_all(
            "SELECT t.id,t.slug,t.version,t.category,t.title,t.description FROM suite_cases sc "
            "JOIN test_cases t ON t.id=sc.test_case_id WHERE sc.suite_id=? ORDER BY sc.position",
            (suite_id,),
        )
        return suite

    def list_suite_cases(self, suite_id: str) -> list[dict[str, Any]]:
        """Narrow case-preview endpoint: whitelist fields only, never expose definition."""
        suite = self.database.fetch_one("SELECT id FROM test_suites WHERE id=?", (suite_id,))
        if not suite:
            raise KeyError("suite_not_found")
        rows = self.database.fetch_all(
            "SELECT t.id,t.slug,t.category,t.title,t.description,t.definition_json "
            "FROM suite_cases sc JOIN test_cases t ON t.id=sc.test_case_id "
            "WHERE sc.suite_id=? ORDER BY sc.position",
            (suite_id,),
        )
        cases: list[dict[str, Any]] = []
        for row in rows:
            definition = _json(row["definition_json"], {})
            metadata = definition.get("metadata") or {}
            validators = definition.get("validators") or []
            limits = definition.get("limits") or {}
            cases.append(
                {
                    "id": row["id"],
                    "slug": row["slug"],
                    "title": row["title"],
                    "description": row["description"],
                    "category": row["category"],
                    "difficulty": int(metadata.get("difficulty", 1)),
                    "estimated_minutes": int(metadata.get("estimated_minutes", 5)),
                    "requires_docker": bool(limits.get("docker_image"))
                    or any(
                        item.get("type") in {"command", "command_metrics"} for item in validators
                    ),
                    "instruction": definition.get("instruction", ""),
                }
            )
        return cases

    # Experiments
    def create_experiment(self, value: ExperimentCreate) -> dict[str, Any]:
        self.get_suite(value.suite_id)
        for participant in value.participants:
            model = self.get_model(participant.model_id)
            runner = self.database.fetch_one(
                "SELECT * FROM agent_runners WHERE id=?", (participant.runner_id,)
            )
            if not runner:
                raise KeyError("runner_not_found")
            if not model["enabled"] or not runner["enabled"]:
                raise ValueError("Disabled models or runners cannot participate")
        experiment_id = new_id()
        now = utc_now()
        participants = [item.model_dump() for item in value.participants]
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO experiments(id,name,suite_id,participants_json,repetitions,concurrency,"
                "benchmark_generation,scoring_profile,status,created_at) "
                "VALUES (?,?,?,?,?,?,'v3','balanced-v3','draft',?)",
                (
                    experiment_id,
                    value.name,
                    value.suite_id,
                    json.dumps(participants),
                    value.repetitions,
                    value.concurrency,
                    now,
                ),
            )
            cases = connection.execute(
                "SELECT sc.test_case_id,tr.id AS test_revision_id "
                "FROM suite_cases sc JOIN test_cases t ON t.id=sc.test_case_id "
                "LEFT JOIN test_case_revisions tr ON tr.test_case_id=t.id "
                "AND tr.definition_hash=t.definition_hash "
                "WHERE sc.suite_id=? ORDER BY sc.position",
                (value.suite_id,),
            ).fetchall()
            for repetition in range(1, value.repetitions + 1):
                for participant in participants:
                    runner = connection.execute(
                        "SELECT runner_type FROM agent_runners WHERE id=?",
                        (participant["runner_id"],),
                    ).fetchone()
                    lane = "unified" if runner["runner_type"] == "unified" else "native"
                    for case in cases:
                        connection.execute(
                            "INSERT INTO runs(id,experiment_id,test_case_id,model_id,runner_id,"
                            "test_revision_id,repetition,lane,scoring_profile,status,created_at) "
                            "VALUES (?,?,?,?,?,?,?,?,'balanced-v3','queued',?)",
                            (
                                new_id(),
                                experiment_id,
                                case["test_case_id"],
                                participant["model_id"],
                                participant["runner_id"],
                                case["test_revision_id"],
                                repetition,
                                lane,
                                now,
                            ),
                        )
        self.database.insert_audit("experiment.created", "experiment", experiment_id)
        return self.get_experiment(experiment_id)

    def list_experiments(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            "SELECT e.*,s.name AS suite_name,COUNT(r.id) AS run_count,"
            "SUM(CASE WHEN r.status IN ('completed','failed','cancelled','environment_unavailable',"
            "'needs_review','interrupted') THEN 1 ELSE 0 END) AS finished_count,AVG(r.score) AS avg_score "
            "FROM experiments e JOIN test_suites s ON s.id=e.suite_id "
            "LEFT JOIN runs r ON r.experiment_id=e.id GROUP BY e.id ORDER BY e.created_at DESC LIMIT ?",
            (min(max(limit, 1), 500),),
        )
        for row in rows:
            row["participants"] = _json(row.pop("participants_json"), [])
            math_score = self._math_experiment_score(row["id"])
            if math_score:
                row["avg_score"] = math_score["weighted_score"]
                row.update(math_score)
        return rows

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT e.*,s.name AS suite_name FROM experiments e JOIN test_suites s ON s.id=e.suite_id "
            "WHERE e.id=?",
            (experiment_id,),
        )
        if not row:
            raise KeyError("experiment_not_found")
        row["participants"] = _json(row.pop("participants_json"), [])
        row["summary"] = self.database.fetch_one(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed,"
            "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed,"
            "SUM(CASE WHEN status='environment_unavailable' THEN 1 ELSE 0 END) blocked,"
            "AVG(score) avg_score,SUM(cost_usd) cost_usd,SUM(tokens_input+tokens_output) tokens,"
            "SUM(CASE WHEN cost_source='unpriced' THEN 1 ELSE 0 END) unpriced_runs,"
            "AVG((SELECT sc.score FROM score_components sc WHERE sc.run_id=runs.id "
            "AND sc.dimension='objective_quality' LIMIT 1)) avg_objective_score,"
            "AVG((SELECT sc.score FROM score_components sc WHERE sc.run_id=runs.id "
            "AND sc.dimension='judge_quality' LIMIT 1)) avg_judge_score,"
            "AVG((SELECT sc.score FROM score_components sc WHERE sc.run_id=runs.id "
            "AND sc.dimension='time_efficiency' LIMIT 1)) avg_time_score,"
            "AVG((SELECT sc.score FROM score_components sc WHERE sc.run_id=runs.id "
            "AND sc.dimension='token_efficiency' LIMIT 1)) avg_token_score "
            "FROM runs WHERE experiment_id=?",
            (experiment_id,),
        )
        math_score = self._math_experiment_score(experiment_id)
        if math_score and row["summary"]:
            row["summary"]["avg_score"] = math_score["weighted_score"]
            row["summary"].update(math_score)
        return row

    def start_experiment(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.get_experiment(experiment_id)
        if experiment["status"] not in {"draft", "interrupted"}:
            raise ValueError("experiment_not_startable")
        preflight = self.preflight_experiment(experiment_id)
        if not preflight["ok"]:
            detail = "\n- ".join(preflight["errors"])
            raise ValueError(f"评测启动前检查未通过：\n- {detail}")
        self.database.execute(
            "UPDATE experiments SET status='running',started_at=?,completed_at=NULL WHERE id=?",
            (utc_now(), experiment_id),
        )
        semaphore = threading.Semaphore(int(experiment["concurrency"]))
        self._experiment_semaphores[experiment_id] = semaphore
        runs = self.database.fetch_all(
            "SELECT id FROM runs WHERE experiment_id=? AND status IN ('queued','interrupted')",
            (experiment_id,),
        )
        for run in runs:
            self.executor.submit(self._run_with_semaphore, run["id"], semaphore)
        self.database.insert_audit("experiment.started", "experiment", experiment_id)
        return self.get_experiment(experiment_id)

    def preflight_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Validate shared environment once before any queued run is dispatched."""
        experiment = self.get_experiment(experiment_id)
        errors: list[str] = []
        warnings: list[str] = []
        participants = experiment["participants"]
        native_runners: list[dict[str, Any]] = []
        seen_runner_ids: set[str] = set()
        for participant in participants:
            model = self.get_model(participant["model_id"])
            runner = self.database.fetch_one(
                "SELECT * FROM agent_runners WHERE id=?", (participant["runner_id"],)
            )
            if not runner:
                errors.append(f"Runner {participant['runner_id']} 不存在")
                continue
            if not model["enabled"] or not runner["enabled"]:
                errors.append(f"{model['name']} × {runner['name']} 已被停用")
            if runner["runner_type"] == "unified":
                continue
            if runner["id"] not in seen_runner_ids:
                seen_runner_ids.add(runner["id"])
                native_runners.append(runner)

        if native_runners and not self._native_cli_allowed():
            errors.append("原生 CLI Runner 尚未启用，请先在“本地设置”中开启")
        for runner in native_runners:
            runner_errors, runner_warnings = self._check_runner(runner)
            errors.extend(runner_errors)
            warnings.extend(runner_warnings)

        definitions = self.database.fetch_all(
            "SELECT DISTINCT COALESCE(tr.definition_json,t.definition_json) AS definition_json "
            "FROM runs r JOIN test_cases t ON t.id=r.test_case_id "
            "LEFT JOIN test_case_revisions tr ON tr.id=r.test_revision_id "
            "WHERE r.experiment_id=?",
            (experiment_id,),
        )
        validators = [
            validator
            for row in definitions
            for validator in (_json(row["definition_json"], {}).get("validators") or [])
        ]
        native_incompatible = any(
            (_json(row["definition_json"], {}).get("metadata") or {}).get(
                "native_agent_compatible"
            )
            is False
            for row in definitions
        )
        if native_runners and native_incompatible:
            errors.append("所选闭卷测试要求完全禁用工具，仅允许统一 Agent 参测")
        requires_docker = any(item.get("type") == "command" for item in validators)
        requires_judge = any(item.get("type") == "ai_rubric" for item in validators)
        if requires_docker and not self.docker.available:
            errors.append("所选测试集包含命令验证题，但 Docker Desktop 当前不可用")

        judge_model_id = self.get_setting("judge_model_id")
        judge_runner_id = self.get_setting("judge_runner_id")
        if requires_judge and not judge_model_id and not judge_runner_id:
            warnings.append("测试集包含 AI Rubric；未配置匿名 AI 裁判的题目将进入人工复核")
        elif requires_judge:
            if not judge_model_id or not judge_runner_id:
                errors.append("AI 裁判配置不完整：裁判模型和裁判 Runner 必须同时选择")
            else:
                judge_model = self.database.fetch_one(
                    "SELECT * FROM models WHERE id=?", (judge_model_id,)
                )
                judge_runner = self.database.fetch_one(
                    "SELECT * FROM agent_runners WHERE id=?", (judge_runner_id,)
                )
                if not judge_model or not judge_model["enabled"]:
                    errors.append("已配置的裁判模型不存在或已停用")
                if not judge_runner or not judge_runner["enabled"]:
                    errors.append("已配置的裁判 Runner 不存在或已停用")
                elif judge_runner["runner_type"] != "unified":
                    if not self._native_cli_allowed():
                        errors.append("裁判使用原生 CLI Runner，但原生 CLI 尚未启用")
                    judge_errors, judge_warnings = self._check_runner(judge_runner)
                    errors.extend(f"裁判：{item}" for item in judge_errors)
                    warnings.extend(f"裁判：{item}" for item in judge_warnings)
                if judge_model_id in {item["model_id"] for item in participants}:
                    errors.append("匿名裁判模型不能同时作为本实验的参测模型")

            participant_model_ids = {item["model_id"] for item in participants}
            for label, model_key, runner_key in (
                ("第二匿名裁判", "judge_model_id_secondary", "judge_runner_id_secondary"),
                ("仲裁裁判", "judge_model_id_tiebreaker", "judge_runner_id_tiebreaker"),
            ):
                configured_model_id = self.get_setting(model_key)
                configured_runner_id = self.get_setting(runner_key)
                if bool(configured_model_id) != bool(configured_runner_id):
                    errors.append(f"{label}配置不完整：模型和 Runner 必须同时选择")
                    continue
                if not configured_model_id:
                    continue
                configured_model = self.database.fetch_one(
                    "SELECT * FROM models WHERE id=?", (configured_model_id,)
                )
                configured_runner = self.database.fetch_one(
                    "SELECT * FROM agent_runners WHERE id=?", (configured_runner_id,)
                )
                if not configured_model or not configured_model["enabled"]:
                    errors.append(f"{label}模型不存在或已停用")
                if not configured_runner or not configured_runner["enabled"]:
                    errors.append(f"{label} Runner 不存在或已停用")
                elif configured_runner["runner_type"] != "unified":
                    if not self._native_cli_allowed():
                        errors.append(f"{label}使用原生 CLI，但原生 CLI 尚未启用")
                    slot_errors, slot_warnings = self._check_runner(configured_runner)
                    errors.extend(f"{label}：{item}" for item in slot_errors)
                    warnings.extend(f"{label}：{item}" for item in slot_warnings)
                if configured_model_id in participant_model_ids:
                    errors.append(f"{label}模型不能同时作为本实验的参测模型")
            if requires_judge and judge_model_id and not self.get_setting(
                "judge_model_id_secondary"
            ):
                warnings.append("当前仅配置一个匿名裁判；V3 建议配置第二裁判以检测评分分歧")

        return {
            "ok": not errors,
            "errors": list(dict.fromkeys(errors)),
            "warnings": list(dict.fromkeys(warnings)),
            "checks": {
                "participants": len(participants),
                "native_runners": len(native_runners),
                "requires_docker": requires_docker,
                "requires_judge": requires_judge,
            },
        }

    @staticmethod
    def _runner_required_args(runner_type: str) -> tuple[str, ...]:
        return {
            "codex_cli": ("exec", "--json", "--skip-git-repo-check", "{model_name}", "{prompt}"),
            "claude_code_cli": (
                "--print",
                "--output-format",
                "json",
                "--no-session-persistence",
                "--permission-mode",
                "auto",
                "--effort",
                "medium",
                "{model_name}",
                "{prompt}",
            ),
            "opencode_cli": (
                "run",
                "--format",
                "json",
                "--auto",
                "{model_name}",
                "{prompt}",
            ),
            "reasonix_cli": (
                "run",
                "--output-format",
                "json",
                "--permission-mode",
                "auto",
                "{model_name}",
                "{prompt}",
            ),
            "gemini_cli": ("--output-format", "stream-json", "{model_name}", "{prompt}"),
            "aider_cli": ("--no-git", "--message", "{model_name}", "{prompt}"),
            "kimi_code_cli": (
                "--print",
                "--output-format",
                "stream-json",
                "{model_name}",
                "{prompt}",
            ),
            "qoder_cli": ("--print", "--output-format", "{prompt}"),
            "command": ("{prompt}",),
        }.get(runner_type, ())

    def _check_runner(self, runner: dict[str, Any]) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        name = str(runner.get("name") or runner.get("runner_type") or "Runner")
        executable = runner.get("executable")
        if not executable:
            return [f"{name} 未配置可执行文件"], warnings
        args = _json(runner.get("args_json"), [])
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            errors.append(f"{name} 的参数不是有效字符串数组")
        else:
            missing = [
                item for item in self._runner_required_args(str(runner["runner_type"])) if item not in args
            ]
            if missing:
                errors.append(f"{name} 缺少必要参数：{', '.join(missing)}")
        capability = native_cli_status(str(executable))
        if not capability.get("installed"):
            detail = capability.get("error") or f"未检测到可执行文件 {executable}"
            install = capability.get("install_command")
            errors.append(f"{name} 不可用：{detail}" + (f"；可执行：{install}" if install else ""))
        if capability.get("warning"):
            warnings.append(f"{name}：{capability['warning']}")
        return errors, warnings

    def cancel_experiment(self, experiment_id: str) -> dict[str, Any]:
        self.get_experiment(experiment_id)
        self.database.execute(
            "UPDATE runs SET status='cancelled',completed_at=? WHERE experiment_id=? AND status='queued'",
            (utc_now(), experiment_id),
        )
        with self._state_lock:
            run_ids = self.database.fetch_all(
                "SELECT id FROM runs WHERE experiment_id=? AND status IN ('preparing','running')",
                (experiment_id,),
            )
            for row in run_ids:
                self._cancel_events.setdefault(row["id"], threading.Event()).set()
        self.database.execute(
            "UPDATE experiments SET status='cancelled',completed_at=? WHERE id=?",
            (utc_now(), experiment_id),
        )
        self.database.insert_audit("experiment.cancelled", "experiment", experiment_id)
        return self.get_experiment(experiment_id)

    def list_runs(self, experiment_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        where = "WHERE r.experiment_id=?" if experiment_id else ""
        params: tuple[Any, ...] = (
            (experiment_id, min(limit, 1000)) if experiment_id else (min(limit, 1000),)
        )
        rows = self.database.fetch_all(
            "SELECT r.*,t.title AS test_title,t.category,m.name AS model_name,a.name AS runner_name,"
            "(SELECT score FROM score_components sc WHERE sc.run_id=r.id "
            "AND sc.dimension='objective_quality' LIMIT 1) AS objective_score,"
            "(SELECT score FROM score_components sc WHERE sc.run_id=r.id "
            "AND sc.dimension='judge_quality' LIMIT 1) AS judge_score,"
            "(SELECT score FROM score_components sc WHERE sc.run_id=r.id "
            "AND sc.dimension='time_efficiency' LIMIT 1) AS time_score,"
            "(SELECT score FROM score_components sc WHERE sc.run_id=r.id "
            "AND sc.dimension='step_efficiency' LIMIT 1) AS step_score "
            ",(SELECT score FROM score_components sc WHERE sc.run_id=r.id "
            "AND sc.dimension='token_efficiency' LIMIT 1) AS token_score "
            "FROM runs r JOIN test_cases t ON t.id=r.test_case_id JOIN models m ON m.id=r.model_id "
            f"JOIN agent_runners a ON a.id=r.runner_id {where} ORDER BY r.created_at DESC LIMIT ?",
            params,
        )
        for row in rows:
            row["passed"] = None if row["passed"] is None else bool(row["passed"])
        return rows

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT r.*,t.title AS test_title,t.category,m.name AS model_name,"
            "m.model_name,a.name AS runner_name,a.runner_type FROM runs r "
            "JOIN test_cases t ON t.id=r.test_case_id JOIN models m ON m.id=r.model_id "
            "JOIN agent_runners a ON a.id=r.runner_id WHERE r.id=?",
            (run_id,),
        )
        if not row:
            raise KeyError("run_not_found")
        row["passed"] = None if row["passed"] is None else bool(row["passed"])
        definition, revision = self._definition_for_run(row)
        row["test_case_version"] = revision.get("version")
        row["test_definition_hash"] = revision.get("definition_hash")
        definition.pop("metadata", None)
        public = public_definition(definition)
        # Slim payload: never ship material bytes inline; expose a name/size manifest only.
        initial_files = public.pop("initial_files", None) or {}
        row["materials"] = [
            {"name": name, "size_bytes": _material_size_bytes(value)}
            for name, value in initial_files.items()
        ]
        row["test_definition"] = public
        row["events"] = self.get_run_events(run_id)
        row["validators"] = self.database.fetch_all(
            "SELECT * FROM validator_results WHERE run_id=? ORDER BY created_at", (run_id,)
        )
        for item in row["validators"]:
            item["evidence"] = _json(item.pop("evidence_json"), {})
        row["score_dimensions"] = self.database.fetch_all(
            "SELECT * FROM score_components WHERE run_id=? ORDER BY created_at", (run_id,)
        )
        for item in row["score_dimensions"]:
            item["evidence"] = _json(item.pop("evidence_json"), {})
        row["attempts"] = self.database.fetch_all(
            "SELECT * FROM run_attempts WHERE run_id=? ORDER BY attempt_no", (run_id,)
        )
        for attempt in row["attempts"]:
            attempt["result"] = _json(attempt.pop("result_json"), {})
            attempt["passed"] = bool(attempt["passed"])
        row["artifacts"] = self.database.fetch_all(
            "SELECT * FROM artifacts WHERE run_id=?", (run_id,)
        )
        row["judge_reviews"] = self.database.fetch_all(
            "SELECT * FROM judge_reviews WHERE run_id=? ORDER BY created_at", (run_id,)
        )
        for review in row["judge_reviews"]:
            review["evidence"] = _json(review.pop("evidence_json"), {})
        return row

    def get_run_material(self, run_id: str, filename: str) -> tuple[bytes, str]:
        """Download one initial_files material of the run's test case.

        Whitelist semantics: filename must exactly match an initial_files key.
        Never touches validators/private_files. Returns (content, filename).
        """
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            raise KeyError("material_not_found")
        row = self.database.fetch_one(
            "SELECT r.test_case_id,r.test_revision_id FROM runs r WHERE r.id=?",
            (run_id,),
        )
        if not row:
            raise KeyError("run_not_found")
        definition, _ = self._definition_for_run(row)
        initial_files = definition.get("initial_files") or {}
        if filename not in initial_files:
            raise KeyError("material_not_found")
        content = initial_files[filename]
        if isinstance(content, str) and content.startswith("base64:"):
            return base64.b64decode(content[len("base64:"):]), filename
        return str(content).encode("utf-8"), filename

    def get_run_events(
        self, run_id: str, after: int = 0, *, viewer_safe: bool = True
    ) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            "SELECT id,seq,event_type,payload_json,created_at FROM run_events "
            "WHERE run_id=? AND seq>? ORDER BY seq",
            (run_id, after),
        )
        for row in rows:
            row["payload"] = _json(row.pop("payload_json"), {})
            if viewer_safe:
                row["payload"] = _viewer_safe_event_payload(row["event_type"], row["payload"])
        return rows

    def retry_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] in {"preparing", "running", "validating", "judging"}:
            raise ValueError("run_is_active")
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM run_events WHERE run_id=?", (run_id,))
            connection.execute("DELETE FROM validator_results WHERE run_id=?", (run_id,))
            connection.execute("DELETE FROM score_components WHERE run_id=?", (run_id,))
            connection.execute("DELETE FROM run_attempts WHERE run_id=?", (run_id,))
            connection.execute("DELETE FROM artifacts WHERE run_id=?", (run_id,))
            connection.execute("DELETE FROM judge_reviews WHERE run_id=?", (run_id,))
            connection.execute(
                "UPDATE runs SET status='queued',final_answer=NULL,score=NULL,error_code=NULL,"
                "error_message=NULL,tokens_input=0,tokens_output=0,cost_usd=0,"
                "cost_source='unavailable',duration_ms=0,steps=0,attempt_count=1,passed=NULL,"
                "started_at=NULL,completed_at=NULL WHERE id=?",
                (run_id,),
            )
        self.executor.submit(self._run_with_semaphore, run_id, threading.Semaphore(1))
        return self.get_run(run_id)

    def rejudge_run(self, run_id: str, *, reuse_judge: bool = False) -> dict[str, Any]:
        """Re-score a stored answer without re-running the candidate model.

        ``reuse_judge`` is used by deterministic batch revalidation after a parser or
        checker update.  Existing AI-rubric evidence is retained in that mode so a
        historical repair does not create fresh judge cost or change a judge opinion.
        """
        run = self.get_run(run_id)
        if run["status"] not in {"needs_review", "completed"}:
            raise ValueError("run_not_rejudgeable")
        final_answer = run.get("final_answer") or ""
        if not final_answer.strip():
            raise ValueError("run_has_no_final_answer")
        definition, _ = self._definition_for_run(run)
        workspace_path = (
            Path(run["workspace_path"])
            if run.get("workspace_path")
            else self.settings.workspaces_dir / run_id
        )
        workspace = Workspace(workspace_path)
        seq_row = self.database.fetch_one(
            "SELECT COALESCE(MAX(seq), 0) AS seq FROM run_events WHERE run_id=?", (run_id,)
        )
        seq = int(seq_row["seq"]) if seq_row else 0

        def event_sink(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal seq
            seq += 1
            self.database.execute(
                "INSERT INTO run_events(run_id,seq,event_type,payload_json,created_at) VALUES (?,?,?,?,?)",
                (run_id, seq, event_type, json.dumps(payload, ensure_ascii=False), utc_now()),
            )

        previous_score = run.get("score")
        event_sink(
            "rejudge.started",
            {
                "previous_status": run["status"],
                "previous_score": previous_score,
                "judge_mode": "reuse" if reuse_judge else "fresh",
            },
        )
        fresh_judge_callback = self._judge_callback(run, definition, workspace, event_sink)
        if reuse_judge:
            stored_judges = self.database.fetch_all(
                "SELECT score,status,evidence_json FROM validator_results "
                "WHERE run_id=? AND validator_type='ai_rubric' ORDER BY created_at,id",
                (run_id,),
            )
            stored_judge_index = 0

            def reused_judge_callback(
                config: dict[str, Any], weight: float
            ) -> ValidationResult:
                nonlocal stored_judge_index
                if stored_judge_index < len(stored_judges):
                    stored = stored_judges[stored_judge_index]
                    stored_judge_index += 1
                    evidence = _json(stored.get("evidence_json"), {})
                    evidence = {
                        **evidence,
                        "reused_for_revalidation": True,
                        "source_run_id": run_id,
                    }
                    return ValidationResult(
                        "ai_rubric",
                        weight,
                        float(stored.get("score") or 0),
                        str(stored.get("status") or "needs_review"),
                        evidence,
                    )
                if fresh_judge_callback is not None:
                    return fresh_judge_callback(config, weight)
                return ValidationResult(
                    "ai_rubric",
                    weight,
                    0,
                    "needs_review",
                    {"reason": "No reusable or configured judge is available"},
                )

            judge_callback = reused_judge_callback
        else:
            judge_callback = fresh_judge_callback
        score = self.scoring.score(
            definition=definition,
            final_answer=final_answer,
            workspace=workspace,
            steps=int(run.get("steps") or 0),
            duration_ms=int(run.get("duration_ms") or 0),
            tokens_input=int(run.get("tokens_input") or 0),
            tokens_output=int(run.get("tokens_output") or 0),
            judge_callback=judge_callback,
            scoring_profile=run.get("scoring_profile") or "balanced-v2",
        )
        policy = definition.get("attempt_policy") or {}
        pass_threshold = float(policy.get("pass_threshold", 60.0))
        objective = next(
            (
                dimension.score
                for dimension in score.dimensions
                if dimension.validator_type == "objective_quality"
            ),
            score.score or 0,
        )
        critical_ok = True
        for validator_index, validator in enumerate(definition.get("validators") or []):
            validator_config = validator.get("config") or {}
            if not validator_config.get("critical"):
                continue
            related = [
                component
                for component in score.components
                if component.evidence.get("validator_index") == validator_index
            ]
            related_weight = sum(component.weight for component in related)
            related_score = (
                sum(component.score * component.weight for component in related)
                / related_weight
                if related_weight
                else 0
            )
            critical_ok = critical_ok and related_score >= float(
                validator_config.get("critical_min_score", 100)
            )
        passed = score.status == "scored" and objective >= pass_threshold and critical_ok
        attempt_row = self.database.fetch_one(
            "SELECT id,multiplier FROM run_attempts WHERE run_id=? "
            "ORDER BY attempt_no DESC LIMIT 1",
            (run_id,),
        )
        multiplier = float(attempt_row["multiplier"]) if attempt_row else 1.0
        adjusted_score = (
            round((score.score or 0) * multiplier, 2) if score.score is not None else None
        )
        result_payload = {
            "components": [item.as_dict() for item in score.components],
            "dimensions": [item.as_dict() for item in score.dimensions],
            "objective_score": objective,
            "pass_threshold": pass_threshold,
        }
        final_status = {
            "scored": "completed",
            "environment_unavailable": "environment_unavailable",
            "needs_review": "needs_review",
        }[score.status]
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM validator_results WHERE run_id=?", (run_id,))
            connection.execute("DELETE FROM score_components WHERE run_id=?", (run_id,))
        for component in score.components:
            self.database.execute(
                "INSERT INTO validator_results(id,run_id,validator_type,weight,score,status,"
                "evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    new_id(),
                    run_id,
                    component.validator_type,
                    component.weight,
                    component.score,
                    component.status,
                    json.dumps(component.evidence, ensure_ascii=False),
                    utc_now(),
                ),
            )
        for dimension in score.dimensions:
            self.database.execute(
                "INSERT INTO score_components(id,run_id,dimension,score,weight,evidence_json,"
                "created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    new_id(),
                    run_id,
                    dimension.validator_type,
                    dimension.score,
                    dimension.weight,
                    json.dumps(dimension.evidence, ensure_ascii=False),
                    utc_now(),
                ),
            )
        if attempt_row:
            self.database.execute(
                "UPDATE run_attempts SET raw_score=?,adjusted_score=?,passed=?,result_json=? "
                "WHERE id=?",
                (
                    score.score,
                    adjusted_score,
                    int(passed),
                    json.dumps(result_payload, ensure_ascii=False),
                    attempt_row["id"],
                ),
            )
        self.database.execute(
            "UPDATE runs SET status=?,score=?,passed=?,error_code=NULL,error_message=NULL,"
            "completed_at=? WHERE id=?",
            (final_status, adjusted_score, int(passed), utc_now(), run_id),
        )
        event_sink(
            "run.rejudged",
            {
                "status": final_status,
                "previous_score": previous_score,
                "score": adjusted_score,
                "raw_score": score.score,
                "passed": passed,
                "judge_mode": "reuse" if reuse_judge else "fresh",
            },
        )
        self.database.insert_audit(
            "run.rejudged",
            "run",
            run_id,
            {
                "status": final_status,
                "previous_score": previous_score,
                "score": adjusted_score,
                "judge_mode": "reuse" if reuse_judge else "fresh",
            },
        )
        self._refresh_experiment(run["experiment_id"])
        return self.get_run(run_id)

    def rejudge_experiment(
        self, experiment_id: str, *, scope: str = "structured"
    ) -> dict[str, Any]:
        """Batch-revalidate stored experiment answers with an auditable score delta."""
        before = self.get_experiment(experiment_id)
        rows = self.database.fetch_all(
            "SELECT id,status,final_answer FROM runs WHERE experiment_id=? ORDER BY created_at,id",
            (experiment_id,),
        )
        updated: list[dict[str, Any]] = []
        skipped = 0
        failures: list[dict[str, str]] = []
        for row in rows:
            if row["status"] not in {"needs_review", "completed"} or not (
                row.get("final_answer") or ""
            ).strip():
                skipped += 1
                continue
            run = self.get_run(row["id"])
            definition, _revision = self._definition_for_run(run)
            validators = definition.get("validators") or []
            if scope == "structured" and not any(
                validator.get("type") == "symbolic_json" for validator in validators
            ):
                skipped += 1
                continue
            old_score = run.get("score")
            try:
                result = self.rejudge_run(row["id"], reuse_judge=True)
                updated.append(
                    {
                        "run_id": row["id"],
                        "previous_score": old_score,
                        "score": result.get("score"),
                        "passed": result.get("passed"),
                    }
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                failures.append({"run_id": row["id"], "error": str(exc)})
        after = self.get_experiment(experiment_id)
        payload = {
            "experiment_id": experiment_id,
            "scope": scope,
            "updated": len(updated),
            "skipped": skipped,
            "failed": len(failures),
            "previous_score": (before.get("summary") or {}).get("avg_score"),
            "score": (after.get("summary") or {}).get("avg_score"),
            "previous_exam_score": (before.get("summary") or {}).get("exam_score"),
            "exam_score": (after.get("summary") or {}).get("exam_score"),
            "runs": updated,
            "failures": failures,
        }
        self.database.insert_audit(
            "experiment.rejudged", "experiment", experiment_id, payload
        )
        return payload

    def _run_with_semaphore(self, run_id: str, semaphore: threading.Semaphore) -> None:
        with semaphore:
            self._execute_run(run_id)

    def _execute_run(self, run_id: str) -> None:
        run = self.database.fetch_one("SELECT * FROM runs WHERE id=?", (run_id,))
        if not run or run["status"] not in {"queued", "interrupted"}:
            return
        cancel_event = threading.Event()
        with self._state_lock:
            self._cancel_events[run_id] = cancel_event
        seq = 0
        event_lock = threading.Lock()

        def event_sink(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal seq
            with event_lock:
                seq += 1
                self.database.execute(
                    "INSERT INTO run_events(run_id,seq,event_type,payload_json,created_at) VALUES (?,?,?,?,?)",
                    (run_id, seq, event_type, json.dumps(payload, ensure_ascii=False), utc_now()),
                )

        try:
            self.database.execute(
                "UPDATE runs SET status='preparing',started_at=?,completed_at=NULL WHERE id=?",
                (utc_now(), run_id),
            )
            model = self.get_model(run["model_id"])
            runner = self.database.fetch_one(
                "SELECT * FROM agent_runners WHERE id=?", (run["runner_id"],)
            )
            assert runner
            definition, revision = self._definition_for_run(run)
            event_sink(
                "run.started",
                {
                    "run_id": run_id,
                    "test_revision_id": revision.get("id"),
                    "test_version": revision.get("version"),
                    "definition_hash": revision.get("definition_hash"),
                    "scoring_profile": run.get("scoring_profile") or "balanced-v2",
                },
            )
            workspace_path = (self.settings.workspaces_dir / run_id).resolve()
            if not workspace_path.is_relative_to(self.settings.workspaces_dir.resolve()):
                raise RuntimeError("Invalid workspace path")
            if workspace_path.exists():
                shutil.rmtree(workspace_path)
            workspace = Workspace(workspace_path)
            workspace.seed(definition.get("initial_files") or {})
            self.database.execute(
                "UPDATE runs SET status='running',workspace_path=? WHERE id=?",
                (str(workspace.root), run_id),
            )
            event_sink(
                "run.environment_ready",
                {
                    "runner_type": runner["runner_type"],
                    "model": model["model_name"],
                    "tools": definition.get("tools") or [],
                },
            )
            policy = definition.get("attempt_policy") or {}
            max_attempts = min(3, max(1, int(policy.get("max_attempts", 1))))
            multipliers = [float(item) for item in policy.get("multipliers", [1.0, 0.85, 0.70])]
            while len(multipliers) < max_attempts:
                multipliers.append(max(0.1, multipliers[-1] - 0.15))
            hints = [str(item) for item in policy.get("hints", [])]
            pass_threshold = float(policy.get("pass_threshold", 60.0))
            cumulative_usage = self._empty_usage()
            cumulative_duration = 0
            cumulative_steps = 0
            score = None
            result = None
            adjusted_score: float | None = None
            passed = False
            previous_summary = ""
            for attempt_no in range(1, max_attempts + 1):
                attempt_instruction = self._attempt_instruction(
                    definition["instruction"], attempt_no, hints, previous_summary
                )
                attempt_definition = {**definition, "instruction": attempt_instruction}
                multiplier = multipliers[attempt_no - 1]
                attempt_id = new_id()
                attempt_started = utc_now()
                self.database.execute(
                    "INSERT INTO run_attempts(id,run_id,attempt_no,status,prompt,multiplier,created_at) "
                    "VALUES (?,?,?,'running',?,?,?)",
                    (attempt_id, run_id, attempt_no, attempt_instruction, multiplier, attempt_started),
                )
                event_sink(
                    "attempt.started",
                    {"attempt": attempt_no, "max_attempts": max_attempts, "multiplier": multiplier},
                )
                self.database.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))
                if runner["runner_type"] == "unified":
                    client = self._model_client(model, definition.get("metadata") or {})
                    limits = {
                        **_json(runner["limits_json"], {}),
                        **(definition.get("limits") or {}),
                    }
                    if "max_runtime_seconds" not in limits:
                        configured_watchdog = self.get_setting("default_max_runtime_seconds")
                        limits["max_runtime_seconds"] = (
                            7200 if configured_watchdog is None else configured_watchdog
                        )
                    harness = AgentHarness(
                        client=client,
                        workspace=workspace,
                        docker=self.docker,
                        allowed_capabilities=definition.get("tools") or [],
                        limits=limits,
                        system_prompt=runner["system_prompt"],
                        event_sink=event_sink,
                    )
                    result = harness.run(attempt_instruction)
                else:
                    result = self._run_native_agent(
                        runner, model, attempt_definition, workspace, event_sink, cancel_event
                    )
                cumulative_usage.add(result.usage)
                cumulative_duration += result.duration_ms
                cumulative_steps += result.steps
                cost, cost_source = self._usage_cost(model, cumulative_usage)
                attempt_cost, _ = self._usage_cost(model, result.usage)
                if cancel_event.is_set():
                    self.database.execute(
                        "UPDATE run_attempts SET status='cancelled',completed_at=? WHERE id=?",
                        (utc_now(), attempt_id),
                    )
                    self.database.execute(
                        "UPDATE runs SET status='cancelled',completed_at=? WHERE id=?",
                        (utc_now(), run_id),
                    )
                    event_sink("run.cancelled", {})
                    return
                if not result.ok:
                    infrastructure_failure = result.error_code in {
                        "runtime_safety_limit",
                        "cli_missing",
                        "cli_unavailable",
                        "native_cli_disabled",
                        "model_error",
                    }
                    self.database.execute(
                        "UPDATE run_attempts SET status=?,tokens_input=?,tokens_output=?,cost_usd=?,"
                        "duration_ms=?,steps=?,error_code=?,error_message=?,completed_at=? WHERE id=?",
                        (
                            "environment_unavailable" if infrastructure_failure else "failed",
                            result.usage.input_tokens,
                            result.usage.output_tokens,
                            attempt_cost,
                            result.duration_ms,
                            result.steps,
                            result.error_code,
                            result.error_message,
                            utc_now(),
                            attempt_id,
                        ),
                    )
                    terminal_status = "environment_unavailable" if infrastructure_failure else "failed"
                    self.database.execute(
                        "UPDATE runs SET status=?,final_answer=?,steps=?,tokens_input=?,tokens_output=?,"
                        "cost_usd=?,cost_source=?,duration_ms=?,attempt_count=?,passed=0,error_code=?,"
                        "error_message=?,completed_at=? WHERE id=?",
                        (
                            terminal_status,
                            result.final_answer,
                            cumulative_steps,
                            cumulative_usage.input_tokens,
                            cumulative_usage.output_tokens,
                            cost,
                            cost_source,
                            cumulative_duration,
                            attempt_no - 1 if infrastructure_failure else attempt_no,
                            result.error_code,
                            result.error_message,
                            utc_now(),
                            run_id,
                        ),
                    )
                    event_sink(
                        "run.failed",
                        {
                            "code": result.error_code,
                            "message": result.error_message,
                            "attempt_consumed": not infrastructure_failure,
                        },
                    )
                    return
                self.database.execute("UPDATE runs SET status='validating' WHERE id=?", (run_id,))
                event_sink("run.validating", {"attempt": attempt_no})
                judge_callback = self._judge_callback(
                    {**run, "final_answer": result.final_answer},
                    attempt_definition,
                    workspace,
                    event_sink,
                )
                score = self.scoring.score(
                    definition=attempt_definition,
                    final_answer=result.final_answer,
                    workspace=workspace,
                    steps=cumulative_steps,
                    duration_ms=cumulative_duration,
                    tokens_input=cumulative_usage.input_tokens,
                    tokens_output=cumulative_usage.output_tokens,
                    judge_callback=judge_callback,
                    scoring_profile=run.get("scoring_profile") or "balanced-v2",
                )
                if score.status == "environment_unavailable":
                    platform_component = next(
                        (
                            component
                            for component in score.components
                            if component.status == "environment_unavailable"
                        ),
                        None,
                    )
                    platform_evidence = platform_component.evidence if platform_component else {}
                    platform_code = str(
                        platform_evidence.get("error_code") or "validator_environment_unavailable"
                    )
                    platform_message = str(
                        platform_evidence.get("reason")
                        or platform_evidence.get("stderr")
                        or "评分验证环境不可用"
                    )[:2000]
                    self.database.execute(
                        "UPDATE run_attempts SET status='environment_unavailable',tokens_input=?,"
                        "tokens_output=?,cost_usd=?,duration_ms=?,steps=?,error_code=?,error_message=?,"
                        "result_json=?,completed_at=? WHERE id=?",
                        (
                            result.usage.input_tokens,
                            result.usage.output_tokens,
                            attempt_cost,
                            result.duration_ms,
                            result.steps,
                            platform_code,
                            platform_message,
                            json.dumps(
                                {"components": [item.as_dict() for item in score.components]},
                                ensure_ascii=False,
                            ),
                            utc_now(),
                            attempt_id,
                        ),
                    )
                    self.database.execute(
                        "UPDATE runs SET status='environment_unavailable',final_answer=?,steps=?,"
                        "tokens_input=?,tokens_output=?,cost_usd=?,cost_source=?,duration_ms=?,"
                        "attempt_count=?,passed=0,error_code=?,error_message=?,completed_at=? WHERE id=?",
                        (
                            result.final_answer,
                            cumulative_steps,
                            cumulative_usage.input_tokens,
                            cumulative_usage.output_tokens,
                            cost,
                            cost_source,
                            cumulative_duration,
                            attempt_no - 1,
                            platform_code,
                            platform_message,
                            utc_now(),
                            run_id,
                        ),
                    )
                    event_sink(
                        "run.failed",
                        {
                            "code": platform_code,
                            "message": platform_message,
                            "attempt_consumed": False,
                            "phase": "validation",
                        },
                    )
                    return
                objective = next(
                    (
                        dimension.score
                        for dimension in score.dimensions
                        if dimension.validator_type == "objective_quality"
                    ),
                    score.score or 0,
                )
                critical_ok = True
                for validator_index, validator in enumerate(
                    attempt_definition.get("validators") or []
                ):
                    validator_config = validator.get("config") or {}
                    if not validator_config.get("critical"):
                        continue
                    related = [
                        component
                        for component in score.components
                        if component.evidence.get("validator_index") == validator_index
                    ]
                    related_weight = sum(component.weight for component in related)
                    related_score = (
                        sum(component.score * component.weight for component in related)
                        / related_weight
                        if related_weight
                        else 0
                    )
                    critical_ok = critical_ok and related_score >= float(
                        validator_config.get("critical_min_score", 100)
                    )
                passed = score.status == "scored" and objective >= pass_threshold and critical_ok
                adjusted_score = (
                    round((score.score or 0) * multiplier, 2) if score.score is not None else None
                )
                result_payload = {
                    "components": [item.as_dict() for item in score.components],
                    "dimensions": [item.as_dict() for item in score.dimensions],
                    "objective_score": objective,
                    "pass_threshold": pass_threshold,
                }
                self.database.execute(
                    "UPDATE run_attempts SET status='completed',raw_score=?,adjusted_score=?,passed=?,"
                    "tokens_input=?,tokens_output=?,cost_usd=?,duration_ms=?,steps=?,result_json=?,"
                    "completed_at=? WHERE id=?",
                    (
                        score.score,
                        adjusted_score,
                        int(passed),
                        result.usage.input_tokens,
                        result.usage.output_tokens,
                        attempt_cost,
                        result.duration_ms,
                        result.steps,
                        json.dumps(result_payload, ensure_ascii=False),
                        utc_now(),
                        attempt_id,
                    ),
                )
                event_sink(
                    "attempt.completed",
                    {
                        "attempt": attempt_no,
                        "raw_score": score.score,
                        "adjusted_score": adjusted_score,
                        "passed": passed,
                    },
                )
                if passed or attempt_no == max_attempts or score.status != "scored":
                    break
                previous_summary = self._attempt_feedback(score)
                event_sink(
                    "attempt.retry_scheduled",
                    {"next_attempt": attempt_no + 1, "feedback": previous_summary},
                )
            assert score is not None and result is not None
            cost, cost_source = self._usage_cost(model, cumulative_usage)
            for component in score.components:
                self.database.execute(
                    "INSERT INTO validator_results(id,run_id,validator_type,weight,score,status,"
                    "evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        new_id(),
                        run_id,
                        component.validator_type,
                        component.weight,
                        component.score,
                        component.status,
                        json.dumps(component.evidence, ensure_ascii=False),
                        utc_now(),
                    ),
                )
                event_sink("validator.completed", component.as_dict())
            for dimension in score.dimensions:
                self.database.execute(
                    "INSERT INTO score_components(id,run_id,dimension,score,weight,evidence_json,"
                    "created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        new_id(),
                        run_id,
                        dimension.validator_type,
                        dimension.score,
                        dimension.weight,
                        json.dumps(dimension.evidence, ensure_ascii=False),
                        utc_now(),
                    ),
                )
            final_status = {
                "scored": "completed",
                "environment_unavailable": "environment_unavailable",
                "needs_review": "needs_review",
            }[score.status]
            self._record_artifacts(run_id, workspace, event_sink)
            self.database.execute(
                "UPDATE runs SET status=?,final_answer=?,score=?,steps=?,tokens_input=?,tokens_output=?,"
                "cost_usd=?,cost_source=?,duration_ms=?,attempt_count=?,passed=?,error_code=NULL,"
                "error_message=NULL,completed_at=? WHERE id=?",
                (
                    final_status,
                    result.final_answer,
                    adjusted_score,
                    cumulative_steps,
                    cumulative_usage.input_tokens,
                    cumulative_usage.output_tokens,
                    cost,
                    cost_source,
                    cumulative_duration,
                    attempt_no,
                    int(passed),
                    utc_now(),
                    run_id,
                ),
            )
            event_sink(
                "run.completed",
                {
                    "status": final_status,
                    "score": adjusted_score,
                    "raw_score": score.score,
                    "attempts": attempt_no,
                    "passed": passed,
                },
            )
        except Exception as exc:  # the worker must persist every terminal failure
            logger.exception("Run %s failed", run_id)
            self.database.execute(
                "UPDATE runs SET status='failed',error_code='internal_error',error_message=?,"
                "completed_at=? WHERE id=?",
                (str(exc)[:2000], utc_now(), run_id),
            )
            try:
                event_sink("run.failed", {"code": "internal_error", "message": str(exc)[:2000]})
            except Exception:
                logger.exception("Could not persist failure event for %s", run_id)
        finally:
            with self._state_lock:
                self._cancel_events.pop(run_id, None)
            if run:
                self._refresh_experiment(run["experiment_id"])

    @staticmethod
    def _attempt_instruction(
        base_instruction: str,
        attempt_no: int,
        hints: list[str],
        previous_summary: str,
    ) -> str:
        if attempt_no <= 1:
            return base_instruction
        hint = hints[attempt_no - 2] if attempt_no - 2 < len(hints) else ""
        sections = [base_instruction, f"\n\nULTRA ATTEMPT {attempt_no}/3"]
        if previous_summary:
            sections.append(
                "上一轮只提供以下验证维度摘要，不包含隐藏答案：\n" + previous_summary
            )
        if hint:
            sections.append("本轮标准提示：\n" + hint)
        sections.append("保留并检查当前工作区中的上一轮成果，继续修复后重新验证。")
        return "\n\n".join(sections)

    @staticmethod
    def _attempt_feedback(score) -> str:
        lines = []
        for component in score.components:
            if component.validator_type in {
                "time_efficiency",
                "step_efficiency",
                "token_efficiency",
            }:
                continue
            lines.append(
                f"- {component.validator_type}: {component.score:.1f}/100 ({component.status})"
            )
        return "\n".join(lines[:20])

    @staticmethod
    def _usage_cost(model: dict[str, Any], usage) -> tuple[float, str]:
        if usage.reported_cost_usd is not None:
            return round(max(0.0, float(usage.reported_cost_usd)), 8), "reported"
        total_tokens = usage.input_tokens + usage.output_tokens
        input_price = float(model.get("input_price") or 0)
        output_price = float(model.get("output_price") or 0)
        if total_tokens <= 0:
            return 0.0, "unavailable"
        if input_price <= 0 and output_price <= 0:
            return 0.0, "unpriced"
        return (
            round(
                (
                    usage.input_tokens * input_price
                    + usage.output_tokens * output_price
                )
                / 1_000_000,
                8,
            ),
            "configured",
        )

    def _run_native_agent(
        self,
        runner: dict[str, Any],
        model: dict[str, Any],
        definition: dict[str, Any],
        workspace: Workspace,
        event_sink,
        cancel_event: threading.Event,
    ) -> AgentResult:
        if not self._native_cli_allowed():
            return AgentResult(
                False,
                "",
                0,
                self._empty_usage(),
                0,
                "native_cli_disabled",
                "Native CLI Agents require explicit enablement in Settings",
            )
        executable = runner.get("executable")
        if not executable:
            return AgentResult(
                False, "", 0, self._empty_usage(), 0, "cli_missing", "No executable configured"
            )
        if (definition.get("metadata") or {}).get("connection_test"):
            prompt = str(definition["instruction"])
        else:
            prompt = (
                "You are participating in an AgentBench task. Work only in the current workspace. "
                "Do not reveal private chain-of-thought. Complete the task, verify the result, and "
                f"give a concise final summary.\n\nTASK:\n{definition['instruction']}"
            )
        runner_limits = _json(runner.get("limits_json"), {})
        definition_limits = definition.get("limits") or {}
        args = _json(runner.get("args_json"), [])
        model_settings = _json(model.get("settings_json"), {})
        if model.get("model_name") in {"auto", "default"} and "--model" in args:
            model_index = args.index("--model")
            del args[model_index : model_index + 2]
        if (
            runner["runner_type"] == "codex_cli"
            and model.get("provider") == "codex-cli"
            and model_settings.get("agent_provider")
        ):
            provider_override = json.dumps(
                str(model_settings["agent_provider"]), ensure_ascii=False
            )
            insertion_index = 1 if args and args[0] == "exec" else 0
            args[insertion_index:insertion_index] = [
                "-c",
                f"model_provider={provider_override}",
            ]
        placeholders = {
            "model_name": model["model_name"],
            "prompt": prompt,
            "workspace": str(workspace.root),
        }
        event_sink(
            "native_cli.started", {"runner_type": runner["runner_type"], "executable": executable}
        )
        live_line_count = 0
        live_lock = threading.Lock()

        def workspace_state() -> dict[str, tuple[int, int]]:
            state: dict[str, tuple[int, int]] = {}
            for relative in workspace.list_files(max_items=500):
                target = workspace.root / relative
                with suppress(OSError):
                    stat = target.stat()
                    state[relative] = (int(stat.st_size), int(stat.st_mtime_ns))
            return state

        previous_workspace_state = workspace_state()

        def line_callback(stream_name: str, line: str) -> None:
            nonlocal live_line_count
            with live_lock:
                live_line_count += 1
                line_no = live_line_count
            normalized = self._normalize_native_live_event(
                runner["runner_type"], stream_name, line, line_no
            )
            if normalized is not None:
                event_sink(*normalized)

        def heartbeat_callback(elapsed_ms: int) -> None:
            nonlocal previous_workspace_state
            current_state = workspace_state()
            changes: list[dict[str, Any]] = []
            for path, (size, modified) in current_state.items():
                previous = previous_workspace_state.get(path)
                if previous is None:
                    changes.append({"path": path, "change": "created", "size": size})
                elif previous != (size, modified):
                    changes.append(
                        {
                            "path": path,
                            "change": "modified",
                            "size": size,
                            "size_delta": size - previous[0],
                        }
                    )
            for path in previous_workspace_state.keys() - current_state.keys():
                changes.append({"path": path, "change": "deleted", "size": 0})
            previous_workspace_state = current_state
            for change in changes[:25]:
                event_sink("live.file_change", change)
            event_sink(
                "live.heartbeat",
                {
                    "elapsed_ms": elapsed_ms,
                    "line_count": live_line_count,
                    "workspace_files": len(current_state),
                    "changes": len(changes),
                },
            )

        command_result = run_native_cli(
            executable=executable,
            args=args,
            workspace=workspace,
            placeholders=placeholders,
            extra_env=_json(runner.get("env_json"), {}),
            timeout=int(
                definition_limits.get(
                    "max_runtime_seconds",
                    runner_limits.get(
                        "max_runtime_seconds",
                        self.get_setting("default_max_runtime_seconds")
                        if self.get_setting("default_max_runtime_seconds") is not None
                        else 7200,
                    ),
                )
            ),
            cancel_event=cancel_event,
            line_callback=line_callback,
            heartbeat_callback=heartbeat_callback,
        )
        heartbeat_callback(command_result.duration_ms)
        final_answer, input_tokens, output_tokens, reported_cost, event_count = self._parse_native_output(
            runner["runner_type"], command_result.stdout, None
        )
        usage = self._empty_usage()
        usage.input_tokens = input_tokens
        usage.output_tokens = output_tokens
        usage.reported_cost_usd = reported_cost
        return AgentResult(
            command_result.ok,
            final_answer or command_result.stdout[-20_000:],
            max(1, event_count),
            usage,
            command_result.duration_ms,
            command_result.error_code,
            (
                command_result.stderr[-2000:]
                or command_result.stdout[-2000:]
                or command_result.error_code
            )
            if not command_result.ok
            else None,
        )

    @staticmethod
    def _normalize_native_live_event(
        runner_type: str, stream_name: str, raw_line: str, line_no: int
    ) -> tuple[str, dict[str, Any]] | None:
        line = raw_line.strip()
        if not line:
            return None
        base: dict[str, Any] = {
            "runner_type": runner_type,
            "stream": stream_name,
            "line_no": line_no,
        }
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            lower = line.lower()
            if any(marker in lower for marker in ("pytest", "vitest", "jest", "cargo test")):
                return "live.test", {
                    **base,
                    "status": "running",
                    "summary": "Agent 正在运行公开测试",
                    "detail": _redact_viewer_text(line, 700),
                }
            if line.startswith(("$ ", "> ")):
                return "live.command", {
                    **base,
                    "status": "running",
                    "command": _redact_viewer_text(line[2:], 700),
                }
            return "live.activity", {
                **base,
                "summary": "Agent 持续处理任务",
                "detail": f"{stream_name} 产生 {len(raw_line)} 个字符的已过滤输出",
            }
        if not isinstance(item, dict):
            return "live.activity", {**base, "summary": "Agent 产生结构化进度事件"}

        nested = item.get("item") if isinstance(item.get("item"), dict) else {}
        part = item.get("part") if isinstance(item.get("part"), dict) else {}
        message = item.get("message") if isinstance(item.get("message"), dict) else {}
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        sources = [item, nested, part, *[block for block in blocks if isinstance(block, dict)]]
        kind = str(
            item.get("type")
            or nested.get("type")
            or part.get("type")
            or "activity"
        )
        base["source_type"] = kind

        usage = (
            item.get("usage")
            or (item.get("turn") or {}).get("usage")
            or (part.get("tokens") if isinstance(part, dict) else None)
            or {}
        )
        if isinstance(usage, dict) and usage:
            base["usage"] = {
                "input_tokens": int(usage.get("input_tokens", usage.get("input", 0)) or 0),
                "output_tokens": int(usage.get("output_tokens", usage.get("output", 0)) or 0)
                + int(usage.get("reasoning", 0) or 0),
            }

        def first_value(*names: str) -> Any:
            for source in sources:
                for name in names:
                    value = source.get(name)
                    if value not in (None, "", [], {}):
                        return value
            return None

        tool_name = first_value("tool_name", "name")
        tool_input = first_value("input", "arguments", "args")
        command = first_value("command", "cmd")
        if not command and isinstance(tool_input, dict):
            command = tool_input.get("command") or tool_input.get("cmd")
        path = first_value("path", "file_path", "filename")
        if not path and isinstance(tool_input, dict):
            path = tool_input.get("path") or tool_input.get("file_path")
        output = first_value("aggregated_output", "stdout", "result")
        descriptor = " ".join(
            str(value).lower()
            for value in (kind, tool_name, command)
            if value not in (None, "")
        )

        if command:
            safe_command = _redact_viewer_text(str(command), 900)
            if any(marker in descriptor for marker in ("pytest", "vitest", "jest", "cargo test", "test")):
                return "live.test", {
                    **base,
                    "status": first_value("status") or "running",
                    "command": safe_command,
                    "detail": _redact_viewer_text(str(output), 800) if output else "公开测试正在执行",
                }
            return "live.command", {
                **base,
                "status": first_value("status") or "running",
                "command": safe_command,
                "exit_code": first_value("exit_code"),
                "detail": _redact_viewer_text(str(output), 800) if output else None,
            }
        if path or any(marker in descriptor for marker in ("write", "edit", "patch", "file")):
            return "live.file_change", {
                **base,
                "path": _redact_viewer_text(str(path or "工作区文件"), 500),
                "change": "modified",
                "tool": _redact_viewer_text(str(tool_name or kind), 160),
            }
        if tool_name or "tool" in descriptor:
            detail = ""
            if isinstance(tool_input, dict):
                visible = {
                    key: value
                    for key, value in tool_input.items()
                    if key.lower() in {"path", "file_path", "query", "pattern", "status"}
                }
                detail = json.dumps(_viewer_safe_value(visible), ensure_ascii=False)
            return "live.tool", {
                **base,
                "tool": _redact_viewer_text(str(tool_name or kind), 160),
                "status": first_value("status") or "running",
                "detail": detail,
            }
        if kind in {"result", "turn.completed", "step_finish", "step-finish"}:
            return "live.phase", {
                **base,
                "phase": "agent_result",
                "summary": "Agent 已提交本阶段结果",
                "status": first_value("status") or "completed",
            }
        return "live.activity", {
            **base,
            "summary": "Agent 产生新的可验证进度",
            "kind": kind,
        }

    @staticmethod
    def _empty_usage():
        from .model_clients import ModelUsage

        return ModelUsage()

    @staticmethod
    def _parse_native_output(
        runner_type: str, output: str, event_sink=None
    ) -> tuple[str, int, int, float | None, int]:
        final = ""
        input_tokens = 0
        output_tokens = 0
        reported_cost: float | None = None
        count = 0
        for raw_line in output.splitlines():
            if not raw_line.strip():
                continue
            try:
                item = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            count += 1
            if event_sink is not None:
                event_sink("native_cli.event", {"runner_type": runner_type, "event": item})
            if item.get("type") == "result" and isinstance(item.get("result"), str):
                final = item["result"]
            if item.get("type") in {"text", "assistant", "message", "output"}:
                candidate = item.get("text") or item.get("content") or item.get("output")
                if isinstance(candidate, str):
                    final = candidate
            nested = item.get("item") or {}
            if nested.get("type") in {"agent_message", "message"}:
                final = str(nested.get("text") or nested.get("content") or final)
            part = item.get("part") or {}
            if isinstance(part, dict) and part.get("type") in {"text", "assistant_text"}:
                final = str(part.get("text") or part.get("content") or final)
            response = item.get("response") or {}
            if isinstance(response, dict):
                final = str(response.get("output_text") or response.get("text") or final)
            message = item.get("message") or {}
            blocks = message.get("content") if isinstance(message, dict) else None
            if isinstance(blocks, list):
                text_blocks = [
                    block.get("text", "") for block in blocks if block.get("type") == "text"
                ]
                if text_blocks:
                    final = "\n".join(text_blocks)
            usage = (
                item.get("usage")
                or (item.get("turn") or {}).get("usage")
                or (part.get("tokens") if isinstance(part, dict) else None)
                or {}
            )
            input_value = int(usage.get("input_tokens", usage.get("input", 0)) or 0)
            output_value = int(usage.get("output_tokens", usage.get("output", 0)) or 0)
            if "output_tokens" not in usage:
                output_value += int(usage.get("reasoning", 0) or 0)
            is_incremental = item.get("type") in {"step_finish", "step-finish"}
            if is_incremental:
                input_tokens += input_value
                output_tokens += output_value
            else:
                input_tokens = max(input_tokens, input_value)
                output_tokens = max(output_tokens, output_value)
            raw_cost = (
                item.get("total_cost_usd")
                or item.get("cost_usd")
                or item.get("costUSD")
                or (usage.get("cost_usd") if isinstance(usage, dict) else None)
            )
            if raw_cost is not None:
                with suppress(TypeError, ValueError):
                    reported_cost = max(reported_cost or 0.0, float(raw_cost))
        return final, input_tokens, output_tokens, reported_cost, count

    def _model_client(self, model: dict[str, Any], metadata: dict[str, Any]) -> ModelClient:
        style = model["api_style"]
        settings = _json(model.get("settings_json"), {})
        if style == "mock":
            return MockModelClient(metadata)
        api_key = self.secrets.get(model.get("credential_ref"))
        if style == "anthropic":
            return AnthropicClient(
                base_url=model.get("base_url") or "https://api.anthropic.com",
                api_key=api_key,
                model_name=model["model_name"],
                max_tokens=int(settings.get("max_tokens", 4096)),
            )
        return OpenAICompatibleClient(
            base_url=model.get("base_url") or "https://api.openai.com/v1",
            api_key=api_key,
            model_name=model["model_name"],
            temperature=float(settings.get("temperature", 0)),
            max_tokens=int(settings.get("max_tokens", 4096)),
        )

    # Long judge prompts are sent via stdin (and mirrored into judge_prompt.md) because
    # Windows cmd.exe truncates/drops .cmd command lines beyond 8191 characters. The
    # {prompt} placeholder therefore renders to this short guidance only, which keeps
    # existing runner configurations (args containing {prompt}) fully compatible.
    JUDGE_STDIN_GUIDANCE = (
        "完整评审任务已通过标准输入(stdin)提供，并同步保存在当前工作区的 judge_prompt.md 文件中。"
        "请阅读该评审任务，并严格按照其中的要求只输出一个JSON对象"
        "（键为 score, summary, strengths, weaknesses, evidence），不要输出任何其他内容。"
    )

    def _single_judge_callback(
        self,
        run,
        definition,
        workspace,
        event_sink,
        *,
        judge_model_id=None,
        judge_runner_id=None,
        anonymous_slot: str = "primary",
    ):
        rubric_validators = [
            item for item in definition.get("validators") or [] if item.get("type") == "ai_rubric"
        ]
        if not rubric_validators:
            return None
        judge_model_id = judge_model_id or self.get_setting("judge_model_id")
        judge_runner_id = judge_runner_id or self.get_setting("judge_runner_id")
        if not judge_model_id or not judge_runner_id or judge_model_id == run["model_id"]:
            return None

        def callback(config: dict[str, Any], weight: float) -> ValidationResult:
            model = self.get_model(str(judge_model_id))
            runner = self.database.fetch_one(
                "SELECT * FROM agent_runners WHERE id=?", (judge_runner_id,)
            )
            if not runner:
                return ValidationResult(
                    "ai_rubric", weight, 0, "needs_review", {"reason": "Judge runner not found"}
                )
            files = workspace.list_files()[:50]
            file_samples: dict[str, str] = {}
            sample_budget = 50_000
            for path in files[:20]:
                if sample_budget <= 0:
                    break
                try:
                    sample = workspace.read_file(path, min(4_000, sample_budget))
                except OSError:
                    continue
                file_samples[path] = sample
                sample_budget -= len(sample)
            prompt = (
                "You are an anonymous evaluator. The candidate identity is intentionally hidden. "
                "Score the result from 0 to 100 using the rubric. Return strict JSON with keys "
                "score, summary, strengths, weaknesses, evidence.\n\n"
                f"TASK:\n{definition['instruction']}\n\nRUBRIC:\n{json.dumps(config, ensure_ascii=False)}\n\n"
                f"FINAL ANSWER:\n{run.get('final_answer') or ''}\n\n"
                f"WORKSPACE FILE SAMPLES:\n{json.dumps(file_samples, ensure_ascii=False)}"
            )
            def invoke(cli_capture: dict[str, Any]) -> str:
                if runner["runner_type"] == "unified":
                    decision = self._model_client(model, {}).complete(
                        [
                            {"role": "system", "content": "Return strict JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                        [],
                    )
                    return decision.content
                if not self._native_cli_allowed() or not runner.get("executable"):
                    raise ValueError("Native judge Agent is disabled or unavailable")
                judge_workspace_path = (
                    self.settings.workspaces_dir / f"judge-{run['id']}-{new_id()}"
                ).resolve()
                shutil.copytree(workspace.root, judge_workspace_path)
                try:
                    judge_workspace = Workspace(judge_workspace_path)
                    # Fallback channel for CLIs that ignore stdin.
                    judge_workspace.write_file("judge_prompt.md", prompt)
                    judge_result = run_native_cli(
                        executable=runner["executable"],
                        args=_json(runner.get("args_json"), []),
                        workspace=judge_workspace,
                        placeholders={
                            "model_name": model["model_name"],
                            "prompt": self.JUDGE_STDIN_GUIDANCE,
                            "workspace": str(judge_workspace.root),
                        },
                        extra_env=_json(runner.get("env_json"), {}),
                        timeout=min(
                            int(
                                _json(runner.get("limits_json"), {}).get("timeout_seconds", 900)
                            ),
                            1800,
                        ),
                        stdin_text=prompt,
                    )
                    cli_capture["judge_cli_stdout"] = judge_result.stdout[-20_000:]
                    cli_capture["judge_cli_stderr"] = judge_result.stderr[-20_000:]
                    if not judge_result.ok:
                        raise ValueError(
                            judge_result.stderr
                            or judge_result.error_code
                            or "Judge Agent failed"
                        )
                    response_text, _, _, _, _ = self._parse_native_output(
                        runner["runner_type"], judge_result.stdout, event_sink
                    )
                    if not response_text:
                        response_text = judge_result.stdout
                    return response_text
                finally:
                    shutil.rmtree(judge_workspace_path, ignore_errors=True)

            cli_capture: dict[str, Any] = {}
            failure_evidence: dict[str, Any] = {
                "reason": "Judge invocation failed",
                "anonymous_slot": anonymous_slot,
            }
            for attempt in range(2):  # judge failures are retried once
                try:
                    if attempt == 0:
                        self.database.execute(
                            "UPDATE runs SET status='judging' WHERE id=?", (run["id"],)
                        )
                        event_sink("run.judging", {"anonymous_slot": anonymous_slot})
                    response_text = invoke(cli_capture)
                    data = self._parse_json_object(response_text)
                    score = min(100.0, max(0.0, float(data["score"])))
                except (ModelClientError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    failure_evidence = {
                        "reason": str(exc),
                        "judge_attempts": attempt + 1,
                        "anonymous_slot": anonymous_slot,
                        **cli_capture,
                    }
                    continue
                data = {**data, "anonymous_slot": anonymous_slot}
                event_sink(
                    "judge.completed",
                    {"score": score, "anonymous_slot": anonymous_slot, "evidence": data},
                )
                self.database.execute(
                    "INSERT INTO judge_reviews(id,run_id,judge_model_id,judge_runner_id,score,"
                    "status,evidence_json,created_at) VALUES (?,?,?,?,?,'completed',?,?)",
                    (
                        new_id(),
                        run["id"],
                        judge_model_id,
                        judge_runner_id,
                        score,
                        json.dumps(data, ensure_ascii=False),
                        utc_now(),
                    ),
                )
                return ValidationResult("ai_rubric", weight, score, "passed", data)
            return ValidationResult("ai_rubric", weight, 0, "needs_review", failure_evidence)

        return callback

    def _judge_callback(self, run, definition, workspace, event_sink):
        primary = self._single_judge_callback(
            run,
            definition,
            workspace,
            event_sink,
            anonymous_slot="primary",
        )
        if primary is None:
            return None
        secondary_model_id = self.get_setting("judge_model_id_secondary")
        secondary_runner_id = self.get_setting("judge_runner_id_secondary")
        secondary = None
        if (
            secondary_model_id
            and secondary_runner_id
            and secondary_model_id != run["model_id"]
        ):
            secondary = self._single_judge_callback(
                run,
                definition,
                workspace,
                event_sink,
                judge_model_id=secondary_model_id,
                judge_runner_id=secondary_runner_id,
                anonymous_slot="secondary",
            )
        tiebreaker_model_id = self.get_setting("judge_model_id_tiebreaker")
        tiebreaker_runner_id = self.get_setting("judge_runner_id_tiebreaker")
        tiebreaker = None
        if (
            tiebreaker_model_id
            and tiebreaker_runner_id
            and tiebreaker_model_id != run["model_id"]
        ):
            tiebreaker = self._single_judge_callback(
                run,
                definition,
                workspace,
                event_sink,
                judge_model_id=tiebreaker_model_id,
                judge_runner_id=tiebreaker_runner_id,
                anonymous_slot="tiebreaker",
            )
        threshold_setting = self.get_setting("judge_disagreement_threshold")
        disagreement_threshold = float(
            12.0 if threshold_setting is None else threshold_setting
        )

        def callback(config: dict[str, Any], weight: float) -> ValidationResult:
            first = primary(config, weight)
            if first.status != "passed" or secondary is None:
                return first
            second = secondary(config, weight)
            if second.status != "passed":
                return ValidationResult(
                    "ai_rubric",
                    weight,
                    0,
                    "needs_review",
                    {
                        "reason": "Secondary anonymous judge did not return a valid review",
                        "reviews": [first.evidence, second.evidence],
                    },
                )
            difference = abs(first.score - second.score)
            reviews = [first, second]
            if difference > disagreement_threshold:
                if tiebreaker is None:
                    event_sink(
                        "judge.disagreement",
                        {
                            "difference": round(difference, 2),
                            "threshold": disagreement_threshold,
                            "status": "needs_review",
                        },
                    )
                    return ValidationResult(
                        "ai_rubric",
                        weight,
                        0,
                        "needs_review",
                        {
                            "reason": "Anonymous judge disagreement exceeds threshold",
                            "difference": round(difference, 2),
                            "threshold": disagreement_threshold,
                            "reviews": [item.evidence for item in reviews],
                        },
                    )
                third = tiebreaker(config, weight)
                if third.status != "passed":
                    return ValidationResult(
                        "ai_rubric",
                        weight,
                        0,
                        "needs_review",
                        {
                            "reason": "Tiebreaker judge did not return a valid review",
                            "reviews": [first.evidence, second.evidence, third.evidence],
                        },
                    )
                reviews.append(third)
            consensus_score = statistics.median(item.score for item in reviews)
            evidence = {
                "summary": "Anonymous multi-judge consensus",
                "judge_count": len(reviews),
                "scores": [round(item.score, 2) for item in reviews],
                "spread": round(max(item.score for item in reviews) - min(item.score for item in reviews), 2),
                "disagreement_threshold": disagreement_threshold,
                "reviews": [item.evidence for item in reviews],
            }
            event_sink(
                "judge.consensus",
                {"score": round(consensus_score, 2), "judge_count": len(reviews)},
            )
            return ValidationResult(
                "ai_rubric", weight, round(consensus_score, 2), "passed", evidence
            )

        return callback

    @staticmethod
    def _parse_json_object(value: str) -> dict[str, Any]:
        text = value.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise
            parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("Judge output must be a JSON object")
        return parsed

    def _record_artifacts(self, run_id: str, workspace: Workspace, event_sink) -> None:
        for item in workspace.changed_files():
            self.database.execute(
                "INSERT INTO artifacts(id,run_id,kind,name,path,size,sha256,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    new_id(),
                    run_id,
                    "workspace_file",
                    Path(item["path"]).name,
                    item["path"],
                    item["size"],
                    item["sha256"],
                    utc_now(),
                ),
            )
            event_sink("artifact.created", item)

    def _refresh_experiment(self, experiment_id: str) -> None:
        summary = self.database.fetch_one(
            "SELECT COUNT(*) total,SUM(CASE WHEN status IN ('queued','preparing','running','validating',"
            "'judging') THEN 1 ELSE 0 END) active FROM runs WHERE experiment_id=?",
            (experiment_id,),
        )
        if summary and summary["total"] and not summary["active"]:
            current = self.database.fetch_one(
                "SELECT status FROM experiments WHERE id=?", (experiment_id,)
            )
            if current and current["status"] != "cancelled":
                self.database.execute(
                    "UPDATE experiments SET status='completed',completed_at=? WHERE id=?",
                    (utc_now(), experiment_id),
                )

    def _native_cli_allowed(self) -> bool:
        configured = self.get_setting("allow_native_cli")
        return self.settings.allow_native_cli or configured is True

    # Settings, analytics, reports
    def get_setting(self, key: str) -> Any:
        row = self.database.fetch_one("SELECT value_json FROM app_settings WHERE key=?", (key,))
        return _json(row["value_json"], None) if row else None

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        for key, value in values.items():
            self.database.execute(
                "INSERT INTO app_settings(key,value_json,updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                (key, json.dumps(value), utc_now()),
            )
        self.database.insert_audit("settings.updated", detail={"keys": list(values)})
        return self.system_status()

    def system_status(self) -> dict[str, Any]:
        runners = self.list_runners()
        return {
            "version": __version__,
            "data_dir": str(self.settings.data_dir),
            "workspaces_dir": str(self.settings.workspaces_dir),
            "database": {
                "path": str(self.settings.database_path),
                "ready": self.settings.database_path.exists(),
            },
            "docker": self.docker.status(),
            "native_cli_enabled": self._native_cli_allowed(),
            "settings": {
                "judge_model_id": self.get_setting("judge_model_id"),
                "judge_runner_id": self.get_setting("judge_runner_id"),
                "judge_model_id_secondary": self.get_setting("judge_model_id_secondary"),
                "judge_runner_id_secondary": self.get_setting("judge_runner_id_secondary"),
                "judge_model_id_tiebreaker": self.get_setting("judge_model_id_tiebreaker"),
                "judge_runner_id_tiebreaker": self.get_setting("judge_runner_id_tiebreaker"),
                "judge_disagreement_threshold": (
                    12.0
                    if self.get_setting("judge_disagreement_threshold") is None
                    else self.get_setting("judge_disagreement_threshold")
                ),
                "default_concurrency": self.get_setting("default_concurrency") or 2,
                "default_max_runtime_seconds": (
                    7200
                    if self.get_setting("default_max_runtime_seconds") is None
                    else self.get_setting("default_max_runtime_seconds")
                ),
            },
            "runners": [
                {"id": r["id"], "name": r["name"], "capability": r["capability"]} for r in runners
            ],
        }

    def dashboard(self) -> dict[str, Any]:
        stats = (
            self.database.fetch_one(
                "SELECT COUNT(*) total_runs,COALESCE(SUM(CASE WHEN status='running' THEN 1 ELSE 0 END),0) active_runs,"
                "AVG(score) avg_score,SUM(cost_usd) total_cost,SUM(tokens_input+tokens_output) total_tokens,"
                "COALESCE(SUM(CASE WHEN cost_source='unpriced' THEN 1 ELSE 0 END),0) unpriced_runs "
                "FROM runs"
            )
            or {}
        )
        stats["models"] = (
            self.database.fetch_one("SELECT COUNT(*) count FROM models WHERE enabled=1") or {}
        ).get("count", 0)
        stats["test_cases"] = (
            self.database.fetch_one("SELECT COUNT(*) count FROM test_cases WHERE enabled=1") or {}
        ).get("count", 0)
        stats["recent_experiments"] = self.list_experiments(6)
        stats["categories"] = self.database.fetch_all(
            "SELECT category,COUNT(*) count FROM test_cases WHERE enabled=1 GROUP BY category ORDER BY category"
        )
        return stats

    def leaderboard(
        self,
        lane: str = "unified",
        suite_id: str | None = None,
        benchmark_generation: str = "v3",
    ) -> list[dict[str, Any]]:
        clauses = ["r.lane=?", "r.status='completed'", "t.enabled=1"]
        params: list[Any] = [lane]
        if benchmark_generation != "all":
            clauses.append("e.benchmark_generation=?")
            params.append(benchmark_generation)
        if suite_id:
            clauses.append("e.suite_id=?")
            params.append(suite_id)
        return self.database.fetch_all(
            "SELECT r.model_id,r.runner_id,m.name AS model_name,a.name AS runner_name,r.lane,"
            "COUNT(*) AS runs,AVG(r.score) AS avg_score,"
            "AVG((SELECT sc.score FROM score_components sc WHERE sc.run_id=r.id "
            "AND sc.dimension='objective_quality' LIMIT 1)) AS avg_objective_score,"
            "AVG((SELECT sc.score FROM score_components sc WHERE sc.run_id=r.id "
            "AND sc.dimension='time_efficiency' LIMIT 1)) AS avg_time_score,"
            "AVG((SELECT sc.score FROM score_components sc WHERE sc.run_id=r.id "
            "AND sc.dimension='token_efficiency' LIMIT 1)) AS avg_token_score,"
            "SUM(CASE WHEN COALESCE(r.passed,r.score>=60) THEN 1 ELSE 0 END)*100.0/COUNT(*) AS success_rate,"
            "AVG(r.duration_ms) AS avg_duration_ms,SUM(r.cost_usd) AS total_cost,"
            "AVG(r.tokens_input+r.tokens_output) AS avg_tokens FROM runs r "
            "JOIN experiments e ON e.id=r.experiment_id JOIN test_cases t ON t.id=r.test_case_id "
            "JOIN models m ON m.id=r.model_id "
            "JOIN agent_runners a ON a.id=r.runner_id WHERE "
            + " AND ".join(clauses)
            + " GROUP BY r.model_id,r.runner_id,r.lane ORDER BY avg_score DESC,success_rate DESC",
            params,
        )

    def model_profiles(
        self, lane: str | None = None, benchmark_generation: str = "v3"
    ) -> list[dict[str, Any]]:
        clauses = ["r.status='completed'", "r.score IS NOT NULL", "t.enabled=1"]
        params: list[Any] = []
        if benchmark_generation != "all":
            clauses.append("e.benchmark_generation=?")
            params.append(benchmark_generation)
        if lane:
            clauses.append("r.lane=?")
            params.append(lane)
        rows = self.database.fetch_all(
            "SELECT r.model_id AS model_id,m.name AS model_name,m.provider AS provider,"
            "t.category AS category,AVG(r.score) AS avg_score,COUNT(*) AS runs,"
            "SUM(CASE WHEN COALESCE(r.passed,r.score>=60) THEN 1 ELSE 0 END)*100.0/COUNT(*) AS success_rate,"
            "MAX(r.created_at) AS last_run_at FROM runs r "
            "JOIN experiments e ON e.id=r.experiment_id "
            "JOIN test_cases t ON t.id=r.test_case_id JOIN models m ON m.id=r.model_id WHERE "
            + " AND ".join(clauses)
            + " GROUP BY r.model_id,t.category",
            params,
        )
        profiles: dict[str, dict[str, Any]] = {}
        for row in rows:
            profile = profiles.setdefault(
                row["model_id"],
                {
                    "model_id": row["model_id"],
                    "model_name": row["model_name"],
                    "provider": row["provider"],
                    "total_runs": 0,
                    "score_sum": 0.0,
                    "passed_runs": 0,
                    "last_run_at": row["last_run_at"],
                    "dimensions": [],
                },
            )
            runs = row["runs"]
            profile["total_runs"] += runs
            profile["score_sum"] += row["avg_score"] * runs
            profile["passed_runs"] += round(row["success_rate"] * runs / 100.0)
            profile["last_run_at"] = max(profile["last_run_at"], row["last_run_at"])
            profile["dimensions"].append(
                {
                    "category": row["category"],
                    "avg_score": round(row["avg_score"], 1),
                    "runs": runs,
                    "success_rate": round(row["success_rate"], 1),
                }
            )
        result = []
        for profile in profiles.values():
            total = profile["total_runs"]
            result.append(
                {
                    "model_id": profile["model_id"],
                    "model_name": profile["model_name"],
                    "provider": profile["provider"],
                    "total_runs": total,
                    "avg_score": round(profile["score_sum"] / total, 1),
                    "success_rate": round(profile["passed_runs"] * 100.0 / total, 1),
                    "last_run_at": profile["last_run_at"],
                    "dimensions": sorted(
                        profile["dimensions"], key=lambda item: -item["avg_score"]
                    ),
                }
            )
        return sorted(result, key=lambda item: -item["avg_score"])

    def export(self, experiment_id: str, fmt: str) -> tuple[str, bytes, str]:
        self.get_experiment(experiment_id)
        rows = self.database.fetch_all(
            "SELECT r.id AS run_id,t.title AS test_title,t.category,m.name AS model_name,"
            "a.name AS runner_name,r.lane,r.status,r.score,r.tokens_input,r.tokens_output,"
            "r.cost_usd,r.duration_ms FROM runs r JOIN test_cases t ON t.id=r.test_case_id "
            "JOIN models m ON m.id=r.model_id JOIN agent_runners a ON a.id=r.runner_id "
            "WHERE r.experiment_id=? ORDER BY t.category,t.title,m.name,a.name,r.repetition",
            (experiment_id,),
        )
        return export_experiment(rows, fmt)

    def backup(self) -> Path:
        path = create_backup(self.database, self.settings)
        self.database.insert_audit("backup.created", "backup", path.name)
        return path

    def restore(self, content: bytes) -> dict[str, Any]:
        active = self.database.fetch_one(
            "SELECT COUNT(*) count FROM runs WHERE status IN "
            "('queued','preparing','running','validating','judging')"
        )
        if active and active["count"]:
            raise ValueError("Cannot restore while evaluation runs are active")
        safety_backup = create_backup(self.database, self.settings)
        result = restore_backup(content, self.database, self.settings)
        seed_builtin_data(self.database)
        self.database.sync_test_case_revisions()
        self.database.insert_audit(
            "backup.restored",
            "backup",
            safety_backup.name,
            {"safety_backup": safety_backup.name},
        )
        return {**result, "safety_backup": str(safety_backup)}

    def manual_score(self, run_id: str, score: float, reason: str) -> dict[str, Any]:
        self.get_run(run_id)
        evidence = {"reason": reason, "source": "human_review"}
        self.database.execute(
            "INSERT INTO judge_reviews(id,run_id,score,status,evidence_json,created_at) "
            "VALUES (?,?,?,'manual',?,?)",
            (new_id(), run_id, score, json.dumps(evidence, ensure_ascii=False), utc_now()),
        )
        self.database.execute(
            "UPDATE runs SET score=?,status='completed',completed_at=? WHERE id=?",
            (score, utc_now(), run_id),
        )
        self.database.insert_audit("run.manually_scored", "run", run_id, evidence)
        return self.get_run(run_id)
