"""
agents/organizer_agent.py

The "real-time decision support" half of StadiumMind. Takes the current
crowd congestion snapshot (and any incident reports) and asks an LLM to
produce a prioritized, plain-English action plan for stadium staff.

MOCK MODE:
If no GROQ_API_KEY is found in the environment, this falls back to a
rule-based mock response instead of crashing or blocking development.
This lets you build and test the full app before wiring up a real key.
Once GROQ_API_KEY is set in .env, this automatically switches to calling
the real Groq API — no code changes needed anywhere else.
"""

import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = "llama-3.3-70b-versatile"  # stronger reasoning model - good fit for triage/prioritization

# Only create the API client if a real key is present. This means the
# `openai` package's config never has to run at all in mock mode.
_client = None
if GROQ_API_KEY and GROQ_API_KEY != "your_groq_api_key_here":
    from openai import OpenAI
    _client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")


def _build_prompt(congestion_snapshot: dict, incident_reports: list) -> str:
    """
    Build the LLM prompt from current state. Kept as its own function so
    the prompt can be tweaked or unit-tested independently of the API call.
    """
    return f"""You are an AI operations assistant for a live sports stadium.

Current live congestion levels (0-100 scale, higher = more crowded):
{congestion_snapshot}

Active incident reports from staff:
{incident_reports if incident_reports else "None reported"}

Based on this, provide:
1. A one-line summary of the overall crowd situation.
2. The single highest-priority action organizers should take right now.
3. Up to 2 additional recommended actions, ranked by priority.

Keep it concise and actionable - this will be read by staff during a live event, not analyzed later."""


def _mock_recommendation(congestion_snapshot: dict, incident_reports: list) -> str:
    """
    PLACEHOLDER used only when no GROQ_API_KEY is configured.

    Still reacts to the REAL congestion data (finds the actual most-crowded
    node) rather than returning a static string, so the demo looks sensible
    even in mock mode. Clearly labeled so it's never mistaken for real AI
    output. To replace: add a real key to .env - nothing else changes.
    """
    if not congestion_snapshot:
        return "[MOCK - no API key configured] No congestion data available yet."

    worst_node = max(congestion_snapshot, key=congestion_snapshot.get)
    worst_score = congestion_snapshot[worst_node]

    lines = [
        "[MOCK RESPONSE - add a real GROQ_API_KEY to .env for live AI reasoning]",
        f"Summary: {worst_node} is currently the most congested area at {worst_score}/100.",
        f"Priority action: Redirect incoming foot traffic away from {worst_node} and open an alternate route.",
    ]
    if incident_reports:
        lines.append(f"Incident noted: '{incident_reports[0]}' - dispatch nearest available staff.")
    else:
        lines.append("No active incidents reported - continue monitoring congestion trend.")

    return "\n".join(lines)


def get_organizer_recommendation(congestion_snapshot: dict, incident_reports: list | None = None) -> str:
    """
    Main entry point used by app.py.

    Args:
        congestion_snapshot: dict like {"Gate_A": 82, "Section_2": 45, ...}
        incident_reports: optional list of strings describing active incidents

    Returns:
        A human-readable recommendation string - real LLM output if a key
        is configured, otherwise a clearly-labeled mock response.
    """
    incident_reports = incident_reports or []

    if _client is None:
        return _mock_recommendation(congestion_snapshot, incident_reports)

    prompt = _build_prompt(congestion_snapshot, incident_reports)
    try:
        response = _client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.4,
        )
        return response.choices[0].message.content
    except Exception as e:
        # A rate limit or network blip shouldn't crash a live demo -
        # fall back to the mock so the show goes on.
        return f"[AI temporarily unavailable: {e}]\n" + _mock_recommendation(congestion_snapshot, incident_reports)


if __name__ == "__main__":
    # Quick manual check: python agents/organizer_agent.py
    sample_congestion = {"Gate_A": 85, "Gate_B": 30, "Section_2": 60}
    print(get_organizer_recommendation(sample_congestion, ["Medical situation near Gate_A"]))
