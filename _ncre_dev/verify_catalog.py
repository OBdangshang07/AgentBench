"""临时：验证 catalog.py NCRE 变更（一致性 + 结构）。"""
import base64
import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agentbench import catalog  # noqa: E402
from agentbench.ncre_assets import blobs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

cases = catalog.build_catalog()
print("total base cases:", len(cases))
ncre = [c for c in cases if c["category"] == "office-exam"]
print("ncre cases:", [c["slug"] for c in ncre])
assert len(cases) == 204, len(cases)
assert [c["slug"] for c in ncre] == [
    "ncre.office.paper01.choice",
    "ncre.office.paper01.word",
    "ncre.office.paper01.excel",
    "ncre.office.paper01.ppt",
]
assert cases[-4:] == ncre, "NCRE 必须位于末尾（防切片漂移）"

# 判分脚本一致性：catalog 内嵌 vs ncre_assets 文件 vs _ncre_dev 验证版
dev = ROOT / "_ncre_dev"
for case, name in zip(ncre, ["judge_choice.py", "judge_word.py", "judge_excel.py", "judge_ppt.py"]):
    embedded = case["private_files"][name]
    pkg = (ROOT / "backend" / "agentbench" / "ncre_assets" / name).read_text(encoding="utf-8")
    verified = (dev / name).read_text(encoding="utf-8")
    assert embedded == pkg == verified, f"{name} 不一致"
    print("judge 一致:", name, len(embedded), "chars")

# initial_files base64 可解码且为合法 OOXML zip
for case, fname in [(ncre[1], "Word.docx"), (ncre[2], "Excel.xlsx"), (ncre[3], "图书策划案.docx")]:
    content = case["initial_files"][fname]
    assert content.startswith("base64:")
    data = base64.b64decode(content[len("base64:"):])
    assert data[:2] == b"PK", fname
    print("素材可解码:", fname, len(data), "bytes")

# 验证器结构与分值
for case in ncre:
    weights = sum(v["weight"] for v in case["validators"])
    cm = next(v for v in case["validators"] if v["type"] == "command_metrics")
    declared = sum(m["weight"] for m in cm["config"]["metrics"])
    meta = case["metadata"]
    assert weights == 100, (case["slug"], weights)
    print(case["slug"], "validators=100, metric权重和=", declared,
          "exam_points=", meta["exam_points"], "exam=", meta["exam"],
          "internal_research_only=", meta["internal_research_only"])
assert sum(m["weight"] for m in next(v for v in ncre[0]["validators"] if v["type"] == "command_metrics")["config"]["metrics"]) == 20
assert sum(m["weight"] for m in next(v for v in ncre[1]["validators"] if v["type"] == "command_metrics")["config"]["metrics"]) == 30
assert sum(m["weight"] for m in next(v for v in ncre[2]["validators"] if v["type"] == "command_metrics")["config"]["metrics"]) == 30
assert sum(m["weight"] for m in next(v for v in ncre[3]["validators"] if v["type"] == "command_metrics")["config"]["metrics"]) == 20

# instruction 无答案泄漏
choice_instr = ncre[0]["instruction"]
assert choice_instr.count("q") >= 20 and "答案" not in "".join(
    v["config"].get("expected", "") for v in ncre[0]["validators"])
assert "EDCBA54321" in choice_instr  # q01 选项在题干中
for case in ncre:
    for key in ("instruction", "initial_files", "description"):
        blob = str(case[key])
        for leak in ('"q01": "B"', "ANSWERS"):
            assert leak not in blob, (case["slug"], leak)

print("suite id:", catalog.NCRE_OFFICE_SUITE_ID)
print("ALL CATALOG CHECKS PASS")
