from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agentbench.api import create_app
from agentbench.browser_mcp import BrowserMcpBridge
from agentbench.browser_runtime import BrowserRuntime, BrowserRuntimeError
from agentbench.catalog import MOCK_MODEL_ID, UNIFIED_RUNNER_ID
from agentbench.db import SCHEMA_VERSION
from agentbench.execution import CommandResult
from agentbench.model_clients import ModelDecision, ModelUsage
from agentbench.schemas import (
    ApprovalDecision,
    FileChangeReview,
    McpServerCreate,
    McpServerUpdate,
    McpToolCall,
    ProjectCreate,
    RuntimeProfileCreate,
    SessionAttachmentImport,
    SessionCreate,
    SessionForkCreate,
    SessionTurnCreate,
    SkillPackCreate,
    SkillPackUpdate,
    TaskGraphCreate,
    TaskGraphUpdate,
    TaskItemCreate,
    TerminalCreate,
    TerminalInput,
)
from agentbench.service import EvaluationService, runner_adapter_capabilities


class StudioWriteClient:
    def __init__(self) -> None:
        self.index = 0

    def complete(self, history, tools) -> ModelDecision:
        del history, tools
        self.index += 1
        if self.index == 1:
            return ModelDecision(
                kind="tool",
                tool_name="write_file",
                tool_arguments={"path": "generated.txt", "content": "studio runtime\n"},
                tool_call_id="studio-write-1",
                usage=ModelUsage(input_tokens=80, output_tokens=25),
                raw={"test": True},
            )
        return ModelDecision(
            kind="final",
            content="Created generated.txt and verified the Studio runtime.",
            usage=ModelUsage(input_tokens=60, output_tokens=12),
            raw={"test": True},
        )


class BrowserToolClient:
    def __init__(self) -> None:
        self.index = 0

    def complete(self, history, tools) -> ModelDecision:
        del history
        self.index += 1
        if self.index == 1:
            assert "browser_navigate" in {tool["name"] for tool in tools}
            return ModelDecision(
                kind="tool",
                tool_name="browser_navigate",
                tool_arguments={"url": "https://example.com"},
                tool_call_id="browser-call-1",
                usage=ModelUsage(input_tokens=20, output_tokens=10),
            )
        return ModelDecision(
            kind="final",
            content="Browser navigation completed.",
            usage=ModelUsage(input_tokens=10, output_tokens=5),
        )


class BlockingStudioClient:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def complete(self, history, tools) -> ModelDecision:
        del history, tools
        self.started.set()
        if not self.release.wait(5):
            raise AssertionError("Cancellation test did not release the model call")
        return ModelDecision(
            kind="final",
            content="This response should be cancelled.",
            usage=ModelUsage(input_tokens=20, output_tokens=5),
            raw={"test": True},
        )


class QueuedStudioClient:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def complete(self, history, tools) -> ModelDecision:
        del history, tools
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            if not self.release.wait(5):
                raise AssertionError("Queued turn test did not release the first model call")
        return ModelDecision(
            kind="final",
            content=f"Completed queued instruction {self.calls}.",
            usage=ModelUsage(input_tokens=12, output_tokens=6),
            raw={"test": True},
        )


class ShellApprovalClient:
    def __init__(self) -> None:
        self.index = 0

    def complete(self, history, tools) -> ModelDecision:
        del history, tools
        self.index += 1
        if self.index == 1:
            return ModelDecision(
                kind="tool",
                tool_name="run_command",
                tool_arguments={"command": "python --version"},
                tool_call_id="shell-approval-1",
                usage=ModelUsage(input_tokens=15, output_tokens=5),
                raw={},
            )
        return ModelDecision(
            kind="final",
            content="Approved command completed.",
            usage=ModelUsage(input_tokens=10, output_tokens=5),
            raw={},
        )


def wait_for_turn(service: EvaluationService, turn_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        turn = service.database.fetch_one("SELECT * FROM session_turns WHERE id=?", (turn_id,))
        if turn and turn["status"] not in {
            "queued",
            "preparing",
            "running",
            "waiting_approval",
        }:
            return turn
        time.sleep(0.02)
    raise AssertionError(f"Studio turn {turn_id} did not finish")


def wait_for_record(service: EvaluationService, table: str, record_id: str) -> dict:
    assert table in {"task_items", "task_graphs"}
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        row = service.database.fetch_one(f"SELECT * FROM {table} WHERE id=?", (record_id,))
        if row and row["status"] in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.03)
    raise AssertionError(f"{table} record {record_id} did not finish")


def create_project(service: EvaluationService, root: Path, name: str = "Studio project"):
    root.mkdir(parents=True, exist_ok=True)
    return service.studio.create_project(
        ProjectCreate(
            name=name,
            root_path=str(root),
            default_runner_id=UNIFIED_RUNNER_ID,
            default_model_id=MOCK_MODEL_ID,
            permission_profile="workspace",
        )
    )


def test_control_center_only_lists_active_sessions_and_surfaces_failures(
    settings, tmp_path
) -> None:
    with TestClient(create_app(settings)) as client:
        service = client.app.state.service
        project = create_project(service, tmp_path / "dashboard-project")
        running = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Still running")
        )
        failed = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Needs attention")
        )
        service.database.execute(
            "UPDATE agent_sessions SET status='running' WHERE id=?", (running["id"],)
        )
        service.database.execute(
            "UPDATE agent_sessions SET status='failed' WHERE id=?", (failed["id"],)
        )

        response = client.get("/api/v1/studio/dashboard")

        assert response.status_code == 200
        payload = response.json()
        assert [item["id"] for item in payload["active_sessions_list"]] == [running["id"]]
        assert payload["recent_failures"][0]["id"] == failed["id"]


def test_control_center_unifies_session_task_and_flow_activity(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "activity-project")
        session = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Activity session")
        )
        service.studio.append_event(session["id"], "turn.started", {"turn_no": 1})
        task = service.studio.create_task(
            TaskItemCreate(
                project_id=project["id"],
                title="Activity task",
                priority="high",
            )
        )
        service.database.execute(
            "UPDATE task_items SET status='running' WHERE id=?", (task["id"],)
        )
        service.studio.append_task_event(task["id"], "task.running", {})
        graph = service.studio.create_graph(
            TaskGraphCreate(
                project_id=project["id"],
                name="Activity Flow",
                nodes=[
                    {
                        "id": "gate",
                        "type": "condition",
                        "name": "Gate",
                        "config": {"operator": "contains", "value": "ready"},
                    }
                ],
            )
        )
        service.database.execute(
            "UPDATE task_graphs SET status='running' WHERE id=?", (graph["id"],)
        )
        service.studio.create_graph_run(graph["id"], status="running")

        payload = service.studio.dashboard()

        assert {item["source_type"] for item in payload["activity"]} >= {
            "session",
            "task",
            "flow",
        }
        assert payload["active_tasks_list"][0]["id"] == task["id"]
        assert payload["active_flows_list"][0]["id"] == graph["id"]
        assert next(
            item for item in payload["activity"] if item["source_type"] == "session"
        )["href"] == f"/studio/{session['id']}"
    finally:
        service.close()
        assert payload["runtime_health"]["models_enabled"] >= 1
        assert payload["runtime_health"]["runners_enabled"] >= 1


def test_diagnostics_export_is_downloadable_and_excludes_private_content(
    settings, tmp_path
) -> None:
    with TestClient(create_app(settings)) as client:
        service = client.app.state.service
        project = create_project(service, tmp_path / "diagnostics-project")
        session = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Diagnostic session")
        )
        service.database.execute(
            "INSERT INTO session_messages(id,session_id,role,content,metadata_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("private-message", session["id"], "user", "TOP SECRET PROMPT", "{}", "2026-01-01T00:00:00Z"),
        )

        response = client.get("/api/v1/system/diagnostics")

        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.json()["database"] == {"schema_version": SCHEMA_VERSION, "quick_check": "ok"}
        assert "TOP SECRET PROMPT" not in response.text
        assert "prompts" in response.json()["privacy"]


