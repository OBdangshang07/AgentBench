"""Detailed six-dimension experiment reports and a video-ready SVG panel."""

from __future__ import annotations

import html
import json
import math
from collections import defaultdict
from typing import Any

from .db import Database, utc_now
from .six_dimension_suite import DIMENSIONS

REPORT_SCHEMA = "agentbench.capability-report/v1"


def _json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _confidence_label(value: float) -> str:
    if value >= 0.9:
        return "high"
    if value >= 0.7:
        return "medium"
    return "low"


def _run_source(run: dict[str, Any], components: list[dict[str, Any]], judge_count: int) -> tuple[str, float]:
    manual = run.get("manual_review") or {}
    if manual.get("status") == "submitted" and manual.get("total_score") is not None:
        return "manual_review", 0.95
    validator_types = {str(item.get("dimension") or "") for item in components}
    if judge_count >= 2:
        return "anonymous_judges", 0.90
    if judge_count == 1 or "ai_rubric" in validator_types or "judge_quality" in validator_types:
        return "ai_judge", 0.75
    if run.get("score") is not None:
        return "deterministic", 0.95
    return "pending", 0.0


def build_capability_report(database: Database, experiment_id: str) -> dict[str, Any]:
    experiment = database.fetch_one(
        "SELECT e.*,s.name suite_name,s.version suite_version FROM experiments e "
        "JOIN test_suites s ON s.id=e.suite_id WHERE e.id=?",
        (experiment_id,),
    )
    if not experiment:
        raise KeyError("experiment_not_found")

    rows = database.fetch_all(
        "SELECT r.*,t.slug,t.title case_title,t.category,"
        "COALESCE(tr.definition_json,t.definition_json) definition_json,"
        "m.name model_name,m.provider model_provider,m.model_name model_route,"
        "ar.name runner_name,ar.runner_type "
        "FROM runs r JOIN test_cases t ON t.id=r.test_case_id "
        "LEFT JOIN test_case_revisions tr ON tr.id=r.test_revision_id "
        "JOIN models m ON m.id=r.model_id JOIN agent_runners ar ON ar.id=r.runner_id "
        "WHERE r.experiment_id=? ORDER BY m.name,ar.name,t.slug,r.repetition",
        (experiment_id,),
    )

    run_ids = [str(row["id"]) for row in rows]
    component_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    artifact_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    judge_counts: dict[str, int] = defaultdict(int)
    manual_map: dict[str, dict[str, Any]] = {}
    if run_ids:
        placeholders = ",".join("?" for _ in run_ids)
        for item in database.fetch_all(
            f"SELECT run_id,dimension,score,weight,evidence_json FROM score_components "
            f"WHERE run_id IN ({placeholders}) ORDER BY created_at,id",
            tuple(run_ids),
        ):
            component_map[str(item["run_id"])].append(
                {
                    "dimension": item["dimension"],
                    "score": round(float(item["score"]), 2),
                    "weight": float(item["weight"]),
                    "evidence": _json(item["evidence_json"], {}),
                }
            )
        for item in database.fetch_all(
            f"SELECT id,run_id,kind,name,size,sha256 FROM artifacts "
            f"WHERE run_id IN ({placeholders}) ORDER BY run_id,name",
            tuple(run_ids),
        ):
            artifact_map[str(item["run_id"])].append(
                {
                    "id": item["id"],
                    "kind": item["kind"],
                    "name": item["name"],
                    "size": int(item["size"] or 0),
                    "sha256": item.get("sha256"),
                    "download_url": f"/api/v1/runs/{item['run_id']}/artifacts/{item['id']}",
                }
            )
        for item in database.fetch_all(
            f"SELECT run_id,COUNT(*) count FROM judge_reviews "
            f"WHERE run_id IN ({placeholders}) AND status='completed' GROUP BY run_id",
            tuple(run_ids),
        ):
            judge_counts[str(item["run_id"])] = int(item["count"] or 0)
        for item in database.fetch_all(
            f"SELECT run_id,status,rubric_version,reviewer,dimension_scores_json,"
            f"checklist_json,critical_defects_json,comment,evidence_json,total_score,submitted_at "
            f"FROM manual_reviews WHERE run_id IN ({placeholders})",
            tuple(run_ids),
        ):
            manual_map[str(item["run_id"])] = {
                "status": item["status"],
                "rubric_version": item["rubric_version"],
                "reviewer": item["reviewer"],
                "dimension_scores": _json(item["dimension_scores_json"], {}),
                "checklist": _json(item["checklist_json"], {}),
                "critical_defects": _json(item["critical_defects_json"], []),
                "comment": item["comment"],
                "evidence": _json(item["evidence_json"], []),
                "total_score": item["total_score"],
                "submitted_at": item["submitted_at"],
            }

    profiles: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        definition = _json(row["definition_json"], {})
        metadata = definition.get("metadata") or {}
        dimension = str(metadata.get("capability_dimension") or "")
        if not dimension:
            continue
        profile_key = (str(row["model_id"]), str(row["runner_id"]))
        profile = profiles.setdefault(
            profile_key,
            {
                "profile_id": f"{row['model_id']}:{row['runner_id']}",
                "model": {
                    "id": row["model_id"],
                    "name": row["model_name"],
                    "provider": row["model_provider"],
                    "route": row["model_route"],
                },
                "runner": {
                    "id": row["runner_id"],
                    "name": row["runner_name"],
                    "type": row["runner_type"],
                },
                "runs": [],
            },
        )
        run_id = str(row["id"])
        manual_review = manual_map.get(run_id)
        row["manual_review"] = manual_review
        components = component_map.get(run_id, [])
        score_source, confidence = _run_source(row, components, judge_counts.get(run_id, 0))
        hard_gates: list[dict[str, Any]] = []
        raw_quality = None
        for component in components:
            evidence = component.get("evidence") or {}
            if component.get("dimension") == "hard_gate":
                hard_gates.extend(evidence.get("failures") or [])
            hard_gates.extend(evidence.get("score_caps") or [])
            hard_gates.extend(evidence.get('hard_failures') or [])
            if isinstance(evidence.get('raw_quality_score'), (int, float)):
                raw_quality = round(float(evidence['raw_quality_score']), 2)
        hard_gates = list({json.dumps(item, sort_keys=True, ensure_ascii=False): item
                           for item in hard_gates}.values())
        profile["runs"].append(
            {
                "run_id": run_id,
                "test_case_id": row["test_case_id"],
                "slug": row["slug"],
                "title": row["case_title"],
                "category": row["category"],
                "dimension": dimension,
                "repetition": int(row["repetition"] or 1),
                "status": row["status"],
                "passed": None if row["passed"] is None else bool(row["passed"]),
                "score": None if row["score"] is None else round(float(row["score"]), 2),
                "score_source": score_source,
                "raw_quality_score": raw_quality,
                "attempt_count": int(row.get('attempt_count') or 0),
                "effective_reasoning_effort": row.get('effective_reasoning_effort'),
                "effort_verified": bool(row.get('effort_verified')),
                "measurement_version": metadata.get('measurement_version'),
                "cost_source": row.get('cost_source'),
                "confidence": confidence,
                "confidence_label": _confidence_label(confidence),
                "duration_ms": int(row["duration_ms"] or 0),
                "steps": int(row["steps"] or 0),
                "tokens_input": int(row["tokens_input"] or 0),
                "tokens_output": int(row["tokens_output"] or 0),
                "cost_usd": round(float(row["cost_usd"] or 0), 6),
                "failure_class": row.get("failure_class"),
                "error_code": row.get("error_code"),
                "error_message": row.get("error_message"),
                "manual_review": manual_review,
                "judge_review_count": judge_counts.get(run_id, 0),
                "hard_gates": hard_gates,
                "components": components,
                "artifacts": artifact_map.get(run_id, []),
                "run_url": f"/runs/{run_id}",
                "preview_recommended": bool(metadata.get("video_capture_recommended")),
                "delivery_mode": metadata.get("delivery_mode", "workspace"),
            }
        )

    result_profiles: list[dict[str, Any]] = []
    for profile in profiles.values():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for run in profile.pop("runs"):
            grouped[run["dimension"]].append(run)
        dimensions: list[dict[str, Any]] = []
        for definition in DIMENSIONS:
            key = definition["key"]
            dimension_runs = grouped.get(key, [])
            scored = [item for item in dimension_runs if item["score"] is not None]
            score = (
                round(sum(float(item["score"]) for item in scored) / len(scored), 2)
                if scored
                else None
            )
            confidence = (
                sum(float(item["confidence"]) for item in scored) / len(scored)
                if scored
                else 0.0
            )
            dimensions.append(
                {
                    **definition,
                    "score": score,
                    "provisional": len(scored) != len(dimension_runs) or not dimension_runs,
                    "completed": sum(item["status"] in {"completed", "failed", "environment_unavailable"} for item in dimension_runs),
                    "scored": len(scored),
                    "total": len(dimension_runs),
                    "excluded": not dimension_runs,
                    "exclusion_reason": 'not_selected_in_experiment' if not dimension_runs else None,
                    "confidence": round(confidence, 3),
                    "confidence_label": _confidence_label(confidence),
                    "duration_ms": sum(int(item["duration_ms"]) for item in dimension_runs),
                    "tokens": sum(int(item["tokens_input"]) + int(item["tokens_output"]) for item in dimension_runs),
                    "cost_usd": round(sum(float(item["cost_usd"]) for item in dimension_runs), 6),
                    "runs": dimension_runs,
                }
            )
        available = [item for item in dimensions if item["score"] is not None]
        overall = (
            round(sum(float(item["score"]) for item in available) / len(available), 2)
            if available
            else None
        )
        ranked = sorted(available, key=lambda item: float(item["score"]), reverse=True)
        result_profiles.append(
            {
                **profile,
                "overall_score": overall,
                "overall_complete": bool(available)
                and all(not item["provisional"] for item in dimensions if item['total']),
                "measured_dimension_count": len(available),
                "requested_dimension_count": sum(bool(item['total']) for item in dimensions),
                "dimensions": dimensions,
                "strengths": [item["label"] for item in ranked[:2]],
                "weaknesses": [item["label"] for item in ranked[-2:]] if len(ranked) >= 2 else [],
                "totals": {
                    "runs": sum(item["total"] for item in dimensions),
                    "scored": sum(item["scored"] for item in dimensions),
                    "duration_ms": sum(item["duration_ms"] for item in dimensions),
                    "tokens": sum(item["tokens"] for item in dimensions),
                    "cost_usd": round(sum(item["cost_usd"] for item in dimensions), 6),
                },
            }
        )

    return {
        "schema": REPORT_SCHEMA,
        "generated_at": utc_now(),
        "experiment": {
            "id": experiment["id"],
            "name": experiment["name"],
            "status": experiment["status"],
            "suite_id": experiment["suite_id"],
            "suite_name": experiment["suite_name"],
            "suite_version": experiment["suite_version"],
            "started_at": experiment["started_at"],
            "completed_at": experiment["completed_at"],
        },
        "dimension_definitions": list(DIMENSIONS),
        "profiles": result_profiles,
    }


