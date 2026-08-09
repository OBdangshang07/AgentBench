from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import shutil
import sqlite3
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .db import SCHEMA_VERSION, Database


def export_experiment(rows: list[dict[str, Any]], fmt: str) -> tuple[str, bytes, str]:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    if fmt == "json":
        return (
            f"agentbench-{timestamp}.json",
            json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
        )
    if fmt == "csv":
        stream = io.StringIO()
        fields = [
            "run_id",
            "test_title",
            "category",
            "model_name",
            "runner_name",
            "lane",
            "status",
            "score",
            "tokens_input",
            "tokens_output",
            "cost_usd",
            "duration_ms",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return f"agentbench-{timestamp}.csv", stream.getvalue().encode("utf-8-sig"), "text/csv"
    if fmt == "html":
        body_rows = "".join(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(row.get(field, '')))}</td>"
                for field in (
                    "test_title",
                    "model_name",
                    "runner_name",
                    "status",
                    "score",
                    "cost_usd",
                )
            )
            + "</tr>"
            for row in rows
        )
        document = f"""<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">
<title>AgentBench 实验报告</title><style>
body{{font-family:system-ui;margin:40px;color:#172033}}table{{border-collapse:collapse;width:100%}}
th,td{{padding:10px;border-bottom:1px solid #dde3ee;text-align:left}}th{{background:#f4f7fb}}
</style><h1>AgentBench 实验报告</h1><p>生成时间：{timestamp}</p>
<table><thead><tr><th>测试</th><th>模型</th><th>Agent</th><th>状态</th><th>得分</th><th>费用</th></tr></thead>
<tbody>{body_rows}</tbody></table></html>"""
        return f"agentbench-{timestamp}.html", document.encode("utf-8"), "text/html"
    raise ValueError("Unsupported export format")


def _exam_grade(score: float) -> str:
    if score >= 90:
        return "优秀"
    if score >= 80:
        return "良好"
    if score >= 60:
        return "及格"
    return "不及格"


def _exam_paper_overall(
    task_ids: list[str], tasks: dict[str, dict[str, Any]], attempts: dict[tuple[str, str, str, str], list[dict[str, Any]]]
) -> dict[str, Any]:
    """Compute earned points / percentage / grade for a subset of exam tasks."""
    total_points = sum(tasks[task_id]["exam_points"] for task_id in task_ids)
    earned = 0.0
    for task_id in task_ids:
        task = tasks[task_id]
        best = max(
            (item for key, items in attempts.items() if key[3] == task_id for item in items),
            key=lambda item: item["score"],
            default=None,
        )
        weighted = best["score"] / 100 * task["exam_points"] if best and task["exam_points"] else 0.0
        earned += weighted
    percentage = earned / total_points * 100 if total_points else 0.0
    return {
        "task_count": len(task_ids),
        "earned_points": round(earned, 2),
        "total_points": round(total_points, 2),
        "total_score": round(percentage, 2),
        "grade": _exam_grade(percentage),
    }