def test_session_detail_pages_messages_on_the_server(settings, tmp_path) -> None:
    with TestClient(create_app(settings)) as client:
        service = client.app.state.service
        project = create_project(service, tmp_path / "long-session-project")
        session = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Long conversation")
        )
        service.database.executemany(
            "INSERT INTO session_messages(id,session_id,role,content,metadata_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            [
                (
                    f"message-{index:03d}",
                    session["id"],
                    "user" if index % 2 == 0 else "assistant",
                    f"message {index}",
                    "{}",
                    f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}Z",
                )
                for index in range(250)
            ],
        )

        response = client.get(
            f"/api/v1/sessions/{session['id']}?message_limit=120"
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["message_count"] == 250
        assert payload["messages_truncated"] is True
        assert len(payload["messages"]) == 120
        assert payload["messages"][0]["content"] == "message 130"
        assert payload["messages"][-1]["content"] == "message 249"


def test_workspace_search_finds_operational_entities_without_benchmarks(settings, tmp_path) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        service = app.state.service
        project = create_project(service, tmp_path / "search-workspace", "Aurora workspace")
        session = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Aurora migration session")
        )
        task = service.studio.create_task(
            TaskItemCreate(project_id=project["id"], title="Aurora release task")
        )
        flow = service.studio.create_graph(
            TaskGraphCreate(
                project_id=project["id"],
                name="Aurora review flow",
                nodes=[{"id": "review", "type": "agent", "name": "Review"}],
            )
        )

        response = client.get("/api/v1/studio/search", params={"query": "Aurora"})
        assert response.status_code == 200
        results = response.json()
        assert {(item["kind"], item["id"]) for item in results} >= {
            ("project", project["id"]),
            ("session", session["id"]),
            ("task", task["id"]),
            ("flow", flow["id"]),
        }
        assert all(item["path"].startswith(("/projects", "/studio", "/tasks", "/flows")) for item in results)
        assert service.studio.search_workspace("   ") == []


def test_v4_schema_keeps_benchmarks_separate_from_studio(settings) -> None:
    service = EvaluationService(settings)
    try:
        tables = {
            row["name"]
            for row in service.database.fetch_all(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "projects",
            "project_roots",
            "agent_sessions",
            "session_turns",
            "session_messages",
            "session_events",
            "approval_requests",
            "permission_rules",
            "task_graphs",
            "task_nodes",
            "task_edges",
            "task_items",
            "mcp_servers",
        } <= tables
        assert {"experiments", "runs", "run_events", "test_cases"} <= tables
        assert service.database.fetch_one("SELECT version FROM schema_meta") == {"version": SCHEMA_VERSION}
    finally:
        service.close()


def test_project_file_access_rejects_symlinks_that_leave_the_authorized_root(
    settings, tmp_path
) -> None:
    service = EvaluationService(settings)
    try:
        root = tmp_path / "authorized-root"
        project = create_project(service, root)
        outside = tmp_path / "outside-secret.txt"
        outside.write_text("must stay outside", encoding="utf-8")
        link = root / "escape.txt"
        try:
            os.symlink(outside, link)
        except OSError as exc:
            pytest.skip(f"Symlink creation is unavailable on this Windows host: {exc}")

        with pytest.raises(ValueError, match="project_path_escape"):
            service.studio.read_project_file(project["id"], "escape.txt")
        listed = service.studio.list_project_files(project["id"])
        assert "escape.txt" not in {item["name"] for item in listed["entries"]}
        searched = service.studio.search_project_files(project["id"], "escape")
        assert searched["entries"] == []
    finally:
        service.close()


def test_project_session_turn_and_restart_recovery(settings, tmp_path) -> None:
    root = tmp_path / "repository"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "src" / "agent-search-panel.tsx").write_text(
        "export const panel = true;\n", encoding="utf-8"
    )
    (root / "node_modules").mkdir()
    (root / "node_modules" / "agent-search-ignored.js").write_text(
        "ignored\n", encoding="utf-8"
    )
    first = EvaluationService(settings)
    try:
        project = create_project(first, root)
        assert project["root_path"] == str(root.resolve())
        assert project["session_count"] == 0

        tree = first.studio.list_project_files(project["id"])
        assert [item["name"] for item in tree["entries"]] == ["src"]
        search = first.studio.search_project_files(project["id"], "agent-search")
        assert [item["path"] for item in search["entries"]] == [
            "src/agent-search-panel.tsx"
        ]
        assert search["scanned"] >= 2
        assert search["truncated"] is False
        with pytest.raises(ValueError, match="project_search_query_too_short"):
            first.studio.search_project_files(project["id"], "a")
        content = first.studio.read_project_file(project["id"], "src/main.py")
        assert content["content"] == "print('hello')\n"
        with pytest.raises(ValueError, match="project_path_escape"):
            first.studio.read_project_file(project["id"], "../outside.txt")

        session = first.studio.create_session(
            SessionCreate(
                project_id=project["id"],
                runner_id=UNIFIED_RUNNER_ID,
                model_id=MOCK_MODEL_ID,
                title="Build session runtime",
            )
        )
        turn = first.studio.queue_turn(
            session["id"],
            SessionTurnCreate(
                message="Inspect the project and propose a migration.",
                context=[{"type": "file", "path": "src/main.py"}],
            ),
        )
        assert turn["turn_no"] == 1
        assert turn["status"] == "queued"
        detail = first.studio.get_session(session["id"])
        assert detail["status"] == "queued"
        assert detail["messages"][0]["role"] == "user"
        assert detail["messages"][0]["metadata"]["context"][0]["path"] == "src/main.py"
        assert [event["event_type"] for event in detail["events"]] == [
            "session.created",
            "turn.queued",
        ]
    finally:
        first.close()

    second = EvaluationService(settings)
    try:
        recovered = second.studio.get_session(session["id"])
        assert recovered["status"] == "interrupted"
        assert recovered["turns"][0]["status"] == "interrupted"
        assert recovered["events"][-1]["event_type"] == "session.interrupted"
    finally:
        second.close()


def test_approval_decision_creates_scoped_permission_rule(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "approval-project")
        session = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Approval test")
        )
        approval = service.studio.create_approval(
            session["id"],
            request_type="command",
            title="Install project dependency",
            description="The Agent wants to update the project lockfile.",
            request={"command": "pnpm add @xyflow/react", "cwd": str(tmp_path)},
            risk_level="medium",
        )
        assert approval["status"] == "pending"
        assert service.studio.get_session(session["id"])["status"] == "waiting_approval"

        resolved = service.studio.decide_approval(
            approval["id"], ApprovalDecision(decision="allow_project", reason="Expected change")
        )
        assert resolved["status"] == "approved"
        assert resolved["decision"]["decision"] == "allow_project"
        assert service.studio.get_session(session["id"])["status"] == "idle"
        rule = service.database.fetch_one(
            "SELECT scope,pattern,decision FROM permission_rules WHERE project_id=?",
            (project["id"],),
        )
        assert rule == {
            "scope": "command",
            "pattern": "pnpm add @xyflow/react",
            "decision": "allow",
        }
    finally:
        service.close()


def test_session_runtime_controls_and_full_access_resolve_pending_approval(
    settings, tmp_path
) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "runtime-controls")
        session = service.studio.create_session(
            SessionCreate(
                project_id=project["id"],
                title="Runtime controls",
                permission_profile="workspace",
                reasoning_effort="high",
            )
        )
        assert session["reasoning_effort"] == "high"
        approval = service.studio.create_approval(
            session["id"],
            request_type="native_agent",
            title="Allow native Agent",
            description="The native Agent needs project access.",
            request={"runner_id": "runner-test"},
        )

        updated = service.studio.update_session(
            session["id"],
            {"permission_profile": "full", "reasoning_effort": "max"},
        )

        assert updated["permission_profile"] == "full"
        assert updated["reasoning_effort"] == "max"
        assert updated["status"] == "idle"
        assert service.studio.get_approval(approval["id"])["status"] == "approved"
    finally:
        service.close()


def test_session_attachment_import_is_bound_and_materialized_only_for_turn(
    settings, tmp_path
) -> None:
    service = EvaluationService(settings)
    try:
        project_root = tmp_path / "attachment-project"
        project = create_project(service, project_root)
        session = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Attachment turn")
        )
        source = tmp_path / "diagram.png"
        source.write_bytes(b"not-a-real-png-but-safe-for-copy-test")
        imported = service.studio.import_session_attachments(
            session["id"], SessionAttachmentImport(paths=[str(source)])
        )
        assert imported[0]["name"] == "diagram.png"
        turn = service.studio.queue_turn(
            session["id"],
            SessionTurnCreate(
                message="Inspect the attached diagram",
                context=[
                    {"type": "attachment", "artifact_id": imported[0]["id"]}
                ],
            ),
        )
        detail = service.studio.get_session(session["id"])
        context = detail["messages"][-1]["metadata"]["context"][0]
        assert context["artifact_id"] == imported[0]["id"]
        assert "path" not in context
        materialized, attachment_root = service._materialize_studio_attachments(
            detail, turn["id"], project_root.resolve()
        )
        assert materialized[0]["is_image"] is True
        assert Path(materialized[0]["absolute_path"]).read_bytes() == source.read_bytes()
        assert detail["messages"][-1]["metadata"]["context"][0]["path"].startswith(
            ".agentbench/attachments/"
        )
        assert attachment_root is not None
    finally:
        service.close()


