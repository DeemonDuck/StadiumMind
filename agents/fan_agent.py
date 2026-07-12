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

import networkx as nx
import streamlit as st
from dotenv import load_dotenv

from core.crowd_sim import CrowdSimulator
from core.routing import congestion_weighted_path, explain_route_choice
from core.transport import TransitOption, get_transit_options, recommend_greenest_option

load_dotenv()


def _get_groq_api_key() -> str | None:
    """
    Reads GROQ_API_KEY from either source - see organizer_agent.py's
    version of this same helper for the full explanation of why
    st.secrets.get() needs a try/except here rather than a plain `or`.
    """
    key = os.getenv("GROQ_API_KEY")
    if key:
        return key
    try:
        return st.secrets.get("GROQ_API_KEY")
    except FileNotFoundError:
        return None


# Local dev reads from .env via os.getenv. Streamlit Community Cloud
# doesn't deploy .env files - it injects secrets via st.secrets instead.
# Check both so the same code works in both environments.
GROQ_API_KEY = _get_groq_api_key()
MODEL = "llama-3.1-8b-instant"  # fast model - plenty for short directions/translation

_client = None
if GROQ_API_KEY and GROQ_API_KEY != "your_groq_api_key_here":
    from openai import OpenAI, OpenAIError
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
in {language}. Naturally work in why this route was chosen, based on the
reason given - don't just say "avoids crowds" generically."""


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


def get_fan_directions(
    graph: nx.Graph, simulator: CrowdSimulator, start: str, destination: str, language: str = "English"
) -> tuple[str, list[str], str]:
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
        content = response.choices[0].message.content
        if content is None:
            # See organizer_agent.py's identical check for why: the SDK
            # types this as str | None, so fall back to mock rather than
            # let None reach st.success() downstream.
            return _mock_directions(path, distance, language, explanation), path, explanation
        return content, path, explanation
    except OpenAIError as e:
        return (
            f"[AI temporarily unavailable: {e}]\n" + _mock_directions(path, distance, language, explanation),
            path,
            explanation,
        )


def _build_transit_prompt(gate: str, options: list, recommended: TransitOption, language: str) -> str:
    """Build the LLM prompt for the transit-comparison feature. Separate
    function so it can be tweaked/tested in isolation, same pattern as
    _build_prompt() above."""
    options_description = "\n".join(
        f"- {opt.label}: ~{opt.total_minutes} min total, ~{opt.co2_grams:.0f}g CO2 per person" for opt in options
    )
    gate_label = gate.replace("_", " ")
    return f"""A fan wants to know how to get TO the stadium, before entering {gate_label}.
Available transport options:
{options_description}

The greenest option is {recommended.label}, which saves about
{recommended.co2_saved_vs_car_grams:.0f}g of CO2 per person compared to driving alone.

Write 2-3 short, friendly sentences in {language} comparing these options and
recommending the greenest one. Naturally work in the actual CO2 savings number
as the reason - don't just say "it's eco-friendly" generically."""


def _mock_transit_summary(gate: str, options: list, recommended: TransitOption, language: str) -> str:
    """
    PLACEHOLDER used only when no GROQ_API_KEY is configured.

    The options, times, and CO2 numbers are always real (core.transport
    logic doesn't need the LLM) - only the friendly phrasing/translation
    is mocked, same approach as _mock_directions() above.
    """
    gate_label = gate.replace("_", " ")
    options_lines = "\n".join(
        f"  - {opt.label}: ~{opt.total_minutes} min, ~{opt.co2_grams:.0f}g CO2" for opt in options
    )
    return (
        "[MOCK RESPONSE - add a real GROQ_API_KEY to .env for AI-written, translated comparisons]\n"
        f"Options to reach {gate_label}:\n{options_lines}\n"
        f"Greenest pick: {recommended.label} "
        f"(saves ~{recommended.co2_saved_vs_car_grams:.0f}g CO2 vs driving alone).\n"
        f"(Requested language: {language} - mock mode does not translate.)"
    )


