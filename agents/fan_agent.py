"""
agents/fan_agent.py

The "navigation + multi-language" half of StadiumMind. Given a fan's
current location and destination, finds a congestion-aware route (via
core.routing) and asks an LLM to phrase it as short, friendly directions
in the fan's chosen language - explicitly referencing WHY that route was
chosen, not just what it is.

MOCK MODE:
If no GROQ_API_KEY is found, falls back to an untranslated template
response instead of crashing. The route and its explanation are always
REAL (routing/explanation logic doesn't need the LLM) - only the friendly
phrasing/translation is mocked. Once GROQ_API_KEY is set in .env, this
automatically switches over.
"""

import os
import streamlit as st
from dotenv import load_dotenv
from core.routing import congestion_weighted_path, explain_route_choice

load_dotenv()

# Local dev reads from .env via os.getenv. Streamlit Community Cloud
# doesn't deploy .env files - it injects secrets via st.secrets instead.
# Check both so the same code works in both environments.
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or st.secrets.get("GROQ_API_KEY")
MODEL = "llama-3.1-8b-instant"  # fast model - plenty for short directions/translation

_client = None
if GROQ_API_KEY and GROQ_API_KEY != "your_groq_api_key_here":
    from openai import OpenAI
    _client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")


def _build_prompt(path: list, distance: float, language: str, explanation: str) -> str:
    """Build the LLM prompt. Separate function so it can be tweaked/tested in isolation."""
    path_description = " -> ".join(path)
    return f"""A fan at a stadium wants directions to their destination.
The recommended route is:
{path_description}
Total approximate distance: {distance:.0f} meters.
Reason this specific route was chosen: {explanation}

Write these directions as 2-3 short, friendly, easy-to-follow sentences,
in {language}. Naturally work in why this route was chosen, based on the reason given - don't just say "avoids crowds" generically."""


def _mock_directions(path: list, distance: float, language: str, explanation: str) -> str:
    """
    PLACEHOLDER used only when no GROQ_API_KEY is configured.

    The route, distance, and explanation are always real - only the
    friendly phrasing and translation are mocked, since those genuinely
    need the LLM. Clearly labeled so it's never mistaken for real output.
    """
    path_description = " -> ".join(path)
    return (
        "[MOCK RESPONSE - add a real GROQ_API_KEY to .env for AI-written, translated directions]\n"
        f"Head this way: {path_description}. Approx {distance:.0f} meters.\n"
        f"Why this route: {explanation}\n"
        f"(Requested language: {language} - mock mode does not translate.)"
    )


def get_fan_directions(graph, simulator, start: str, destination: str, language: str = "English"):
    """
    Main entry point used by app.py.

    Args:
        graph: the venue graph
        simulator: a CrowdSimulator instance with live congestion data
        start: fan's current location (node name)
        destination: where the fan wants to go (node name)
        language: language to phrase the directions in

    Returns:
        (directions_text, path, explanation):
            - directions_text: human-readable directions (real or mock)
            - path: the raw list of node names, for display/debugging
            - explanation: plain-English reason the route was chosen
              (always real, computed independently of mock/LLM mode)
    """
    path, distance = congestion_weighted_path(graph, simulator, start, destination)
    explanation = explain_route_choice(graph, simulator, path)

    if _client is None:
        return _mock_directions(path, distance, language, explanation), path, explanation

    prompt = _build_prompt(path, distance, language, explanation)
    try:
        response = _client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.5,
        )
        return response.choices[0].message.content, path, explanation
    except Exception as e:
        return (
            f"[AI temporarily unavailable: {e}]\n" + _mock_directions(path, distance, language, explanation),
            path,
            explanation,
        )


if __name__ == "__main__":
    # Quick manual check - run from project root with: python -m agents.fan_agent
    from core.venue import build_venue_graph
    from core.crowd_sim import CrowdSimulator

    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    sim.trigger_incident("Section_1", spike=70)
    sim.trigger_incident("Restroom_1", spike=70)

    text, path, explanation = get_fan_directions(G, sim, "Gate_A", "Restroom_2", language="Hindi")
    print(text)
    print("Path:", path)
    print("Explanation:", explanation)