def test_native_studio_options_map_permission_effort_and_images() -> None:
    attachment = {
        "absolute_path": "C:/tmp/diagram.png",
        "is_image": True,
    }
    reasonix = EvaluationService._studio_native_options(
        [
            "run",
            "--output-format",
            "json",
            "--permission-mode",
            "auto",
            "{prompt}",
        ],
        "reasonix_cli",
        "readonly",
        "xhigh",
        [attachment],
        "deepseek-v4-flash",
    )
    assert reasonix[reasonix.index("--permission-mode") + 1] == "plan"
    assert reasonix[reasonix.index("--effort") + 1] == "high"
    assert "--events-jsonl" not in reasonix
    assert reasonix[reasonix.index("--output-format") + 1] == "stream-json"

    codex = EvaluationService._studio_native_options(
        ["exec", "--sandbox", "workspace-write", "{prompt}"],
        "codex_cli",
        "full",
        "max",
        [attachment],
    )
    assert "--dangerously-bypass-approvals-and-sandbox" in codex
    assert "--sandbox" not in codex
    assert 'model_reasoning_effort="xhigh"' in codex
    assert codex[codex.index("--image") + 1] == attachment["absolute_path"]

    qoder = EvaluationService._studio_native_options(
        [
            "--print",
            "--output-format",
            "json",
            "--dangerously-skip-permissions",
            "{prompt}",
        ],
        "qoder_cli",
        "readonly",
        "max",
        [attachment],
    )
    assert "--dangerously-skip-permissions" not in qoder
    assert qoder[qoder.index("--permission-mode") + 1] == "dont_ask"
    assert qoder[qoder.index("--reasoning-effort") + 1] == "high"
    assert qoder[qoder.index("--attachment") + 1] == attachment["absolute_path"]

    kimi = EvaluationService._studio_native_options(
        ["--print", "--yolo", "--prompt", "{prompt}"],
        "kimi_code_cli",
        "readonly",
        "high",
        [attachment],
    )
    assert "--yolo" not in kimi
    assert "--plan" in kimi
    assert "--thinking" in kimi

    cursor = EvaluationService._studio_native_options(
        ["--print", "--sandbox", "enabled", "{prompt}"],
        "cursor_cli",
        "full",
        "high",
        [attachment],
    )
    assert cursor[cursor.index("--sandbox") + 1] == "disabled"
    assert "--force" in cursor
    assert attachment["absolute_path"] in cursor[-1]


def test_native_studio_resume_options_cover_supported_session_clis() -> None:
    codex = EvaluationService._studio_native_resume_options(
        ["exec", "--ephemeral", "{prompt}"], "codex_cli", "codex-session"
    )
    assert codex[:3] == ["exec", "resume", "codex-session"]
    assert "--ephemeral" not in codex

    claude = EvaluationService._studio_native_resume_options(
        ["--print", "--no-session-persistence", "{prompt}"],
        "claude_code_cli",
        "claude-session",
    )
    assert "--no-session-persistence" not in claude
    assert claude[claude.index("--resume") + 1] == "claude-session"

    qoder = EvaluationService._studio_native_resume_options(
        ["--print", "{prompt}"], "qoder_cli", "qoder-session"
    )
    assert qoder[qoder.index("--resume") + 1] == "qoder-session"

    kimi = EvaluationService._studio_native_resume_options(
        ["--print", "--prompt", "{prompt}"], "kimi_code_cli", "kimi-session"
    )
    assert kimi[kimi.index("--session") + 1] == "kimi-session"

    cursor = EvaluationService._studio_native_resume_options(
        ["--print", "{prompt}"], "cursor_cli", "cursor-session"
    )
    assert cursor[cursor.index("--resume") + 1] == "cursor-session"

    for runner_type in ("codex_cli", "claude_code_cli", "kimi_code_cli", "qoder_cli", "cursor_cli"):
        capabilities = runner_adapter_capabilities(runner_type, [])
        assert capabilities["native_resume"] is True
        assert capabilities["conversation_mode"] == "native_resume"
        assert capabilities["visible_browser"] is (runner_type != "cursor_cli")


def test_cursor_stream_event_exposes_tool_progress_without_raw_payload() -> None:
    event = EvaluationService._normalize_native_live_event(
        "cursor_cli",
        "stdout",
        json.dumps(
            {
                "type": "tool_call",
                "subtype": "started",
                "tool_call": {"readToolCall": {"args": {"path": "src/app.ts"}}},
            }
        ),
        1,
    )

    assert event is not None
    event_type, payload = event
    assert event_type == "live.tool"
    assert payload["tool"] == "readToolCall"
    assert "src/app.ts" in payload["detail"]

    delta = EvaluationService._normalize_native_live_event(
        "cursor_cli",
        "stdout",
        json.dumps(
            {
                "type": "assistant",
                "timestamp_ms": 2,
                "message": {"content": [{"type": "text", "text": "正在检查"}]},
            },
            ensure_ascii=False,
        ),
        2,
    )
    assert delta == (
        "live.text_delta",
        {
            "runner_type": "cursor_cli",
            "stream": "stdout",
            "line_no": 2,
            "source_type": "assistant",
            "delta": "正在检查",
        },
    )


def test_reasonix_stream_events_expose_public_progress_without_private_reasoning() -> None:
    assert EvaluationService._normalize_native_live_event(
        "reasonix_cli",
        "stdout",
        json.dumps({"kind": "reasoning", "text": "private reasoning"}),
        1,
    ) is None

    delta = EvaluationService._normalize_native_live_event(
        "reasonix_cli",
        "stdout",
        json.dumps({"kind": "text", "text": "正在读取"}, ensure_ascii=False),
        2,
    )
    assert delta == (
        "live.text_delta",
        {
            "runner_type": "reasonix_cli",
            "stream": "stdout",
            "line_no": 2,
            "source_type": "text",
            "delta": "正在读取",
        },
    )

    message = EvaluationService._normalize_native_live_event(
        "reasonix_cli",
        "stdout",
        json.dumps(
            {"kind": "message", "text": "正在读取 package.json", "reasoning": "private"},
            ensure_ascii=False,
        ),
        3,
    )
    assert message is not None
    assert message[0] == "live.message"
    assert message[1]["text"] == "正在读取 package.json"
    assert "private" not in json.dumps(message[1], ensure_ascii=False)

    tool = EvaluationService._normalize_native_live_event(
        "reasonix_cli",
        "stdout",
        json.dumps(
            {
                "kind": "tool_result",
                "tool": {
                    "id": "call-1",
                    "name": "read_file",
                    "args": '{"path":"package.json"}',
                    "output": "file contents",
                    "readOnly": True,
                },
            }
        ),
        4,
    )
    assert tool is not None
    assert tool[0] == "live.tool"
    assert tool[1]["tool_id"] == "call-1"
    assert tool[1]["tool"] == "read_file"
    assert tool[1]["status"] == "completed"
    assert "package.json" in tool[1]["detail"]
    assert "file contents" not in tool[1]["detail"]

    usage = EvaluationService._normalize_native_live_event(
        "reasonix_cli",
        "stdout",
        json.dumps(
            {
                "kind": "usage",
                "usage": {
                    "promptTokens": 120,
                    "completionTokens": 17,
                    "costUsd": 0.0042,
                },
            }
        ),
        5,
    )
    assert usage is not None
    assert usage[0] == "live.usage"
    assert usage[1]["usage"] == {
        "input_tokens": 120,
        "output_tokens": 17,
        "cost_usd": 0.0042,
    }


def test_reasonix_stream_output_aggregates_turn_usage_and_final_result() -> None:
    output = "\n".join(
        json.dumps(item, ensure_ascii=False)
        for item in (
            {"kind": "message", "text": "正在检查项目"},
            {"kind": "usage", "usage": {"promptTokens": 100, "completionTokens": 10, "cost": 0.01}},
            {"kind": "usage", "usage": {"promptTokens": 170, "completionTokens": 5, "cost": 0.02}},
            {
                "type": "result",
                "result": "检查完成",
                "total_cost_usd": 0.03,
                "usage": {"input_tokens": 270, "output_tokens": 15},
            },
        )
    )
    final, input_tokens, output_tokens, cost, count = EvaluationService._parse_native_output(
        "reasonix_cli", output
    )
    assert final == "检查完成"
    assert input_tokens == 270
    assert output_tokens == 15
    assert cost == pytest.approx(0.03)
    assert count == 4


