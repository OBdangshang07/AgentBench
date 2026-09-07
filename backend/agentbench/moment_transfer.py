"""Exact finite moment problem: primal/dual certificates, not a memorized exam."""

from __future__ import annotations

import copy
import json
from fractions import Fraction as F
from functools import lru_cache
from itertools import combinations


def solve(matrix, target):
    rows = [[F(x) for x in row] + [F(b)] for row, b in zip(matrix, target, strict=False)]
    for col in range(len(rows)):
        pivot = next((i for i in range(col, len(rows)) if rows[i][col]), None)
        if pivot is None:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [v / divisor for v in rows[col]]
        for i in range(len(rows)):
            if i != col:
                factor = rows[i][col]
                rows[i] = [a - factor * b for a, b in zip(rows[i], rows[col], strict=False)]
    return [row[-1] for row in rows]


@lru_cache(maxsize=8)
def certificates(weights: tuple[int, ...]):
    support = range(len(weights))
    total = sum(weights)
    moments = [sum(F(w, total) * x**k for x, w in enumerate(weights)) for k in range(4)]
    vertices = []
    for active in combinations(support, 4):
        p = solve([[x**k for x in active] for k in range(4)], moments)
        if p is not None and min(p) >= 0:
            full = [F(0)] * len(weights)
            for x, prob in zip(active, p, strict=False):
                full[x] = prob
            if full not in vertices:
                vertices.append(full)
    answers = {}
    for threshold in (3, 4, 5):
        payoff = [int(x >= threshold) for x in support]
        for upper in (False, True):
            bound = (max if upper else min)(
                sum(p[x] * payoff[x] for x in support) for p in vertices
            )
            primal = next(p for p in vertices if sum(p[x] * payoff[x] for x in support) == bound)
            dual = None
            for active in combinations(support, 4):
                c = solve([[x**k for k in range(4)] for x in active], [payoff[x] for x in active])
                if c is None:
                    continue
                delta = [sum(c[k] * x**k for k in range(4)) - payoff[x] for x in support]
                if (min(delta) >= 0 if upper else max(delta) <= 0) and sum(
                    a * b for a, b in zip(c, moments, strict=False)
                ) == bound:
                    dual = c
                    break
            assert dual is not None
            answers[f"{'upper' if upper else 'lower'}_{threshold}"] = {
                "value": bound,
                "probabilities": primal,
                "dual_coefficients": dual,
            }
    # Full parametric support-function envelope for lambda >= 0.
    lines = sorted(set((sum(p[3:]), sum(p[5:])) for p in vertices))
    crossings = {F(0)}
    for (a, b), (c, d) in combinations(lines, 2):
        if b != d and (value := (c - a) / (b - d)) > 0:
            crossings.add(value)
    cuts = sorted(crossings)
    segments = []
    for i, left in enumerate(cuts):
        right = cuts[i + 1] if i + 1 < len(cuts) else None
        probe = (left + right) / 2 if right is not None else left + 1
        line = max(lines, key=lambda pair: pair[0] + probe * pair[1])
        if not segments or line != segments[-1]["line"]:
            primal = next(p for p in vertices if (sum(p[3:]), sum(p[5:])) == line)
            segments.append({"from": left, "line": line, "probabilities": primal})
    return moments, answers, segments


