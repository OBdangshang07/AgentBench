from __future__ import annotations

import json
import textwrap
from typing import Any


def _validator(kind: str, weight: float, **config: Any) -> dict[str, Any]:
    return {"type": kind, "weight": weight, "config": config}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _scheduler_instance(
    instance_id: str,
    *,
    task_count: int,
    machine_count: int,
    seed: int,
    exact_optimum: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a deterministic, planted-feasible rich scheduling instance."""
    machine_ids = [f"M{index + 1}" for index in range(machine_count)]
    families = ["A", "B", "C"]
    width = min(3, machine_count)
    planned: dict[str, dict[str, Any]] = {}
    tasks: list[dict[str, Any]] = []
    level_ends: list[int] = []
    level_start = 0
    levels = (task_count + width - 1) // width
    blackout_level = max(1, levels // 2)
    blackout_start = 0
    blackout_end = 0

    for level in range(levels):
        if level == blackout_level:
            blackout_start = level_start
            blackout_end = blackout_start + 3
            level_start = blackout_end
        current_level_ends: list[int] = []
        for lane in range(width):
            index = level * width + lane
            if index >= task_count:
                break
            task_id = f"T{index + 1:02d}"
            family = families[(index + level) % len(families)]
            duration = 3 + ((index * 5 + seed) % 3)
            start = level_start + (lane % 2)
            primary = machine_ids[lane % machine_count]
            secondary = machine_ids[(lane + 1 + level) % machine_count]
            if secondary == primary:
                secondary = machine_ids[(lane + 1) % machine_count]
            resources = {"crew": 1 + index % 2, "lab": int((index + level) % 3 == 0)}
            nonrenewable = 3 + duration + index % 4
            balanced = {
                "id": "balanced",
                "duration": duration,
                "resources": resources,
                "nonrenewable": nonrenewable,
                "machines": [primary, secondary],
            }
            fast = {
                "id": "fast",
                "duration": max(2, duration - 1),
                "resources": {"crew": resources["crew"] + 1, "lab": resources["lab"] + 1},
                "nonrenewable": nonrenewable + 5,
                "machines": [primary, secondary],
            }
            eco = {
                "id": "eco",
                "duration": duration + 2,
                "resources": {"crew": 1, "lab": max(0, resources["lab"] - 1)},
                "nonrenewable": max(1, nonrenewable - 3),
                "machines": [secondary, primary],
            }
            predecessors: list[dict[str, int | str]] = []
            if level:
                predecessor_index = (level - 1) * width + lane
                if predecessor_index < task_count:
                    predecessor = f"T{predecessor_index + 1:02d}"
                    predecessor_end = int(planned[predecessor]["end"])
                    slack = max(0, start - predecessor_end)
                    predecessors.append(
                        {"id": predecessor, "min_lag": max(0, slack - 2), "max_lag": slack + 4}
                    )
                if lane > 0 and level % 2 == 1:
                    cross_index = (level - 1) * width
                    cross = f"T{cross_index + 1:02d}"
                    if cross != predecessor:
                        cross_end = int(planned[cross]["end"])
                        slack = max(0, start - cross_end)
                        predecessors.append(
                            {"id": cross, "min_lag": max(0, slack - 3), "max_lag": slack + 5}
                        )
            task = {
                "id": task_id,
                "family": family,
                "release": max(0, start - 2),
                "deadline": start + duration + 5,
                "weight": 1 + index % 5,
                "predecessors": predecessors,
                "modes": [balanced, fast, eco],
            }
            tasks.append(task)
            planned[task_id] = {
                "start": start,
                "end": start + duration,
                "mode": "balanced",
                "machine": primary,
            }
            current_level_ends.append(start + duration)
        level_ends = current_level_ends
        level_start = max(level_ends, default=level_start) + 3

    reference_makespan = max(item["end"] for item in planned.values())
    horizon = reference_makespan + 10
    machines = []
    setup = {
        left: {right: (0 if left == right else 1 + (ord(left) + ord(right)) % 2) for right in families}
        for left in families
    }
    for machine_id in machine_ids:
        calendar = [[0, horizon]]
        if blackout_start and blackout_end:
            calendar = [[0, blackout_start], [blackout_end, horizon]]
        machines.append({"id": machine_id, "calendar": calendar, "setup": setup})

    if exact_optimum:
        anchor_id = "ZZ"
        machines.append({"id": "ANCHOR", "calendar": [[0, horizon]], "setup": {"Z": {"Z": 0}}})
        tasks.append(
            {
                "id": anchor_id,
                "family": "Z",
                "release": reference_makespan - 1,
                "deadline": reference_makespan,
                "weight": 1,
                "predecessors": [],
                "modes": [
                    {
                        "id": "fixed",
                        "duration": 1,
                        "resources": {"crew": 0, "lab": 0},
                        "nonrenewable": 0,
                        "machines": ["ANCHOR"],
                    }
                ],
            }
        )
        planned[anchor_id] = {
            "start": reference_makespan - 1,
            "end": reference_makespan,
            "mode": "fixed",
            "machine": "ANCHOR",
        }

    reference_rows = [
        {
            "id": task["id"],
            "start": int(planned[task["id"]]["start"]),
            "mode": str(planned[task["id"]]["mode"]),
            "machine": str(planned[task["id"]]["machine"]),
        }
        for task in tasks
    ]
    reference_nonrenewable = sum(
        next(mode for mode in task["modes"] if mode["id"] == planned[task["id"]]["mode"])[
            "nonrenewable"
        ]
        for task in tasks
    )
    reference_weighted_completion = sum(
        int(task["weight"]) * int(planned[task["id"]]["end"]) for task in tasks
    )
    instance = {
        "id": instance_id,
        "horizon": horizon,
        "renewable_capacity": {"crew": width * 2 + 1, "lab": max(2, width - 1)},
        "nonrenewable_budget": reference_nonrenewable + max(4, task_count // 3),
        "machines": machines,
        "tasks": tasks,
        "objective": {
            "order": ["makespan", "nonrenewable", "weighted_completion"],
            "reference_upper_bound": {
                "makespan": reference_makespan,
                "nonrenewable": reference_nonrenewable,
                "weighted_completion": reference_weighted_completion,
            },
            "known_optimal_makespan": reference_makespan if exact_optimum else None,
        },
    }
    return instance, {"id": instance_id, "schedule": reference_rows}


def _scheduler_payload(
    profiles: list[tuple[str, int, int, int, bool]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    for instance_id, count, machines, seed, exact in profiles:
        instance, reference = _scheduler_instance(
            instance_id,
            task_count=count,
            machine_count=machines,
            seed=seed,
            exact_optimum=exact,
        )
        instances.append(instance)
        references.append(reference)
    return {"instances": instances}, {"instances": references}


SCHEDULER_CHECK_LIB = textwrap.dedent(
    r'''
    import json
    from pathlib import Path

    def analyze(instance, answer):
        checks = []
        def check(name, condition):
            checks.append((name, bool(condition)))

        tasks = {task["id"]: task for task in instance["tasks"]}
        machines = {machine["id"]: machine for machine in instance["machines"]}
        rows = answer.get("schedule") if isinstance(answer, dict) else None
        check("schedule_is_list", isinstance(rows, list))
        rows = rows if isinstance(rows, list) else []
        check("row_count", len(rows) == len(tasks))
        valid_rows = [row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)]
        choices = {row["id"]: row for row in valid_rows}
        check("task_ids", set(choices) == set(tasks) and len(valid_rows) == len(choices))
        selected = {}
        starts = {}
        ends = {}
        assigned_machines = {}
        nonrenewable = 0
        for task_id, task in tasks.items():
            row = choices.get(task_id, {})
            start = row.get("start")
            mode_id = row.get("mode")
            machine_id = row.get("machine")
            modes = {mode["id"]: mode for mode in task["modes"]}
            check(f"{task_id}.start", isinstance(start, int) and not isinstance(start, bool))
            check(f"{task_id}.mode", mode_id in modes)
            mode = modes.get(mode_id)
            check(f"{task_id}.machine", bool(mode) and machine_id in mode.get("machines", []))
            if not isinstance(start, int) or isinstance(start, bool) or not mode or machine_id not in machines:
                continue
            end = start + int(mode["duration"])
            starts[task_id], ends[task_id] = start, end
            selected[task_id], assigned_machines[task_id] = mode, machine_id
            nonrenewable += int(mode.get("nonrenewable", 0))
            check(f"{task_id}.release", start >= int(task.get("release", 0)))
            check(f"{task_id}.deadline", end <= int(task["deadline"]))
            calendar_ok = any(start >= int(left) and end <= int(right) for left, right in machines[machine_id]["calendar"])
            check(f"{task_id}.calendar", calendar_ok)

        for task_id, task in tasks.items():
            for relation in task.get("predecessors", []):
                predecessor = relation["id"]
                available = task_id in starts and predecessor in ends
                lag = starts.get(task_id, 0) - ends.get(predecessor, 0)
                check(f"{task_id}.pred.{predecessor}.min", available and lag >= int(relation.get("min_lag", 0)))
                maximum = relation.get("max_lag")
                check(f"{task_id}.pred.{predecessor}.max", available and (maximum is None or lag <= int(maximum)))

        for machine_id, machine in machines.items():
            members = [task_id for task_id in starts if assigned_machines.get(task_id) == machine_id]
            members.sort(key=lambda task_id: (starts[task_id], task_id))
            for left, right in zip(members, members[1:]):
                left_family = tasks[left]["family"]
                right_family = tasks[right]["family"]
                setup = int(machine.get("setup", {}).get(left_family, {}).get(right_family, 0))
                check(f"machine.{machine_id}.{left}.{right}", ends[left] + setup <= starts[right])

        horizon = int(instance["horizon"])
        for tick in range(horizon):
            active = [task_id for task_id in starts if starts[task_id] <= tick < ends[task_id]]
            for resource, limit in instance["renewable_capacity"].items():
                used = sum(int(selected[task_id].get("resources", {}).get(resource, 0)) for task_id in active)
                check(f"resource.{resource}.{tick}", used <= int(limit))
        check("nonrenewable_budget", nonrenewable <= int(instance["nonrenewable_budget"]))
        check("horizon", bool(ends) and max(ends.values()) <= horizon and len(ends) == len(tasks))
        passed = sum(int(ok) for _, ok in checks)
        feasible = bool(checks) and passed == len(checks)
        objective = None
        if ends:
            objective = {
                "makespan": max(ends.values()),
                "nonrenewable": nonrenewable,
                "weighted_completion": sum(int(tasks[task_id]["weight"]) * ends[task_id] for task_id in ends),
            }
        return {
            "feasible": feasible,
            "passed_checks": passed,
            "total_checks": len(checks),
            "failed": [name for name, ok in checks if not ok][:30],
            "objective": objective,
        }

    def analyze_payload(payload, answer):
        instances = {item["id"]: item for item in payload.get("instances", [])}
        answers = {
            item.get("id"): item
            for item in answer.get("instances", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        } if isinstance(answer, dict) else {}
        return {instance_id: analyze(instance, answers.get(instance_id, {})) for instance_id, instance in instances.items()}
    '''
).strip() + "\n"


REFERENCE_SOLVER = textwrap.dedent(
    r'''
    import json
    import sys
    from pathlib import Path

    def solve(instance):
        tasks = {task["id"]: task for task in instance["tasks"]}
        machine_map = {machine["id"]: machine for machine in instance["machines"]}
        order = []
        remaining = set(tasks)
        while remaining:
            ready = [task_id for task_id in remaining if all(edge["id"] in order for edge in tasks[task_id].get("predecessors", []))]
            if not ready:
                raise RuntimeError("precedence cycle")
            ready.sort(key=lambda task_id: (tasks[task_id]["deadline"] - tasks[task_id]["release"], tasks[task_id]["deadline"], task_id))
            order.extend(ready)
            remaining.difference_update(ready)

        starts, ends, modes, assigned = {}, {}, {}, {}
        budget_used = 0
        capacity = instance["renewable_capacity"]

        def can_place(task, mode, machine_id, start):
            end = start + int(mode["duration"])
            if not any(start >= left and end <= right for left, right in machine_map[machine_id]["calendar"]):
                return False
            for edge in task.get("predecessors", []):
                if edge["id"] not in ends:
                    return False
                lag = start - ends[edge["id"]]
                if lag < int(edge.get("min_lag", 0)) or (edge.get("max_lag") is not None and lag > int(edge["max_lag"])):
                    return False
            for other_id, other_machine in assigned.items():
                if other_machine != machine_id:
                    continue
                other = tasks[other_id]
                other_start, other_end = starts[other_id], ends[other_id]
                setup = machine_map[machine_id].get("setup", {})
                if end <= other_start:
                    gap = int(setup.get(task["family"], {}).get(other["family"], 0))
                    if end + gap > other_start:
                        return False
                elif other_end <= start:
                    gap = int(setup.get(other["family"], {}).get(task["family"], 0))
                    if other_end + gap > start:
                        return False
                else:
                    return False
            for tick in range(start, end):
                for resource, limit in capacity.items():
                    used = sum(int(modes[item].get("resources", {}).get(resource, 0)) for item in starts if starts[item] <= tick < ends[item])
                    if used + int(mode.get("resources", {}).get(resource, 0)) > int(limit):
                        return False
            return True

        sys.setrecursionlimit(10000)
        def search(position):
            nonlocal budget_used
            if position == len(order):
                return True
            task_id = order[position]
            task = tasks[task_id]
            mode_order = sorted(task["modes"], key=lambda mode: (mode["id"] != "balanced", mode["duration"], mode["nonrenewable"]))
            for mode in mode_order:
                next_budget = budget_used + int(mode.get("nonrenewable", 0))
                if next_budget > int(instance["nonrenewable_budget"]):
                    continue
                earliest = int(task.get("release", 0))
                for edge in task.get("predecessors", []):
                    earliest = max(earliest, ends[edge["id"]] + int(edge.get("min_lag", 0)))
                latest = int(task["deadline"]) - int(mode["duration"])
                for edge in task.get("predecessors", []):
                    if edge.get("max_lag") is not None:
                        latest = min(latest, ends[edge["id"]] + int(edge["max_lag"]))
                for start in range(earliest, latest + 1):
                    for machine_id in mode["machines"]:
                        if not can_place(task, mode, machine_id, start):
                            continue
                        starts[task_id] = start
                        ends[task_id] = start + int(mode["duration"])
                        modes[task_id] = mode
                        assigned[task_id] = machine_id
                        budget_used = next_budget
                        if search(position + 1):
                            return True
                        budget_used -= int(mode.get("nonrenewable", 0))
                        del starts[task_id], ends[task_id], modes[task_id], assigned[task_id]
            return False

        if not search(0):
            raise RuntimeError(f"no schedule found for {instance['id']}")
        return {
            "id": instance["id"],
            "schedule": [
                {"id": task_id, "start": starts[task_id], "mode": modes[task_id]["id"], "machine": assigned[task_id]}
                for task_id in tasks
            ],
        }

    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    output = {"instances": [solve(instance) for instance in payload["instances"]]}
    target = Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    '''
).strip() + "\n"


def _public_checker() -> str:
    return (
        SCHEDULER_CHECK_LIB
        + textwrap.dedent(
            r'''
            import sys
            payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
            answer = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
            report = analyze_payload(payload, answer)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if not all(item["feasible"] for item in report.values()):
                raise SystemExit(1)
            print("PUBLIC_SCHEDULER_V5_OK")
            '''
        ).strip()
        + "\n"
    )


def _scheduler_private_validator(hidden_payload: dict[str, Any]) -> str:
    hidden_text = json.dumps(hidden_payload, ensure_ascii=False, separators=(",", ":"))
    return (
        SCHEDULER_CHECK_LIB
        + textwrap.dedent(
            f'''
            import hashlib
            import subprocess
            import sys
            import traceback

            METRIC_KEYS = ["interface", "constraint_correctness", "feasibility", "optimality", "stability"]
            metrics = {{key: 0.0 for key in METRIC_KEYS}}
            evidence = {{}}
            private_root = Path(__file__).resolve().parent
            workspace = Path(__file__).resolve().parents[1]
            solver = workspace / "solver.py"
            hidden = json.loads({hidden_text!r})
            hidden_path = private_root / "hidden_instances.json"
            output_one = private_root / "hidden_output_1.json"
            output_two = private_root / "hidden_output_2.json"
            try:
                hidden_path.write_text(json.dumps(hidden, ensure_ascii=False), encoding="utf-8")
                original_hash = hashlib.sha256(hidden_path.read_bytes()).hexdigest()
                runs = []
                answers = []
                for target in (output_one, output_two):
                    completed = subprocess.run(
                        [sys.executable, str(solver), str(hidden_path), str(target)],
                        cwd=workspace,
                        capture_output=True,
                        text=True,
                        timeout=150,
                        check=False,
                    )
                    runs.append({{"exit_code": completed.returncode, "stdout": completed.stdout[-1500:], "stderr": completed.stderr[-2500:]}})
                    if target.is_file():
                        try:
                            answers.append(json.loads(target.read_text(encoding="utf-8-sig")))
                        except Exception:
                            answers.append(None)
                    else:
                        answers.append(None)
                valid_answer = next((answer for answer in answers if isinstance(answer, dict)), None)
                metrics["interface"] = 100.0 if runs[0]["exit_code"] == 0 and isinstance(answers[0], dict) else 40.0 if solver.is_file() else 0.0
                report = analyze_payload(hidden, valid_answer or {{}})
                evidence["instances"] = report
                total_checks = sum(item["total_checks"] for item in report.values())
                passed_checks = sum(item["passed_checks"] for item in report.values())
                metrics["constraint_correctness"] = round(100.0 * passed_checks / max(1, total_checks), 2)
                feasible = [item for item in report.values() if item["feasible"]]
                metrics["feasibility"] = round(100.0 * len(feasible) / max(1, len(report)), 2)
                optimality_scores = []
                instances = {{item["id"]: item for item in hidden["instances"]}}
                for instance_id, result in report.items():
                    if not result["feasible"] or not result["objective"]:
                        optimality_scores.append(0.0)
                        continue
                    objective = result["objective"]
                    reference = instances[instance_id]["objective"]["reference_upper_bound"]
                    gap = max(0.0, (objective["makespan"] - reference["makespan"]) / max(1, reference["makespan"]))
                    if instance_id == "hidden-small":
                        score = 100.0 if objective["makespan"] <= reference["makespan"] else 0.0
                    elif instance_id == "hidden-medium":
                        score = 100.0 if gap <= 0.02 else max(0.0, 100.0 * (0.20 - gap) / 0.18)
                    else:
                        score = 100.0 if gap <= 0.08 else max(0.0, 100.0 * (0.30 - gap) / 0.22)
                    budget_gap = max(0.0, (objective["nonrenewable"] - reference["nonrenewable"]) / max(1, reference["nonrenewable"]))
                    completion_gap = max(0.0, (objective["weighted_completion"] - reference["weighted_completion"]) / max(1, reference["weighted_completion"]))
                    score = 0.75 * score + 25.0 * max(0.0, 1.0 - min(1.0, (budget_gap + completion_gap) / 0.30))
                    optimality_scores.append(round(score, 2))
                metrics["optimality"] = round(sum(optimality_scores) / max(1, len(optimality_scores)), 2)
                input_unchanged = hashlib.sha256(hidden_path.read_bytes()).hexdigest() == original_hash
                metrics["stability"] = 100.0 if answers[0] == answers[1] and all(run["exit_code"] == 0 for run in runs) and input_unchanged else 50.0 if all(isinstance(answer, dict) for answer in answers) and input_unchanged else 0.0
                evidence["runs"] = runs
                evidence["optimality_by_instance"] = optimality_scores
            except subprocess.TimeoutExpired as exc:
                evidence["solver_timeout"] = str(exc)
            except Exception:
                evidence["validator_exception"] = traceback.format_exc()[-4000:]
            print("AGENTBENCH_METRICS=" + json.dumps({{"metrics": metrics, "evidence": evidence}}, ensure_ascii=False, separators=(",", ":")))
            '''
        ).strip()
        + "\n"
    )


def _event_private_validator() -> str:
    return textwrap.dedent(
        r'''
        import json
        import sqlite3
        import subprocess
        import sys
        import tempfile
        import time
        import traceback
        from pathlib import Path

        workspace = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(workspace))
        if len(sys.argv) > 1 and sys.argv[1] == "hot-worker":
            from event_store import ConcurrencyError, EventStore
            path, worker = sys.argv[2], int(sys.argv[3])
            local = EventStore(path)
            for index in range(8):
                for retry in range(200):
                    current = len(local.read("hot")) - 1
                    try:
                        local.append("hot", current, [{"worker":worker,"index":index,"part":0},{"worker":worker,"index":index,"part":1}], f"hot-{worker}-{index}")
                        break
                    except ConcurrencyError:
                        if retry == 199:
                            raise
            raise SystemExit(0)
        if len(sys.argv) > 1 and sys.argv[1] == "crash-worker":
            from event_store import EventStore
            path, ready_path = sys.argv[2], Path(sys.argv[3])
            local = EventStore(path)
            blob = "x" * 4096
            batch = [{"index": index, "blob": blob} for index in range(30000)]
            ready_path.write_text("ready", encoding="utf-8")
            local.append("crash", -1, batch, "crash-command")
            raise SystemExit(0)
        keys = ["migration_schema", "idempotency_json", "multiprocess", "crash_atomicity", "integrity_snapshot", "file_integrity"]
        metrics = {key: 0.0 for key in keys}
        evidence = {}
        root = Path(tempfile.mkdtemp())
        try:
            from event_store import ConcurrencyError, EventStore, IntegrityError
        except Exception:
            evidence["import"] = traceback.format_exc()[-3000:]
            print("AGENTBENCH_METRICS=" + json.dumps({"metrics": metrics, "evidence": evidence}, ensure_ascii=False, separators=(",", ":")))
            raise SystemExit(0)

        def run_metric(name, callback):
            try:
                value, detail = callback()
                metrics[name] = max(0.0, min(100.0, float(value)))
                evidence[name] = detail
            except Exception:
                evidence[name] = traceback.format_exc()[-3000:]

        def migration_schema():
            path = root / "legacy.db"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE events(stream TEXT,version INTEGER,payload TEXT)")
            connection.execute("INSERT INTO events VALUES ('legacy',0,'{\"old\":true}')")
            connection.commit(); connection.close()
            store = EventStore(path)
            checks = [store.read("legacy") == [{"version":0,"payload":{"old":True}}]]
            checks.append(store.append("legacy", 0, [{"new":True}], "legacy-command") == [1])
            connection = sqlite3.connect(path)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            columns = {row[1] for row in connection.execute("PRAGMA table_info(events)")}
            snapshot_columns = {row[1] for row in connection.execute("PRAGMA table_info(snapshots)")}
            connection.close()
            checks.extend([{"events", "commands", "snapshots"} <= tables, {"stream", "version", "payload", "checksum"} <= columns, {"stream", "version", "state", "checksum"} <= snapshot_columns])
            return 100 * sum(checks) / len(checks), {"checks": checks}

        def idempotency_json():
            store = EventStore(root / "canonical.db")
            expected = [{"z":1,"nested":{"b":2,"a":"值"}},{"number":3.5}]
            checks = [store.append("s", -1, expected, "same-command") == [0, 1]]
            replay = [{"nested":{"a":"值","b":2},"z":1},{"number":3.5}]
            checks.append(store.append("s", -1, replay, "same-command") == [0, 1])
            try:
                store.append("other", -1, expected, "same-command")
                checks.append(False)
            except ValueError:
                checks.append(True)
            before = store.read("s")
            try:
                store.append("s", 1, [{"ok":1},{"bad":{1,2}}], "bad-json")
                checks.append(False)
            except (TypeError, ValueError):
                checks.append(store.read("s") == before)
            return 100 * sum(checks) / len(checks), {"checks": checks}

        def multiprocess_test():
            path = root / "hot.db"
            EventStore(path)
            workers = [
                subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "hot-worker", str(path), str(worker)],
                    cwd=workspace,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for worker in range(6)
            ]
            outputs = []
            for worker in workers:
                try:
                    stdout, stderr = worker.communicate(timeout=45)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    stdout, stderr = worker.communicate()
                outputs.append({"exit_code": worker.returncode, "stdout": stdout[-500:], "stderr": stderr[-1500:]})
            checks = [all(item["exit_code"] == 0 for item in outputs)]
            rows = EventStore(path).read("hot")
            checks.extend([len(rows) == 96, [item["version"] for item in rows] == list(range(96))])
            return 100 * sum(checks) / len(checks), {"checks": checks, "rows": len(rows), "workers": outputs}

        def crash_test():
            path = root / "crash.db"
            ready_path = root / "crash.ready"
            EventStore(path)
            doomed = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "crash-worker", str(path), str(ready_path)],
                cwd=workspace,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 20
            while not ready_path.is_file() and doomed.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            checks = [ready_path.is_file()]
            time.sleep(0.04)
            checks.append(doomed.poll() is None)
            if doomed.poll() is None:
                doomed.kill()
            doomed.wait(timeout=20)
            connection = sqlite3.connect(path)
            count = connection.execute("SELECT COUNT(*) FROM events WHERE stream='crash'").fetchone()[0]
            connection.close()
            checks.append(count == 0)
            recovered = EventStore(path)
            checks.append(recovered.append("crash", -1, [{"recovered":True}], "after-crash") == [0])
            checks.append(recovered.read("crash")[0]["payload"] == {"recovered":True})
            return 100 * sum(checks) / len(checks), {"checks": checks, "surviving_rows": count}

        def integrity_snapshot_test():
            checks = []
            snap_path = root / "snapshots.db"
            snapshots = EventStore(snap_path)
            snapshots.append("account", -1, [{"n":n} for n in range(6)], "seed-snapshots")
            snapshots.save_snapshot("account", 2, {"balance":3})
            snapshots.save_snapshot("account", 5, {"balance":6})
            connection = sqlite3.connect(snap_path)
            connection.execute("UPDATE snapshots SET state='corrupt' WHERE stream='account' AND version=5")
            connection.commit(); connection.close()
            checks.append(snapshots.load_snapshot("account") == {"version":2,"state":{"balance":3}})
            try:
                snapshots.save_snapshot("account", 1, {"balance":2})
                checks.append(False)
            except (ConcurrencyError, ValueError):
                checks.append(True)
            tamper_path = root / "tamper.db"
            tamper = EventStore(tamper_path)
            tamper.append("audit", -1, [{"secure":True}], "audit-1")
            connection = sqlite3.connect(tamper_path)
            connection.execute("UPDATE events SET payload='{}' WHERE stream='audit' AND version=0")
            connection.commit(); connection.close()
            try:
                tamper.read("audit")
                checks.append(False)
            except IntegrityError:
                checks.append(True)
            return 100 * sum(checks) / len(checks), {"checks": checks}

        def file_integrity_test():
            smoke = workspace / "public_smoke.py"
            spec = workspace / "SPEC.md"
            checks = [smoke.is_file(), spec.is_file(), (workspace / "event_store.py").is_file()]
            checks.append("Durable EventStore v5" in spec.read_text(encoding="utf-8", errors="replace"))
            checks.append("PUBLIC_EVENT_STORE_SMOKE_OK" in smoke.read_text(encoding="utf-8", errors="replace"))
            return 100 * sum(checks) / len(checks), {"checks": checks}

        run_metric("migration_schema", migration_schema)
        run_metric("idempotency_json", idempotency_json)
        run_metric("multiprocess", multiprocess_test)
        run_metric("crash_atomicity", crash_test)
        run_metric("integrity_snapshot", integrity_snapshot_test)
        run_metric("file_integrity", file_integrity_test)
        print("AGENTBENCH_METRICS=" + json.dumps({"metrics": metrics, "evidence": evidence}, ensure_ascii=False, separators=(",", ":")))
        '''
    ).strip() + "\n"


def build_ultra_catalog_v5(event_solution: str) -> list[dict[str, Any]]:
    public_payload, _ = _scheduler_payload(
        [("public-small", 6, 3, 1409, True), ("public-medium", 9, 3, 1423, False)]
    )
    hidden_payload, _ = _scheduler_payload(
        [
            ("hidden-small", 10, 3, 1907, True),
            ("hidden-medium", 18, 4, 2017, False),
            ("hidden-large", 30, 4, 2203, False),
        ]
    )
    public_text = json.dumps(public_payload, ensure_ascii=False, indent=2)
    public_checker = _public_checker()
    event_validator = _event_private_validator()
    scheduler_validator = _scheduler_private_validator(hidden_payload)
    event_initial = textwrap.dedent(
        '''
        import json
        import sqlite3

        class ConcurrencyError(RuntimeError):
            pass

        class IntegrityError(RuntimeError):
            pass

        class EventStore:
            def __init__(self, path):
                self.path = str(path)
                connection = sqlite3.connect(self.path)
                connection.execute("CREATE TABLE IF NOT EXISTS events(stream TEXT,version INTEGER,payload TEXT)")
                connection.commit(); connection.close()

            def append(self, stream_id, expected_version, events, command_id):
                raise NotImplementedError

            def read(self, stream_id):
                raise NotImplementedError

            def save_snapshot(self, stream_id, version, state):
                raise NotImplementedError

            def load_snapshot(self, stream_id):
                raise NotImplementedError
        '''
    ).strip() + "\n"
    event_smoke = textwrap.dedent(
        '''
        import tempfile
        from pathlib import Path
        from event_store import ConcurrencyError, EventStore

        store = EventStore(Path(tempfile.mkdtemp()) / "events.db")
        assert store.append("orders", -1, [{"type":"created"},{"type":"paid"}], "cmd-1") == [0, 1]
        assert store.append("orders", -1, [{"type":"created"},{"type":"paid"}], "cmd-1") == [0, 1]
        assert [item["version"] for item in store.read("orders")] == [0, 1]
        try:
            store.append("orders", 0, [{"type":"bad"}], "cmd-2")
            raise AssertionError("expected ConcurrencyError")
        except ConcurrencyError:
            pass
        store.save_snapshot("orders", 0, {"status":"created"})
        store.save_snapshot("orders", 1, {"status":"ready"})
        assert store.load_snapshot("orders") == {"version":1,"state":{"status":"ready"}}
        print("PUBLIC_EVENT_STORE_SMOKE_OK")
        '''
    ).strip() + "\n"
    common_policy = {
        "max_attempts": 3,
        "pass_threshold": 85,
        "multipliers": [1.0, 0.85, 0.70],
        "preserve_workspace": True,
    }
    event_metrics = [
        {"key": "migration_schema", "name": "迁移与模式", "weight": 15},
        {"key": "idempotency_json", "name": "幂等与规范 JSON", "weight": 15},
        {"key": "multiprocess", "name": "多进程并发", "weight": 20},
        {"key": "crash_atomicity", "name": "强杀恢复与批次原子性", "weight": 25},
        {"key": "integrity_snapshot", "name": "哈希链与快照回退", "weight": 20},
        {"key": "file_integrity", "name": "文件完整性", "weight": 5},
    ]
    scheduler_metrics = [
        {"key": "interface", "name": "求解器接口", "weight": 10},
        {"key": "constraint_correctness", "name": "约束正确性", "weight": 30},
        {"key": "feasibility", "name": "隐藏实例可行率", "weight": 25},
        {"key": "optimality", "name": "多目标解质量", "weight": 30},
        {"key": "stability", "name": "重复运行稳定性", "weight": 5},
    ]
    return [
        {
            "slug": "ultra.event-store-crash-consistency-003",
            "version": "5.0.0",
            "category": "ultra-engineering",
            "title": "ULTRA · 崩溃一致性事件存储 III",
            "description": "以六个独立维度连续评分跨进程竞争、强杀恢复、迁移、幂等与哈希链完整性。",
            "instruction": (
                "阅读 `SPEC.md` 并完成 `event_store.py`，保持四个公开方法不变。公开 smoke 仅覆盖基础契约；"
                "私有验证会分项测试迁移、规范 JSON、跨进程并发、强杀原子性、哈希链与快照回退。"
            ),
            "tools": ["filesystem", "search", "shell"],
            "limits": {
                "max_steps": 160,
                "time_target_seconds": 3600,
                "max_runtime_seconds": 14400,
                "validator_timeout_seconds": 480,
                "token_budget": 280000,
                "network": "disabled",
                "docker_image": "python:3.12-alpine",
            },
            "validators": [
                _validator("file_exists", 3, path="event_store.py"),
                _validator(
                    "command_metrics",
                    94,
                    command="python {private_root}/validate_event_store.py",
                    private_files={"validate_event_store.py": event_validator},
                    metrics=event_metrics,
                    critical=True,
                    critical_min_score=80,
                ),
                _validator("file_content", 1, path="public_smoke.py", expected=event_smoke),
                _validator("file_contains", 1, path="SPEC.md", text="Durable EventStore v5"),
                _validator("forbidden_paths", 1, paths=[".git", ".agentbench-private-*"]),
            ],
            "tags": ["ultra", "sqlite", "multiprocessing", "crash-consistency", "migration", "hash-chain"],
            "initial_files": {
                "event_store.py": event_initial,
                "public_smoke.py": event_smoke,
                "SPEC.md": (
                    "# Durable EventStore v5\n\nUse only Python's standard library and SQLite. Implement atomic batches under process kill, "
                    "optimistic concurrency, global command-id idempotency over canonical JSON, process-safe writes, a per-stream "
                    "event integrity hash chain, monotonic snapshot history with corrupt-row fallback, and lossless migration from "
                    "`events(stream, version, payload)`. Tables must be named `events`, `commands`, `snapshots`; snapshots expose "
                    "`stream, version, state, checksum`. `read` raises IntegrityError on tampering.\n"
                ),
            },
            "attempt_policy": {
                **common_policy,
                "hints": [
                    "先把每个失败维度独立定位：初始化迁移用排他事务，写入用 BEGIN IMMEDIATE；规范化和指纹在事务前完成。",
                    "每个进程使用独立 SQLite 连接并设置 busy_timeout。事件哈希包含 stream/version/previous_hash/canonical_payload；快照保留历史并倒序校验。",
                ],
            },
            "metadata": {
                "difficulty": 6,
                "tier": "ultra",
                "estimated_minutes": 95,
                "capability": "crash-consistent-multiprocess-engineering",
                "private_validation": True,
                "scoring_breakdown": event_metrics,
                "demo_actions": [{"tool": "write_file", "arguments": {"path": "event_store.py", "content": event_solution}}],
                "demo_response": "事件存储实现完成。",
            },
        },
        {
            "slug": "ultra.hidden-general-resource-scheduler-003",
            "version": "5.0.0",
            "category": "ultra-planning",
            "title": "ULTRA · 隐藏实例通用资源调度器",
            "description": "提交可执行的通用求解器，现场求解未公开的小、中、大型多约束实例并按可行率与最优差距连续评分。",
            "instruction": (
                "实现 `solver.py`，接口固定为 `python solver.py instances.json output.json`。不得只提交公开样例答案。"
                "评分时会注入未公开实例并现场运行两次，覆盖最小/最大时间间隔、机器日历、序列相关切换时间、"
                "替代机器、共享可再生资源、非可再生预算与多目标优化。小型实例要求已知最优，中型按 2% 差距线评分，"
                "大型要求稳定地产生高质量可行解。运行环境仅保证 Python 3.12 标准库。"
            ),
            "tools": ["filesystem", "search", "shell"],
            "limits": {
                "max_steps": 180,
                "time_target_seconds": 4200,
                "max_runtime_seconds": 14400,
                "validator_timeout_seconds": 420,
                "token_budget": 300000,
                "network": "disabled",
                "docker_image": "python:3.12-alpine",
            },
            "validators": [
                _validator("file_exists", 3, path="solver.py"),
                _validator(
                    "command_metrics",
                    95,
                    command="python {private_root}/evaluate_solver.py",
                    private_files={"evaluate_solver.py": scheduler_validator},
                    metrics=scheduler_metrics,
                    critical=True,
                    critical_min_score=75,
                ),
                _validator("file_content", 1, path="public_instances.json", expected=public_text),
                _validator("forbidden_paths", 1, paths=[".git", ".agentbench-private-*"]),
            ],
            "tags": ["ultra", "solver", "hidden-instances", "rcpsp-max", "machine-calendar", "multi-objective"],
            "initial_files": {
                "public_instances.json": public_text,
                "check_solution.py": public_checker,
                "FORMAT.md": (
                    "Run `python solver.py public_instances.json deliverables/public_solution.json`, then "
                    "`python check_solution.py public_instances.json deliverables/public_solution.json`. Output is "
                    "`{\"instances\":[{\"id\":...,\"schedule\":[{\"id\":...,\"start\":0,\"mode\":\"balanced\",\"machine\":\"M1\"}]}]}`.\n"
                ),
            },
            "attempt_policy": {
                **common_policy,
                "hints": [
                    "先实现严格的通用校验与拓扑排序，再用最小剩余时间窗选点；联合枚举模式、机器与开始时刻，并维护逐时刻资源占用及机器前后切换间隔。",
                    "第二阶段加入分支定界：以下界剪枝 makespan，按非可再生消耗和加权完成时间排序候选；保留当前最好可行解，在大型实例达到时间预算时也必须写出结果。",
                ],
            },
            "metadata": {
                "difficulty": 6,
                "tier": "ultra",
                "estimated_minutes": 120,
                "capability": "hidden-instance-general-constraint-optimization",
                "private_validation": True,
                "instance_count": 3,
                "task_count": 58,
                "scoring_breakdown": scheduler_metrics,
                "demo_actions": [{"tool": "write_file", "arguments": {"path": "solver.py", "content": REFERENCE_SOLVER}}],
                "demo_response": "通用调度求解器实现完成。",
            },
        },
    ]