@pytest.mark.skipif(sys.platform != "win32", reason="ConPTY is a Windows runtime")
def test_interactive_terminal_accepts_input_and_can_restart(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "terminal-project")
        session = service.studio.create_session(
            SessionCreate(
                project_id=project["id"],
                title="Interactive terminal",
                permission_profile="standard",
            )
        )
        terminal = service.start_terminal(session["id"], TerminalCreate())
        service.write_terminal(
            session["id"],
            terminal["id"],
            TerminalInput(data="Write-Output 'AGENTBENCH_TERMINAL_OK'\r"),
        )
        deadline = time.monotonic() + 5
        output = ""
        while time.monotonic() < deadline:
            state = service.read_terminal(session["id"], terminal["id"], 0)
            output = "".join(item["data"] for item in state["chunks"])
            if "AGENTBENCH_TERMINAL_OK" in output:
                break
            time.sleep(0.05)
        assert "AGENTBENCH_TERMINAL_OK" in output
        service.close_terminal(session["id"], terminal["id"])
        restarted = service.start_terminal(session["id"], TerminalCreate())
        assert restarted["running"] is True
        assert restarted["id"] != terminal["id"]
    finally:
        service.close()


def test_tasks_graphs_and_mcp_definitions_are_real_local_records(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "flow-project")
        task = service.studio.create_task(
            TaskItemCreate(
                project_id=project["id"],
                title="Implement project service",
                priority="high",
                runner_id=UNIFIED_RUNNER_ID,
                model_id=MOCK_MODEL_ID,
            )
        )
        assert task["status"] == "backlog"
        assert service.studio.list_tasks(project["id"])[0]["id"] == task["id"]
        dependent = service.studio.create_task(
            TaskItemCreate(
                project_id=project["id"],
                title="Run after implementation",
                runner_id=UNIFIED_RUNNER_ID,
                model_id=MOCK_MODEL_ID,
                depends_on=[task["id"]],
            )
        )
        with pytest.raises(ValueError, match="task_dependencies_incomplete"):
            service.start_task(dependent["id"])
        with pytest.raises(ValueError, match="task_dependency_cycle"):
            service.studio.update_task(task["id"], {"depends_on": [dependent["id"]]})

        graph = service.studio.create_graph(
            TaskGraphCreate(
                project_id=project["id"],
                name="Plan, implement, approve",
                nodes=[
                    {"id": "plan", "type": "agent", "name": "Plan", "x": 10, "y": 20},
                    {"id": "build", "type": "agent", "name": "Build", "x": 240, "y": 20},
                    {"id": "approve", "type": "approval", "name": "Approve", "x": 470, "y": 20},
                ],
                edges=[
                    {"source": "plan", "target": "build"},
                    {"source": "build", "target": "approve"},
                ],
            )
        )
        assert len(graph["nodes"]) == 3
        assert len(graph["edges"]) == 2
        assert service.studio.list_graphs(project["id"])[0]["node_count"] == 3

        mcp = service.studio.create_mcp_server(
            McpServerCreate(
                name="Local browser tools",
                transport="stdio",
                command="node",
                args=["browser-mcp.js"],
            )
        )
        assert mcp["command"] == "node"
        assert mcp["args"] == ["browser-mcp.js"]
        assert mcp["env_keys"] == []
        assert service.studio.list_mcp_servers()[0]["id"] == mcp["id"]
    finally:
        service.close()


def test_task_detail_persists_acceptance_criteria_and_activity_timeline(
    settings, tmp_path
) -> None:
    with TestClient(create_app(settings)) as client:
        service = client.app.state.service
        project = create_project(service, tmp_path / "task-detail-project")

        created_response = client.post(
            "/api/v1/tasks",
            json={
                "project_id": project["id"],
                "title": "Ship the task detail experience",
                "description": "Implement and verify the task detail page.",
                "priority": "high",
                "acceptance_criteria": [
                    {"text": "The detail route opens directly"},
                    {"text": "The activity timeline is chronological"},
                ],
            },
        )
        assert created_response.status_code == 201
        task = created_response.json()

        detail_response = client.get(f"/api/v1/tasks/{task['id']}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["acceptance_criteria"] == [
            {"text": "The detail route opens directly", "completed": False},
            {"text": "The activity timeline is chronological", "completed": False},
        ]
        assert [event["event_type"] for event in detail["events"]] == ["task.created"]

        updated = client.patch(
            f"/api/v1/tasks/{task['id']}",
            json={
                "acceptance_criteria": [
                    {"text": "The detail route opens directly", "completed": True},
                    {"text": "The activity timeline is chronological"},
                ]
            },
        )
        assert updated.status_code == 200
        assert updated.json()["acceptance_criteria"][0]["completed"] is True
        events = client.get(f"/api/v1/tasks/{task['id']}/events").json()
        assert [event["event_type"] for event in events] == [
            "task.created",
            "task.updated",
        ]


