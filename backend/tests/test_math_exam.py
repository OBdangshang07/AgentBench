from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from agentbench.api import create_app
from agentbench.catalog import MATH_2025_CLOSED_SUITE_ID, MOCK_MODEL_ID, UNIFIED_RUNNER_ID
from agentbench.math_builtin import SOURCE_SHA256, build_builtin_math_cases, builtin_math_manifest
from agentbench.math_exam import build_question_drafts, import_math_pdf


def _blank_pdf() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(output)
    return output.getvalue()


def test_math_question_drafts_keep_official_150_point_structure():
    text = "\n".join(f"{number}. 这是第 {number} 题的待校对文本，公式需要人工确认。" for number in range(1, 23))
    drafts = build_question_drafts([text])

    assert len(drafts) == 22
    assert sum(item["points"] for item in drafts) == 150
    assert sum(item["points"] for item in drafts if item["type"] == "choice") == 50
    assert sum(item["points"] for item in drafts if item["type"] == "fill") == 30
    assert sum(item["points"] for item in drafts if item["type"] == "solution") == 70
    assert [item["points"] for item in drafts[16:]] == [10, 12, 12, 12, 12, 12]
    assert drafts[16]["rubric"]["validators"][0]["weight"] == 40
    assert drafts[16]["rubric"]["validators"][1]["weight"] == 60


def test_user_pdf_is_bundled_as_two_verified_22_question_suites():
    manifest = builtin_math_manifest()
    cases = build_builtin_math_cases()

    assert manifest["source"]["sha256"] == SOURCE_SHA256
    assert manifest["source"]["page_count"] == 17
    assert len(manifest["questions"]) == 22
    assert sum(item["points"] for item in manifest["questions"]) == 150
    assert [item["points"] for item in manifest["questions"][16:]] == [10, 12, 12, 12, 12, 12]
    assert len(cases["closed-book"]) == 22
    assert len(cases["tool-augmented"]) == 22
    assert cases["closed-book"][0]["definition"]["tools"] == []
    assert cases["tool-augmented"][0]["definition"]["tools"]
    proof_validators = cases["closed-book"][18]["definition"]["validators"]
    assert [item["type"] for item in proof_validators] == ["ai_rubric"]
    assert proof_validators[0]["weight"] == 100


def test_math_pdf_import_is_local_and_stays_in_review(settings):
    manifest = import_math_pdf(
        settings.data_dir,
        filename="2025-math-1.pdf",
        content=_blank_pdf(),
        year=2025,
    )

    assert manifest["status"] == "needs_review"
    assert manifest["score_structure"]["total"] == 150
    assert manifest["source"]["sha256"]
    assert manifest["lanes"][0]["native_agent_compatible"] is False
    assert manifest["lanes"][1]["native_agent_compatible"] is True
    assert (settings.data_dir / "math-papers" / manifest["id"] / "source.pdf").is_file()


def test_math_pdf_import_api_returns_review_manifest(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/math-papers/import?filename=2025-math-1.pdf&year=2025",
            content=_blank_pdf(),
            headers={"Content-Type": "application/pdf"},
        )
        assert response.status_code == 201
        manifest = response.json()
        assert manifest["status"] == "needs_review"
        imports = client.get("/api/v1/math-papers/imports").json()
        assert imports[0]["id"] == manifest["id"]
        detail = client.get(f"/api/v1/math-papers/imports/{manifest['id']}")
        assert detail.status_code == 200
        assert len(detail.json()["questions"]) == 22


