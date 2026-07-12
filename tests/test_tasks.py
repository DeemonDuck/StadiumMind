"""
tests/test_tasks.py

Tests for core/tasks.py - deterministic volunteer/staff task-card
generation from congestion + incidents. No LLM involved, so fully
deterministic and fast.

Run with: pytest tests/test_tasks.py -v
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.incidents import Incident
from core.tasks import Task, generate_tasks_from_state, sort_tasks_by_priority


def test_incident_generates_a_task():
    tasks = generate_tasks_from_state({}, [Incident("Medical situation", "Gate_A", "HIGH")])
    assert len(tasks) == 1
    assert tasks[0].location == "Gate_A"
    assert tasks[0].priority == "HIGH"
    assert "Medical situation" in tasks[0].description


def test_congestion_hotspot_generates_a_task_above_threshold():
    congestion = {"Gate_A": 82, "Gate_B": 20}
    tasks = generate_tasks_from_state(congestion, [])
    locations = {t.location for t in tasks}
    assert "Gate_A" in locations
    assert "Gate_B" not in locations  # below the default threshold


def test_congestion_at_or_above_75_is_marked_critical():
    congestion = {"Gate_A": 82}
    tasks = generate_tasks_from_state(congestion, [])
    assert tasks[0].priority == "CRITICAL"


def test_congestion_between_threshold_and_75_is_marked_high():
    congestion = {"Gate_A": 60}
    tasks = generate_tasks_from_state(congestion, [])
    assert tasks[0].priority == "HIGH"


def test_no_task_generated_below_threshold():
    congestion = {"Gate_A": 10}
    tasks = generate_tasks_from_state(congestion, [])
    assert tasks == []


def test_task_ids_are_stable_across_repeated_calls():
    """Same underlying data in -> same task ids out. This is what lets
    app.py merge fresh tasks into an existing dict without wiping out an
    assignment/status a volunteer already set."""
    congestion = {"Gate_A": 82}
    incidents = [Incident("Medical situation", "Gate_A", "HIGH")]

    first = generate_tasks_from_state(congestion, incidents)
    second = generate_tasks_from_state(congestion, incidents)

    first_ids = {t.id for t in first}
    second_ids = {t.id for t in second}
    assert first_ids == second_ids


def test_sort_tasks_by_priority_orders_critical_first():
    low = Task(id="a", description="d", location="Gate_A", priority="LOW")
    critical = Task(id="b", description="d", location="Gate_B", priority="CRITICAL")
    medium = Task(id="c", description="d", location="Gate_C", priority="MEDIUM")

    ranked = sort_tasks_by_priority([low, medium, critical])
    assert ranked[0] is critical
    assert ranked[-1] is low


def test_unknown_priority_falls_back_to_medium_rank():
    weird = Task(id="a", description="d", location="Gate_A", priority="UNKNOWN_LEVEL")
    medium = Task(id="b", description="d", location="Gate_B", priority="MEDIUM")
    assert weird.priority_rank() == medium.priority_rank()


def test_custom_threshold_is_respected():
    congestion = {"Gate_A": 40}
    assert generate_tasks_from_state(congestion, [], congestion_threshold=50) == []
    assert len(generate_tasks_from_state(congestion, [], congestion_threshold=30)) == 1


if __name__ == "__main__":
    # Allows running directly with `python tests/test_tasks.py` without pytest installed
    import traceback

    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL: {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