def test_task_bulk_actions_report_partial_failures(settings, tmp_path) -> None:
    with TestClient(create_app(settings)) as client:
        service = client.app.state.service
        project = create_project(service, tmp_path / "task-bulk-project")
        ready = service.studio.create_task(
            TaskItemCreate(project_id=project["id"], title="Ready to archive")
        )
        active = service.studio.create_task(
            TaskItemCreate(project_id=project["id"], title="Currently running")
        )
        service.database.execute(
            "UPDATE task_items SET status='running' WHERE id=?", (active["id"],)
        )

        response = client.post(
            "/api/v1/tasks/bulk",
            json={
                "task_ids": [ready["id"], active["id"], "missing-task"],
                "action": "archive",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["requested"] == 3
        assert [item["id"] for item in payload["updated"]] == [ready["id"]]
        assert {item["task_id"] for item in payload["errors"]} == {
            active["id"],
            "missing-task",
        }
        assert service.studio.get_task(ready["id"])["archived"] is True
        assert service.studio.get_task(active["id"])["archived"] is False


def test_flow_mcp_skill_and_browser_management_apis_are_mutable(settings, tmp_path) -> None:
    with TestClient(create_app(settings)) as client:
        root = tmp_path / "management-api"
        root.mkdir()
        project = client.post(
            "/api/v1/projects",
            json={
                "name": "Management API",
                "root_path": str(root),
                "default_runner_id": UNIFIED_RUNNER_ID,
                "default_model_id": MOCK_MODEL_ID,
            },
        ).json()

        flow_response = client.post(
            "/api/v1/flows",
            json={
                "project_id": project["id"],
                "name": "API flow",
                "nodes": [{"id": "plan", "type": "agent", "name": "Plan"}],
            },
        )
        assert flow_response.status_code == 201
        flow = flow_response.json()
        edited = client.patch(
            f"/api/v1/flows/{flow['id']}",
            json={
                "name": "Edited API flow",
                "nodes": [
                    {"id": "plan", "type": "agent", "name": "Plan"},
                    {"id": "gate", "type": "condition", "name": "Gate"},
                ],
                "edges": [{"source": "plan", "target": "gate"}],
            },
        ).json()
        assert edited["name"] == "Edited API flow"
        assert len(edited["nodes"]) == 2
        validation = client.get(f"/api/v1/flows/{flow['id']}/validation").json()
        assert validation["valid"] is True
        assert validation["topological_order"]
        draft_validation = client.post(
            "/api/v1/flows/validate",
            json={
                "project_id": project["id"],
                "name": "Invalid draft",
                "nodes": [
                    {"id": "tool", "type": "tool", "name": "Missing MCP", "config": {}}
                ],
            },
        ).json()
        assert draft_validation["valid"] is False
        assert {item["code"] for item in draft_validation["errors"]} >= {
            "tool_server_required",
            "tool_name_required",
        }
        versions = client.get(f"/api/v1/flows/{flow['id']}/versions").json()
        assert [item["version_no"] for item in versions] == [2, 1]
        dry_run = client.post(f"/api/v1/flows/{flow['id']}/dry-run").json()
        assert dry_run["dry_run"] is True
        assert dry_run["status"] == "completed"
        assert dry_run["result"]["steps"]
        runs = client.get(f"/api/v1/flows/{flow['id']}/runs").json()
        assert runs[0]["id"] == dry_run["id"]
        restored = client.post(
            f"/api/v1/flows/{flow['id']}/versions/1/restore"
        ).json()
        assert restored["name"] == "API flow"
        assert len(restored["nodes"]) == 1

        mcp = client.post(
            "/api/v1/mcp-servers",
            json={"name": "API MCP", "transport": "stdio", "command": "cmd", "args": []},
        ).json()
        assert client.patch(
            f"/api/v1/mcp-servers/{mcp['id']}", json={"name": "Edited API MCP"}
        ).json()["name"] == "Edited API MCP"

        skill = client.post(
            "/api/v1/skill-packs",
            json={
                "name": "API skill",
                "description": "Created through HTTP",
                "content": "Inspect the selected project.",
                "tools": ["search"],
            },
        ).json()
        assert client.patch(
            f"/api/v1/skill-packs/{skill['id']}", json={"description": "Editable"}
        ).json()["description"] == "Editable"
        browser_status = client.get("/api/v1/browser/status")
        assert browser_status.status_code == 200
        assert "installed" in browser_status.json()

        assert client.delete(f"/api/v1/flows/{flow['id']}").status_code == 204
        assert client.delete(f"/api/v1/mcp-servers/{mcp['id']}").status_code == 204
        assert client.delete(f"/api/v1/skill-packs/{skill['id']}").status_code == 204


def test_flow_templates_preserve_data_bindings_and_validate(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "flow-template-project")
        templates = service.studio.list_graph_templates()
        assert {item["id"] for item in templates} == {
            "single-delivery",
            "parallel-review",
            "conditional-recovery",
        }
        template = next(item for item in templates if item["id"] == "parallel-review")
        graph = service.studio.create_graph(
            TaskGraphCreate(
                project_id=project["id"],
                name="Template binding graph",
                description=template["description"],
                settings=template["settings"],
                nodes=template["nodes"],
                edges=template["edges"],
            )
        )

        validation = service.studio.validate_graph(graph["id"])
        synthesis = next(item for item in graph["nodes"] if item["name"] == "汇总结论")
        incoming_ids = {
            edge["source_node_id"]
            for edge in graph["edges"]
            if edge["target_node_id"] == synthesis["id"]
        }
        binding_ids = {
            item["source_node_id"] for item in synthesis["config"]["input_bindings"]
        }
        assert validation["valid"] is True
        assert binding_ids == incoming_ids
    finally:
        service.close()


def test_flow_binding_drives_condition_and_continue_strategy_contains_failure(
    settings, tmp_path
) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "flow-binding-project")
        graph = service.studio.create_graph(
            TaskGraphCreate(
                project_id=project["id"],
                name="Binding runtime",
                nodes=[
                    {
                        "id": "source",
                        "type": "condition",
                        "name": "Source",
                        "config": {"operator": "contains", "value": "READY"},
                    },
                    {
                        "id": "target",
                        "type": "condition",
                        "name": "Target",
                        "config": {
                            "operator": "contains",
                            "value": "READY",
                            "input_bindings": [
                                {
                                    "source_node_id": "source",
                                    "path": "summary",
                                    "target": "source",
                                }
                            ],
                        },
                    },
                    {
                        "id": "recoverable-tool",
                        "type": "tool",
                        "name": "Recoverable tool",
                        "config": {
                            "server_id": "missing-server",
                            "tool_name": "missing-tool",
                            "error_strategy": "continue",
                            "retry_count": 0,
                        },
                    },
                ],
                edges=[{"source": "source", "target": "target"}],
            )
        )
        source = next(item for item in graph["nodes"] if item["name"] == "Source")
        target = next(item for item in graph["nodes"] if item["name"] == "Target")
        recoverable = next(
            item for item in graph["nodes"] if item["name"] == "Recoverable tool"
        )
        source["output"] = {"summary": "PROJECT READY"}

        matched = service._execute_flow_node(
            graph, target, [source], threading.Event(), isolated=False
        )
        continued = service._execute_flow_node(
            graph, recoverable, [], threading.Event(), isolated=False
        )

        assert matched["matched"] is True
        assert continued["continued"] is True
        persisted = service.database.fetch_one(
            "SELECT status,error_message FROM task_nodes WHERE id=?", (recoverable["id"],)
        )
        assert persisted is not None
        assert persisted["status"] == "completed"
        assert persisted["error_message"]
    finally:
        service.close()


def test_single_flow_node_test_runs_without_executing_the_full_graph(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "single-node-test-project")
        graph = service.studio.create_graph(
            TaskGraphCreate(
                project_id=project["id"],
                name="Single node test",
                nodes=[
                    {
                        "id": "condition",
                        "type": "condition",
                        "name": "Test condition",
                        "config": {
                            "operator": "contains",
                            "value": "READY",
                            "test_input": {"summary": "READY"},
                            "retry_count": 0,
                        },
                    },
                    {
                        "id": "untouched",
                        "type": "agent",
                        "name": "Must not run",
                        "config": {"prompt": "Do not execute in a node test"},
                    },
                ],
                edges=[{"source": "condition", "target": "untouched"}],
            )
        )
        condition = next(item for item in graph["nodes"] if item["name"] == "Test condition")

        started = service.start_flow_node_test(graph["id"], condition["id"])
        deadline = time.monotonic() + 5
        run = started["run"]
        while time.monotonic() < deadline:
            run = service.studio.get_graph_run(graph["id"], run["id"])
            if run["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.03)

        refreshed = service.studio.get_graph(graph["id"])
        tested = next(item for item in refreshed["nodes"] if item["id"] == condition["id"])
        untouched = next(item for item in refreshed["nodes"] if item["name"] == "Must not run")
        assert run["status"] == "completed"
        assert run["result"]["node_test"] is True
        assert tested["output"]["matched"] is True
        assert untouched["status"] == "pending"
        assert refreshed["status"] == "draft"
    finally:
        service.close()


def test_skill_packs_are_persisted_and_applied_to_studio_sessions(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "skill-project")
        assert {item["name"] for item in service.studio.list_skill_packs()} >= {
            "代码审查",
            "前端实现",
            "发布前验证",
        }
        skill = service.studio.create_skill_pack(
            SkillPackCreate(
                name="只读巡查",
                description="只读取项目并报告",
                content="只进行可验证的只读巡查。",
                tools=["filesystem_read", "search"],
                permission_profile="readonly",
            )
        )
        session = service.studio.create_session(
            SessionCreate(
                project_id=project["id"],
                title="Skill session",
                skill_pack_id=skill["id"],
            )
        )
        assert session["skill_pack_name"] == "只读巡查"
        assert session["permission_profile"] == "readonly"
        assert service._studio_session_tools(session) == ["filesystem_read", "search"]

        updated = service.studio.update_skill_pack(
            skill["id"], SkillPackUpdate(description="更新后的说明")
        )
        assert updated["description"] == "更新后的说明"
        service.studio.delete_skill_pack(skill["id"])
        assert service.studio.get_session(session["id"])["skill_pack_id"] is None
    finally:
        service.close()


def test_runtime_profiles_inherit_configuration_and_expose_selected_mcp_tools(
    settings, tmp_path
) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "profile-project")
        mcp = service.studio.create_mcp_server(
            McpServerCreate(
                name="Issue tracker",
                transport="stdio",
                command=sys.executable,
                args=["fake-mcp.py"],
            )
        )
        service.studio.update_mcp_health(
            mcp["id"],
            status="online",
            tools=[
                {
                    "name": "create_issue",
                    "description": "Create one issue",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"],
                    },
                }
            ],
            error=None,
        )
        profile = service.studio.create_runtime_profile(
            RuntimeProfileCreate(
                name="Release operator",
                description="Full release runtime",
                runner_id=UNIFIED_RUNNER_ID,
                model_id=MOCK_MODEL_ID,
                permission_profile="full",
                reasoning_effort="high",
                mcp_server_ids=[mcp["id"]],
            )
        )

        session = service.studio.create_session(
            SessionCreate(
                project_id=project["id"],
                profile_id=profile["id"],
                title="Profile inheritance",
            )
        )
        assert session["runner_id"] == UNIFIED_RUNNER_ID
        assert session["model_id"] == MOCK_MODEL_ID
        assert session["permission_profile"] == "full"
        assert session["reasoning_effort"] == "high"
        assert session["profile_name"] == "Release operator"

        model_tools, native_tools, mapping = service._studio_profile_mcp_catalog(session)
        assert len(model_tools) == len(native_tools) == len(mapping) == 1
        alias = model_tools[0]["name"]
        assert alias.startswith("mcp__")
        assert model_tools[0]["parameters"]["required"] == ["title"]
        assert native_tools[0]["inputSchema"]["properties"]["title"]["type"] == "string"
        assert mapping[alias] == (mcp["id"], "create_issue")

        updated = service.studio.update_runtime_profile(
            profile["id"], {"description": "Updated", "reasoning_effort": "xhigh"}
        )
        assert updated["description"] == "Updated"
        assert updated["reasoning_effort"] == "xhigh"
        service.studio.delete_runtime_profile(profile["id"])
        assert service.studio.get_session(session["id"])["profile_id"] is None
        builtin = next(item for item in service.studio.list_runtime_profiles() if item["builtin"])
        with pytest.raises(ValueError, match="builtin_runtime_profile_cannot_be_deleted"):
            service.studio.delete_runtime_profile(builtin["id"])
    finally:
        service.close()