def _variant(weights, number):
    moments, answers, segments = certificates(tuple(weights))
    fields = {
        key: {"kind": "expression", "expected": str(value["value"]), "variables": [], "weight": 1}
        for key, value in answers.items()
    }
    fields["switch_count"] = {
        "kind": "expression",
        "expected": str(len(segments) - 1),
        "variables": [],
        "weight": 1,
    }
    prompt = (
        "闭卷数学迁移与证书构造。随机变量 X 的支持严格为 {0,1,2,3,4,5,6,7} 的子集，"
        f"E[X]={moments[1]}，E[X²]={moments[2]}，E[X³]={moments[3]}。除此之外没有分布假设。\n"
        "1. 分别求 P(X≥3)、P(X≥4)、P(X≥5) 的精确最小值与最大值。每一界都要给出达到它的概率向量。\n"
        "2. 对六个界分别构造次数≤3的多项式对偶证书：在全部八个支持点上逐点证明其位于事件指标函数上方/下方，"
        "再用已知矩计算期望并证明与候选分布的目标值相同。仅枚举或引用求解器不算证明。\n"
        "3. 对所有 λ≥0 求 V(λ)=sup[P(X≥3)+λP(X≥5)] 的完整分段线性公式、所有切换点以及各段达到上界的分布。"
        "说明能否把两个尾概率的各自上界同时相加，给出可行性或不可能性证明。\n"
        "4. 解释为何这些矩不能唯一识别分布，构造两个不同的可行分布，并证明你的上下界并未额外假设独立性或最大熵。\n"
        "所有结论用精确有理数。最终给单个 JSON，字段 lower_3、upper_3、lower_4、upper_4、lower_5、upper_5 为有理数字符串；"
        "switch_count 为 λ>0 时最优公式的切换点个数；solution 包含全部构造与证明。不能使用工具。"
    )
    reference = json.dumps(
        {"moments": moments, "bounds": answers, "envelope": segments},
        default=str,
        ensure_ascii=False,
    )
    return {
        "variant_id": f"finite-moments-{number}",
        "instruction": prompt,
        "validator_config_overrides": [
            {"type": "symbolic_json", "config": {"fields": fields}},
            {
                "type": "ai_rubric",
                "config": {"reference_answer": reference, "solution_obligations": [prompt]},
            },
        ],
    }


def build_moment_transfer_case():
    variants = [
        _variant(w, i)
        for i, w in enumerate(
            ((1, 2, 3, 4, 4, 3, 2, 1), (3, 1, 4, 2, 5, 2, 1, 2), (2, 5, 1, 3, 1, 4, 3, 1)), 1
        )
    ]
    first = variants[0]
    descriptions = [
        ("六个最优界与六个达到界的概率分布；逐一核对归一性、非负性和三个矩", 30),
        ("六个对偶多项式，在八个支持点逐项验证方向及原始/对偶目标一致", 30),
        ("完整 λ≥0 参数包络、精确切换点、各段最优分布以及联合上界可达性", 30),
        ("不同可行分布的构造、不可识别性解释和未添加分布假设", 10),
    ]
    points = [
        {
            "point_id": f"moment.{i}",
            "description": description,
            "max_points": weight,
            "critical": True,
            "mandatory": True,
            "depends_on": [],
            "minimum_defect_deduction": 2,
            "evidence_required": ["引用具体概率向量、多项式、逐点检验或推导；不得凭结论给满分"],
        }
        for i, (description, weight) in enumerate(descriptions, 1)
    ]
    return {
        "slug": "sixdim.math.moment-duality-transfer",
        "version": "5.0.0",
        "category": "math",
        "title": "数学迁移 Frontier · 部分识别与参数化最优证书",
        "description": "隐藏矩参数；精确原始/对偶证书、不可识别性与联合风险边界。",
        "instruction": first["instruction"],
        "tools": [],
        "limits": {
            "max_steps": 160,
            "time_target_seconds": 3600,
            "max_runtime_seconds": 10800,
            "token_budget": 180000,
        },
        "validators": [
            {
                "type": "symbolic_json",
                "weight": 40,
                "config": {
                    **copy.deepcopy(first["validator_config_overrides"][0]["config"]),
                    "score_cap_on_failure": 70,
                    "score_cap_threshold": 100,
                },
            },
            {
                "type": "ai_rubric",
                "weight": 60,
                "config": {
                    **copy.deepcopy(first["validator_config_overrides"][1]["config"]),
                    "rubric_version": "moment-transfer-v1",
                    "scoring_points": points,
                    "max_points": 100,
                    "question_points": 100,
                    "required_judges": 3,
                    "consensus_mode": "defect_aware",
                    "full_credit_confidence": 0.95,
                    "judge_disagreement_threshold": 2,
                    "critical_failure_score_cap": 60,
                    "mandatory_failure_score_cap": 80,
                },
            },
        ],
        "_private_frontier_variants": {
            "schema": "agentbench.frontier-variants/v1",
            "pool_version": "moment-transfer-pool-v1",
            "variants": variants,
        },
        "metadata": {
            "capability_dimension": "mathematical_reasoning",
            "score_basis": "quality_only",
            "mastery_curve": "frontier_v1",
            "requires_judge": True,
            "difficulty": 6,
            "tier": "frontier",
            "frontier_profile": "primal-dual-transfer-v1",
        },
        "tags": [
            "six-dimension",
            "closed-book",
            "transfer",
            "partial-identification",
            "dual-certificate",
        ],
    }
