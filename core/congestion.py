"""
core/congestion.py

The congestion scale itself: the 0-100 score bands and the label they map to.

WHY THIS EXISTS:
These four bands are the project's single most cross-cutting concept - the
organizer agent reasons in them, the fan router avoids the top ones, the task
board escalates on them, the map colours by them, and the dashboard prints
them. Until now the thresholds were written out in three separate places:

  - CrowdSimulator.get_congestion_label()      (75 / 50 / 25)
  - organizer_agent._congestion_label()        (75 / 50 / 25, a copy)
  - core/tasks.py                              (>= 50 to raise a task,
                                                >= 75 to make it CRITICAL)

The copy in organizer_agent was a deliberate one - the agent should reason over
plain data (snapshot/trend dicts), not need a live CrowdSimulator instance
handed to it just to name a number. That constraint was right, but duplicating
the thresholds wasn't the only way to satisfy it: a free function over an int
needs no simulator either. So the agent keeps its independence AND the numbers
stop being written down three times, where they could silently drift apart and
leave the map, the agent, and the task board disagreeing about what "critical"
means.

Anything that needs to interpret a congestion score should import from here.
"""

from __future__ import annotations

# A score at or above each threshold earns that label. Ordered high -> low,
# which is also the order congestion_label() tests them in.
CRITICAL_THRESHOLD = 75
HIGH_THRESHOLD = 50
MODERATE_THRESHOLD = 25

# {node_name: score 0-100} - what CrowdSimulator.get_all() hands out, and what
# the agents, the task board and the map all read. Named because it's passed
# across nearly every module boundary in the project; "dict" said nothing about
# which dict, and there are several in play (trends, positions, translations).
CongestionSnapshot = dict[str, int]


def congestion_label(score: int) -> str:
    """
    Turn a 0-100 congestion score into its human-readable band.

    Used in the UI, in LLM prompts (a model reads "critical" more naturally
    than a bare 82), and to colour the venue map. A plain function over an int
    on purpose: callers reasoning about congestion don't need a CrowdSimulator
    instance just to name a number.

    Returns one of: "low", "moderate", "high", "critical".
    """
    if score >= CRITICAL_THRESHOLD:
        return "critical"
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MODERATE_THRESHOLD:
        return "moderate"
    return "low"