def test_math_pdf_import_rejects_non_pdf(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/math-papers/import?filename=paper.txt&year=2025",
            content=b"not a PDF",
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "math_paper_must_be_pdf"


def test_math_paper_review_and_publish_creates_two_real_suites(settings):
    with TestClient(create_app(settings)) as client:
        imported = client.post(
            "/api/v1/math-papers/import?filename=2025-math-1.pdf&year=2025",
            content=_blank_pdf(),
            headers={"Content-Type": "application/pdf"},
        ).json()
        for number in range(1, 23):
            payload = {
                "question_text": f"第 {number} 题的人工校对题面",
                "answer": "A" if number <= 10 else "x",
                "accepted_answers": [],
                "variables": [] if number <= 10 else ["x"],
                "solution_obligations": (
                    ["建立正确模型", "给出可复核推导", "结论正确"] if number >= 17 else []
                ),
                "review_status": "confirmed",
            }
            response = client.patch(
                f"/api/v1/math-papers/imports/{imported['id']}/questions/{number}",
                json=payload,
            )
            assert response.status_code == 200
        ready = client.get(
            f"/api/v1/math-papers/imports/{imported['id']}"
        ).json()
        assert ready["status"] == "ready_to_publish"

        response = client.post(
            f"/api/v1/math-papers/imports/{imported['id']}/publish"
        )
        assert response.status_code == 200
        published = response.json()
        assert published["status"] == "published"
        assert {item["lane"] for item in published["published_suites"]} == {
            "closed-book",
            "tool-augmented",
        }
        for suite in published["published_suites"]:
            detail = client.get(f"/api/v1/suites/{suite['id']}").json()
            assert len(detail["cases"]) == 22

        closed_suite = next(
            item for item in published["published_suites"] if item["lane"] == "closed-book"
        )
        case_id = client.get(
            f"/api/v1/suites/{closed_suite['id']}/cases"
        ).json()[16]["id"]
        public_case = client.get(f"/api/v1/test-cases/{case_id}").json()
        serialized = str(public_case["definition"])
        assert "reference_answer" not in serialized
        assert "solution_obligations" not in serialized

        experiment = client.post(
            "/api/v1/experiments",
            json={
                "name": "数学卷面加权验证",
                "suite_id": closed_suite["id"],
                "participants": [
                    {"model_id": MOCK_MODEL_ID, "runner_id": UNIFIED_RUNNER_ID}
                ],
                "repetitions": 1,
                "concurrency": 1,
            },
        ).json()
        service = client.app.state.service
        runs = service.database.fetch_all(
            "SELECT r.id,t.definition_json FROM runs r JOIN test_cases t "
            "ON t.id=r.test_case_id WHERE r.experiment_id=?",
            (experiment["id"],),
        )
        selected = {}
        for run in runs:
            metadata = json.loads(run["definition_json"])["metadata"]
            if metadata["question_no"] in {1, 17}:
                selected[metadata["question_no"]] = run["id"]
        service.database.execute(
            "UPDATE runs SET status='completed',score=100 WHERE id=?", (selected[1],)
        )
        service.database.execute(
            "UPDATE runs SET status='completed',score=0 WHERE id=?", (selected[17],)
        )
        summary = client.get(f"/api/v1/experiments/{experiment['id']}").json()["summary"]
        assert summary["avg_score"] == 3.33
        assert summary["exam_score"] == 5.0
        assert summary["exam_total"] == 150.0
        assert summary["exam_scoring_basis"] == "answer_quality"


def test_math_paper_score_uses_answer_quality_not_efficiency(settings):
    with TestClient(create_app(settings)) as client:
        experiment = client.post(
            "/api/v1/experiments",
            json={
                "name": "quality-only-math-score",
                "suite_id": MATH_2025_CLOSED_SUITE_ID,
                "participants": [
                    {"model_id": MOCK_MODEL_ID, "runner_id": UNIFIED_RUNNER_ID}
                ],
                "repetitions": 1,
                "concurrency": 1,
            },
        ).json()
        service = client.app.state.service
        run = service.database.fetch_one(
            "SELECT r.id FROM runs r JOIN test_cases t ON t.id=r.test_case_id "
            "WHERE r.experiment_id=? ORDER BY t.slug LIMIT 1",
            (experiment["id"],),
        )
        service.database.execute(
            "UPDATE runs SET status='completed',score=6 WHERE id=?", (run["id"],)
        )
        now = "2026-01-01T00:00:00+00:00"
        service.database.execute(
            "INSERT INTO score_components(id,run_id,dimension,score,weight,evidence_json,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("math-quality", run["id"], "objective_quality", 0, 94, "{}", now),
        )
        service.database.execute(
            "INSERT INTO score_components(id,run_id,dimension,score,weight,evidence_json,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("math-time", run["id"], "time_efficiency", 100, 3, "{}", now),
        )

        summary = client.get(f"/api/v1/experiments/{experiment['id']}").json()["summary"]
        assert summary["exam_score"] == 0
        assert summary["weighted_score"] == 0


def test_math_paper_keeps_declared_objective_and_judge_weights(settings):
    with TestClient(create_app(settings)) as client:
        experiment = client.post(
            "/api/v1/experiments",
            json={
                "name": "weighted-math-quality",
                "suite_id": MATH_2025_CLOSED_SUITE_ID,
                "participants": [
                    {"model_id": MOCK_MODEL_ID, "runner_id": UNIFIED_RUNNER_ID}
                ],
                "repetitions": 1,
                "concurrency": 1,
            },
        ).json()
        service = client.app.state.service
        run = service.database.fetch_one(
            "SELECT r.id FROM runs r JOIN test_cases t ON t.id=r.test_case_id "
            "WHERE r.experiment_id=? AND json_extract(t.definition_json, "
            "'$.metadata.question_no')=17",
            (experiment["id"],),
        )
        service.database.execute(
            "UPDATE runs SET status='completed',score=59.97 WHERE id=?", (run["id"],)
        )
        now = "2026-01-01T00:00:00+00:00"
        for component_id, dimension, score, weight in (
            ("math-objective", "objective_quality", 0, 37.6),
            ("math-judge", "judge_quality", 100, 56.4),
            ("math-token", "token_efficiency", 0, 1),
        ):
            service.database.execute(
                "INSERT INTO score_components(id,run_id,dimension,score,weight,evidence_json,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (component_id, run["id"], dimension, score, weight, "{}", now),
            )

        summary = client.get(f"/api/v1/experiments/{experiment['id']}").json()["summary"]
        assert summary["weighted_score"] == 4
        assert summary["exam_score"] == 6


def test_math_question_cannot_be_confirmed_without_required_review_data(settings):
    with TestClient(create_app(settings)) as client:
        imported = client.post(
            "/api/v1/math-papers/import?filename=2025-math-1.pdf&year=2025",
            content=_blank_pdf(),
            headers={"Content-Type": "application/pdf"},
        ).json()
        response = client.patch(
            f"/api/v1/math-papers/imports/{imported['id']}/questions/17",
            json={
                "question_text": "解答题",
                "answer": "x",
                "review_status": "confirmed",
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "confirmed_solution_requires_obligations"
