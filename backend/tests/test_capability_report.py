from __future__ import annotations

import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from agentbench.api import create_app
from agentbench.catalog import MOCK_MODEL_ID, SIX_DIMENSION_SUITE_ID, UNIFIED_RUNNER_ID


def test_six_dimension_report_and_svg_panel_are_video_ready(settings):
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/experiments",
            json={
                "name": "六维面板回归",
                "suite_id": SIX_DIMENSION_SUITE_ID,
                "participants": [
                    {"model_id": MOCK_MODEL_ID, "runner_id": UNIFIED_RUNNER_ID}
                ],
                "repetitions": 1,
                "concurrency": 1,
            },
        )
        assert created.status_code == 201, created.text
        experiment_id = created.json()["id"]
        service = client.app.state.service
        expected_scores = {
            "creative_frontend": 91,
            "systems_backend": 84,
            "mathematical_reasoning": 88,
            "research_writing": 79,
            "data_engineering_science": 86,
            "agent_execution": 82,
        }
        rows = service.database.fetch_all(
            "SELECT r.id,COALESCE(tr.definition_json,t.definition_json) definition_json "
            "FROM runs r JOIN test_cases t ON t.id=r.test_case_id "
            "LEFT JOIN test_case_revisions tr ON tr.id=r.test_revision_id "
            "WHERE r.experiment_id=?",
            (experiment_id,),
        )
        import json

        for index, row in enumerate(rows):
            definition = json.loads(row["definition_json"])
            dimension = definition["metadata"]["capability_dimension"]
            service.database.execute(
                "UPDATE runs SET status='completed',score=?,passed=1,duration_ms=?,"
                "tokens_input=1000,tokens_output=500 WHERE id=?",
                (expected_scores[dimension], 60_000 + index, row["id"]),
            )

        response = client.get(
            f"/api/v1/experiments/{experiment_id}/capability-report"
        )
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["schema"] == "agentbench.capability-report/v1"
        assert len(report["profiles"]) == 1
        profile = report["profiles"][0]
        assert profile["overall_complete"] is True
        assert profile["overall_score"] == 85.0
        assert {
            item["key"]: item["score"] for item in profile["dimensions"]
        } == expected_scores
        assert profile["totals"]["runs"] == 18
        assert all(item["runs"] for item in profile["dimensions"])

        detail = client.get(f"/api/v1/experiments/{experiment_id}").json()
        assert detail["summary"]["avg_score"] == 85.0
        assert detail["summary"]["capability_score"] == 85.0
        assert detail["summary"]["score_basis"] == "six_dimension_equal_weight"
        listed = client.get("/api/v1/experiments").json()
        listed_experiment = next(item for item in listed if item["id"] == experiment_id)
        assert listed_experiment["avg_score"] == 85.0
        assert listed_experiment["capability_score"] == 85.0
        assert listed_experiment["score_basis"] == "six_dimension_equal_weight"

        panel = client.get(
            f"/api/v1/experiments/{experiment_id}/capability-panel.svg"
        )
        assert panel.status_code == 200
        assert panel.headers["content-type"].startswith("image/svg+xml")
        assert 'viewBox="0 0 1600 900"' in panel.text
        assert "AgentBench Demo Model" in panel.text
        assert "创意前端" in panel.text and "数据工程与数据科学" in panel.text
        root = ET.fromstring(panel.text)
        top_labels = [
            float(node.attrib["y"])
            for node in root.iter("{http://www.w3.org/2000/svg}text")
            if (node.text or "") == "创意前端"
        ]
        assert min(top_labels) >= 200  # radar label must clear subtitle at y=158

        download = client.get(
            f"/api/v1/experiments/{experiment_id}/capability-panel.svg?download=true"
        )
        assert download.headers["content-disposition"].startswith("attachment")

        # A pending dimension is unknown rather than zero: the panel must not
        # draw a centre point or a filled/closed radar through that axis.
        frontend_run_ids = []
        for row in rows:
            definition = json.loads(row["definition_json"])
            if definition["metadata"]["capability_dimension"] == "creative_frontend":
                frontend_run_ids.append(row["id"])
        for run_id in frontend_run_ids:
            service.database.execute(
                "UPDATE runs SET status='queued',score=NULL,passed=NULL WHERE id=?",
                (run_id,),
            )

        pending_report = client.get(
            f"/api/v1/experiments/{experiment_id}/capability-report"
        ).json()
        pending_profile = pending_report["profiles"][0]
        pending_frontend = next(
            item
            for item in pending_profile["dimensions"]
            if item["key"] == "creative_frontend"
        )
        assert pending_frontend["score"] is None
        assert pending_profile["overall_complete"] is False

        pending_panel = client.get(
            f"/api/v1/experiments/{experiment_id}/capability-panel.svg"
        )
        pending_root = ET.fromstring(pending_panel.text)
        nodes = list(pending_root.iter())
        assert not any(
            node.attrib.get("data-role") == "capability-shape" for node in nodes
        )
        assert sum(
            node.attrib.get("data-role") == "capability-segment" for node in nodes
        ) == 4
        assert not any(
            node.attrib.get("data-dimension") == "creative_frontend"
            for node in nodes
        )
        assert "待评分" in pending_panel.text