def test_runtime_profile_crud_api_and_ephemeral_studio_mcp_bridge(settings, tmp_path) -> None:
    with TestClient(create_app(settings)) as client:
        service = client.app.state.service
        project = create_project(service, tmp_path / "profile-api-project")
        mcp = service.studio.create_mcp_server(
            McpServerCreate(
                name="Read service",
                transport="stdio",
                command=sys.executable,
                args=["fake-mcp.py"],
            )
        )
        service.studio.update_mcp_health(
            mcp["id"],
            status="online",
            tools=[
                {
                    "name": "lookup",
                    "description": "Look up a record",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ],
            error=None,
        )
        created = client.post(
            "/api/v1/runtime-profiles",
            json={
                "name": "API profile",
                "runner_id": UNIFIED_RUNNER_ID,
                "model_id": MOCK_MODEL_ID,
                "permission_profile": "full",
                "reasoning_effort": "medium",
                "mcp_server_ids": [mcp["id"]],
            },
        )
        assert created.status_code == 201
        profile = created.json()
        assert client.patch(
            f"/api/v1/runtime-profiles/{profile['id']}",
            json={"description": "Edited through API"},
        ).json()["description"] == "Edited through API"

        session = service.studio.create_session(
            SessionCreate(
                project_id=project["id"],
                profile_id=profile["id"],
                title="Bridge session",
            )
        )
        turn = service.studio.queue_turn(
            session["id"], SessionTurnCreate(message="Use the configured MCP tool")
        )
        _model_tools, native_tools, mapping = service._studio_profile_mcp_catalog(session)
        calls: list[tuple[str, str, dict]] = []
        service.execute_mcp_tool = lambda server_id, value: (
            calls.append((server_id, value.tool_name, value.arguments))
            or {"ok": True, "result": "found"}
        )
        token, definition = service._register_studio_bridge(
            session,
            turn["id"],
            threading.Event(),
            include_browser=False,
            mcp_tools=native_tools,
            mcp_mapping=mapping,
        )
        try:
            advertised = client.get(f"/api/v1/studio/bridge/{token}/tools")
            assert advertised.status_code == 200
            alias = advertised.json()["tools"][0]["name"]
            called = client.post(
                f"/api/v1/studio/bridge/{token}",
                json={"tool_name": alias, "arguments": {"id": 7}},
            )
            assert called.status_code == 200, called.text
            assert called.json()["result"] == "found"
            assert calls == [(mcp["id"], "lookup", {"id": 7})]
            assert "--studio-mcp" in definition["args"]
        finally:
            service._unregister_studio_bridge(token)
        assert client.get(f"/api/v1/studio/bridge/{token}/tools").status_code == 400
        assert client.delete(f"/api/v1/runtime-profiles/{profile['id']}").status_code == 204


def test_flow_agent_node_uses_its_runtime_profile(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "flow-profile-project")
        profile = service.studio.create_runtime_profile(
            RuntimeProfileCreate(
                name="Flow profile",
                runner_id=UNIFIED_RUNNER_ID,
                model_id=MOCK_MODEL_ID,
                permission_profile="full",
                reasoning_effort="high",
            )
        )
        graph = service.studio.create_graph(
            TaskGraphCreate(
                project_id=project["id"],
                name="Profile flow",
                settings={"max_retries": 0},
                nodes=[
                    {
                        "id": "agent",
                        "type": "agent",
                        "name": "Profile agent",
                        "config": {
                            "prompt": "Create generated.txt",
                            "profile_id": profile["id"],
                        },
                    }
                ],
            )
        )
        service._model_client = lambda _model, _metadata: StudioWriteClient()

        service.start_flow(graph["id"])
        completed = wait_for_record(service, "task_graphs", graph["id"])
        assert completed["status"] == "completed"
        node = service.studio.get_graph(graph["id"])["nodes"][0]
        session = service.studio.get_session(node["session_id"])
        assert session["profile_id"] == profile["id"]
        assert session["permission_profile"] == "full"
        assert session["reasoning_effort"] == "high"
    finally:
        service.close()


def test_browser_runtime_rejects_non_web_urls_before_launch(tmp_path) -> None:
    browser = BrowserRuntime(tmp_path / "browser-runtime")
    with pytest.raises(BrowserRuntimeError, match="browser_url_scheme_not_allowed"):
        browser.launch("file:///C:/Windows/System32")


def test_unified_studio_agent_can_control_the_visible_browser(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    calls: list[str] = []
    service.browser = SimpleNamespace(
        is_running=lambda: False,
        launch=lambda: calls.append("launch") or {"running": True},
        navigate=lambda url, page_id=None: calls.append(f"navigate:{url}:{page_id}")
        or {"title": "Example", "url": url, "text": "Example Domain"},
        close=lambda: None,
    )
    try:
        project = create_project(service, tmp_path / "browser-agent")
        session = service.studio.create_session(
            SessionCreate(
                project_id=project["id"],
                title="Browser Agent",
                permission_profile="full",
            )
        )
        service._model_client = lambda _model, _metadata: BrowserToolClient()
        turn = service.queue_session_turn(
            session["id"], SessionTurnCreate(message="Open the example page")
        )
        completed = wait_for_turn(service, turn["id"])
        assert completed["status"] == "completed"
        assert calls == ["launch", "navigate:https://example.com:None"]
    finally:
        service.close()


def test_native_agent_browser_bridge_is_ephemeral_and_capability_scoped(
    settings, tmp_path
) -> None:
    service = EvaluationService(settings)
    calls: list[str] = []
    service.browser = SimpleNamespace(
        is_running=lambda: False,
        launch=lambda: calls.append("launch") or {"running": True},
        navigate=lambda url, page_id=None: calls.append(f"navigate:{url}:{page_id}")
        or {"title": "Example", "url": url},
        close=lambda: None,
    )
    try:
        project = create_project(service, tmp_path / "native-browser")
        session = service.studio.create_session(
            SessionCreate(
                project_id=project["id"],
                title="Native browser",
                permission_profile="full",
            )
        )
        turn = service.studio.queue_turn(
            session["id"], SessionTurnCreate(message="Use the visible browser")
        )
        token, definition = service._register_browser_bridge(
            session, turn["id"], threading.Event()
        )
        assert Path(definition["command"]).is_file()
        result = service.execute_browser_bridge_tool(
            token, "browser_navigate", {"url": "https://example.com"}
        )
        assert result["ok"] is True
        assert calls == ["launch", "navigate:https://example.com:None"]
        with pytest.raises(ValueError, match="browser_tool_not_allowed"):
            service.execute_browser_bridge_tool(token, "run_command", {})
        service._unregister_browser_bridge(token)
        with pytest.raises(ValueError, match="browser_bridge_expired"):
            service.execute_browser_bridge_tool(token, "browser_snapshot", {})
    finally:
        service.close()


def test_native_cli_adapters_receive_non_persistent_browser_mcp_configuration() -> None:
    bridge = {"command": r"C:\AgentBench\backend.exe", "args": ["--browser-mcp", "token"]}
    cases = {
        "codex_cli": ["exec", "--json", "{prompt}"],
        "claude_code_cli": ["--print", "{prompt}"],
        "kimi_code_cli": ["--print", "--prompt", "{prompt}"],
        "qoder_cli": ["--print", "{prompt}"],
        "opencode_cli": ["run", "{prompt}"],
        "cursor_cli": ["--print", "{prompt}"],
    }
    for runner_type, original in cases.items():
        args, environment = EvaluationService._studio_native_browser_options(
            original, runner_type, bridge, {}
        )
        if runner_type == "codex_cli":
            assert any("mcp_servers.agentbench_browser.command" in item for item in args)
        elif runner_type in {"claude_code_cli", "kimi_code_cli", "qoder_cli"}:
            assert "--mcp-config" in args
            config = json.loads(args[args.index("--mcp-config") + 1])
            assert config["mcpServers"]["agentbench_browser"]["command"] == bridge["command"]
        elif runner_type == "cursor_cli":
            assert args == original
            assert environment == {}
        else:
            config = json.loads(environment["OPENCODE_CONFIG_CONTENT"])
            assert config["mcp"]["agentbench_browser"]["command"][0] == bridge["command"]


def test_browser_mcp_protocol_lists_tools_and_returns_tool_results() -> None:
    bridge = BrowserMcpBridge("http://127.0.0.1:43765", "bridge-token")
    bridge._request = lambda *_args, **_kwargs: {
        "ok": True,
        "title": "Example",
        "url": "https://example.com",
    }
    initialized = bridge.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }
    )
    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    listed = bridge.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert {item["name"] for item in listed["result"]["tools"]} == {
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_fill",
        "browser_screenshot",
    }
    called = bridge.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "browser_navigate",
                "arguments": {"url": "https://example.com"},
            },
        }
    )
    assert called["result"]["isError"] is False
    assert "Example" in called["result"]["content"][0]["text"]


