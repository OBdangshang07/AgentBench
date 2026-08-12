import asyncio
import json
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from . import __version__
from .config import Settings
from .reports import export_exam_report
from .schemas import (
    ApprovalDecision,
    AppSettingUpdate,
    BrowserAction,
    BrowserLaunch,
    BrowserNavigate,
    BrowserToolCall,
    ExperimentCreate,
    FileChangeReview,
    ManualScoreUpdate,
    MathQuestionUpdate,
    McpServerCreate,
    McpServerUpdate,
    McpToolCall,
    ModelCreate,
    ModelDiscoveryRequest,
    ModelUpdate,
    ProjectCreate,
    ProjectRootCreate,
    ProjectUpdate,
    RunnerCreate,
    RuntimeProfileCreate,
    RuntimeProfileUpdate,
    SessionAttachmentImport,
    SessionCreate,
    SessionForkCreate,
    SessionTurnCreate,
    SessionUpdate,
    SkillPackCreate,
    SkillPackUpdate,
    StudioToolCall,
    TaskBulkAction,
    TaskGraphCreate,
    TaskGraphUpdate,
    TaskItemCreate,
    TaskItemUpdate,
    TerminalCreate,
    TerminalInput,
    TerminalResize,
    TestCaseImport,
)
from .service import EvaluationService