def get_transit_directions(gate: str, language: str = "English") -> tuple[str, list[TransitOption], TransitOption]:
    """
    Main entry point for the transportation + sustainability feature: this
    is the "how do I get to the stadium" mode of the Fan Assistant, distinct
    from get_fan_directions() above (which routes *inside* the venue).

    Args:
        gate: which gate the fan is headed to (e.g. "Gate_A")
        language: language to phrase the comparison in

    Returns:
        (summary_text, options, recommended):
            - summary_text: friendly comparison of transit options (real
              LLM output, or a mock placeholder - see MOCK MODE above)
            - options: the full list of core.transport.TransitOption, for
              display in the UI regardless of mock/live mode
            - recommended: the greenest TransitOption (always real,
              computed independently of mock/LLM mode) - used both for
              display and to update the app's running sustainability
              impact counter
    """
    options = get_transit_options(gate)
    recommended = recommend_greenest_option(options)

    if _client is None:
        return _mock_transit_summary(gate, options, recommended, language), options, recommended

    prompt = _build_transit_prompt(gate, options, recommended, language)
    try:
        response = _client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.5,
        )
        content = response.choices[0].message.content
        if content is None:
            return _mock_transit_summary(gate, options, recommended, language), options, recommended
        return content, options, recommended
    except OpenAIError as e:
        return (
            f"[AI temporarily unavailable: {e}]\n" + _mock_transit_summary(gate, options, recommended, language),
            options,
            recommended,
        )


def _build_task_translation_prompt(description: str, language: str) -> str:
    """Build the LLM prompt for translating a single volunteer/staff task
    description. Separate function so it can be tweaked/tested in
    isolation, same pattern as _build_prompt() and _build_transit_prompt()
    above."""
    return f"""Translate the following volunteer/staff task instruction into {language}.
Keep it short and clear - a volunteer reads this on a task board, not a
paragraph of prose. Preserve place/location names exactly as written
(e.g. "Gate_A", "Section_1") - do not translate them.

Task: {description}

Respond with ONLY the translated task text, nothing else."""


def _mock_task_translation(description: str, language: str) -> str:
    """
    PLACEHOLDER used only when no GROQ_API_KEY is configured.

    Same approach as _mock_directions()/_mock_transit_summary() above: the
    task text itself is always real - only the translation is mocked.
    """
    return f"[MOCK - {language} translation unavailable without a GROQ_API_KEY] {description}"


def translate_task_description(description: str, language: str = "English") -> str:
    """
    Translate a single Volunteer & Staff Board task description (see
    core/tasks.py) into the requested language.

    Reuses the exact same translate-with-mock-fallback pattern as
    get_fan_directions()/get_transit_directions() above, so the Volunteer &
    Staff Board's multilingual support (app.py, tab 3) is one more view
    over this agent rather than a second, separately-maintained translation
    path - ties the board into the same multilingual story as the Fan
    Assistant instead of leaving it English-only.

    Args:
        description: the English task description (from core.tasks.Task)
        language: language to translate into. "English" is a no-op and
            skips the LLM call entirely, since the source text already IS
            English - callers can call this unconditionally without
            special-casing the default language themselves.

    Returns:
        Translated text (real or mock, per MOCK MODE rules above), or the
        original description unchanged when language == "English".
    """
    if language == "English":
        return description

    if _client is None:
        return _mock_task_translation(description, language)

    prompt = _build_task_translation_prompt(description, language)
    try:
        response = _client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.3,
        )
        content = response.choices[0].message.content
        if content is None:
            return _mock_task_translation(description, language)
        return content.strip()
    except OpenAIError as e:
        return f"[AI temporarily unavailable: {e}]\n" + _mock_task_translation(description, language)


if __name__ == "__main__":
    # Quick manual check - run from project root with: python -m agents.fan_agent
    from core.crowd_sim import CrowdSimulator
    from core.venue import build_venue_graph

    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    sim.trigger_incident("Section_1", spike=70)
    sim.trigger_incident("Restroom_1", spike=70)

    text, path, explanation = get_fan_directions(G, sim, "Gate_A", "Restroom_2", language="Hindi")
    print(text)
    print("Path:", path)
    print("Explanation:", explanation)

    transit_text, transit_options, greenest = get_transit_directions("Gate_A", language="English")
    print("\n--- Transit comparison ---")
    print(transit_text)
    print("Recommended:", greenest.mode, f"(saves {greenest.co2_saved_vs_car_grams:.0f}g CO2)")

    print("\n--- Task translation (Volunteer & Staff Board) ---")
    print(translate_task_description("Redirect or assist foot traffic at Gate_A (82/100 congestion)", "Spanish"))