def test_unified_session_runtime_persists_output_events_and_file_changes(
    settings, tmp_path
) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "runtime-project")
        session = service.studio.create_session(
            SessionCreate(
                project_id=project["id"],
                runner_id=UNIFIED_RUNNER_ID,
                model_id=MOCK_MODEL_ID,
                title="Runtime execution",
            )
        )
        service._model_client = lambda _model, _metadata: StudioWriteClient()

        queued = service.queue_session_turn(
            session["id"], SessionTurnCreate(message="Create generated.txt")
        )
        completed = wait_for_turn(service, queued["id"])

        assert completed["status"] == "completed"
        assert completed["final_answer"].startswith("Created generated.txt")
        detail = service.studio.get_session(session["id"])
        assert detail["status"] == "idle"
        assert detail["messages"][-1]["role"] == "assistant"
        assert detail["messages"][-1]["content"] == completed["final_answer"]
        assert detail["tokens_input"] == 140
        assert detail["tokens_output"] == 37
        assert (tmp_path / "runtime-project" / "generated.txt").read_text(
            encoding="utf-8"
        ) == "studio runtime\n"
        assert detail["file_changes"] == [
            {
                **detail["file_changes"][0],
                "turn_id": queued["id"],
                "path": "generated.txt",
                "change_type": "created",
                "status": "observed",
            }
        ]

        public_types = {event["event_type"] for event in detail["events"]}
        assert {"tool.requested", "tool.completed", "file.changed", "turn.completed"} <= (
            public_types
        )
        assert "model.requested" not in public_types
        assert "model.responded" not in public_types
        all_types = {
            event["event_type"]
            for event in service.studio.get_events(
                session["id"], include_sensitive=True
            )
        }
        assert {"model.requested", "model.responded"} <= all_types
    finally:
        service.close()


def test_cancel_endpoint_resolves_a_queued_session(settings, tmp_path) -> None:
    with TestClient(create_app(settings)) as client:
        root = tmp_path / "cancel-project"
        root.mkdir()
        project = client.post(
            "/api/v1/projects",
            json={
                "name": "Cancel project",
                "root_path": str(root),
                "default_runner_id": UNIFIED_RUNNER_ID,
                "default_model_id": MOCK_MODEL_ID,
            },
        ).json()
        session = client.post(
            "/api/v1/sessions",
            json={"project_id": project["id"], "title": "Cancelable turn"},
        ).json()
        service = client.app.state.service
        turn = service.studio.queue_turn(
            session["id"], SessionTurnCreate(message="Wait for cancellation")
        )

        response = client.post(f"/api/v1/sessions/{session['id']}/cancel")

        assert response.status_code == 202
        assert response.json()["status"] == "cancelled"
        stored = service.database.fetch_one(
            "SELECT status,error_code FROM session_turns WHERE id=?", (turn["id"],)
        )
        assert stored == {"status": "cancelled", "error_code": "user_cancelled"}


def test_running_unified_session_honors_cancellation(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    client = BlockingStudioClient()
    try:
        project = create_project(service, tmp_path / "running-cancel-project")
        session = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Running cancellation")
        )
        service._model_client = lambda _model, _metadata: client
        turn = service.queue_session_turn(
            session["id"], SessionTurnCreate(message="Begin a cancellable response")
        )
        assert client.started.wait(3)

        service.cancel_session(session["id"])
        client.release.set()
        cancelled = wait_for_turn(service, turn["id"])

        assert cancelled["status"] == "cancelled"
        assert cancelled["error_code"] == "user_cancelled"
        detail = service.studio.get_session(session["id"])
        assert detail["status"] == "cancelled"
        assert detail["messages"][-1]["role"] == "user"
        assert detail["events"][-1]["event_type"] == "turn.cancelled"
    finally:
        client.release.set()
        service.close()


def test_running_session_queues_and_dispatches_follow_up_turns(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    model_client = QueuedStudioClient()
    try:
        project = create_project(service, tmp_path / "queued-follow-up-project")
        session = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Queued follow-ups")
        )
        service._model_client = lambda _model, _metadata: model_client
        first = service.queue_session_turn(
            session["id"], SessionTurnCreate(message="Run the first instruction")
        )
        assert model_client.started.wait(3)

        second = service.queue_session_turn(
            session["id"], SessionTurnCreate(message="Run this after the first")
        )
        assert second["status"] == "queued"
        assert second["queued_behind_active"] is True
        assert service.database.fetch_one(
            "SELECT status FROM session_turns WHERE id=?", (second["id"],)
        ) == {"status": "queued"}

        model_client.release.set()
        assert wait_for_turn(service, first["id"])["status"] == "completed"
        assert wait_for_turn(service, second["id"])["status"] == "completed"
        detail = service.studio.get_session(session["id"])
        assert detail["status"] == "idle"
        assert [turn["status"] for turn in detail["turns"]] == ["completed", "completed"]
        assert model_client.calls == 2
        assert {event["event_type"] for event in detail["events"]} >= {
            "turn.enqueued",
            "turn.dequeued",
        }
    finally:
        model_client.release.set()
        service.close()


def test_queued_follow_up_can_be_removed_without_cancelling_active_turn(
    settings, tmp_path
) -> None:
    service = EvaluationService(settings)
    model_client = BlockingStudioClient()
    try:
        project = create_project(service, tmp_path / "remove-queued-project")
        session = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Remove queued turn")
        )
        service._model_client = lambda _model, _metadata: model_client
        active = service.queue_session_turn(
            session["id"], SessionTurnCreate(message="Keep running")
        )
        assert model_client.started.wait(3)
        queued = service.queue_session_turn(
            session["id"], SessionTurnCreate(message="Remove this queued item")
        )

        removed = service.studio.cancel_queued_turn(session["id"], queued["id"])

        assert removed["status"] == "running"
        assert removed["removed_turn_id"] == queued["id"]
        assert service.database.fetch_one(
            "SELECT status,error_code FROM session_turns WHERE id=?", (queued["id"],)
        ) == {"status": "cancelled", "error_code": "queue_removed"}
        assert service.database.fetch_one(
            "SELECT status FROM session_turns WHERE id=?", (active["id"],)
        ) == {"status": "running"}
    finally:
        service.cancel_session(session["id"])
        model_client.release.set()
        wait_for_turn(service, active["id"])
        service.close()


def test_shell_approval_really_pauses_and_resumes_the_running_turn(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "approval-runtime")
        session = service.studio.create_session(
            SessionCreate(
                project_id=project["id"],
                title="Command approval",
                permission_profile="standard",
            )
        )
        service._model_client = lambda _model, _metadata: ShellApprovalClient()
        service.docker = SimpleNamespace(
            run=lambda *_args, **_kwargs: CommandResult(True, 0, "Python 3", "", 1)
        )
        turn = service.queue_session_turn(
            session["id"], SessionTurnCreate(message="Run a version check")
        )
        deadline = time.monotonic() + 5
        approval = None
        while time.monotonic() < deadline:
            pending = service.studio.list_approvals(session["id"], "pending")
            if pending:
                approval = pending[0]
                break
            time.sleep(0.02)
        assert approval is not None
        assert service.studio.get_session(session["id"])["status"] == "waiting_approval"
        assert service.database.fetch_one(
            "SELECT status FROM session_turns WHERE id=?", (turn["id"],)
        ) == {"status": "waiting_approval"}

        service.studio.decide_approval(
            approval["id"], ApprovalDecision(decision="allow_once", reason="Expected test")
        )
        completed = wait_for_turn(service, turn["id"])
        assert completed["status"] == "completed"
        assert completed["final_answer"] == "Approved command completed."
    finally:
        service.close()


def test_file_change_diff_can_be_rejected_without_clobbering_later_edits(
    settings, tmp_path
) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "diff-project")
        session = service.studio.create_session(
            SessionCreate(project_id=project["id"], title="Diff review")
        )
        service._model_client = lambda _model, _metadata: StudioWriteClient()
        turn = service.queue_session_turn(
            session["id"], SessionTurnCreate(message="Create a reviewable file")
        )
        wait_for_turn(service, turn["id"])
        change = service.studio.get_session(session["id"])["file_changes"][0]

        preview = service.studio.file_change_diff(session["id"], change["id"])
        assert "+studio runtime" in preview["diff"]
        assert preview["can_restore"] is True

        rejected = service.studio.review_file_change(
            change["id"],
            FileChangeReview(action="reject"),
        )
        assert rejected["status"] == "rejected"
        assert not (tmp_path / "diff-project" / "generated.txt").exists()
    finally:
        service.close()


