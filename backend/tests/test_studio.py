from __future__ import annotations

import json
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
from agentbench.execution import CommandResult
from agentbench.model_clients import ModelDecision, ModelUsage
from agentbench.schemas import (
    ApprovalDecision,
    FileChangeReview,
    McpServerCreate,
    McpServerUpdate,
    McpToolCall,
    ProjectCreate,
    SessionAttachmentImport,
    SessionCreate,
    SessionTurnCreate,
    SkillPackCreate,
    SkillPackUpdate,
    TaskGraphCreate,
    TaskGraphUpdate,
    TaskItemCreate,
    TerminalCreate,
    TerminalInput,
)
from agentbench.service import EvaluationService


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
        assert service.database.fetch_one("SELECT version FROM schema_meta") == {"version": 8}
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
        "opencode_cli": ["run", "{prompt}"],
    }
    for runner_type, original in cases.items():
        args, environment = EvaluationService._studio_native_browser_options(
            original, runner_type, bridge, {}
        )
        if runner_type == "codex_cli":
            assert any("mcp_servers.agentbench_browser.command" in item for item in args)
        elif runner_type in {"claude_code_cli", "kimi_code_cli"}:
            assert "--mcp-config" in args
            config = json.loads(args[args.index("--mcp-config") + 1])
            assert config["mcpServers"]["agentbench_browser"]["command"] == bridge["command"]
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
            )
        )
        service._model_client = lambda _model, _metadata: StudioWriteClient()

        queued = service.start_task(task["id"])
        assert queued["status"] == "queued"
        completed = wait_for_record(service, "task_items", task["id"])
        assert completed["status"] == "completed"
        assert completed["session_id"]
        assert service.studio.get_session(completed["session_id"])["status"] == "idle"
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
