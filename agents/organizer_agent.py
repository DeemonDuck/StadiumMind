"""
agents/organizer_agent.py

The "real-time decision support" half of StadiumMind. Takes the current
crowd congestion snapshot, an optional trend dict (from CrowdSimulator's
get_trend/estimate_ticks_to_critical), the venue graph, and a list of
structured Incident objects, and asks an LLM to produce a prioritized,
plain-English action plan for stadium staff.

MOCK MODE:
If no GROQ_API_KEY is configured, this falls back to a rule-based mock
response instead of crashing or blocking development. The mock still reacts
to real data, so the demo stays sensible. See agents/llm_client.py, which
owns the client and that fallback policy for both agents.
"""

from __future__ import annotations  # allows `dict | None` etc. on Python < 3.10

import networkx as nx

from agents.llm_client import complete
from core.congestion import CongestionSnapshot, congestion_label
from core.crowd_sim import Trends
from core.incidents import Incident, sort_by_urgency

MODEL = "llama-3.3-70b-versatile"  # stronger reasoning model - good fit for triage/prioritization


def _format_incidents(incidents: list[Incident]) -> str:
    """Format a list of Incident objects (already urgency-sorted) for the prompt."""
    if not incidents:
        return "None reported"
    return "\n".join(inc.to_prompt_line() for inc in incidents)


def _trend_phrase(trends: Trends | None, node: str) -> str:
    """
    Turn a node's trend info into a short natural-language fragment, e.g.
    ", up 18% recently, projected to reach critical in ~3 more updates".
    Returns "" if there's nothing meaningful to say.
    """
    if not trends or node not in trends:
        return ""
    info = trends[node]
    pct = info.get("trend_pct", 0)
    eta = info.get("eta_ticks")

    parts = []
    if pct > 5:
        parts.append(f"up {pct}% recently")
    elif pct < -5:
        parts.append(f"down {abs(pct)}% recently")

    if eta == 0:
        parts.append("already at critical level")
    elif eta is not None:
        parts.append(f"projected to reach critical in ~{eta} more updates")

    return ", " + " and ".join(parts) if parts else ""


def _format_trends_for_prompt(congestion_snapshot: CongestionSnapshot, trends: Trends | None) -> str:
    """Format trend info for every node that has a meaningful trend, for the LLM prompt."""
    if not trends:
        return "No trend data available."
    lines = []
    for node in congestion_snapshot:
        phrase = _trend_phrase(trends, node)
        if phrase:
            lines.append(f"- {node}{phrase}")
    return "\n".join(lines) if lines else "No significant trends right now."


def _build_prompt(congestion_snapshot: CongestionSnapshot, incidents: list[Incident], trends: Trends | None) -> str:
    """
    Build the LLM prompt from current state. Kept as its own function so
    the prompt can be tweaked or unit-tested independently of the API call.
    """
    return f"""You are an AI operations assistant for a live sports stadium.

Current live congestion levels (0-100 scale, higher = more crowded):
{congestion_snapshot}

Recent trends:
{_format_trends_for_prompt(congestion_snapshot, trends)}

Active incidents (most urgent first):
{_format_incidents(incidents)}

Respond in exactly this structure:

Summary: <one line on overall crowd situation, mentioning any concerning trend>

Priority 1:
  Action: <the single highest-priority action>
  Estimated congestion reduction: ~<X>% (simulated estimate)
  Affected areas: <comma-separated locations>

Priority 2 (only include if there's a genuine second issue - an incident or a second congestion hotspot):
  Action: <second action>
  Affected areas: <comma-separated locations>

Keep it concise and actionable - this will be read by staff during a live event, not analyzed later."""


def _mock_recommendation(
    graph: nx.Graph,
    congestion_snapshot: CongestionSnapshot,
    incidents: list[Incident],
    trends: Trends | None,
) -> str:
    """
    PLACEHOLDER used only when no GROQ_API_KEY is configured.

    Still reacts to REAL data - the actual most-crowded node, its actual
    neighbors from the graph, its actual trend, and real incident
    severity/location - rather than returning a static string, so the
    demo looks sensible even in mock mode. Clearly labeled so it's never
    mistaken for real AI output.
    """
    if not congestion_snapshot:
        return "[MOCK - no API key configured] No congestion data available yet."

    worst_node = max(congestion_snapshot, key=lambda node: congestion_snapshot[node])
    worst_score = congestion_snapshot[worst_node]
    neighbors = list(graph.neighbors(worst_node)) if graph is not None else []
    affected = ", ".join(neighbors) if neighbors else "surrounding areas"
    # Simple heuristic, not a real prediction model - proportional to how
    # congested the worst node is, capped at a plausible 40%.
    estimated_reduction = min(40, round(worst_score * 0.22))
    trend_note = _trend_phrase(trends, worst_node)

    lines = [
        "[MOCK RESPONSE - add a real GROQ_API_KEY to .env for live AI reasoning]",
        (
            f"Summary: {worst_node} is the most congested area at {worst_score}/100 "
            f"({congestion_label(worst_score)}){trend_note}."
        ),
        "",
        "Priority 1:",
        f"  Action: Redirect incoming foot traffic away from {worst_node}.",
        f"  Estimated congestion reduction: ~{estimated_reduction}% (simulated estimate)",
        f"  Affected areas: {affected}",
    ]

    if incidents:
        top = incidents[0]  # already urgency-sorted by caller
        lines += [
            "",
            "Priority 2:",
            f"  Action: Dispatch nearest available staff to {top.location} - {top.description} ({top.severity}).",
            f"  Affected areas: {top.location}",
        ]
    else:
        lines += ["", "No active incidents reported - continue monitoring congestion trend."]

    return "\n".join(lines)


def get_organizer_recommendation(
    graph: nx.Graph,
    congestion_snapshot: CongestionSnapshot,
    incidents: list[Incident] | None = None,
    trends: Trends | None = None,
) -> str:
    """
    Main entry point used by app.py.

    Args:
        graph: the venue graph (used to find neighbors of hotspots for
            "affected areas" - only strictly needed in mock mode, but
            always passed for consistency)
        congestion_snapshot: dict like {"Gate_A": 82, "Section_2": 45, ...}
        incidents: optional list of core.incidents.Incident objects
        trends: optional dict like
            {"Gate_A": {"trend_pct": 18, "eta_ticks": 3}, ...}
            from CrowdSimulator.get_trend() / estimate_ticks_to_critical()

    Returns:
        A human-readable recommendation string - real LLM output if a key
        is configured, otherwise a clearly-labeled mock response.
    """
    incidents = sort_by_urgency(incidents) if incidents else []

    return complete(
        _build_prompt(congestion_snapshot, incidents, trends),
        model=MODEL,
        max_tokens=300,
        temperature=0.4,
        fallback=lambda: _mock_recommendation(graph, congestion_snapshot, incidents, trends),
    )


if __name__ == "__main__":
    # Quick manual check - run from project root with: python -m agents.organizer_agent
    from core.incidents import Incident
    from core.venue import build_venue_graph

    G = build_venue_graph()
    sample_congestion = {"Gate_A": 85, "Gate_B": 30, "Section_2": 60}
    sample_incidents = [Incident("Medical situation", "Gate_A", "HIGH")]
    sample_trends: Trends = {"Gate_A": {"trend_pct": 22, "eta_ticks": None}}
    print(get_organizer_recommendation(G, sample_congestion, sample_incidents, sample_trends))
