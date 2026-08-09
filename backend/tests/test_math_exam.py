from __future__ import annotations

import io

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from agentbench.api import create_app
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
    assert drafts[16]["rubric"]["validators"][0]["weight"] == 40
    assert drafts[16]["rubric"]["validators"][1]["weight"] == 60


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
