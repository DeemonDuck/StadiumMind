"""
core/tasks.py

Turns the same live data the Organizer Agent reasons over - congestion
hotspots and structured incidents - into assignable task cards for
volunteers and venue staff.

WHY THIS EXISTS:
The PromptWars brief names four groups to help: "fans, organizers,
volunteers, or venue staff." The original build served fans (Fan Agent)
and organizers (Organizer Agent's recommendations), but volunteers/staff
had no distinct view - they'd have had to read the organizer's freeform
AI paragraph and manually figure out who should do what.

DESIGN CHOICE - deterministic, not LLM-parsed:
Task generation here is a plain function over data (congestion_snapshot +
incidents), not a parser of the organizer agent's freeform LLM text. Two
reasons: (1) parsing structured fields back out of a natural-language
paragraph is brittle and would need re-parsing every time the prompt
wording changes, and (2) it keeps this piece fully unit-testable without
mocking an LLM - important since agents/ already had zero test coverage
before this feature existed. The organizer agent and this module are two
independent "views" over the same underlying congestion/incident data.
"""

from __future__ import annotations  # allows `str | None` etc. on Python < 3.10

from dataclasses import dataclass, field
from datetime import datetime

from core.congestion import CRITICAL_THRESHOLD, HIGH_THRESHOLD, CongestionSnapshot
from core.incidents import SEVERITY_LEVELS, Incident

TASK_STATUSES = ["OPEN", "ASSIGNED", "RESOLVED"]

# A congestion hotspot at or above this score generates a task. This IS the
# "high" band from core/congestion.py, not a number that happens to match it,
# so a task appears exactly when the dashboard would already be showing that
# node as orange/red - there's no second threshold that could drift out of sync.
DEFAULT_CONGESTION_THRESHOLD = HIGH_THRESHOLD


@dataclass
class Task:
    """A single assignable task card for a volunteer or staff member."""

    id: str  # stable identity (see generate_tasks_from_state) - used as the
    #          dict key in st.session_state so re-generating tasks doesn't
    #          wipe out an existing assignment/status for the same task.
    description: str
    location: str
    priority: str = "MEDIUM"
    status: str = "OPEN"
    assigned_to: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def priority_rank(self) -> int:
        """Numeric rank for sorting - higher means more urgent. Reuses the
        exact same LOW/MEDIUM/HIGH/CRITICAL scale as core/incidents.py so
        volunteer priority and organizer incident severity always mean the
        same thing."""
        try:
            return SEVERITY_LEVELS.index(self.priority.upper())
        except ValueError:
            return SEVERITY_LEVELS.index("MEDIUM")  # unknown -> treat as medium


def sort_tasks_by_priority(tasks: list[Task]) -> list[Task]:
    """Highest priority first; ties keep their original relative order."""
    return sorted(tasks, key=lambda t: -t.priority_rank())


def generate_tasks_from_state(
    congestion_snapshot: CongestionSnapshot,
    incidents: list[Incident],
    congestion_threshold: int = DEFAULT_CONGESTION_THRESHOLD,
) -> list[Task]:
    """
    Derive a list of volunteer/staff task cards from current conditions.

    Two sources, both already tracked elsewhere in the app:
      - Every open Incident becomes a task ("Respond to: <description>").
      - Every node at/above congestion_threshold becomes a task
        ("Redirect / assist foot traffic at <node>").

    Args:
        congestion_snapshot: {node: score} as returned by
            CrowdSimulator.get_all()
        incidents: list of core.incidents.Incident
        congestion_threshold: score at/above which a node gets a task

    Returns:
        List of Task, sorted highest-priority first. Each Task.id is
        stable across calls for the same incident/node, so callers can
        merge into an existing dict (keyed by id) without clobbering a
        task someone already assigned or resolved.
    """
    tasks: list[Task] = []

    for inc in incidents:
        tasks.append(
            Task(
                id=f"incident::{inc.location}::{inc.description}",
                description=f"Respond to: {inc.description}",
                location=inc.location,
                priority=inc.severity,
            )
        )

    hotspots = {node: score for node, score in congestion_snapshot.items() if score >= congestion_threshold}
    for node, score in sorted(hotspots.items(), key=lambda item: -item[1]):
        priority = "CRITICAL" if score >= CRITICAL_THRESHOLD else "HIGH"
        tasks.append(
            Task(
                id=f"congestion::{node}",
                description=f"Redirect or assist foot traffic at {node} ({score}/100 congestion)",
                location=node,
                priority=priority,
            )
        )

    return sort_tasks_by_priority(tasks)


if __name__ == "__main__":
    # Quick manual check: python core/tasks.py
    from core.incidents import Incident

    sample_congestion = {"Gate_A": 82, "Gate_B": 30, "Section_2": 60}
    sample_incidents = [Incident("Medical situation", "Gate_A", "HIGH")]

    for t in generate_tasks_from_state(sample_congestion, sample_incidents):
        print(f"[{t.priority}] {t.description} (id={t.id})")
