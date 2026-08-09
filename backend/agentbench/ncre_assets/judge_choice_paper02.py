# NCRE 选择题私有判分脚本（经典题库第2套，AgentBench command_metrics 协议）
# 读取工作区 answers.json，与私有答案表逐题比对；文件缺失/JSON 损坏时输出全 0。
import contextlib
import json
import sys

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ANSWERS = {
    "q01": "A", "q02": "A", "q03": "A", "q04": "A", "q05": "A",
    "q06": "A", "q07": "C", "q08": "B", "q09": "D", "q10": "B",
    "q11": "A", "q12": "B", "q13": "C", "q14": "D", "q15": "B",
    "q16": "A", "q17": "A", "q18": "A", "q19": "C", "q20": "A",
}

metrics = {key: 0.0 for key in ANSWERS}
evidence = {}

try:
    with open("answers.json", encoding="utf-8") as handle:
        data = json.load(handle)
except Exception as exc:  # noqa: BLE001 - 判分脚本必须容错
    data = None
    evidence["error"] = f"answers.json 读取失败: {str(exc)[:200]}"

if isinstance(data, dict):
    for key, expected in ANSWERS.items():
        given = data.get(key)
        evidence[key] = str(given)[:10]
        if isinstance(given, str) and given.strip().upper() == expected:
            metrics[key] = 100.0
else:
    evidence.setdefault("error", "answers.json 不是 JSON 对象")

print("AGENTBENCH_METRICS=" + json.dumps({"metrics": metrics, "evidence": evidence}))
