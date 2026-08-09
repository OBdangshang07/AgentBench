"""临时：sync_catalog 端到端冒烟（临时 DB）。"""
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agentbench import catalog  # noqa: E402
from agentbench.db import Database  # noqa: E402

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    db = Database(Path(tmp) / "smoke.db")
    db.initialize()
    catalog.seed_builtin_data(db)
    total = db.fetch_one("SELECT COUNT(*) AS n FROM test_cases WHERE builtin=1")["n"]
    ncre = db.fetch_all(
        "SELECT slug FROM test_cases WHERE category='office-exam' ORDER BY slug")
    suite = db.fetch_one(
        "SELECT name, description, version FROM test_suites WHERE id=?",
        (catalog.NCRE_OFFICE_SUITE_ID,))
    members = db.fetch_one(
        "SELECT COUNT(*) AS n FROM suite_cases WHERE suite_id=?",
        (catalog.NCRE_OFFICE_SUITE_ID,))["n"]
    v2 = db.fetch_one("SELECT description FROM test_suites WHERE id=?",
                      (catalog.V2_FULL_SUITE_ID,))["description"]
    v2n = db.fetch_one(
        "SELECT COUNT(*) AS n FROM suite_cases WHERE suite_id=?",
        (catalog.V2_FULL_SUITE_ID,))["n"]
    print("builtin cases:", total)
    print("ncre slugs:", [r["slug"] for r in ncre])
    print("suite:", suite["name"], "|", suite["version"], "| members:", members)
    print("v2_full:", v2, "| members:", v2n)
    assert total == 204 + 2 or total >= 204  # ultra 另计
    assert len(ncre) == 4 and members == 4 and v2n == 204
    assert v2.startswith("204 个")
    # 定义 JSON 含 private_files（DB 内完整）且 public 定义剥离
    row = db.fetch_one(
        "SELECT definition_json FROM test_cases WHERE slug='ncre.office.paper01.choice'")
    import json
    definition = json.loads(row["definition_json"])
    assert "judge_choice.py" in definition["private_files"]
    print("SYNC SMOKE PASS")
