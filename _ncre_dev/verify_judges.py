"""临时脚本：在标准产物工作区运行三卷判分脚本并断言满分；空工作区断言全 0。

用法：python verify_judges.py [paper01|paper02|paper03|all]（默认 all）。
paper01 judge 取本目录副本；paper02/03 judge 取 backend/agentbench/ncre_assets。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

DEV = Path(__file__).parent
ASSETS = DEV.parent / "backend" / "agentbench" / "ncre_assets"

PAPERS = {
    "paper01": {
        "workspace": DEV / "reference-workspace",
        "judges": {
            DEV / "judge_choice.py": [f"q{i:02d}" for i in range(1, 21)],
            DEV / "judge_word.py": [f"w{i}" for i in range(1, 10)],
            DEV / "judge_excel.py": [f"e{i}" for i in range(1, 10)],
            DEV / "judge_ppt.py": [f"p{i}" for i in range(1, 9)],
        },
    },
    "paper02": {
        "workspace": DEV / "reference-workspace-paper02",
        "judges": {
            ASSETS / "judge_choice_paper02.py": [f"q{i:02d}" for i in range(1, 21)],
            ASSETS / "judge_word_paper02.py": [f"w{i}" for i in range(1, 10)],
            ASSETS / "judge_excel_paper02.py": [f"e{i}" for i in range(1, 9)],
            ASSETS / "judge_ppt_paper02.py": [f"p{i}" for i in range(1, 8)],
        },
    },
    "paper03": {
        "workspace": DEV / "reference-workspace-paper03",
        "judges": {
            ASSETS / "judge_choice_paper03.py": [f"q{i:02d}" for i in range(1, 21)],
            ASSETS / "judge_word_paper03.py": [f"w{i}" for i in range(1, 10)],
            ASSETS / "judge_excel_paper03.py": [f"e{i}" for i in range(1, 9)],
            ASSETS / "judge_ppt_paper03.py": [f"p{i}" for i in range(1, 8)],
        },
    },
}

PREFIX = "AGENTBENCH_METRICS="


def run_judge(judge: Path, workspace: Path) -> dict | None:
    result = subprocess.run(
        [sys.executable, str(judge)], cwd=workspace,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False)
    line = next((item for item in result.stdout.splitlines()
                 if item.startswith(PREFIX)), None)
    if line is None:
        print(f"[FAIL] {judge.name}: 无协议行\nstdout={result.stdout}\nstderr={result.stderr}")
        return None
    return json.loads(line[len(PREFIX):])


def main(papers: list[str]) -> int:
    failures = 0
    for paper in papers:
        config = PAPERS[paper]
        print(f"==== {paper} ====")
        for judge, keys in config["judges"].items():
            payload = run_judge(judge, config["workspace"])
            if payload is None:
                failures += 1
                continue
            metrics = payload["metrics"]
            bad = {k: metrics.get(k) for k in keys if metrics.get(k) != 100.0}
            missing = [k for k in keys if k not in metrics]
            if bad or missing:
                failures += 1
                print(f"[FAIL] {judge.name}: 未满分 {bad} 缺失 {missing}")
                print("evidence:",
                      json.dumps(payload["evidence"], ensure_ascii=False, indent=1))
            else:
                print(f"[OK] {judge.name}: {len(keys)} 项全部 100")

        # 容错场景：空工作区应输出全 0 协议行而非崩溃
        empty = Path(tempfile.mkdtemp(prefix=f"ncre-empty-{paper}-"))
        for judge in config["judges"]:
            payload = run_judge(judge, empty)
            if payload is None:
                failures += 1
                continue
            if any(value != 0.0 for value in payload["metrics"].values()):
                print(f"[FAIL] {judge.name} 空工作区: 存在非零指标 {payload['metrics']}")
                failures += 1
            else:
                print(f"[OK] {judge.name} 空工作区: 全 0 协议行")
    return failures


if __name__ == "__main__":
    targets = sys.argv[1:] or list(PAPERS)
    if targets == ["all"]:
        targets = list(PAPERS)
    unknown = [item for item in targets if item not in PAPERS]
    if unknown:
        raise SystemExit(f"未知卷别: {unknown}（可选 {list(PAPERS)} 或 all）")
    failed = main(targets)
    print("ALL PASS" if failed == 0 else f"{failed} FAILURES")
    raise SystemExit(0 if failed == 0 else 1)
