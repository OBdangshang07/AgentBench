import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from . import __version__
from .config import Settings
from .schemas import (
    AppSettingUpdate,
    ExperimentCreate,
    ManualScoreUpdate,
    ModelCreate,
    ModelDiscoveryRequest,
    ModelUpdate,
    RunnerCreate,
    TestCaseImport,
)
from .service import EvaluationService


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

    @app.get("/api/v1/system/status")
    def system_status(svc: Service) -> dict[str, Any]:
        return svc.system_status()

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

    @app.get("/api/v1/suites")
    def suites(svc: Service) -> list[dict[str, Any]]:
        return svc.list_suites()

    @app.get("/api/v1/suites/{suite_id}")
    def suite(suite_id: str, svc: Service) -> dict[str, Any]:
        return svc.get_suite(suite_id)

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
                    yield f"id: {cursor}\nevent: {item['event_type']}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
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

    @app.get("/api/v1/leaderboard")
    def leaderboard(
        svc: Service,
        lane: str = Query(default="unified", pattern="^(unified|native)$"),
        suite_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return svc.leaderboard(lane, suite_id)

    return app