_MATERIAL_MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".py": "text/x-python",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    service = EvaluationService(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        service.close()

    app = FastAPI(
        title="AgentBench Desktop API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            # Tauri uses an HTTP custom-protocol origin on Windows.
            "http://tauri.localhost",
            "tauri://localhost",
            "https://tauri.localhost",
        ],
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):14\d{2}$",
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Accept"],
    )

    @app.exception_handler(KeyError)
    async def key_error_handler(_: Request, exc: KeyError):
        return Response(
            content=json.dumps({"detail": str(exc).strip("'")}),
            status_code=404,
            media_type="application/json",
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError):
        return Response(
            content=json.dumps({"detail": str(exc)}),
            status_code=400,
            media_type="application/json",
        )

    def get_service() -> EvaluationService:
        return service

    Service = Annotated[EvaluationService, Depends(get_service)]

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "name": "AgentBench Desktop", "version": __version__}

    @app.get("/api/v1/dashboard")
    def dashboard(svc: Service) -> dict[str, Any]:
        return svc.dashboard()

    @app.get("/api/v1/studio/dashboard")
    def studio_dashboard(svc: Service) -> dict[str, Any]:
        return svc.studio.dashboard()

    @app.get("/api/v1/studio/search")
    def studio_search(
        svc: Service,
        query: str = Query(min_length=1, max_length=160),
        limit: int = Query(default=30, ge=1, le=80),
    ) -> list[dict[str, Any]]:
        return svc.studio.search_workspace(query, limit)

    @app.get("/api/v1/projects")
    def projects(svc: Service, include_archived: bool = False) -> list[dict[str, Any]]:
        return svc.studio.list_projects(include_archived)

    @app.post("/api/v1/projects", status_code=201)
    def create_project(payload: ProjectCreate, svc: Service) -> dict[str, Any]:
        return svc.studio.create_project(payload)

    @app.get("/api/v1/projects/{project_id}")
    def project(project_id: str, svc: Service) -> dict[str, Any]:
        return svc.studio.get_project(project_id)

    @app.get("/api/v1/projects/{project_id}/health")
    def project_health(project_id: str, svc: Service) -> dict[str, Any]:
        return svc.studio.project_health(project_id)

    @app.patch("/api/v1/projects/{project_id}")
    def update_project(
        project_id: str, payload: ProjectUpdate, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.update_project(project_id, payload.model_dump(exclude_unset=True))

    @app.delete("/api/v1/projects/{project_id}")
    def archive_project(project_id: str, svc: Service) -> dict[str, Any]:
        return svc.studio.archive_project(project_id)

    @app.post("/api/v1/projects/{project_id}/roots", status_code=201)
    def add_project_root(
        project_id: str, payload: ProjectRootCreate, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.add_project_root(project_id, payload)

    @app.get("/api/v1/projects/{project_id}/files")
    def project_files(
        project_id: str,
        svc: Service,
        path: str = Query(default=".", max_length=2048),
        limit: int = Query(default=500, ge=1, le=2000),
    ) -> dict[str, Any]:
        return svc.studio.list_project_files(project_id, path, limit)

    @app.get("/api/v1/projects/{project_id}/files/search")
    def search_project_files(
        project_id: str,
        svc: Service,
        query: str = Query(min_length=2, max_length=160),
        limit: int = Query(default=120, ge=1, le=200),
    ) -> dict[str, Any]:
        return svc.studio.search_project_files(project_id, query, limit)

    @app.get("/api/v1/projects/{project_id}/file")
    def project_file(
        project_id: str,
        svc: Service,
        path: str = Query(min_length=1, max_length=2048),
    ) -> dict[str, Any]:
        return svc.studio.read_project_file(project_id, path)

    @app.get("/api/v1/sessions")
    def sessions(
        svc: Service,
        project_id: str | None = None,
        include_archived: bool = False,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return svc.studio.list_sessions(project_id, include_archived, limit)

    @app.get("/api/v1/runtime-profiles")
    def runtime_profiles(svc: Service) -> list[dict[str, Any]]:
        return svc.studio.list_runtime_profiles()

    @app.post("/api/v1/runtime-profiles", status_code=201)
    def create_runtime_profile(
        payload: RuntimeProfileCreate, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.create_runtime_profile(payload)

    @app.patch("/api/v1/runtime-profiles/{profile_id}")
    def update_runtime_profile(
        profile_id: str, payload: RuntimeProfileUpdate, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.update_runtime_profile(
            profile_id, payload.model_dump(exclude_unset=True)
        )

    @app.delete("/api/v1/runtime-profiles/{profile_id}", status_code=204)
    def delete_runtime_profile(profile_id: str, svc: Service) -> Response:
        svc.studio.delete_runtime_profile(profile_id)
        return Response(status_code=204)

    @app.post("/api/v1/sessions", status_code=201)
    def create_session(payload: SessionCreate, svc: Service) -> dict[str, Any]:
        return svc.studio.create_session(payload)

    @app.get("/api/v1/sessions/{session_id}")
    def session(
        session_id: str,
        svc: Service,
        message_limit: int | None = Query(default=None, ge=20, le=2000),
    ) -> dict[str, Any]:
        return svc.studio.get_session(session_id, message_limit)

    @app.patch("/api/v1/sessions/{session_id}")
    def update_session(
        session_id: str, payload: SessionUpdate, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.update_session(session_id, payload.model_dump(exclude_unset=True))

    @app.post("/api/v1/sessions/{session_id}/fork", status_code=201)
    def fork_session(
        session_id: str, payload: SessionForkCreate, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.fork_session(session_id, payload)

    @app.post("/api/v1/sessions/{session_id}/turns", status_code=202)
    def create_session_turn(
        session_id: str, payload: SessionTurnCreate, svc: Service
    ) -> dict[str, Any]:
        return svc.queue_session_turn(session_id, payload)

    @app.delete("/api/v1/sessions/{session_id}/turns/{turn_id}")
    def cancel_queued_session_turn(
        session_id: str, turn_id: str, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.cancel_queued_turn(session_id, turn_id)

    @app.post("/api/v1/sessions/{session_id}/attachments", status_code=201)
    def import_session_attachments(
        session_id: str, payload: SessionAttachmentImport, svc: Service
    ) -> list[dict[str, Any]]:
        return svc.studio.import_session_attachments(session_id, payload)

    @app.delete(
        "/api/v1/sessions/{session_id}/attachments/{attachment_id}", status_code=204
    )
    def delete_session_attachment(
        session_id: str, attachment_id: str, svc: Service
    ) -> Response:
        svc.studio.delete_session_attachment(session_id, attachment_id)
        return Response(status_code=204)

    @app.post("/api/v1/sessions/{session_id}/cancel", status_code=202)
    def cancel_session(session_id: str, svc: Service) -> dict[str, Any]:
        return svc.cancel_session(session_id)

    @app.post("/api/v1/sessions/{session_id}/terminals", status_code=201)
    def start_terminal(
        session_id: str, payload: TerminalCreate, svc: Service
    ) -> dict[str, Any]:
        return svc.start_terminal(session_id, payload)

    @app.get("/api/v1/sessions/{session_id}/terminals")
    def list_terminals(session_id: str, svc: Service) -> list[dict[str, Any]]:
        return svc.list_terminals(session_id)

    @app.get("/api/v1/sessions/{session_id}/terminals/{terminal_id}")
    def read_terminal(
        session_id: str,
        terminal_id: str,
        svc: Service,
        after: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return svc.read_terminal(session_id, terminal_id, after)

    @app.post("/api/v1/sessions/{session_id}/terminals/{terminal_id}/input")
    def write_terminal(
        session_id: str,
        terminal_id: str,
        payload: TerminalInput,
        svc: Service,
    ) -> dict[str, Any]:
        return svc.write_terminal(session_id, terminal_id, payload)

    @app.post("/api/v1/sessions/{session_id}/terminals/{terminal_id}/resize")
    def resize_terminal(
        session_id: str,
        terminal_id: str,
        payload: TerminalResize,
        svc: Service,
    ) -> dict[str, Any]:
        return svc.resize_terminal(session_id, terminal_id, payload)

    @app.delete("/api/v1/sessions/{session_id}/terminals/{terminal_id}")
    def close_terminal(
        session_id: str, terminal_id: str, svc: Service
    ) -> dict[str, Any]:
        return svc.close_terminal(session_id, terminal_id)

    @app.get("/api/v1/sessions/{session_id}/events")
    def session_events(
        session_id: str,
        svc: Service,
        after: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        return svc.studio.get_events(session_id, after)

    @app.get("/api/v1/sessions/{session_id}/changes/{change_id}")
    def session_file_change(
        session_id: str, change_id: str, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.file_change_diff(session_id, change_id)

    @app.post("/api/v1/file-changes/{change_id}/review")
    def review_file_change(
        change_id: str, payload: FileChangeReview, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.review_file_change(change_id, payload)

    @app.get("/api/v1/sessions/{session_id}/events/stream")
    async def session_event_stream(
        session_id: str,
        request: Request,
        svc: Service,
        after: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        svc.studio.get_session(session_id)

        async def stream():
            cursor = after
            idle_ticks = 0
            while True:
                if await request.is_disconnected():
                    break
                events = svc.studio.get_events(session_id, cursor)
                for item in events:
                    cursor = item["seq"]
                    yield f"id: {cursor}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                    idle_ticks = 0
                idle_ticks += 1
                if idle_ticks % 15 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/v1/approvals")
    def approvals(
        svc: Service,
        session_id: str | None = None,
        status: str | None = Query(default=None, pattern="^(pending|approved|denied)$"),
    ) -> list[dict[str, Any]]:
        return svc.studio.list_approvals(session_id, status)

    @app.post("/api/v1/approvals/{approval_id}/decision")
    def decide_approval(
        approval_id: str, payload: ApprovalDecision, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.decide_approval(approval_id, payload)

    @app.get("/api/v1/tasks")
    def tasks(
        svc: Service,
        project_id: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        return svc.studio.list_tasks(project_id, include_archived)

    @app.post("/api/v1/tasks", status_code=201)
    def create_task(payload: TaskItemCreate, svc: Service) -> dict[str, Any]:
        return svc.studio.create_task(payload)

    @app.post("/api/v1/tasks/bulk")
    def bulk_update_tasks(payload: TaskBulkAction, svc: Service) -> dict[str, Any]:
        return svc.studio.bulk_update_tasks(
            payload.task_ids,
            payload.action,
            payload.value,
        )

    @app.get("/api/v1/tasks/{task_id}")
    def task_detail(task_id: str, svc: Service) -> dict[str, Any]:
        return svc.studio.get_task_detail(task_id)

    @app.get("/api/v1/tasks/{task_id}/events")
    def task_events(
        task_id: str,
        svc: Service,
        limit: int = Query(default=300, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return svc.studio.list_task_events(task_id, limit)

    @app.patch("/api/v1/tasks/{task_id}")
    def update_task(
        task_id: str, payload: TaskItemUpdate, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.update_task(task_id, payload.model_dump(exclude_unset=True))

    @app.delete("/api/v1/tasks/{task_id}")
    def archive_task(task_id: str, svc: Service) -> dict[str, Any]:
        task = svc.studio.get_task(task_id)
        if task["status"] in {"queued", "running", "approval"}:
            raise ValueError("active_task_cannot_be_archived")
        return svc.studio.update_task(task_id, {"archived": True})

    @app.post("/api/v1/tasks/{task_id}/duplicate", status_code=201)
    def duplicate_task(task_id: str, svc: Service) -> dict[str, Any]:
        return svc.studio.duplicate_task(task_id)

    @app.post("/api/v1/tasks/{task_id}/start", status_code=202)
    def start_task(task_id: str, svc: Service) -> dict[str, Any]:
        return svc.start_task(task_id)

    @app.post("/api/v1/tasks/{task_id}/cancel", status_code=202)
    def cancel_task(task_id: str, svc: Service) -> dict[str, Any]:
        return svc.cancel_task(task_id)

    @app.get("/api/v1/flows")
    def flows(svc: Service, project_id: str | None = None) -> list[dict[str, Any]]:
        return svc.studio.list_graphs(project_id)

    @app.get("/api/v1/flow-templates")
    def flow_templates(svc: Service) -> list[dict[str, Any]]:
        return svc.studio.list_graph_templates()

    @app.post("/api/v1/flows", status_code=201)
    def create_flow(payload: TaskGraphCreate, svc: Service) -> dict[str, Any]:
        return svc.studio.create_graph(payload)

    @app.post("/api/v1/flows/validate")
    def validate_flow_draft(payload: TaskGraphCreate, svc: Service) -> dict[str, Any]:
        return svc.studio.validate_graph_definition(
            project_id=payload.project_id,
            settings=payload.settings,
            nodes=payload.nodes,
            edges=payload.edges,
        )

    @app.get("/api/v1/flows/{graph_id}")
    def flow(graph_id: str, svc: Service) -> dict[str, Any]:
        return svc.studio.get_graph(graph_id)

    @app.patch("/api/v1/flows/{graph_id}")
    def update_flow(
        graph_id: str, payload: TaskGraphUpdate, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.update_graph(graph_id, payload)

    @app.get("/api/v1/flows/{graph_id}/validation")
    def validate_flow(graph_id: str, svc: Service) -> dict[str, Any]:
        return svc.studio.validate_graph(graph_id)

    @app.post("/api/v1/flows/{graph_id}/dry-run", status_code=201)
    def dry_run_flow(graph_id: str, svc: Service) -> dict[str, Any]:
        return svc.studio.dry_run_graph(graph_id)

    @app.get("/api/v1/flows/{graph_id}/versions")
    def flow_versions(graph_id: str, svc: Service) -> list[dict[str, Any]]:
        return svc.studio.list_graph_versions(graph_id)

    @app.post("/api/v1/flows/{graph_id}/versions/{version_no}/restore")
    def restore_flow_version(graph_id: str, version_no: int, svc: Service) -> dict[str, Any]:
        return svc.studio.restore_graph_version(graph_id, version_no)

    @app.get("/api/v1/flows/{graph_id}/runs")
    def flow_runs(
        graph_id: str, svc: Service, limit: int = Query(default=50, ge=1, le=200)
    ) -> list[dict[str, Any]]:
        return svc.studio.list_graph_runs(graph_id, limit)

    @app.delete("/api/v1/flows/{graph_id}", status_code=204)
    def delete_flow(graph_id: str, svc: Service) -> Response:
        svc.studio.delete_graph(graph_id)
        return Response(status_code=204)

    @app.post("/api/v1/flows/{graph_id}/run", status_code=202)
    def run_flow(graph_id: str, svc: Service) -> dict[str, Any]:
        return svc.start_flow(graph_id)

    @app.post("/api/v1/flows/{graph_id}/cancel", status_code=202)
    def cancel_flow(graph_id: str, svc: Service) -> dict[str, Any]:
        return svc.cancel_flow(graph_id)

    @app.post("/api/v1/flows/{graph_id}/nodes/{node_id}/retry", status_code=202)
    def retry_flow_node(graph_id: str, node_id: str, svc: Service) -> dict[str, Any]:
        return svc.retry_flow_node(graph_id, node_id)

    @app.post("/api/v1/flows/{graph_id}/nodes/{node_id}/test", status_code=202)
    def test_flow_node(graph_id: str, node_id: str, svc: Service) -> dict[str, Any]:
        return svc.start_flow_node_test(graph_id, node_id)

    @app.get("/api/v1/mcp-servers")
    def mcp_servers(svc: Service) -> list[dict[str, Any]]:
        return svc.studio.list_mcp_servers()

    @app.post("/api/v1/mcp-servers", status_code=201)
    def create_mcp_server(payload: McpServerCreate, svc: Service) -> dict[str, Any]:
        return svc.studio.create_mcp_server(payload)

    @app.patch("/api/v1/mcp-servers/{server_id}")
    def update_mcp_server(
        server_id: str, payload: McpServerUpdate, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.update_mcp_server(server_id, payload)

    @app.delete("/api/v1/mcp-servers/{server_id}", status_code=204)
    def delete_mcp_server(server_id: str, svc: Service) -> Response:
        svc.studio.delete_mcp_server(server_id)
        return Response(status_code=204)

    @app.post("/api/v1/mcp-servers/health")
    def check_all_mcp_servers(svc: Service) -> list[dict[str, Any]]:
        return svc.check_all_mcp_servers()

    @app.post("/api/v1/mcp-servers/{server_id}/health")
    def check_mcp_server(server_id: str, svc: Service) -> dict[str, Any]:
        return svc.check_mcp_server(server_id)

    @app.post("/api/v1/mcp-servers/{server_id}/tools/call")
    def execute_mcp_tool(
        server_id: str, payload: McpToolCall, svc: Service
    ) -> dict[str, Any]:
        return svc.execute_mcp_tool(server_id, payload)

    @app.get("/api/v1/skill-packs")
    def skill_packs(svc: Service) -> list[dict[str, Any]]:
        return svc.studio.list_skill_packs()

    @app.post("/api/v1/skill-packs", status_code=201)
    def create_skill_pack(payload: SkillPackCreate, svc: Service) -> dict[str, Any]:
        return svc.studio.create_skill_pack(payload)

    @app.patch("/api/v1/skill-packs/{pack_id}")
    def update_skill_pack(
        pack_id: str, payload: SkillPackUpdate, svc: Service
    ) -> dict[str, Any]:
        return svc.studio.update_skill_pack(pack_id, payload)

    @app.delete("/api/v1/skill-packs/{pack_id}", status_code=204)
    def delete_skill_pack(pack_id: str, svc: Service) -> Response:
        svc.studio.delete_skill_pack(pack_id)
        return Response(status_code=204)

    @app.get("/api/v1/tools/status")
    def tool_gateway_status(svc: Service) -> list[dict[str, Any]]:
        return svc.tool_gateway_status()

    @app.get("/api/v1/browser/status")
    def browser_status(svc: Service) -> dict[str, Any]:
        return svc.browser.status()

    @app.post("/api/v1/browser/launch")
    def browser_launch(payload: BrowserLaunch, svc: Service) -> dict[str, Any]:
        return svc.browser.launch(payload.url)

    @app.post("/api/v1/browser/pages")
    def browser_new_page(payload: BrowserLaunch, svc: Service) -> dict[str, Any]:
        return svc.browser.new_page(payload.url)

    @app.get("/api/v1/browser/pages")
    def browser_pages(svc: Service) -> list[dict[str, Any]]:
        return svc.browser.pages()

    @app.delete("/api/v1/browser/pages/{page_id}")
    def browser_close_page(page_id: str, svc: Service) -> dict[str, Any]:
        return svc.browser.close_page(page_id)

    @app.post("/api/v1/browser/navigate")
    def browser_navigate(payload: BrowserNavigate, svc: Service) -> dict[str, Any]:
        return svc.browser.navigate(payload.url, payload.page_id)

    @app.get("/api/v1/browser/snapshot")
    def browser_snapshot(
        svc: Service, page_id: str | None = None
    ) -> dict[str, Any]:
        return svc.browser.snapshot(page_id)

    @app.post("/api/v1/browser/actions")
    def browser_action(payload: BrowserAction, svc: Service) -> dict[str, Any]:
        return svc.browser.interact(
            payload.action, payload.selector, payload.value, payload.page_id
        )

    @app.post("/api/v1/browser/screenshots")
    def browser_screenshot(
        svc: Service, page_id: str | None = None
    ) -> dict[str, Any]:
        artifact = svc.browser.screenshot(page_id)
        return {**artifact, "url": f"/api/v1/browser/artifacts/{artifact['id']}"}

    @app.post("/api/v1/browser/bridge/{bridge_token}", include_in_schema=False)
    def browser_bridge_call(
        bridge_token: str, payload: BrowserToolCall, svc: Service
    ) -> dict[str, Any]:
        return svc.execute_browser_bridge_tool(
            bridge_token, payload.tool_name, payload.arguments
        )

    @app.get("/api/v1/studio/bridge/{bridge_token}/tools", include_in_schema=False)
    def studio_bridge_tools(bridge_token: str, svc: Service) -> dict[str, Any]:
        return {"tools": svc.list_studio_bridge_tools(bridge_token)}

    @app.post("/api/v1/studio/bridge/{bridge_token}", include_in_schema=False)
    def studio_bridge_call(
        bridge_token: str, payload: StudioToolCall, svc: Service
    ) -> dict[str, Any]:
        return svc.execute_studio_bridge_tool(
            bridge_token, payload.tool_name, payload.arguments
        )

    @app.get("/api/v1/browser/artifacts/{artifact_id}")
    def browser_artifact(artifact_id: str, svc: Service) -> FileResponse:
        return FileResponse(svc.browser.artifact(artifact_id), media_type="image/png")

    @app.post("/api/v1/browser/close")
    def browser_close(svc: Service) -> dict[str, Any]:
        return svc.browser.close()

    @app.get("/api/v1/system/status")
    def system_status(svc: Service) -> dict[str, Any]:
        return svc.system_status()

    @app.get("/api/v1/system/diagnostics")
    def system_diagnostics(svc: Service) -> Response:
        content = json.dumps(svc.diagnostics(), ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="agentbench-diagnostics.json"'},
        )

    @app.patch("/api/v1/settings")
    def update_settings(payload: AppSettingUpdate, svc: Service) -> dict[str, Any]:
        return svc.update_settings(payload.model_dump(exclude_unset=True))

    @app.post("/api/v1/system/backup")
    def backup(svc: Service) -> FileResponse:
        path = svc.backup()
        return FileResponse(path, filename=path.name, media_type="application/zip")

    @app.post("/api/v1/system/restore")
    async def restore(request: Request, svc: Service) -> dict[str, Any]:
        content = await request.body()
        if not content:
            raise HTTPException(status_code=400, detail="empty_backup")
        return svc.restore(content)

    @app.get("/api/v1/models")
    def models(svc: Service, include_archived: bool = False) -> list[dict[str, Any]]:
        return svc.list_models(include_archived)

    @app.post("/api/v1/models", status_code=201)
    def create_model(payload: ModelCreate, svc: Service) -> dict[str, Any]:
        return svc.create_model(payload)

    @app.post("/api/v1/models/discover")
    def discover_models(payload: ModelDiscoveryRequest, svc: Service) -> dict[str, Any]:
        return svc.discover_models(payload)

    @app.patch("/api/v1/models/{model_id}")
    def update_model(
        model_id: str, payload: ModelUpdate, svc: Service
    ) -> dict[str, Any]:
        return svc.update_model(model_id, payload)

    @app.delete("/api/v1/models/{model_id}")
    def delete_model(model_id: str, svc: Service) -> dict[str, Any]:
        return svc.delete_model(model_id)

    @app.post("/api/v1/models/{model_id}/test")
    def test_model(model_id: str, svc: Service) -> dict[str, Any]:
        return svc.test_model(model_id)

    @app.get("/api/v1/runners")
    def runners(svc: Service) -> list[dict[str, Any]]:
        return svc.list_runners()

    @app.post("/api/v1/runners", status_code=201)
    def create_runner(payload: RunnerCreate, svc: Service) -> dict[str, Any]:
        return svc.create_runner(payload)

    @app.post("/api/v1/runners/{runner_id}/install", status_code=202)
    def install_runner(runner_id: str, svc: Service) -> dict[str, Any]:
        return svc.start_runner_install(runner_id)

    @app.get("/api/v1/runners/installations/{job_id}")
    def runner_installation(job_id: str, svc: Service) -> dict[str, Any]:
        return svc.get_runner_install(job_id)

    @app.get("/api/v1/test-cases")
    def test_cases(
        svc: Service,
        category: str | None = None,
        query: str | None = None,
        limit: int = Query(default=500, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return svc.list_test_cases(category, query, limit)

    @app.get("/api/v1/test-cases/{case_id}")
    def test_case(case_id: str, svc: Service) -> dict[str, Any]:
        return svc.get_test_case(case_id)

    @app.post("/api/v1/test-cases", status_code=201)
    def import_test_case(payload: TestCaseImport, svc: Service) -> dict[str, Any]:
        return svc.import_test_case(payload)

    @app.post("/api/v1/test-cases/import", status_code=201)
    async def import_test_case_document(request: Request, svc: Service) -> dict[str, Any]:
        try:
            value = yaml.safe_load((await request.body()).decode("utf-8"))
            payload = TestCaseImport.model_validate(value)
        except (UnicodeDecodeError, yaml.YAMLError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid test DSL: {exc}") from exc
        return svc.import_test_case(payload)

    @app.post("/api/v1/math-papers/import", status_code=201)
    async def import_math_paper(
        request: Request,
        svc: Service,
        filename: str = Query(min_length=1, max_length=255),
        year: int = Query(default=2025, ge=2000, le=2100),
    ) -> dict[str, Any]:
        try:
            return svc.import_math_paper(
                filename=Path(filename).name,
                content=await request.body(),
                year=year,
            )
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/math-papers/imports")
    def math_paper_imports(svc: Service) -> list[dict[str, Any]]:
        return svc.list_math_paper_imports()

    @app.get("/api/v1/math-papers/imports/{import_id}")
    def math_paper_import(import_id: str, svc: Service) -> dict[str, Any]:
        try:
            return svc.get_math_paper_import(import_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="math_paper_import_not_found") from exc

    @app.patch("/api/v1/math-papers/imports/{import_id}/questions/{number}")
    def update_math_paper_question(
        import_id: str,
        number: int,
        payload: MathQuestionUpdate,
        svc: Service,
    ) -> dict[str, Any]:
        try:
            return svc.update_math_paper_question(
                import_id, number, payload.model_dump(exclude_unset=True)
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="math_paper_import_not_found") from exc

    @app.post("/api/v1/math-papers/imports/{import_id}/publish")
    def publish_math_paper(import_id: str, svc: Service) -> dict[str, Any]:
        try:
            return svc.publish_math_paper(import_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="math_paper_import_not_found") from exc

    @app.get("/api/v1/suites")
    def suites(svc: Service) -> list[dict[str, Any]]:
        return svc.list_suites()

    @app.get("/api/v1/suites/{suite_id}")
    def suite(suite_id: str, svc: Service) -> dict[str, Any]:
        return svc.get_suite(suite_id)

    @app.get("/api/v1/suites/{suite_id}/cases")
    def suite_cases(suite_id: str, svc: Service) -> list[dict[str, Any]]:
        return svc.list_suite_cases(suite_id)

    @app.get("/api/v1/experiments")
    def experiments(svc: Service, limit: int = Query(default=100, ge=1, le=500)):
        return svc.list_experiments(limit)

    @app.post("/api/v1/experiments", status_code=201)
    def create_experiment(payload: ExperimentCreate, svc: Service) -> dict[str, Any]:
        return svc.create_experiment(payload)

    @app.get("/api/v1/experiments/{experiment_id}")
    def experiment(experiment_id: str, svc: Service) -> dict[str, Any]:
        return svc.get_experiment(experiment_id)

    @app.post("/api/v1/experiments/{experiment_id}/start")
    def start_experiment(experiment_id: str, svc: Service) -> dict[str, Any]:
        return svc.start_experiment(experiment_id)

    @app.get("/api/v1/experiments/{experiment_id}/preflight")
    def preflight_experiment(experiment_id: str, svc: Service) -> dict[str, Any]:
        return svc.preflight_experiment(experiment_id)

    @app.post("/api/v1/experiments/{experiment_id}/cancel")
    def cancel_experiment(experiment_id: str, svc: Service) -> dict[str, Any]:
        return svc.cancel_experiment(experiment_id)

    @app.post("/api/v1/experiments/{experiment_id}/rejudge")
    def rejudge_experiment(
        experiment_id: str,
        svc: Service,
        scope: str = Query(default="structured", pattern="^(structured|all)$"),
    ) -> dict[str, Any]:
        svc.get_experiment(experiment_id)
        return svc.rejudge_experiment(experiment_id, scope=scope)

    @app.get("/api/v1/experiments/{experiment_id}/export")
    def export_experiment(
        experiment_id: str,
        svc: Service,
        format: str = Query(default="json", pattern="^(json|csv|html)$"),
    ) -> Response:
        filename, content, media_type = svc.export(experiment_id, format)
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/v1/experiments/{experiment_id}/exam-report")
    def exam_report(
        experiment_id: str,
        svc: Service,
        exam: str = Query(default="ncre-office", pattern=r"^[a-z0-9_-]{1,40}$"),
        paper: str | None = Query(default=None, pattern=r"^[a-z0-9-]{1,60}$"),
    ) -> dict[str, Any]:
        svc.get_experiment(experiment_id)
        return export_exam_report(svc.database, experiment_id, exam, paper)

    @app.get("/api/v1/runs")
    def runs(
        svc: Service,
        experiment_id: str | None = None,
        limit: int = Query(default=500, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return svc.list_runs(experiment_id, limit)

    @app.get("/api/v1/runs/{run_id}")
    def run(run_id: str, svc: Service) -> dict[str, Any]:
        return svc.get_run(run_id)

    @app.post("/api/v1/runs/{run_id}/retry")
    def retry_run(run_id: str, svc: Service) -> dict[str, Any]:
        return svc.retry_run(run_id)

    @app.post("/api/v1/runs/{run_id}/rejudge")
    def rejudge_run(run_id: str, svc: Service) -> dict[str, Any]:
        row = svc.database.fetch_one(
            "SELECT status,final_answer FROM runs WHERE id=?", (run_id,)
        )
        if not row:
            raise HTTPException(status_code=404, detail="run_not_found")
        if row["status"] not in {"needs_review", "completed"}:
            raise HTTPException(status_code=409, detail="run_not_rejudgeable")
        if not (row["final_answer"] or "").strip():
            raise HTTPException(status_code=409, detail="run_has_no_final_answer")
        return svc.rejudge_run(run_id)

    @app.post("/api/v1/runs/{run_id}/manual-score")
    def manual_score(run_id: str, payload: ManualScoreUpdate, svc: Service) -> dict[str, Any]:
        return svc.manual_score(run_id, payload.score, payload.reason)

    @app.get("/api/v1/runs/{run_id}/events")
    def run_events(run_id: str, svc: Service, after: int = Query(default=0, ge=0)):
        svc.get_run(run_id)
        return svc.get_run_events(run_id, after)

    @app.get("/api/v1/runs/{run_id}/events/stream")
    async def run_event_stream(run_id: str, svc: Service, after: int = Query(default=0, ge=0)):
        svc.get_run(run_id)

        async def stream():
            cursor = after
            idle_ticks = 0
            while True:
                events = svc.get_run_events(run_id, cursor)
                for item in events:
                    cursor = item["seq"]
                    # A single generic SSE message lets the client consume present and
                    # future event types without registering a listener per Agent CLI.
                    yield f"id: {cursor}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                    idle_ticks = 0
                current = svc.database.fetch_one("SELECT status FROM runs WHERE id=?", (run_id,))
                if (
                    current
                    and current["status"]
                    in {
                        "completed",
                        "failed",
                        "cancelled",
                        "environment_unavailable",
                        "needs_review",
                        "interrupted",
                    }
                    and not events
                ):
                    break
                idle_ticks += 1
                if idle_ticks % 15 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.75)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/v1/runs/{run_id}/artifacts/{artifact_id}")
    def artifact(run_id: str, artifact_id: str, svc: Service) -> FileResponse:
        run_row = svc.database.fetch_one("SELECT workspace_path FROM runs WHERE id=?", (run_id,))
        artifact_row = svc.database.fetch_one(
            "SELECT * FROM artifacts WHERE id=? AND run_id=?", (artifact_id, run_id)
        )
        if not run_row or not artifact_row or not run_row["workspace_path"]:
            raise HTTPException(status_code=404, detail="artifact_not_found")
        root = Path(run_row["workspace_path"]).resolve()
        target = (root / artifact_row["path"]).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404, detail="artifact_not_found")
        return FileResponse(target, filename=artifact_row["name"])

    @app.get("/api/v1/runs/{run_id}/materials/{filename}")
    def run_material(run_id: str, filename: str, svc: Service) -> Response:
        content, name = svc.get_run_material(run_id, filename)
        media_type = _MATERIAL_MEDIA_TYPES.get(
            Path(name).suffix.lower(), "application/octet-stream"
        )
        ascii_fallback = (
            name.encode("ascii", "ignore").decode("ascii").strip().strip(".") or "material"
        )
        disposition = (
            f'attachment; filename="{ascii_fallback}"; '
            f"filename*=UTF-8''{urllib.parse.quote(name)}"
        )
        return Response(
            content=content, media_type=media_type, headers={"Content-Disposition": disposition}
        )

    @app.get("/api/v1/leaderboard")
    def leaderboard(
        svc: Service,
        lane: str = Query(default="unified", pattern="^(unified|native)$"),
        suite_id: str | None = None,
        benchmark_generation: str = Query(default="v3", pattern="^(v2|v3|all)$"),
    ) -> list[dict[str, Any]]:
        return svc.leaderboard(lane, suite_id, benchmark_generation)

    @app.get("/api/v1/model-profiles")
    def model_profiles(
        svc: Service,
        lane: str | None = None,
        benchmark_generation: str = Query(default="v3", pattern="^(v2|v3|all)$"),
    ) -> list[dict[str, Any]]:
        return svc.model_profiles(lane, benchmark_generation)

    return app