def render_capability_panel_svg(report: dict[str, Any], profile_id: str | None = None) -> str:
    profiles = list(report.get("profiles") or [])
    if not profiles:
        raise ValueError("capability_report_has_no_profiles")
    profile = next(
        (item for item in profiles if item.get("profile_id") == profile_id),
        profiles[0],
    )
    dimensions = list(profile.get("dimensions") or [])
    values = [
        None if item.get("score") is None else float(item["score"])
        for item in dimensions
    ]
    # Keep the radar clear of the three-line title block.  The former
    # cy=450/r=270 geometry placed the top axis label at y=138, directly over
    # the subtitle at y=158 in a 1600x900 export.
    cx, cy, radius = 490.0, 500.0, 240.0
    angles = [(-math.pi / 2) + index * 2 * math.pi / 6 for index in range(6)]

    def points(scale: float, scores: list[float] | None = None) -> str:
        result = []
        for index, angle in enumerate(angles):
            ratio = (scores[index] / 100.0) if scores is not None else scale
            result.append(f"{cx + math.cos(angle) * radius * ratio:.1f},{cy + math.sin(angle) * radius * ratio:.1f}")
        return " ".join(result)

    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    colors = ["#7C5CFF", "#00D7FF", "#FFB44A", "#FF5FA2", "#74E39A", "#9BA8FF"]
    svg: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900" role="img" aria-label="大模型六维能力面板">',
        "<defs>",
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#090B16"/><stop offset="1" stop-color="#151A32"/></linearGradient>',
        '<linearGradient id="radar" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#7C5CFF" stop-opacity=".72"/><stop offset="1" stop-color="#00D7FF" stop-opacity=".38"/></linearGradient>',
        '<filter id="glow"><feGaussianBlur stdDeviation="9" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        "</defs>",
        '<rect width="1600" height="900" fill="url(#bg)"/>',
        '<circle cx="1440" cy="80" r="280" fill="#7C5CFF" opacity=".08"/>',
        '<circle cx="70" cy="850" r="300" fill="#00D7FF" opacity=".05"/>',
        '<text x="76" y="72" fill="#8F9BBD" font-size="18" font-family="Inter,Segoe UI,sans-serif" letter-spacing="4">MODEL CAPABILITY / SIX DIMENSIONS</text>',
        f'<text x="76" y="125" fill="#F7F8FF" font-size="38" font-weight="700" font-family="Inter,Segoe UI,sans-serif">{esc(profile["model"]["name"])}</text>',
        f'<text x="76" y="158" fill="#8994B5" font-size="17" font-family="Inter,Segoe UI,sans-serif">{esc(profile["runner"]["name"])} · {esc(report["experiment"]["name"])}</text>',
    ]
    for level in (0.2, 0.4, 0.6, 0.8, 1.0):
        svg.append(f'<polygon points="{points(level)}" fill="none" stroke="#FFFFFF" stroke-opacity="{0.08 if level < 1 else 0.16}"/>')
    for angle in angles:
        svg.append(f'<line x1="{cx}" y1="{cy}" x2="{cx + math.cos(angle) * radius:.1f}" y2="{cy + math.sin(angle) * radius:.1f}" stroke="#FFFFFF" stroke-opacity=".12"/>')
    if all(value is not None for value in values):
        complete_values = [float(value) for value in values if value is not None]
        svg.append(
            f'<polygon data-role="capability-shape" points="{points(1, complete_values)}" '
            'fill="url(#radar)" stroke="#87E9FF" stroke-width="3" filter="url(#glow)"/>'
        )
    else:
        # Missing dimensions are unknown, not zero. Draw only edges whose two
        # endpoints were actually scored so a pending axis never collapses the
        # radar to the centre or creates a misleading filled area.
        for index, value in enumerate(values):
            next_index = (index + 1) % len(values)
            next_value = values[next_index]
            if value is None or next_value is None:
                continue
            x1 = cx + math.cos(angles[index]) * radius * value / 100
            y1 = cy + math.sin(angles[index]) * radius * value / 100
            x2 = cx + math.cos(angles[next_index]) * radius * next_value / 100
            y2 = cy + math.sin(angles[next_index]) * radius * next_value / 100
            svg.append(
                f'<line data-role="capability-segment" x1="{x1:.1f}" y1="{y1:.1f}" '
                f'x2="{x2:.1f}" y2="{y2:.1f}" stroke="#87E9FF" '
                'stroke-width="3" stroke-linecap="round" filter="url(#glow)"/>'
            )
    for index, (angle, item) in enumerate(zip(angles, dimensions, strict=True)):
        x = cx + math.cos(angle) * (radius + 52)
        y = cy + math.sin(angle) * (radius + 42)
        anchor = "middle" if abs(math.cos(angle)) < 0.2 else "start" if math.cos(angle) > 0 else "end"
        score_text = ("未测" if item.get('excluded') else "待评分") if item.get("score") is None else f'{float(item["score"]):.1f}'
        value = values[index]
        if value is not None:
            svg.append(
                f'<circle data-role="capability-point" data-dimension="{esc(item["key"])}" '
                f'cx="{cx + math.cos(angle) * radius * value / 100:.1f}" '
                f'cy="{cy + math.sin(angle) * radius * value / 100:.1f}" '
                f'r="6" fill="{colors[index]}"/>'
            )
        svg.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" fill="#DCE2F5" font-size="17" font-weight="600" font-family="Inter,Segoe UI,sans-serif">{esc(item["label"])}</text>')
        svg.append(f'<text x="{x:.1f}" y="{y + 24:.1f}" text-anchor="{anchor}" fill="{colors[index]}" font-size="16" font-family="Inter,Segoe UI,sans-serif">{score_text}</text>')

    overall = profile.get("overall_score")
    overall_text = "—" if overall is None else f"{float(overall):.1f}"
    complete_text = "最终成绩" if profile.get("overall_complete") else "阶段成绩 · 未完成维度不计入"
    svg.extend(
        [
            '<rect x="980" y="92" width="540" height="716" rx="30" fill="#FFFFFF" fill-opacity=".055" stroke="#FFFFFF" stroke-opacity=".1"/>',
            f'<text x="1040" y="178" fill="#F7F8FF" font-size="82" font-weight="750" font-family="Inter,Segoe UI,sans-serif">{overall_text}</text>',
            '<text x="1045" y="210" fill="#7F8BAD" font-size="16" font-family="Inter,Segoe UI,sans-serif">OVERALL / 100</text>',
            f'<text x="1045" y="242" fill="#9FA9C7" font-size="15" font-family="Inter,Segoe UI,sans-serif">{esc(complete_text)}</text>',
        ]
    )
    for index, item in enumerate(dimensions):
        y = 300 + index * 72
        score = item.get("score")
        width = 0 if score is None else 320 * float(score) / 100
        label = "—" if score is None else f"{float(score):.1f}"
        status = f'{item.get("scored", 0)}/{item.get("total", 0)} 已评分'
        svg.append(f'<text x="1045" y="{y}" fill="#DDE3F6" font-size="17" font-family="Inter,Segoe UI,sans-serif">{esc(item["label"])}</text>')
        svg.append(f'<text x="1460" y="{y}" text-anchor="end" fill="{colors[index]}" font-size="18" font-weight="700" font-family="Inter,Segoe UI,sans-serif">{label}</text>')
        svg.append(f'<rect x="1045" y="{y + 15}" width="320" height="8" rx="4" fill="#FFFFFF" opacity=".08"/>')
        svg.append(f'<rect x="1045" y="{y + 15}" width="{width:.1f}" height="8" rx="4" fill="{colors[index]}"/>')
        svg.append(f'<text x="1380" y="{y + 24}" fill="#7782A3" font-size="13" font-family="Inter,Segoe UI,sans-serif">{esc(status)}</text>')
    totals = profile.get("totals") or {}
    svg.extend(
        [
            f'<text x="76" y="850" fill="#7782A3" font-size="15" font-family="Inter,Segoe UI,sans-serif">{esc(report["generated_at"])} · {totals.get("scored", 0)}/{totals.get("runs", 0)} runs scored · {int(totals.get("tokens", 0)):,} tokens</text>',
            '<text x="1520" y="850" text-anchor="end" fill="#7782A3" font-size="15" font-family="Inter,Segoe UI,sans-serif">AgentBench · evidence-backed evaluation</text>',
            "</svg>",
        ]
    )
    return "".join(svg)


__all__ = ["REPORT_SCHEMA", "build_capability_report", "render_capability_panel_svg"]