def export_exam_report(
    database: Database,
    experiment_id: str,
    exam: str = "ncre-office",
    paper: str | None = None,
) -> dict[str, Any]:
    """Build a weighted exam transcript for one experiment.

    Runs are joined to their task definitions; only tasks whose metadata.exam matches
    are kept (optionally narrowed to one metadata.exam_paper via ``paper``). Each
    task's best run quality score (0-100) is weighted by its metadata.exam_points,
    producing a percentage total and a grade. The result also contains a ``papers``
    grouping with per-paper totals and grades.
    """
    rows = database.fetch_all(
        "SELECT r.id AS run_id,r.test_case_id,r.status,r.score,r.lane,"
        "t.title AS test_title,t.definition_json,"
        "m.name AS model_name,a.name AS runner_name "
        "FROM runs r JOIN test_cases t ON t.id=r.test_case_id "
        "JOIN models m ON m.id=r.model_id JOIN agent_runners a ON a.id=r.runner_id "
        "WHERE r.experiment_id=?",
        (experiment_id,),
    )
    tasks: dict[str, dict[str, Any]] = {}
    attempts: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        try:
            definition = json.loads(row["definition_json"] or "{}")
        except json.JSONDecodeError:
            continue
        metadata = definition.get("metadata") or {}
        if metadata.get("exam") != exam:
            continue
        if paper is not None and metadata.get("exam_paper") != paper:
            continue
        task_id = row["test_case_id"]
        exam_points = float(metadata.get("exam_points") or 0)
        tasks.setdefault(
            task_id,
            {
                "title": row["test_title"],
                "exam_paper": metadata.get("exam_paper") or "",
                "exam_section": metadata.get("exam_section") or "",
                "exam_points": exam_points,
            },
        )
        key = (row["model_name"], row["runner_name"], row["lane"], task_id)
        attempts.setdefault(key, []).append(
            {"run_id": row["run_id"], "status": row["status"], "score": float(row["score"] or 0)}
        )
    combinations: dict[tuple[str, str, str], dict[str, Any]] = {}
    for (model_name, runner_name, lane, task_id), items in attempts.items():
        best = max(items, key=lambda item: item["score"])
        combo = combinations.setdefault(
            (model_name, runner_name, lane),
            {"model": model_name, "runner": runner_name, "lane": lane, "tasks": []},
        )
        task = tasks[task_id]
        weighted = best["score"] / 100 * task["exam_points"] if task["exam_points"] else 0.0
        combo["tasks"].append(
            {
                "test_case_id": task_id,
                "title": task["title"],
                "exam_section": task["exam_section"],
                "exam_points": task["exam_points"],
                "best_run_id": best["run_id"],
                "best_status": best["status"],
                "quality_score": round(best["score"], 2),
                "weighted_points": round(weighted, 2),
            }
        )
    total_points = sum(task["exam_points"] for task in tasks.values())
    combo_list = []
    for combo in combinations.values():
        combo["tasks"].sort(key=lambda item: item["exam_section"])
        earned = sum(item["weighted_points"] for item in combo["tasks"])
        percentage = earned / total_points * 100 if total_points else 0.0
        combo.update(
            {
                "earned_points": round(earned, 2),
                "total_points": round(total_points, 2),
                "total_score": round(percentage, 2),
                "grade": _exam_grade(percentage),
            }
        )
        combo_list.append(combo)
    combo_list.sort(key=lambda item: item["total_score"], reverse=True)
    overall_tasks = []
    for task_id, task in tasks.items():
        best = max(
            (item for key, items in attempts.items() if key[3] == task_id for item in items),
            key=lambda item: item["score"],
            default=None,
        )
        weighted = best["score"] / 100 * task["exam_points"] if best and task["exam_points"] else 0.0
        overall_tasks.append(
            {
                "test_case_id": task_id,
                "title": task["title"],
                "exam_section": task["exam_section"],
                "exam_points": task["exam_points"],
                "best_run_id": best["run_id"] if best else None,
                "quality_score": round(best["score"], 2) if best else 0.0,
                "weighted_points": round(weighted, 2),
            }
        )
    overall_tasks.sort(key=lambda item: item["exam_section"])
    overall_earned = sum(item["weighted_points"] for item in overall_tasks)
    overall_percentage = overall_earned / total_points * 100 if total_points else 0.0
    by_paper: dict[str, list[str]] = {}
    for task_id, task in tasks.items():
        by_paper.setdefault(task["exam_paper"], []).append(task_id)
    papers = [
        {"exam_paper": exam_paper, **_exam_paper_overall(sorted(task_ids), tasks, attempts)}
        for exam_paper, task_ids in sorted(by_paper.items())
    ]
    return {
        "experiment_id": experiment_id,
        "exam": exam,
        "paper": paper,
        "generated_at": datetime.now(UTC).isoformat(),
        "task_count": len(tasks),
        "total_points": round(total_points, 2),
        "overall": {
            "tasks": overall_tasks,
            "earned_points": round(overall_earned, 2),
            "total_score": round(overall_percentage, 2),
            "grade": _exam_grade(overall_percentage),
        },
        "papers": papers,
        "combinations": combo_list,
    }


def create_backup(database: Database, settings: Settings) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    staging = settings.backups_dir / f"staging-{timestamp}"
    staging.mkdir(parents=True, exist_ok=False)
    snapshot = staging / "agentbench.db"
    source = database.connect()
    target = sqlite3.connect(snapshot)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    manifest: dict[str, Any] = {
        "format": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "database_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
    }
    (staging / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    destination = settings.backups_dir / f"agentbench-backup-{timestamp}.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(snapshot, "agentbench.db")
        archive.write(staging / "manifest.json", "manifest.json")
    shutil.rmtree(staging)
    return destination


def restore_backup(content: bytes, database: Database, settings: Settings) -> dict[str, Any]:
    if len(content) > 2_000_000_000:
        raise ValueError("Backup is too large")
    staging = settings.backups_dir / f"restore-{uuid.uuid4()}"
    staging.mkdir(parents=True, exist_ok=False)
    archive_path = staging / "upload.zip"
    restored_path = staging / "restored.db"
    archive_path.write_bytes(content)
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = set(archive.namelist())
            if not {"manifest.json", "agentbench.db"}.issubset(names):
                raise ValueError("Backup does not contain the required manifest and database")
            manifest = json.loads(archive.read("manifest.json"))
            database_bytes = archive.read("agentbench.db")
        expected = str(manifest.get("database_sha256") or "")
        actual = hashlib.sha256(database_bytes).hexdigest()
        if not expected or expected != actual:
            raise ValueError("Backup checksum verification failed")
        restored_path.write_bytes(database_bytes)
        source = sqlite3.connect(restored_path)
        target = database.connect()
        try:
            quick_check = source.execute("PRAGMA quick_check").fetchone()
            if not quick_check or quick_check[0] != "ok":
                raise ValueError("Backup database failed SQLite integrity check")
            schema = source.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if not schema or int(schema[0]) > SCHEMA_VERSION:
                raise ValueError("Backup schema is newer than this AgentBench version")
            source.backup(target)
        finally:
            target.close()
            source.close()
        return {"ok": True, "schema_version": int(schema[0]), "manifest": manifest}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
