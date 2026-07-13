"""
core/incidents.py

Structured incident model.

Previously an incident was just a raw string ("Medical emergency"), which
gave the organizer agent nothing to prioritize against. Structuring it as
(description, location, severity, timestamp) lets the agent reason about
WHERE something is happening and HOW urgent it is, not just that something
happened somewhere, sometime.
"""

from dataclasses import dataclass, field
from datetime import datetime

# Ordered low -> high on purpose, so severity can be compared with
# SEVERITY_LEVELS.index(a) < SEVERITY_LEVELS.index(b)
SEVERITY_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@dataclass
class Incident:
    """A single structured incident report from staff."""

    description: str
    location: str
    severity: str = "MEDIUM"
    timestamp: datetime = field(default_factory=datetime.now)

    def minutes_ago(self) -> int:
        """
        How many minutes since this incident was reported. Used for display
        and, later, for prioritization logic (an unresolved HIGH incident
        that's been sitting for 10 minutes is more urgent than one from 30
        seconds ago).
        """
        delta = datetime.now() - self.timestamp
        return max(0, int(delta.total_seconds() // 60))

    def severity_rank(self) -> int:
        """Numeric rank for sorting - higher means more urgent."""
        try:
            return SEVERITY_LEVELS.index(self.severity.upper())
        except ValueError:
            return SEVERITY_LEVELS.index("MEDIUM")  # unknown severity -> treat as medium

    def to_prompt_line(self) -> str:
        """Single-line format for inclusion in an LLM prompt."""
        return f"- {self.description} at {self.location} [{self.severity}] ({self.minutes_ago()} min ago)"

    def __str__(self) -> str:
        return self.to_prompt_line()


def sort_by_urgency(incidents: list[Incident]) -> list[Incident]:
    """
    Sort incidents most-urgent-first: highest severity first, and among
    equal severities, the oldest (longest unresolved) first.
    """
    return sorted(incidents, key=lambda i: (-i.severity_rank(), -i.minutes_ago()))


if __name__ == "__main__":
    # Quick manual check: python core/incidents.py
    import time

    a = Incident("Medical emergency", "Gate_B", "HIGH")
    time.sleep(1)
    b = Incident("Spilled drink, slippery floor", "FoodCourt_1", "LOW")
    c = Incident("Small fight breaking out", "Section_4", "CRITICAL")

    for inc in sort_by_urgency([a, b, c]):
        print(inc)