def test_task_start_runs_a_real_agent_session(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "task-runtime")
        task = service.studio.create_task(
            TaskItemCreate(
                project_id=project["id"],
                title="Generate task artifact",
                description="Create generated.txt",
                runner_id=UNIFIED_RUNNER_ID,
                model_id=MOCK_MODEL_ID,
                acceptance_criteria=[
                    {"text": "generated.txt exists and contains studio runtime"}
                ],
            )
        )
        service._model_client = lambda _model, _metadata: StudioWriteClient()

        queued = service.start_task(task["id"])
        assert queued["status"] == "queued"
        completed = wait_for_record(service, "task_items", task["id"])
        assert completed["status"] == "completed"
        assert completed["session_id"]
        assert service.studio.get_session(completed["session_id"])["status"] == "idle"
        detail = service.studio.get_task_detail(task["id"])
        assert [event["event_type"] for event in detail["events"]] == [
            "task.created",
            "task.queued",
            "task.running",
            "task.completed",
        ]
        user_message = service.database.fetch_one(
            "SELECT content FROM session_messages WHERE session_id=? AND role='user'",
            (completed["session_id"],),
        )
        assert user_message is not None
        assert "验收标准" in user_message["content"]
        assert "不要在未验证时宣称已满足" in user_message["content"]
    finally:
        service.close()


def test_flow_scheduler_executes_agent_node_and_persists_output(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "flow-runtime")
        graph = service.studio.create_graph(
            TaskGraphCreate(
                project_id=project["id"],
                name="Single node runtime",
                settings={"max_retries": 0, "max_concurrency": 2},
                nodes=[
                    {
                        "id": "build",
                        "type": "agent",
                        "name": "Build",
                        "config": {"prompt": "Create generated.txt"},
                    }
                ],
            )
        )
        service._model_client = lambda _model, _metadata: StudioWriteClient()

        service.start_flow(graph["id"])
        completed = wait_for_record(service, "task_graphs", graph["id"])
        assert completed["status"] == "completed"
        node = service.studio.get_graph(graph["id"])["nodes"][0]
        assert node["status"] == "completed"
        assert node["session_id"]
        assert node["output"]["summary"].startswith("Created generated.txt")
    finally:
        service.close()


def test_flow_definition_can_be_edited_and_condition_paths_are_skipped(settings, tmp_path) -> None:
    service = EvaluationService(settings)
    try:
        project = create_project(service, tmp_path / "flow-editor")
        graph = service.studio.create_graph(
            TaskGraphCreate(
                project_id=project["id"],
                name="Editable flow",
                nodes=[{"id": "start", "type": "condition", "name": "Gate"}],
            )
        )
        updated = service.studio.update_graph(
            graph["id"],
            TaskGraphUpdate(
                name="Edited flow",
                settings={"max_retries": 0, "max_concurrency": 2},
                nodes=[
                    {
                        "id": "gate",
                        "type": "condition",
                        "name": "Gate",
                        "config": {"operator": "contains", "value": "never"},
                    },
                    {"id": "yes", "type": "condition", "name": "Yes branch"},
                    {"id": "no", "type": "condition", "name": "No branch"},
                ],
                edges=[
                    {"source": "gate", "target": "yes", "condition": {"when": True}},
                    {"source": "gate", "target": "no", "condition": {"when": False}},
                ],
            ),
        )
        assert updated["name"] == "Edited flow"
        assert len(updated["nodes"]) == 3

        service.start_flow(graph["id"])
        completed = wait_for_record(service, "task_graphs", graph["id"])
        assert completed["status"] == "completed"
        statuses = {node["name"]: node["status"] for node in service.studio.get_graph(graph["id"])["nodes"]}
        assert statuses == {"Gate": "completed", "Yes branch": "skipped", "No branch": "completed"}

        service.studio.delete_graph(graph["id"])
        assert service.studio.list_graphs() == []
    finally:
        service.close()


def test_flow_worktree_merge_applies_nul_delimited_git_changes(tmp_path) -> None:
    project_root = tmp_path / "flow-merge-project"
    project_root.mkdir()
    (project_root / "modified.txt").write_text("before\n", encoding="utf-8")
    (project_root / "deleted.txt").write_text("delete me\n", encoding="utf-8")
    (project_root / "renamed-old.txt").write_text("rename me\n", encoding="utf-8")
    for args in (
        ["init"],
        ["config", "user.email", "agentbench@example.invalid"],
        ["config", "user.name", "AgentBench Test"],
        ["add", "."],
        ["commit", "-m", "fixture"],
    ):
        subprocess.run(
            ["git", "-C", str(project_root), *args],
            check=True,
            capture_output=True,
        )

    worktree = tmp_path / "isolated-worktree"
    subprocess.run(
        ["git", "-C", str(project_root), "worktree", "add", "--detach", str(worktree)],
        check=True,
        capture_output=True,
    )
    (worktree / "modified.txt").write_text("after\n", encoding="utf-8")
    (worktree / "deleted.txt").unlink()
    (worktree / "renamed-old.txt").rename(worktree / "renamed-new.txt")
    (worktree / "created.txt").write_text("created\n", encoding="utf-8")

    applied = EvaluationService._merge_flow_worktree(worktree, project_root)

    assert set(applied) == {
        "modified.txt",
        "deleted.txt",
        "renamed-old.txt",
        "renamed-new.txt",
        "created.txt",
    }
    assert (project_root / "modified.txt").read_text(encoding="utf-8") == "after\n"
    assert not (project_root / "deleted.txt").exists()
    assert not (project_root / "renamed-old.txt").exists()
    assert (project_root / "renamed-new.txt").read_text(encoding="utf-8") == "rename me\n"
    assert (project_root / "created.txt").read_text(encoding="utf-8") == "created\n"


def test_mcp_health_and_tool_call_use_real_json_rpc_stdio(settings, tmp_path) -> None:
    server_script = tmp_path / "mcp_server.py"
    server_script.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    msg=json.loads(line); method=msg.get('method'); rid=msg.get('id')\n"
        "    if rid is None: continue\n"
        "    if method=='initialize': result={'serverInfo': {'name':'test-mcp','version':'1'}}\n"
        "    elif method=='tools/list': result={'tools':[{'name':'echo','description':'Echo','inputSchema':{'type':'object'}}]}\n"
        "    elif method=='tools/call': result={'content':[{'type':'text','text':str(msg['params']['arguments'].get('value'))}]}\n"
        "    else: result={}\n"
        "    print(json.dumps({'jsonrpc':'2.0','id':rid,'result':result}), flush=True)\n"
        ,
        encoding="utf-8",
    )
    service = EvaluationService(settings)
    try:
        mcp = service.studio.create_mcp_server(
            McpServerCreate(
                name="Test MCP",
                transport="stdio",
                command=sys.executable,
                args=[str(server_script)],
            )
        )
        checked = service.check_mcp_server(mcp["id"])
        assert checked["health_status"] == "online"
        assert [tool["name"] for tool in checked["tools"]] == ["echo"]
        result = service.execute_mcp_tool(
            mcp["id"],
            McpToolCall(tool_name="echo", arguments={"value": "hello"}),
        )
        assert result["ok"] is True
        assert result["result"]["content"][0]["text"] == "hello"

        updated = service.studio.update_mcp_server(
            mcp["id"], McpServerUpdate(name="Renamed MCP", enabled=False)
        )
        assert updated["name"] == "Renamed MCP"
        assert updated["enabled"] is False
        service.studio.delete_mcp_server(mcp["id"])
        assert service.studio.list_mcp_servers() == []
    finally:
        service.close()


def test_chat_session_requires_no_project_and_stays_isolated(settings) -> None:
    service = EvaluationService(settings)
    try:
        session = service.studio.create_session(
            SessionCreate(session_mode="chat", title="Pure conversation")
        )

        assert session["session_mode"] == "chat"
        assert session["project_id"] is None
        assert session["project_name"] == "纯对话"
        assert session["permission_profile"] == "readonly"
        assert Path(session["workspace_path"]).is_relative_to(
            (settings.data_dir / "chat-sessions").resolve()
        )
        assert service._studio_session_tools(session) == []
        assert all(project["id"] != "__agentbench_chat__" for project in service.studio.list_projects())
        assert service.studio.dashboard()["project_count"] == 0

        fork = service.studio.fork_session(session["id"], SessionForkCreate())
        assert fork["session_mode"] == "chat"
        assert fork["project_id"] is None
        assert fork["permission_profile"] == "readonly"

        with pytest.raises(ValueError, match="chat_session_is_always_readonly"):
            service.studio.update_session(session["id"], {"permission_profile": "full"})
        with pytest.raises(ValueError, match="chat_session_has_no_terminal"):
            service.start_terminal(session["id"], TerminalCreate())
    finally:
        service.close()


def test_workspace_session_still_requires_project(settings) -> None:
    service = EvaluationService(settings)
    try:
        with pytest.raises(ValueError, match="workspace_session_requires_project"):
            service.studio.create_session(SessionCreate(title="Missing project"))
    finally:
        service.close()
