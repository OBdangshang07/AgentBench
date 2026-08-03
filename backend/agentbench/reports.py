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
from .db import Database


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
            if not schema or int(schema[0]) > 3:
                raise ValueError("Backup schema is newer than this AgentBench version")
            source.backup(target)
        finally:
            target.close()
            source.close()
        return {"ok": True, "schema_version": int(schema[0]), "manifest": manifest}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
