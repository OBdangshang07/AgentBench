from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agentbench.api import create_app
from agentbench.catalog import (
    MATH_2025_CLOSED_SUITE_ID,
    MOCK_MODEL_ID,
    NCRE_OFFICE_SUITE_ID,
    UNIFIED_RUNNER_ID,
)

NOW = "2026-08-13T00:00:00+00:00"


def _suite_cases(service, suite_id: str) -> list[dict]:
    rows = service.database.fetch_all(
        "SELECT t.id,t.definition_json FROM suite_cases sc "
        "JOIN test_cases t ON t.id=sc.test_case_id WHERE sc.suite_id=? ORDER BY sc.position",
        (suite_id,),
    )
    return [
        {"id": row["id"], "metadata": json.loads(row["definition_json"])["metadata"]}
        for row in rows
    ]


def _seed_experiment(service, experiment_id: str, suite_id: str) -> None:
    service.database.execute(
        "INSERT INTO experiments(id,name,suite_id,participants_json,repetitions,"
        "benchmark_generation,status,created_at) VALUES (?,?,?,'[]',2,'v3','completed',?)",
        (experiment_id, experiment_id, suite_id, NOW),
    )


def _seed_run(
    service,
    *,
    run_id: str,
    experiment_id: str,
    case_id: str,
    repetition: int,
    quality: float,
) -> None:
    service.database.execute(
        "INSERT INTO runs(id,experiment_id,test_case_id,model_id,runner_id,repetition,"
        "lane,status,score,tokens_input,tokens_output,cost_usd,duration_ms,created_at) "
        "VALUES (?,?,?,?,?,?,'unified','completed',50,100,50,0.01,1000,?)",
        (
            run_id,
            experiment_id,
            case_id,
            MOCK_MODEL_ID,
            UNIFIED_RUNNER_ID,
            repetition,
            NOW,
        ),
    )
    # Deliberately add a zero efficiency component. Exam paper scores must use only
    # objective/judge answer quality and never inherit the balanced benchmark score.
    for suffix, dimension, score, weight in (
        ("quality", "objective_quality", quality, 94),
        ("time", "time_efficiency", 0, 3),
    ):
        service.database.execute(
            "INSERT INTO score_components(id,run_id,dimension,score,weight,evidence_json,"
            "created_at) VALUES (?,?,?,?,?,'{}',?)",
            (f"{run_id}-{suffix}", run_id, dimension, score, weight, NOW),
        )


def test_math_exam_leaderboard_uses_complete_official_150_point_papers(settings):
    with TestClient(create_app(settings)) as client:
        service = client.app.state.service
        cases = _suite_cases(service, MATH_2025_CLOSED_SUITE_ID)
        assert len(cases) == 22
        _seed_experiment(service, "math-board", MATH_2025_CLOSED_SUITE_ID)
        for case in cases:
            number = int(case["metadata"]["question_no"])
            _seed_run(
                service,
                run_id=f"math-r1-q{number}",
                experiment_id="math-board",
                case_id=case["id"],
                repetition=1,
                quality=50 if number == 17 else 100,
            )
        # Repetition two is incomplete and must not be extrapolated into a paper.
        for case in cases[:-1]:
            number = int(case["metadata"]["question_no"])
            _seed_run(
                service,
                run_id=f"math-r2-q{number}",
                experiment_id="math-board",
                case_id=case["id"],
                repetition=2,
                quality=100,
            )

        response = client.get(
            "/api/v1/leaderboard/exams/math-2025", params={"mode": "closed-book"}
        )
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0] | {"model_name": "", "runner_name": ""} == {
            "model_id": MOCK_MODEL_ID,
            "runner_id": UNIFIED_RUNNER_ID,
            "model_name": "",
            "runner_name": "",
            "board": "math-2025",
            "mode": "closed-book",
            "papers": 1,
            "exam_total": 150.0,
            "avg_exam_score": 145.0,
            "best_exam_score": 145.0,
            "benchmark_score": 90.0,
            "benchmark_rate": 100.0,
            "avg_duration_ms": 22000,
            "avg_tokens": 3300,
            "total_cost": 0.22,
        }
        assert client.get(
            "/api/v1/leaderboard/exams/math-2025",
            params={"mode": "tool-augmented"},
        ).json() == []


def test_ncre_leaderboard_requires_all_four_official_sections(settings):
    with TestClient(create_app(settings)) as client:
        service = client.app.state.service
        cases = _suite_cases(service, NCRE_OFFICE_SUITE_ID)
        assert {case["metadata"]["exam_section"] for case in cases} == {
            "choice",
            "word",
            "excel",
            "ppt",
        }
        _seed_experiment(service, "ncre-board", NCRE_OFFICE_SUITE_ID)
        for case in cases:
            section = case["metadata"]["exam_section"]
            _seed_run(
                service,
                run_id=f"ncre-r1-{section}",
                experiment_id="ncre-board",
                case_id=case["id"],
                repetition=1,
                quality=50 if section == "choice" else 100,
            )
        for case in cases:
            section = case["metadata"]["exam_section"]
            if section == "ppt":
                continue
            _seed_run(
                service,
                run_id=f"ncre-r2-{section}",
                experiment_id="ncre-board",
                case_id=case["id"],
                repetition=2,
                quality=100,
            )

        rows = client.get("/api/v1/leaderboard/exams/ncre").json()
        assert len(rows) == 1
        assert rows[0]["papers"] == 1
        assert rows[0]["exam_total"] == 100.0
        assert rows[0]["avg_exam_score"] == 90.0
        assert rows[0]["best_exam_score"] == 90.0
        assert rows[0]["benchmark_score"] == 60.0
        assert rows[0]["benchmark_rate"] == 100.0
        assert rows[0]["avg_duration_ms"] == 4000
        assert rows[0]["avg_tokens"] == 600


def test_exam_leaderboard_rejects_unknown_board_and_missing_math_mode(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/leaderboard/exams/unknown").status_code == 404
        assert client.get("/api/v1/leaderboard/exams/math-2025").status_code == 422
