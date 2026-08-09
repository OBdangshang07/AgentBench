from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import textwrap
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


def _validator(kind: str, weight: float, **config: Any) -> dict[str, Any]:
    return {"type": kind, "weight": weight, "config": config}


def _flatten_answer(
    value: Any,
    *,
    prefix: str = "",
    literals: set[str] | None = None,
    variables: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    literal_paths = literals or set()
    variable_paths = variables or {}
    fields: dict[str, dict[str, Any]] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            fields.update(
                _flatten_answer(
                    item,
                    prefix=path,
                    literals=literal_paths,
                    variables=variable_paths,
                )
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}.{index}"
            fields.update(
                _flatten_answer(
                    item,
                    prefix=path,
                    literals=literal_paths,
                    variables=variable_paths,
                )
            )
    else:
        spec: dict[str, Any] = {"expected": value, "weight": 1}
        if prefix not in literal_paths:
            spec["kind"] = "expression"
            spec["variables"] = variable_paths.get(prefix, ["x"])
        fields[prefix] = spec
    return fields


def _planning_case(index: int) -> dict[str, Any]:
    scenario_id = f"PLAN-V3-{index:03d}"
    cost_offset = index % 3
    tasks = [
        {"id": "A", "name": "discovery", "depends_on": [], "normal": [2, 8], "fast": [1, 13], "resources": {"analyst": 1}},
        {"id": "B", "name": "architecture", "depends_on": ["A"], "normal": [3, 14], "fast": [2, 19], "resources": {"engineer": 2}},
        {"id": "C", "name": "data-preparation", "depends_on": ["A"], "normal": [4, 12], "fast": [3, 17], "resources": {"data": 2}},
        {"id": "D", "name": "security-controls", "depends_on": ["B"], "normal": [2, 10], "fast": [1, 15], "resources": {"security": 1}},
        {"id": "E", "name": "implementation", "depends_on": ["B", "C"], "normal": [5, 25], "fast": [4, 31], "resources": {"engineer": 2}},
        {"id": "F", "name": "migration-rehearsal", "depends_on": ["C", "D"], "normal": [3, 15], "fast": [2, 21], "resources": {"engineer": 1, "data": 1}},
        {"id": "G", "name": "guarded-pilot", "depends_on": ["E", "F"], "normal": [2, 12], "fast": [1, 18], "resources": {"engineer": 1, "operations": 1}},
        {"id": "H", "name": "progressive-rollout", "depends_on": ["G"], "normal": [2, 18], "fast": [1, 25], "resources": {"operations": 2}},
    ]
    for task in tasks:
        normal_duration, normal_cost = task.pop("normal")
        fast_duration, fast_cost = task.pop("fast")
        task["modes"] = {
            "normal": {"duration": normal_duration, "cost": normal_cost + cost_offset},
            "fast": {"duration": fast_duration, "cost": fast_cost + cost_offset},
        }
    normal_cost = sum(int(task["modes"]["normal"]["cost"]) for task in tasks)
    scenario = {
        "scenario_id": scenario_id,
        "unit": "week",
        "deadline": 16 + (index % 2),
        "budget": normal_cost + 4,
        "resource_capacity": {
            "analyst": 1,
            "engineer": 3,
            "data": 2,
            "security": 1,
            "operations": 2,
        },
        "rollout_window": {"earliest_start": 14, "latest_finish": 17},
        "requirements": {
            "human_override": True,
            "rollback_minutes_max": 30,
            "minimum_contingencies": 2,
        },
        "tasks": tasks,
    }
    scenario_text = json.dumps(scenario, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    scenario_hash = hashlib.sha256(
        json.dumps(scenario, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    reference = {
        "scenario_id": scenario_id,
        "tasks": [
            {"id": task_id, "mode": "normal", "start": start}
            for task_id, start in (
                ("A", 0),
                ("B", 2),
                ("C", 2),
                ("D", 5),
                ("E", 6),
                ("F", 7),
                ("G", 11),
                ("H", 14),
            )
        ],
        "rollback": {
            "owner": "release-manager",
            "trigger": "pilot error rate exceeds 2% or a security control fails",
            "max_minutes": 30,
            "human_override": True,
        },
        "contingencies": [
            "If rehearsal misses its exit criteria, defer the pilot and restore the signed snapshot.",
            "If rollout capacity is unavailable, retain the guarded pilot and move H within its window.",
        ],
        "tradeoffs": [
            "Normal modes preserve the budget reserve while meeting the rollout window.",
            "Engineering capacity is shared by implementation and rehearsal but never exceeds three.",
        ],
    }
    _validator_source = textwrap.dedent(
        r'''
        import hashlib
        import json
        import pathlib

        metrics = {
            "coverage": 0,
            "dependencies": 0,
            "resources": 0,
            "budget_deadline": 0,
            "safety_controls": 0,
            "objective_quality": 0,
        }
        evidence = {}
        workspace = pathlib.Path(__file__).resolve().parent.parent
        try:
            scenario = json.loads((workspace / "scenario.json").read_text(encoding="utf-8-sig"))
            scenario_hash = hashlib.sha256(
                json.dumps(scenario, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if scenario_hash != "__SCENARIO_HASH__":
                raise AssertionError("scenario.json was modified")
            plan = json.loads((workspace / "deliverables" / "plan.json").read_text(encoding="utf-8-sig"))
            task_specs = {item["id"]: item for item in scenario["tasks"]}
        except Exception as exc:
            evidence["bootstrap"] = repr(exc)
        else:
            scheduled = {}
            try:
                assert plan["scenario_id"] == scenario["scenario_id"]
                assert isinstance(plan["tasks"], list) and len(plan["tasks"]) == len(task_specs)
                for item in plan["tasks"]:
                    assert set(item) == {"id", "mode", "start"}
                    assert item["id"] in task_specs and item["id"] not in scheduled
                    assert item["mode"] in task_specs[item["id"]]["modes"]
                    assert type(item["start"]) is int and item["start"] >= 0
                    mode = task_specs[item["id"]]["modes"][item["mode"]]
                    scheduled[item["id"]] = {
                        **item,
                        "duration": int(mode["duration"]),
                        "cost": int(mode["cost"]),
                        "finish": int(item["start"]) + int(mode["duration"]),
                    }
                assert set(scheduled) == set(task_specs)
                metrics["coverage"] = 100
            except Exception as exc:
                evidence["coverage"] = repr(exc)

            try:
                assert set(scheduled) == set(task_specs)
                for task_id, item in scheduled.items():
                    for dependency in task_specs[task_id]["depends_on"]:
                        assert item["start"] >= scheduled[dependency]["finish"], (task_id, dependency)
                metrics["dependencies"] = 100
            except Exception as exc:
                evidence["dependencies"] = repr(exc)

            try:
                assert set(scheduled) == set(task_specs)
                makespan = max(item["finish"] for item in scheduled.values())
                for moment in range(makespan):
                    used = {name: 0 for name in scenario["resource_capacity"]}
                    for task_id, item in scheduled.items():
                        if item["start"] <= moment < item["finish"]:
                            for resource, amount in task_specs[task_id]["resources"].items():
                                used[resource] += int(amount)
                    assert all(
                        used[name] <= int(capacity)
                        for name, capacity in scenario["resource_capacity"].items()
                    ), (moment, used)
                metrics["resources"] = 100
            except Exception as exc:
                evidence["resources"] = repr(exc)

            try:
                total_cost = sum(item["cost"] for item in scheduled.values())
                makespan = max(item["finish"] for item in scheduled.values())
                rollout = scheduled["H"]
                assert total_cost <= scenario["budget"]
                assert makespan <= scenario["deadline"]
                assert rollout["start"] >= scenario["rollout_window"]["earliest_start"]
                assert rollout["finish"] <= scenario["rollout_window"]["latest_finish"]
                metrics["budget_deadline"] = 100
                evidence["budget_deadline"] = {"cost": total_cost, "makespan": makespan}
            except Exception as exc:
                evidence["budget_deadline"] = repr(exc)

            try:
                rollback = plan["rollback"]
                assert rollback["human_override"] is True
                assert 0 < int(rollback["max_minutes"]) <= scenario["requirements"]["rollback_minutes_max"]
                assert len(str(rollback["owner"]).strip()) >= 3
                assert len(str(rollback["trigger"]).strip()) >= 20
                assert len(plan["contingencies"]) >= scenario["requirements"]["minimum_contingencies"]
                assert all(len(str(item).strip()) >= 25 for item in plan["contingencies"])
                metrics["safety_controls"] = 100
            except Exception as exc:
                evidence["safety_controls"] = repr(exc)

            try:
                makespan = max(item["finish"] for item in scheduled.values())
                total_cost = sum(item["cost"] for item in scheduled.values())
                reserve = scenario["budget"] - total_cost
                assert makespan <= 16 and reserve >= 4
                assert len(plan["tradeoffs"]) >= 2
                assert all(len(str(item).strip()) >= 30 for item in plan["tradeoffs"])
                metrics["objective_quality"] = 100
                evidence["objective_quality"] = {"makespan": makespan, "budget_reserve": reserve}
            except Exception as exc:
                evidence["objective_quality"] = repr(exc)

        print("AGENTBENCH_METRICS=" + json.dumps({"metrics": metrics, "evidence": evidence}, sort_keys=True))
        '''
    ).replace("__SCENARIO_HASH__", scenario_hash).strip()
    _metrics = [
        {"key": "coverage", "name": "计划覆盖与接口", "weight": 10},
        {"key": "dependencies", "name": "依赖时序", "weight": 20},
        {"key": "resources", "name": "资源容量", "weight": 20},
        {"key": "budget_deadline", "name": "预算、期限与发布窗口", "weight": 20},
        {"key": "safety_controls", "name": "人工兜底与回滚", "weight": 15},
        {"key": "objective_quality", "name": "可计算方案质量", "weight": 15},
    ]
    return {
        "slug": f"planning.delivery-plan-{index:03d}",
        "version": "3.0.0",
        "category": "planning",
        "title": f"资源约束发布组合规划 {index:02d}",
        "description": "在依赖、资源、预算、发布窗口和人工兜底约束下生成可验证计划。",
        "instruction": (
            "读取 `scenario.json`，把可行计划写入 `deliverables/plan.json`。必须覆盖全部任务；"
            "每项只能包含 id、mode、start。另提供 rollback、contingencies 与 tradeoffs。"
            "满足依赖、逐周资源容量、预算、期限和 rollout_window；禁止修改场景文件。"
        ),
        "tools": ["filesystem", "search", "shell"],
        "limits": {
            "max_steps": 55,
            "time_target_seconds": 1500,
            "token_budget": 38000,
        },
        "validators": [
            _validator("file_exists", 3, path="deliverables/plan.json"),
            _validator(
                "constraint_plan",
                79,
                path="deliverables/plan.json",
                scenario_path="scenario.json",
                critical=True,
                critical_min_score=70,
            ),
            _validator(
                "ai_rubric",
                15,
                criteria=[
                    "tradeoffs 明确解释了成本、工期和资源冲突之间的取舍",
                    "contingencies 与 rollback 针对该场景且可实际执行",
                    "计划避免空泛措辞，并能让执行者据此做出是否继续的决定",
                ],
            ),
            _validator("forbidden_paths", 3, paths=["scenario.json.modified", ".git", "tests"]),
        ],
        "tags": ["planning", "resource-constraints", "critical-path", "rollback", "v3"],
        "initial_files": {"scenario.json": scenario_text},
        "metadata": {
            "demo_actions": [
                {
                    "tool": "write_file",
                    "arguments": {
                        "path": "deliverables/plan.json",
                        "content": json.dumps(reference, ensure_ascii=False, indent=2) + "\n",
                    },
                }
            ],
            "demo_response": "资源约束计划已生成，并完成预算、依赖和发布窗口自检。",
            "difficulty": 5,
            "estimated_minutes": 35,
            "capability": "constraint-planning-and-judgment",
            "quality_revision": "v3-p1",
        },
    }


def _workflow_case(index: int) -> dict[str, Any]:
    minimum_priority = 3 if index % 2 else 4
    initial_events: list[dict[str, Any]] = []
    for item in range(1, 21):
        ticket_id = f"TKT-{index:02d}-{item:03d}"
        create_id = f"evt-{index:02d}-{item:03d}-create"
        priority = 1 + ((item * 3 + index) % 4)
        hours = 1 + ((item * 5 + index) % 12)
        initial_events.append(
            {
                "event_id": create_id,
                "ticket_id": ticket_id,
                "seq": 1,
                "type": "create",
                "payload": {
                    "priority": priority,
                    "hours": hours,
                    "owner": f"team-{(item + index) % 5 + 1}",
                },
            }
        )
        if item % 3 != 0:
            initial_events.append(
                {
                    "event_id": f"evt-{index:02d}-{item:03d}-approve",
                    "ticket_id": ticket_id,
                    "seq": 2,
                    "type": "approve",
                    "payload": {},
                }
            )
        if item % 7 == 0:
            initial_events.append(dict(initial_events[-1]))
    events_text = "\n".join(
        json.dumps(event, ensure_ascii=False, sort_keys=True) for event in initial_events
    ) + "\n"
    solution = textwrap.dedent(
        r'''
        from __future__ import annotations

        import copy
        import hashlib
        import json
        import os
        import tempfile
        from pathlib import Path


        class SourceChanged(ValueError):
            pass


        def _canonical(value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


        def _atomic_json(path, value):
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".workflow-", suffix=".tmp", dir=target.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass


        def _empty_state():
            return {"version": 1, "tickets": {}, "processed": {}, "sources": {}}


        def _validate_create(payload):
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            priority = payload.get("priority")
            hours = payload.get("hours")
            owner = payload.get("owner")
            if type(priority) is not int or not 1 <= priority <= 4:
                raise ValueError("invalid priority")
            if type(hours) is not int or hours <= 0:
                raise ValueError("invalid hours")
            if not isinstance(owner, str) or not owner.strip():
                raise ValueError("invalid owner")
            return {"priority": priority, "hours": hours, "owner": owner.strip()}


        def process_events(source_path, state_path, output_path, minimum_priority=3):
            if type(minimum_priority) is not int or not 1 <= minimum_priority <= 4:
                raise ValueError("invalid minimum priority")
            source = Path(source_path)
            raw = source.read_bytes()
            source_hash = hashlib.sha256(raw).hexdigest()
            events = []
            for line_number, raw_line in enumerate(raw.decode("utf-8-sig").splitlines(), start=1):
                if not raw_line.strip():
                    continue
                value = json.loads(raw_line)
                if not isinstance(value, dict):
                    raise ValueError(f"line {line_number} is not an object")
                events.append((line_number, value))
            state_target = Path(state_path)
            state = (
                json.loads(state_target.read_text(encoding="utf-8-sig"))
                if state_target.exists()
                else _empty_state()
            )
            if not isinstance(state, dict) or state.get("version") != 1:
                raise ValueError("unsupported state")
            source_key = source.name
            previous_hash = state.get("sources", {}).get(source_key)
            if previous_hash is not None and previous_hash != source_hash:
                raise SourceChanged("a processed source name cannot change content")
            next_state = copy.deepcopy(state)
            next_state.setdefault("tickets", {})
            next_state.setdefault("processed", {})
            next_state.setdefault("sources", {})
            errors = []
            accepted = 0
            duplicates = 0
            for line_number, event in events:
                try:
                    required = {"event_id", "ticket_id", "seq", "type", "payload"}
                    if set(event) != required:
                        raise ValueError("event fields must match the contract")
                    event_id = event["event_id"]
                    ticket_id = event["ticket_id"]
                    if not isinstance(event_id, str) or not event_id:
                        raise ValueError("invalid event id")
                    if not isinstance(ticket_id, str) or not ticket_id:
                        raise ValueError("invalid ticket id")
                    fingerprint = hashlib.sha256(_canonical(event).encode()).hexdigest()
                    previous = next_state["processed"].get(event_id)
                    if previous is not None:
                        if previous != fingerprint:
                            raise ValueError("event-id-conflict")
                        duplicates += 1
                        continue
                    current = copy.deepcopy(next_state["tickets"].get(ticket_id))
                    expected_seq = 1 if current is None else int(current["seq"]) + 1
                    if type(event["seq"]) is not int or event["seq"] != expected_seq:
                        raise ValueError(f"sequence-gap-expected-{expected_seq}")
                    kind = event["type"]
                    payload = event["payload"]
                    if current is None:
                        if kind != "create":
                            raise ValueError("first-event-must-create")
                        created = _validate_create(payload)
                        current = {
                            "ticket_id": ticket_id,
                            "seq": 1,
                            "active": True,
                            "approved": False,
                            **created,
                        }
                    else:
                        if not isinstance(payload, dict):
                            raise ValueError("payload must be an object")
                        if kind == "approve" and current["active"]:
                            current["approved"] = True
                        elif kind == "assign" and current["active"]:
                            owner = payload.get("owner")
                            if not isinstance(owner, str) or not owner.strip():
                                raise ValueError("invalid owner")
                            current["owner"] = owner.strip()
                        elif kind == "reprioritize" and current["active"]:
                            priority = payload.get("priority")
                            if type(priority) is not int or not 1 <= priority <= 4:
                                raise ValueError("invalid priority")
                            current["priority"] = priority
                        elif kind == "cancel" and current["active"]:
                            current["active"] = False
                        else:
                            raise ValueError("invalid transition")
                        current["seq"] = event["seq"]
                    next_state["tickets"][ticket_id] = current
                    next_state["processed"][event_id] = fingerprint
                    accepted += 1
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append(
                        {
                            "line": line_number,
                            "event_id": event.get("event_id"),
                            "reason": str(exc),
                        }
                    )
            next_state["sources"][source_key] = source_hash
            eligible = [
                {
                    "ticket_id": ticket["ticket_id"],
                    "priority": ticket["priority"],
                    "hours": ticket["hours"],
                    "owner": ticket["owner"],
                }
                for ticket in next_state["tickets"].values()
                if ticket["active"]
                and ticket["approved"]
                and ticket["priority"] >= minimum_priority
            ]
            eligible.sort(key=lambda item: (-item["priority"], item["hours"], item["ticket_id"]))
            report = {
                "source": source_key,
                "source_sha256": source_hash,
                "minimum_priority": minimum_priority,
                "eligible": eligible,
                "errors": errors,
                "accepted_events": accepted,
                "duplicate_events": duplicates,
                "state_sha256": hashlib.sha256(_canonical(next_state).encode()).hexdigest(),
            }
            _atomic_json(output_path, report)
            _atomic_json(state_path, next_state)
            return copy.deepcopy(report)
        '''
    ).strip() + "\n"
    initial = textwrap.dedent(
        '''
        from __future__ import annotations


        class SourceChanged(ValueError):
            pass


        def process_events(source_path, state_path, output_path, minimum_priority=3):
            raise NotImplementedError
        '''
    ).strip() + "\n"
    public_smoke = textwrap.dedent(
        f'''
        import json
        import tempfile
        from pathlib import Path

        from workflow import process_events

        root = Path(tempfile.mkdtemp())
        source = root / "smoke.jsonl"
        events = [
            {{"event_id":"create-1","ticket_id":"T-1","seq":1,"type":"create","payload":{{"priority":4,"hours":2,"owner":"team-a"}}}},
            {{"event_id":"approve-1","ticket_id":"T-1","seq":2,"type":"approve","payload":{{}}}},
        ]
        source.write_text("\\n".join(json.dumps(item) for item in events) + "\\n", encoding="utf-8")
        report = process_events(source, root / "state.json", root / "report.json", {minimum_priority})
        assert [item["ticket_id"] for item in report["eligible"]] == ["T-1"]
        replay = process_events(source, root / "state.json", root / "report.json", {minimum_priority})
        assert replay["accepted_events"] == 0 and replay["duplicate_events"] == 2
        print("PUBLIC_WORKFLOW_SMOKE_OK")
        '''
    ).strip() + "\n"
    private_validator = textwrap.dedent(
        r'''
        import copy
        import hashlib
        import json
        import pathlib
        import sys
        import tempfile

        workspace = pathlib.Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(workspace))
        metrics = {
            "state_transitions": 0,
            "idempotency": 0,
            "partial_failure": 0,
            "incremental_guard": 0,
            "ordering": 0,
            "atomic_outputs": 0,
        }
        evidence = {}
        try:
            from workflow import SourceChanged, process_events
        except Exception as exc:
            evidence["import"] = repr(exc)
        else:
            minimum = __MINIMUM__

            def root_for(label):
                return pathlib.Path(tempfile.mkdtemp(prefix=label + "-", dir=workspace))

            def write_events(root, name, events):
                path = root / name
                path.write_text("\n".join(json.dumps(item, sort_keys=True) for item in events) + "\n", encoding="utf-8")
                return path

            def event(eid, ticket, seq, kind, payload=None):
                return {"event_id": eid, "ticket_id": ticket, "seq": seq, "type": kind, "payload": payload or {}}

            try:
                root = root_for("transitions")
                events = [
                    event("a1", "A", 1, "create", {"priority": 4, "hours": 5, "owner": "red"}),
                    event("a2", "A", 2, "approve"),
                    event("a3", "A", 3, "assign", {"owner": "blue"}),
                    event("b1", "B", 1, "create", {"priority": minimum, "hours": 2, "owner": "green"}),
                    event("b2", "B", 2, "approve"),
                    event("c1", "C", 1, "create", {"priority": 4, "hours": 1, "owner": "black"}),
                    event("c2", "C", 2, "approve"),
                    event("c3", "C", 3, "cancel"),
                ]
                source = write_events(root, "batch-1.jsonl", events)
                report = process_events(source, root / "state.json", root / "report.json", minimum)
                expected = (
                    [("A", "blue"), ("B", "green")]
                    if minimum < 4
                    else [("B", "green"), ("A", "blue")]
                )
                assert [(item["ticket_id"], item["owner"]) for item in report["eligible"]] == expected
                metrics["state_transitions"] = 100
            except Exception as exc:
                evidence["state_transitions"] = repr(exc)

            try:
                before_state = (root / "state.json").read_bytes()
                replay = process_events(source, root / "state.json", root / "report.json", minimum)
                assert replay["accepted_events"] == 0 and replay["duplicate_events"] == len(events)
                assert (root / "state.json").read_bytes() == before_state
                metrics["idempotency"] = 100
            except Exception as exc:
                evidence["idempotency"] = repr(exc)

            try:
                root = root_for("partial")
                events = [
                    event("x1", "X", 1, "create", {"priority": 4, "hours": 3, "owner": "one"}),
                    event("x-gap", "X", 3, "approve"),
                    event("x2", "X", 2, "approve"),
                    event("x2", "X", 3, "assign", {"owner": "conflict"}),
                    event("y1", "Y", 1, "approve"),
                ]
                report = process_events(write_events(root, "partial.jsonl", events), root / "state.json", root / "report.json", minimum)
                assert [item["ticket_id"] for item in report["eligible"]] == ["X"]
                reasons = [item["reason"] for item in report["errors"]]
                assert any("sequence-gap" in item for item in reasons)
                assert any("event-id-conflict" in item for item in reasons)
                assert any("first-event-must-create" in item for item in reasons)
                metrics["partial_failure"] = 100
            except Exception as exc:
                evidence["partial_failure"] = repr(exc)

            try:
                root = root_for("incremental")
                first = [
                    event("i1", "I", 1, "create", {"priority": 2, "hours": 7, "owner": "old"}),
                    event("i2", "I", 2, "approve"),
                ]
                source = write_events(root, "batch-a.jsonl", first)
                process_events(source, root / "state.json", root / "report.json", minimum)
                source.write_text(source.read_text() + json.dumps(event("i3", "I", 3, "reprioritize", {"priority": 4})) + "\n")
                state_before = (root / "state.json").read_bytes()
                try:
                    process_events(source, root / "state.json", root / "report.json", minimum)
                except SourceChanged:
                    pass
                else:
                    raise AssertionError("changed processed source accepted")
                assert (root / "state.json").read_bytes() == state_before
                second = [event("i3", "I", 3, "reprioritize", {"priority": 4})]
                report = process_events(write_events(root, "batch-b.jsonl", second), root / "state.json", root / "report.json", minimum)
                assert [item["ticket_id"] for item in report["eligible"]] == ["I"]
                metrics["incremental_guard"] = 100
            except Exception as exc:
                evidence["incremental_guard"] = repr(exc)

            try:
                root = root_for("ordering")
                events = []
                for ticket, priority, hours in [("Z", 4, 8), ("A", 4, 8), ("M", 4, 2), ("B", minimum, 1)]:
                    events.extend([
                        event(ticket + "1", ticket, 1, "create", {"priority": priority, "hours": hours, "owner": "owner"}),
                        event(ticket + "2", ticket, 2, "approve"),
                    ])
                report = process_events(write_events(root, "sort.jsonl", events), root / "state.json", root / "report.json", minimum)
                expected = ["M", "A", "Z", "B"] if minimum < 4 else ["B", "M", "A", "Z"]
                assert [item["ticket_id"] for item in report["eligible"]] == expected
                assert report["source_sha256"] == hashlib.sha256((root / "sort.jsonl").read_bytes()).hexdigest()
                metrics["ordering"] = 100
            except Exception as exc:
                evidence["ordering"] = repr(exc)

            try:
                state_before = (root / "state.json").read_bytes()
                report_before = (root / "report.json").read_bytes()
                broken = root / "broken.jsonl"
                broken.write_text('{"event_id":', encoding="utf-8")
                try:
                    process_events(broken, root / "state.json", root / "report.json", minimum)
                except (ValueError, json.JSONDecodeError):
                    pass
                else:
                    raise AssertionError("broken JSON accepted")
                assert (root / "state.json").read_bytes() == state_before
                assert (root / "report.json").read_bytes() == report_before
                assert not list(root.glob(".workflow-*.tmp"))
                metrics["atomic_outputs"] = 100
            except Exception as exc:
                evidence["atomic_outputs"] = repr(exc)

        print("AGENTBENCH_METRICS=" + json.dumps({"metrics": metrics, "evidence": evidence}, sort_keys=True))
        '''
    ).replace("__MINIMUM__", str(minimum_priority)).strip()
    metrics = [
        {"key": "state_transitions", "name": "跨事件状态转换", "weight": 20},
        {"key": "idempotency", "name": "幂等重跑", "weight": 15},
        {"key": "partial_failure", "name": "部分失败隔离", "weight": 20},
        {"key": "incremental_guard", "name": "增量输入与来源哈希", "weight": 20},
        {"key": "ordering", "name": "业务筛选与稳定排序", "weight": 15},
        {"key": "atomic_outputs", "name": "输出原子性", "weight": 10},
    ]
    return {
        "slug": f"workflow.ticket-triage-{index:03d}",
        "version": "3.0.0",
        "category": "agentic-workflow",
        "title": f"增量工单事件编排 {index:02d}",
        "description": "实现可重跑、可增量、可隔离坏事件且保护来源哈希的状态化工作流。",
        "instruction": (
            "按照 `WORKFLOW_CONTRACT.md` 完成 `workflow.py`，运行 `python public_smoke.py`。"
            "随后用 events.jsonl 生成 state.json 与 deliverables/triage.json；"
            f"最低优先级为 {minimum_priority}。不要修改输入、公开脚本或创建 tests/。"
        ),
        "tools": ["filesystem", "search", "shell"],
        "limits": {
            "max_steps": 80,
            "time_target_seconds": 2100,
            "token_budget": 48000,
            "network": "disabled",
            "docker_image": "python:3.12-alpine",
            "validator_timeout_seconds": 240,
        },
        "validators": [
            _validator("file_exists", 3, path="workflow.py"),
            _validator(
                "command_metrics",
                94,
                command="python {private_root}/validate_workflow.py",
                private_files={"validate_workflow.py": private_validator},
                metrics=metrics,
                critical=True,
                critical_min_score=65,
            ),
            _validator("forbidden_paths", 3, paths=["tests", ".git", ".agentbench-private-*"]),
        ],
        "tags": ["workflow", "event-log", "idempotency", "incremental", "partial-failure", "v3"],
        "initial_files": {
            "workflow.py": initial,
            "events.jsonl": events_text,
            "public_smoke.py": public_smoke,
            "WORKFLOW_CONTRACT.md": (
                "Implement process_events(source_path, state_path, output_path, minimum_priority). "
                "Events have exactly event_id, ticket_id, seq, type and payload. Sequence starts at "
                "one per ticket. Support create, approve, assign, reprioritize and cancel. Identical "
                "event IDs are no-ops; changed payloads and invalid transitions become report errors "
                "without blocking later valid events. A processed source filename is immutable by "
                "SHA-256, while a new filename may add incremental events. Persist canonical state "
                "and a report containing provenance, counters, errors and eligible tickets sorted by "
                "priority descending, hours ascending and ticket_id ascending. Writes must be atomic.\n"
            ),
        },
        "metadata": {
            "demo_actions": [
                {"tool": "write_file", "arguments": {"path": "workflow.py", "content": solution}}
            ],
            "demo_response": "增量工单工作流已实现并通过公开验证。",
            "difficulty": 4 if index <= 11 else 5,
            "estimated_minutes": 45,
            "capability": "resumable-agentic-workflow",
            "quality_revision": "v3-p1",
        },
    }


def _orders_dataset(index: int, *, hidden: bool) -> str:
    rows = [
        "order_id,version,region,gross,discount,refunded,customer,occurred_at"
    ]
    count = 95 if hidden else 145
    prefix = "H" if hidden else "O"
    regions = ["north", "south", "east", "west"]
    for item in range(1, count + 1):
        order_id = f"{prefix}-{index:02d}-{item:04d}"
        region = regions[(item * 3 + index) % len(regions)]
        gross = Decimal(80 + ((item * 47 + index * 29) % 1300)) + Decimal(
            f"0.{(item * 17 + index) % 100:02d}"
        )
        discount = Decimal((item + index) % 8 * 7) + Decimal(
            f"0.{(item * 11) % 100:02d}"
        )
        refunded = item % (9 + index % 4) == 0
        customer = f"C-{(item * 13 + index) % 41:03d}"
        day = item % 27 + 1
        rows.append(
            f"{order_id},1,{region},{gross},{discount},{str(refunded).lower()},"
            f"{customer},2026-05-{day:02d}T12:00:00Z"
        )
        if item % 12 == 0:
            rows.append(
                f"{order_id},2,{region},{gross + Decimal('10.125')},{discount},"
                f"{str(refunded).lower()},{customer},2026-06-{day:02d}T12:00:00Z"
            )
        if item % 19 == 0:
            rows.append(rows[-1])
    conflict_id = f"{prefix}-{index:02d}-CONFLICT"
    rows.extend(
        [
            f"{conflict_id},2,north,100.00,1.00,false,C-X,2026-06-01T00:00:00Z",
            f"{conflict_id},2,north,101.00,1.00,false,C-X,2026-06-01T00:00:00Z",
            f"{prefix}-{index:02d}-NAN,1,south,NaN,0,false,C-X,2026-06-01T00:00:00Z",
            f"{prefix}-{index:02d}-REGION,1,moon,90,0,false,C-X,2026-06-01T00:00:00Z",
            f"{prefix}-{index:02d}-FUTURE,1,east,90,0,false,C-X,2027-01-01T00:00:00Z",
            f"{prefix}-{index:02d}-DISCOUNT,1,west,50,60,false,C-X,2026-06-01T00:00:00Z",
        ]
    )
    return "\n".join(rows) + "\n"


def _data_oracle(text: str, policy: dict[str, Any]) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(text))
    required = [
        "order_id",
        "version",
        "region",
        "gross",
        "discount",
        "refunded",
        "customer",
        "occurred_at",
    ]
    if reader.fieldnames != required:
        raise ValueError("invalid headers")
    scale = int(policy["currency_scale"])
    quantum = Decimal(1).scaleb(-scale)
    cutoff = datetime.fromisoformat(str(policy["as_of"]).replace("Z", "+00:00"))
    allowed_regions = [str(item) for item in policy["allowed_regions"]]
    groups: dict[str, list[dict[str, Any]]] = {}
    rejected = 0
    input_rows = 0
    for row in reader:
        input_rows += 1
        try:
            order_id = str(row["order_id"]).strip()
            version = int(row["version"])
            region = str(row["region"]).strip()
            gross = Decimal(str(row["gross"])).quantize(quantum, rounding=ROUND_HALF_UP)
            discount = Decimal(str(row["discount"])).quantize(
                quantum, rounding=ROUND_HALF_UP
            )
            refunded_text = str(row["refunded"]).strip().lower()
            customer = str(row["customer"]).strip()
            occurred_at = datetime.fromisoformat(
                str(row["occurred_at"]).replace("Z", "+00:00")
            )
            if (
                not order_id
                or version <= 0
                or region not in allowed_regions
                or not gross.is_finite()
                or not discount.is_finite()
                or gross <= 0
                or discount < 0
                or discount > gross
                or refunded_text not in {"true", "false"}
                or not customer
                or occurred_at > cutoff
            ):
                raise ValueError("invalid row")
            record = {
                "order_id": order_id,
                "version": version,
                "region": region,
                "gross": gross,
                "discount": discount,
                "refunded": refunded_text == "true",
                "customer": customer,
                "occurred_at": occurred_at.isoformat(),
            }
            groups.setdefault(order_id, []).append(record)
        except (InvalidOperation, TypeError, ValueError):
            rejected += 1
    accepted: list[dict[str, Any]] = []
    superseded = 0
    for records in groups.values():
        maximum = max(int(record["version"]) for record in records)
        latest = [record for record in records if int(record["version"]) == maximum]
        canonical = {
            json.dumps(
                {
                    **record,
                    "gross": format(record["gross"], "f"),
                    "discount": format(record["discount"], "f"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            for record in latest
        }
        if len(canonical) != 1:
            rejected += len(records)
            continue
        accepted.append(latest[0])
        superseded += len(records) - 1
    region_net = {region: Decimal(0).quantize(quantum) for region in allowed_regions}
    customer_net: dict[str, Decimal] = {}
    values: list[Decimal] = []
    refunds = 0
    high_value = 0
    threshold = Decimal(str(policy["high_value_threshold"])).quantize(quantum)
    gross_nonrefunded = Decimal(0).quantize(quantum)
    discount_nonrefunded = Decimal(0).quantize(quantum)
    refunded_gross = Decimal(0).quantize(quantum)
    for record in accepted:
        if record["refunded"]:
            net = Decimal(0).quantize(quantum)
            refunds += 1
            refunded_gross += record["gross"]
        else:
            net = record["gross"] - record["discount"]
            gross_nonrefunded += record["gross"]
            discount_nonrefunded += record["discount"]
        values.append(net)
        region_net[str(record["region"])] += net
        customer = str(record["customer"])
        customer_net[customer] = customer_net.get(customer, Decimal(0)) + net
        high_value += int(net >= threshold)
    total_net = sum(values, Decimal(0)).quantize(quantum)
    top_region = sorted(region_net, key=lambda name: (-region_net[name], name))[0]
    concentration = (
        (max(customer_net.values(), default=Decimal(0)) / total_net * Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if total_net
        else Decimal(0).quantize(Decimal("0.01"))
    )
    samples = int(policy["bootstrap_samples"])
    rng = random.Random(int(policy["bootstrap_seed"]))
    bootstraps = []
    for _ in range(samples):
        bootstraps.append(
            sum((values[rng.randrange(len(values))] for _ in values), Decimal(0)).quantize(
                quantum
            )
            if values
            else Decimal(0).quantize(quantum)
        )
    bootstraps.sort()
    lower_index = math.floor(0.025 * (samples - 1))
    upper_index = math.ceil(0.975 * (samples - 1))
    return {
        "row_counts": {
            "input": input_rows,
            "accepted_orders": len(accepted),
            "rejected_rows": rejected,
            "superseded_rows": superseded,
        },
        "total_net": format(total_net, "f"),
        "region_net": {name: format(value.quantize(quantum), "f") for name, value in region_net.items()},
        "top_region": top_region,
        "refunds": refunds,
        "high_value_orders": high_value,
        "customer_concentration_pct": format(concentration, "f"),
        "bootstrap_ci_95": [
            format(bootstraps[lower_index], "f"),
            format(bootstraps[upper_index], "f"),
        ],
        "reconciliation": {
            "gross_nonrefunded": format(gross_nonrefunded.quantize(quantum), "f"),
            "discount_nonrefunded": format(discount_nonrefunded.quantize(quantum), "f"),
            "refunded_gross": format(refunded_gross.quantize(quantum), "f"),
            "net": format(total_net, "f"),
        },
        "provenance": {
            "bootstrap_seed": int(policy["bootstrap_seed"]),
            "bootstrap_samples": samples,
            "method": "order-level-percentile-bootstrap-v1",
        },
    }


def _data_case(index: int) -> dict[str, Any]:
    policy = {
        "currency_scale": 2,
        "rounding": "ROUND_HALF_UP",
        "as_of": "2026-06-30T23:59:59Z",
        "allowed_regions": ["north", "south", "east", "west"],
        "high_value_threshold": format(Decimal(650 + index * 5), ".2f"),
        "bootstrap_seed": 9300 + index,
        "bootstrap_samples": 401,
    }
    policy_text = json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    initial_csv = _orders_dataset(index, hidden=False)
    hidden_csv = _orders_dataset(index + 31, hidden=True)
    expected = _data_oracle(hidden_csv, policy)
    solution = textwrap.dedent(
        r'''
        from __future__ import annotations

        import csv
        import hashlib
        import io
        import json
        import math
        import random
        from datetime import datetime
        from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
        from pathlib import Path


        def _load_policy(path):
            raw = Path(path).read_bytes()
            policy = json.loads(raw.decode("utf-8-sig"))
            required = {
                "currency_scale", "rounding", "as_of", "allowed_regions",
                "high_value_threshold", "bootstrap_seed", "bootstrap_samples",
            }
            if set(policy) != required or policy["rounding"] != "ROUND_HALF_UP":
                raise ValueError("invalid policy")
            if type(policy["currency_scale"]) is not int or not 0 <= policy["currency_scale"] <= 6:
                raise ValueError("invalid currency scale")
            if type(policy["bootstrap_samples"]) is not int or policy["bootstrap_samples"] < 101:
                raise ValueError("invalid bootstrap sample count")
            return raw, policy


        def analyze_orders(csv_path, policy_path):
            source_raw = Path(csv_path).read_bytes()
            policy_raw, policy = _load_policy(policy_path)
            reader = csv.DictReader(io.StringIO(source_raw.decode("utf-8-sig")))
            required_headers = [
                "order_id", "version", "region", "gross", "discount", "refunded",
                "customer", "occurred_at",
            ]
            if reader.fieldnames != required_headers:
                raise ValueError("invalid headers")
            scale = policy["currency_scale"]
            quantum = Decimal(1).scaleb(-scale)
            cutoff = datetime.fromisoformat(str(policy["as_of"]).replace("Z", "+00:00"))
            allowed_regions = [str(item) for item in policy["allowed_regions"]]
            groups = {}
            rejected = 0
            input_rows = 0
            for row in reader:
                input_rows += 1
                try:
                    order_id = str(row["order_id"]).strip()
                    version = int(row["version"])
                    region = str(row["region"]).strip()
                    gross = Decimal(str(row["gross"])).quantize(quantum, rounding=ROUND_HALF_UP)
                    discount = Decimal(str(row["discount"])).quantize(quantum, rounding=ROUND_HALF_UP)
                    refunded_text = str(row["refunded"]).strip().lower()
                    customer = str(row["customer"]).strip()
                    occurred_at = datetime.fromisoformat(str(row["occurred_at"]).replace("Z", "+00:00"))
                    if (
                        not order_id or version <= 0 or region not in allowed_regions
                        or not gross.is_finite() or not discount.is_finite() or gross <= 0
                        or discount < 0 or discount > gross
                        or refunded_text not in {"true", "false"} or not customer
                        or occurred_at > cutoff
                    ):
                        raise ValueError("invalid row")
                    record = {
                        "order_id": order_id, "version": version, "region": region,
                        "gross": gross, "discount": discount,
                        "refunded": refunded_text == "true", "customer": customer,
                        "occurred_at": occurred_at.isoformat(),
                    }
                    groups.setdefault(order_id, []).append(record)
                except (InvalidOperation, TypeError, ValueError):
                    rejected += 1
            accepted = []
            superseded = 0
            for records in groups.values():
                maximum = max(record["version"] for record in records)
                latest = [record for record in records if record["version"] == maximum]
                canonical = {
                    json.dumps(
                        {**record, "gross": format(record["gross"], "f"), "discount": format(record["discount"], "f")},
                        sort_keys=True, separators=(",", ":"),
                    )
                    for record in latest
                }
                if len(canonical) != 1:
                    rejected += len(records)
                    continue
                accepted.append(latest[0])
                superseded += len(records) - 1
            region_net = {region: Decimal(0).quantize(quantum) for region in allowed_regions}
            customer_net = {}
            values = []
            refunds = 0
            high_value = 0
            threshold = Decimal(str(policy["high_value_threshold"])).quantize(quantum)
            gross_nonrefunded = Decimal(0).quantize(quantum)
            discount_nonrefunded = Decimal(0).quantize(quantum)
            refunded_gross = Decimal(0).quantize(quantum)
            for record in accepted:
                if record["refunded"]:
                    net = Decimal(0).quantize(quantum)
                    refunds += 1
                    refunded_gross += record["gross"]
                else:
                    net = record["gross"] - record["discount"]
                    gross_nonrefunded += record["gross"]
                    discount_nonrefunded += record["discount"]
                values.append(net)
                region_net[record["region"]] += net
                customer_net[record["customer"]] = customer_net.get(record["customer"], Decimal(0)) + net
                high_value += int(net >= threshold)
            total_net = sum(values, Decimal(0)).quantize(quantum)
            top_region = sorted(region_net, key=lambda name: (-region_net[name], name))[0]
            concentration = (
                (max(customer_net.values(), default=Decimal(0)) / total_net * Decimal(100)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if total_net else Decimal(0).quantize(Decimal("0.01"))
            )
            samples = policy["bootstrap_samples"]
            rng = random.Random(policy["bootstrap_seed"])
            bootstraps = []
            for _ in range(samples):
                value = (
                    sum((values[rng.randrange(len(values))] for _ in values), Decimal(0)).quantize(quantum)
                    if values else Decimal(0).quantize(quantum)
                )
                bootstraps.append(value)
            bootstraps.sort()
            lower_index = math.floor(0.025 * (samples - 1))
            upper_index = math.ceil(0.975 * (samples - 1))
            return {
                "row_counts": {
                    "input": input_rows, "accepted_orders": len(accepted),
                    "rejected_rows": rejected, "superseded_rows": superseded,
                },
                "total_net": format(total_net, "f"),
                "region_net": {name: format(value.quantize(quantum), "f") for name, value in region_net.items()},
                "top_region": top_region,
                "refunds": refunds,
                "high_value_orders": high_value,
                "customer_concentration_pct": format(concentration, "f"),
                "bootstrap_ci_95": [format(bootstraps[lower_index], "f"), format(bootstraps[upper_index], "f")],
                "reconciliation": {
                    "gross_nonrefunded": format(gross_nonrefunded.quantize(quantum), "f"),
                    "discount_nonrefunded": format(discount_nonrefunded.quantize(quantum), "f"),
                    "refunded_gross": format(refunded_gross.quantize(quantum), "f"),
                    "net": format(total_net, "f"),
                },
                "provenance": {
                    "input_sha256": hashlib.sha256(source_raw).hexdigest(),
                    "policy_sha256": hashlib.sha256(policy_raw).hexdigest(),
                    "bootstrap_seed": policy["bootstrap_seed"],
                    "bootstrap_samples": samples,
                    "method": "order-level-percentile-bootstrap-v1",
                },
            }
        '''
    ).strip() + "\n"
    initial = textwrap.dedent(
        '''
        from __future__ import annotations


        def analyze_orders(csv_path, policy_path):
            raise NotImplementedError
        '''
    ).strip() + "\n"
    public_smoke = textwrap.dedent(
        '''
        import json
        import tempfile
        from pathlib import Path

        from analytics import analyze_orders

        root = Path(tempfile.mkdtemp())
        source = root / "orders.csv"
        source.write_text(
            "order_id,version,region,gross,discount,refunded,customer,occurred_at\\n"
            "A,1,north,100.005,10,false,C1,2026-01-01T00:00:00Z\\n",
            encoding="utf-8",
        )
        policy = {
            "currency_scale": 2,
            "rounding": "ROUND_HALF_UP",
            "as_of": "2026-06-30T23:59:59Z",
            "allowed_regions": ["north", "south", "east", "west"],
            "high_value_threshold": "80.00",
            "bootstrap_seed": 7,
            "bootstrap_samples": 101,
        }
        policy_path = root / "policy.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        report = analyze_orders(source, policy_path)
        assert report["total_net"] == "90.01"
        assert report["high_value_orders"] == 1
        print("PUBLIC_DATA_SMOKE_OK")
        '''
    ).strip() + "\n"
    validator = textwrap.dedent(
        r'''
        import copy
        import hashlib
        import json
        import pathlib
        import sys
        import tempfile

        workspace = pathlib.Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(workspace))
        metrics = {
            "schema_provenance": 0,
            "dedup_temporal": 0,
            "decimal_reconciliation": 0,
            "regional_metrics": 0,
            "bootstrap": 0,
            "edge_reproducibility": 0,
        }
        evidence = {}
        try:
            from analytics import analyze_orders
        except Exception as exc:
            evidence["import"] = repr(exc)
        else:
            root = pathlib.Path(tempfile.mkdtemp(prefix="hidden-data-", dir=workspace))
            source = root / "hidden-orders.csv"
            policy_path = root / "hidden-policy.json"
            source.write_text(__HIDDEN_CSV__, encoding="utf-8", newline="")
            policy_path.write_text(__POLICY_TEXT__, encoding="utf-8", newline="")
            expected = json.loads(__EXPECTED_JSON__)
            try:
                report = analyze_orders(source, policy_path)
            except Exception as exc:
                evidence["execution"] = repr(exc)
                report = None
            if isinstance(report, dict):
                try:
                    required = {
                        "row_counts", "total_net", "region_net", "top_region", "refunds",
                        "high_value_orders", "customer_concentration_pct", "bootstrap_ci_95",
                        "reconciliation", "provenance",
                    }
                    assert set(report) == required
                    provenance = report["provenance"]
                    assert provenance["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
                    assert provenance["policy_sha256"] == hashlib.sha256(policy_path.read_bytes()).hexdigest()
                    assert {key: provenance[key] for key in ("bootstrap_seed", "bootstrap_samples", "method")} == expected["provenance"]
                    metrics["schema_provenance"] = 100
                except Exception as exc:
                    evidence["schema_provenance"] = repr(exc)
                try:
                    assert report["row_counts"] == expected["row_counts"]
                    assert (
                        report["row_counts"]["accepted_orders"]
                        + report["row_counts"]["rejected_rows"]
                        + report["row_counts"]["superseded_rows"]
                        == report["row_counts"]["input"]
                    )
                    metrics["dedup_temporal"] = 100
                except Exception as exc:
                    evidence["dedup_temporal"] = repr(exc)
                try:
                    assert report["total_net"] == expected["total_net"]
                    assert report["reconciliation"] == expected["reconciliation"]
                    gross = float(report["reconciliation"]["gross_nonrefunded"])
                    discounts = float(report["reconciliation"]["discount_nonrefunded"])
                    assert round(gross - discounts, 2) == float(report["total_net"])
                    metrics["decimal_reconciliation"] = 100
                except Exception as exc:
                    evidence["decimal_reconciliation"] = repr(exc)
                try:
                    for key in ("region_net", "top_region", "refunds", "high_value_orders", "customer_concentration_pct"):
                        assert report[key] == expected[key], key
                    metrics["regional_metrics"] = 100
                except Exception as exc:
                    evidence["regional_metrics"] = repr(exc)
                try:
                    assert report["bootstrap_ci_95"] == expected["bootstrap_ci_95"]
                    assert float(report["bootstrap_ci_95"][0]) <= float(report["total_net"]) <= float(report["bootstrap_ci_95"][1])
                    metrics["bootstrap"] = 100
                except Exception as exc:
                    evidence["bootstrap"] = repr(exc)
                try:
                    again = analyze_orders(source, policy_path)
                    assert again == report
                    changed_policy = json.loads(policy_path.read_text())
                    changed_policy["high_value_threshold"] = "999999.00"
                    alternate = root / "alternate-policy.json"
                    alternate.write_text(json.dumps(changed_policy), encoding="utf-8")
                    changed = analyze_orders(source, alternate)
                    assert changed["high_value_orders"] == 0
                    assert changed["total_net"] == report["total_net"]
                    assert report == again
                    metrics["edge_reproducibility"] = 100
                except Exception as exc:
                    evidence["edge_reproducibility"] = repr(exc)
        print("AGENTBENCH_METRICS=" + json.dumps({"metrics": metrics, "evidence": evidence}, sort_keys=True))
        '''
    )
    validator = (
        validator.replace("__HIDDEN_CSV__", repr(hidden_csv))
        .replace("__POLICY_TEXT__", repr(policy_text))
        .replace("__EXPECTED_JSON__", repr(json.dumps(expected, sort_keys=True)))
        .strip()
    )
    metrics = [
        {"key": "schema_provenance", "name": "报告契约与来源证明", "weight": 15},
        {"key": "dedup_temporal", "name": "版本去重与时点规则", "weight": 20},
        {"key": "decimal_reconciliation", "name": "Decimal 对账", "weight": 20},
        {"key": "regional_metrics", "name": "区域与客户指标", "weight": 15},
        {"key": "bootstrap", "name": "确定性置信区间", "weight": 20},
        {"key": "edge_reproducibility", "name": "策略扰动与可复现性", "weight": 10},
    ]
    return {
        "slug": f"data.orders-analysis-{index:03d}",
        "version": "3.0.0",
        "category": "data-analysis",
        "title": f"订单版本对账与置信区间 {index:02d}",
        "description": "处理脏数据、版本冲突、Decimal 对账、来源证明和确定性 bootstrap。",
        "instruction": (
            "按照 `ANALYTICS_CONTRACT.md` 完成 `analytics.py` 的 analyze_orders，并运行 "
            "`python public_smoke.py`。实现必须适用于隐藏 CSV 和策略，不得硬编码当前报告、"
            "修改输入或创建 tests/。"
        ),
        "tools": ["filesystem", "search", "shell"],
        "limits": {
            "max_steps": 80,
            "time_target_seconds": 2100,
            "token_budget": 48000,
            "network": "disabled",
            "docker_image": "python:3.12-alpine",
            "validator_timeout_seconds": 240,
        },
        "validators": [
            _validator("file_exists", 3, path="analytics.py"),
            _validator(
                "command_metrics",
                94,
                command="python {private_root}/validate_analytics.py",
                private_files={"validate_analytics.py": validator},
                metrics=metrics,
                critical=True,
                critical_min_score=65,
            ),
            _validator("forbidden_paths", 3, paths=["tests", ".git", ".agentbench-private-*"]),
        ],
        "tags": ["data-analysis", "dirty-data", "decimal", "bootstrap", "provenance", "v3"],
        "initial_files": {
            "analytics.py": initial,
            "orders.csv": initial_csv,
            "analysis-policy.json": policy_text,
            "public_smoke.py": public_smoke,
            "ANALYTICS_CONTRACT.md": (
                "Read the exact CSV columns and policy fields supplied. Validate rows before grouping. "
                "Round monetary inputs with Decimal ROUND_HALF_UP. For each order choose the highest "
                "version; identical copies are superseded, while conflicting rows at the highest version "
                "reject the entire order. Reject bad regions, non-finite/invalid money and rows after "
                "as_of. Refunded orders have zero net. Return the documented counts, fixed-scale totals, "
                "regional ranking with lexicographic tie-break, refund/high-value counts, top-customer net "
                "share, reconciliation, SHA-256 provenance and a deterministic order-level percentile "
                "bootstrap interval using random.Random(seed), samples resamples, and floor/ceil 2.5%/97.5% "
                "indices. The function must be pure and reproducible.\n"
            ),
        },
        "metadata": {
            "demo_actions": [
                {"tool": "write_file", "arguments": {"path": "analytics.py", "content": solution}}
            ],
            "demo_response": "版本化订单分析器已实现并通过公开验证。",
            "difficulty": 4 if index <= 14 else 5,
            "estimated_minutes": 45,
            "capability": "reproducible-data-analysis",
            "quality_revision": "v3-p1",
        },
    }


_MATH_PROBLEMS: dict[str, dict[str, Any]] = {
    "math.integral-beta-polynomial": {
        "title": "Beta 积分递推与交叉校验",
        "instruction": (
            "令 I(a,b)=∫[0,1]x^a(1-x)^b dx。计算 I(3,4)、I(4,4) 以及比值 "
            "I(4,4)/I(3,4)。只输出 JSON：i34、i44、ratio，全部使用精确表达式。"
        ),
        "answer": {"i34": "1/280", "i44": "1/630", "ratio": "4/9"},
    },
    "math.integral-bose-einstein": {
        "title": "Bose–Einstein 积分族",
        "instruction": (
            "计算 I_k=∫[0,∞]x^k/(exp(x)-1)dx 的 I_3、I_1 与 I_3/I_1。"
            "只输出 JSON：i3、i1、ratio，使用 pi 的精确表达式。"
        ),
        "answer": {"i3": "pi^4/15", "i1": "pi^2/6", "ratio": "2*pi^2/5"},
    },
    "math.integral-log-sine": {
        "title": "对数正弦一、二阶矩",
        "instruction": (
            "计算 A=∫[0,pi/2]ln(sin(x))dx 与 B=∫[0,pi/2]ln(sin(x))^2dx。"
            "只输出 JSON：first、second，使用 pi 与 ln 的精确表达式。"
        ),
        "answer": {
            "first": "-(pi*ln(2))/2",
            "second": "pi^3/24+pi*ln(2)^2/2",
        },
    },
    "math.integral-parameter-differentiation": {
        "title": "振荡积分实部与虚部",
        "instruction": (
            "分别计算 ∫[0,∞]x^2*exp(-2x)*sin(3x)dx 和对应的 cos(3x) 积分，"
            "并给出 cos 积分与 sin 积分的比值。只输出 JSON：sin_value、cos_value、ratio。"
        ),
        "answer": {
            "sin_value": "18/2197",
            "cos_value": "-92/2197",
            "ratio": "-46/9",
        },
    },
    "math.derivative-high-order-product": {
        "title": "高阶导数与级数系数一致性",
        "instruction": (
            "令 f(x)=x^5*exp(2x)。求 f^(7)(0)、f^(8)(0) 及 Maclaurin 展开中 x^8"
            "的系数。只输出 JSON：d7、d8、coefficient_x8。"
        ),
        "answer": {"d7": "10080", "d8": "53760", "coefficient_x8": "4/3"},
    },
    "math.derivative-implicit-third": {
        "title": "隐函数一至三阶导数",
        "instruction": (
            "曲线 x^2+x*y+y^2=3 在 (1,1) 附近定义 y(x)。计算 y'(1)、y''(1)、"
            "y'''(1)。只输出 JSON：first、second、third。"
        ),
        "answer": {"first": "-1", "second": "-2/3", "third": "-2/3"},
    },
    "math.derivative-taylor-coefficient": {
        "title": "复指数 Taylor 系数与导数",
        "instruction": (
            "对 exp(x)*cos(x) 求 Maclaurin 展开中 x^7、x^8 的系数，并给出第 8 阶"
            "导数在 0 的值。只输出 JSON：c7、c8、d8。"
        ),
        "answer": {"c7": "1/630", "c8": "1/2520", "d8": "16"},
    },
    "math.derivative-directional-second": {
        "title": "多元方向导数与 Hessian 校验",
        "instruction": (
            "令 f(x,y)=exp(x*y)，v=(3/5,4/5)。求 f 在 (0,1) 沿 v 的一阶、二阶"
            "方向导数，并给出该点 Hessian 的行列式。只输出 JSON：first、second、hessian_det。"
        ),
        "answer": {"first": "3/5", "second": "33/25", "hessian_det": "-1"},
    },
    "math.ode-euler-cauchy": {
        "title": "Euler 方程完整解与特征结构",
        "instruction": (
            "在 x>0 上解 x^2*y''-3x*y'+4y=0，y(1)=1、y'(1)=0。只输出 JSON："
            "solution、value_at_e、indicial_root、multiplicity；solution 必须是 x 的表达式。"
        ),
        "answer": {
            "solution": "x^2*(1-2*ln(x))",
            "value_at_e": "-E^2",
            "indicial_root": "2",
            "multiplicity": "2",
        },
        "variables": {"solution": ["x"]},
    },
    "math.ode-logistic-exact": {
        "title": "Logistic 精确解与反求时刻",
        "instruction": (
            "解 y'=y(1-y)、y(0)=1/3。只输出 JSON：solution、value_at_ln4、"
            "time_at_three_quarters；solution 使用变量 t，最后一项是首次达到 3/4 的时刻。"
        ),
        "answer": {
            "solution": "exp(t)/(2+exp(t))",
            "value_at_ln4": "2/3",
            "time_at_three_quarters": "ln(6)",
        },
        "variables": {"solution": ["t"]},
    },
    "math.ode-linear-system-rotation": {
        "title": "线性系统矩阵指数与特殊时刻",
        "instruction": (
            "方程组 x'=3x+4y、y'=-4x+3y，初值 (1,0)。只输出 JSON：x_of_t、"
            "y_of_t、x_at_pi_over_8、y_at_pi_over_8，前两项使用变量 t。"
        ),
        "answer": {
            "x_of_t": "exp(3*t)*cos(4*t)",
            "y_of_t": "-exp(3*t)*sin(4*t)",
            "x_at_pi_over_8": "0",
            "y_at_pi_over_8": "-exp(3*pi/8)",
        },
        "variables": {"x_of_t": ["t"], "y_of_t": ["t"]},
    },
    "math.series-central-binomial": {
        "title": "中心二项式级数与收敛性",
        "instruction": (
            "令 S=Σ[n=1..∞]1/(n^2*C(2n,n))。求 S、2S，并判断其绝对/条件收敛性。"
            "只输出 JSON：sum、twice_sum、convergence。"
        ),
        "answer": {"sum": "pi^2/18", "twice_sum": "pi^2/9", "convergence": "absolute"},
        "literals": {"convergence"},
    },
    "math.series-alternating-harmonic": {
        "title": "交错调和数级数与收敛类型",
        "instruction": (
            "H_n=Σ[k=1..n]1/k。计算 Σ[n=1..∞](-1)^(n-1)H_n/n，判断绝对或条件"
            "收敛，并给出通项极限。只输出 JSON：sum、convergence、term_limit。"
        ),
        "answer": {
            "sum": "pi^2/12-ln(2)^2/2",
            "convergence": "conditional",
            "term_limit": "0",
        },
        "literals": {"convergence"},
    },
    "math.series-endpoint-interval": {
        "title": "幂级数半径与端点义务",
        "instruction": (
            "对 Σ[n=1..∞](x-2)^n/(n*3^n)，给出中心、收敛半径、左右端点是否包含"
            "以及实数收敛区间。只输出 JSON：center、radius、left、right、interval。"
        ),
        "answer": {
            "center": "2",
            "radius": "3",
            "left": "included",
            "right": "excluded",
            "interval": "[-1,5)",
        },
        "literals": {"left", "right", "interval"},
    },
    "math.series-cubic-geometric": {
        "title": "多阶加权几何级数",
        "instruction": (
            "分别计算 Σ[n=1..∞]n/2^n、n^2/2^n、n^3/2^n。只输出 JSON："
            "first_moment、second_moment、third_moment。"
        ),
        "answer": {"first_moment": "2", "second_moment": "6", "third_moment": "26"},
    },
    "math.linear-algebra-hilbert-determinant": {
        "title": "四阶 Hilbert 矩阵精确不变量",
        "instruction": (
            "H_ij=1/(i+j-1)，i,j=1..4。求 det(H)、rank(H) 与 H^{-1} 的迹。"
            "只输出 JSON：determinant、rank、inverse_trace。"
        ),
        "answer": {"determinant": "1/6048000", "rank": "4", "inverse_trace": "10496"},
    },
    "math.linear-algebra-circulant-characteristic": {
        "title": "循环矩阵完整谱结构",
        "instruction": (
            "A=[[2,1,0,1],[1,2,1,0],[0,1,2,1],[1,0,1,2]]。求 det(lambda*I-A)、"
            "按非降序排列的四个特征值及 rank(A)。只输出 JSON：characteristic、eigenvalues、rank。"
        ),
        "answer": {
            "characteristic": "lambda*(lambda-2)^2*(lambda-4)",
            "eigenvalues": ["0", "2", "2", "4"],
            "rank": "3",
        },
        "variables": {"characteristic": ["lambda"]},
    },
    "math.linear-algebra-matrix-power": {
        "title": "矩阵幂递推与行列式校验",
        "instruction": (
            "A=[[2,1],[1,1]]。计算 A^5、A^10 和 det(A^10)。只输出 JSON："
            "a5、a10、det_a10；矩阵为二维数组。"
        ),
        "answer": {
            "a5": [["89", "55"], ["55", "34"]],
            "a10": [["10946", "6765"], ["6765", "4181"]],
            "det_a10": "1",
        },
    },
    "math.linear-algebra-least-squares": {
        "title": "最小二乘解、残差与正规方程",
        "instruction": (
            "A 的四行为 (1,0),(1,1),(1,2),(1,3)，b=(1,2,2,5)^T。求最小二乘"
            "beta、残差平方和 SSE 和 A^T(A*beta-b)。只输出 JSON：beta、sse、normal_residual。"
        ),
        "answer": {
            "beta": ["7/10", "6/5"],
            "sse": "9/5",
            "normal_residual": ["0", "0"],
        },
    },
}


def _math_case(original: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    answer = spec["answer"]
    fields = _flatten_answer(
        answer,
        literals=set(spec.get("literals") or set()),
        variables=dict(spec.get("variables") or {}),
    )
    difficulty = int(original.get("metadata", {}).get("difficulty", 5))
    return {
        **original,
        "version": "3.0.0",
        "title": spec["title"],
        "description": "复合数学任务；按证明义务分项验证，并接受符号等价表达式。",
        "instruction": spec["instruction"],
        "limits": {
            "max_steps": 20,
            "time_target_seconds": 1500 if difficulty == 5 else 1000,
            "token_budget": 30000 if difficulty == 5 else 22000,
        },
        "validators": [_validator("symbolic_json", 100, fields=fields)],
        "tags": [
            "math",
            str(original.get("metadata", {}).get("capability", "reasoning")),
            "symbolic-equivalence",
            "partial-credit",
            "v3",
        ],
        "metadata": {
            **original.get("metadata", {}),
            "demo_response": json.dumps(answer, ensure_ascii=False),
            "estimated_minutes": 25 if difficulty == 5 else 18,
            "quality_revision": "v3-p1",
        },
    }


def upgrade_v3_p1_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for case in cases:
        slug = str(case.get("slug"))
        spec = _MATH_PROBLEMS.get(slug)
        if spec:
            output.append(_math_case(case, spec))
        elif slug.startswith("planning.delivery-plan-"):
            output.append(_planning_case(int(slug.rsplit("-", 1)[1])))
        elif slug.startswith("workflow.ticket-triage-") and int(slug.rsplit("-", 1)[1]) >= 9:
            output.append(_workflow_case(int(slug.rsplit("-", 1)[1])))
        elif slug.startswith("data.orders-analysis-") and int(slug.rsplit("-", 1)[1]) >= 9:
            output.append(_data_case(int(slug.rsplit("-", 1)[1])))
        else:
            output.append(case)
    return output
