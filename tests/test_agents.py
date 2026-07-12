"""
tests/test_agents.py

Closes a real Code Quality gap: agents/organizer_agent.py and
agents/fan_agent.py had zero test coverage before this, even though both
contain pure, deterministic helper functions (prompt-builders, mock
fallbacks, label formatting) that don't need a real API key or network
call to test.

Deliberately does NOT test actual LLM output (get_organizer_recommendation
/ get_fan_directions / get_transit_directions when a real client is
configured) - that's non-deterministic and environment-dependent. This
file tests everything around those calls: the prompt text they build, and
the mock responses returned when no GROQ_API_KEY is configured (which is
exactly the mode this test suite runs in, since no key is set in CI).

Run with: pytest tests/test_agents.py -v
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import agents.fan_agent as fan_agent
import agents.organizer_agent as organizer_agent
from core.incidents import Incident
from core.transport import get_transit_options, recommend_greenest_option
from core.venue import build_venue_graph

# ----------------------------------------------------------------------
# organizer_agent.py
# ----------------------------------------------------------------------

def test_organizer_congestion_label_thresholds():
    assert organizer_agent._congestion_label(10) == "low"
    assert organizer_agent._congestion_label(40) == "moderate"
    assert organizer_agent._congestion_label(60) == "high"
    assert organizer_agent._congestion_label(90) == "critical"


def test_organizer_format_incidents_reports_none_when_empty():
    assert organizer_agent._format_incidents([]) == "None reported"


def test_organizer_format_incidents_includes_each_incident_line():
    incidents = [Incident("Medical situation", "Gate_A", "HIGH")]
    formatted = organizer_agent._format_incidents(incidents)
    assert "Medical situation" in formatted
    assert "Gate_A" in formatted


def test_organizer_trend_phrase_empty_when_no_trend_data():
    assert organizer_agent._trend_phrase({}, "Gate_A") == ""
    assert organizer_agent._trend_phrase({"Gate_B": {"trend_pct": 20}}, "Gate_A") == ""


def test_organizer_trend_phrase_mentions_upward_trend():
    trends = {"Gate_A": {"trend_pct": 22, "eta_ticks": 3}}
    phrase = organizer_agent._trend_phrase(trends, "Gate_A")
    assert "up 22%" in phrase
    assert "3 more updates" in phrase


def test_organizer_trend_phrase_mentions_already_critical():
    trends = {"Gate_A": {"trend_pct": 10, "eta_ticks": 0}}
    phrase = organizer_agent._trend_phrase(trends, "Gate_A")
    assert "already at critical level" in phrase


def test_organizer_build_prompt_includes_congestion_and_incidents():
    congestion = {"Gate_A": 85}
    incidents = [Incident("Medical situation", "Gate_A", "HIGH")]
    prompt = organizer_agent._build_prompt(congestion, incidents, None)
    assert "Gate_A" in prompt
    assert "Medical situation" in prompt
    assert "Priority 1" in prompt


def test_organizer_mock_recommendation_names_the_worst_node():
    graph = build_venue_graph()
    congestion = {"Gate_A": 85, "Gate_B": 20}
    recommendation = organizer_agent._mock_recommendation(graph, congestion, [], None)
    assert "Gate_A" in recommendation
    assert "[MOCK RESPONSE" in recommendation


def test_organizer_mock_recommendation_includes_top_incident_as_priority_2():
    graph = build_venue_graph()
    congestion = {"Gate_A": 85}
    incidents = [Incident("Medical situation", "Gate_A", "HIGH")]
    recommendation = organizer_agent._mock_recommendation(graph, congestion, incidents, None)
    assert "Priority 2" in recommendation
    assert "Medical situation" in recommendation


def test_organizer_mock_recommendation_handles_empty_snapshot():
    recommendation = organizer_agent._mock_recommendation(build_venue_graph(), {}, [], None)
    assert "[MOCK" in recommendation


def test_get_organizer_recommendation_runs_in_mock_mode_without_a_key():
    """End-to-end through the public entry point - since no GROQ_API_KEY is
    set in this test environment, _client is None and this should return a
    clearly-labeled mock string rather than raising."""
    graph = build_venue_graph()
    result = organizer_agent.get_organizer_recommendation(graph, {"Gate_A": 85}, [], None)
    assert isinstance(result, str)
    assert len(result) > 0


# ----------------------------------------------------------------------
# fan_agent.py
# ----------------------------------------------------------------------

def test_fan_build_prompt_includes_path_and_language():
    prompt = fan_agent._build_prompt(
        ["Gate_A", "Section_1", "Restroom_1"], 60.0, "Hindi", "avoids a crowded corridor"
    )
    assert "Gate_A -> Section_1 -> Restroom_1" in prompt
    assert "Hindi" in prompt
    assert "avoids a crowded corridor" in prompt


def test_fan_mock_directions_includes_path_and_distance():
    directions = fan_agent._mock_directions(
        ["Gate_A", "Restroom_1"], 42.0, "English", "shortest available path"
    )
    assert "Gate_A -> Restroom_1" in directions
    assert "42" in directions
    assert "[MOCK RESPONSE" in directions


def test_get_fan_directions_runs_in_mock_mode_without_a_key():
    graph = build_venue_graph()
    from core.crowd_sim import CrowdSimulator

    sim = CrowdSimulator(graph, seed=1)
    text, path, explanation = fan_agent.get_fan_directions(graph, sim, "Gate_A", "Restroom_2", "English")
    assert isinstance(text, str) and len(text) > 0
    assert path[0] == "Gate_A"
    assert path[-1] == "Restroom_2"
    assert isinstance(explanation, str)


def test_fan_build_transit_prompt_mentions_recommended_option_and_co2():
    options = get_transit_options("Gate_A")
    recommended = recommend_greenest_option(options)
    prompt = fan_agent._build_transit_prompt("Gate_A", options, recommended, "French")
    assert "French" in prompt
    assert recommended.label in prompt
    assert "CO2" in prompt


def test_fan_mock_transit_summary_lists_every_option():
    options = get_transit_options("Gate_A")
    recommended = recommend_greenest_option(options)
    summary = fan_agent._mock_transit_summary("Gate_A", options, recommended, "English")
    for opt in options:
        assert opt.mode in summary or opt.label in summary
    assert "[MOCK RESPONSE" in summary


def test_get_transit_directions_runs_in_mock_mode_without_a_key():
    text, options, recommended = fan_agent.get_transit_directions("Gate_A", "English")
    assert isinstance(text, str) and len(text) > 0
    assert recommended in options
    assert recommended.mode == "metro"  # metro is greenest at every named gate


def test_translate_task_description_is_a_noop_for_english():
    """English is the source language of every Task.description - no LLM
    call needed, so callers can invoke this unconditionally."""
    description = "Redirect or assist foot traffic at Gate_A (82/100 congestion)"
    assert fan_agent.translate_task_description(description, "English") == description


def test_build_task_translation_prompt_includes_description_and_language():
    prompt = fan_agent._build_task_translation_prompt("Respond to: Medical situation", "French")
    assert "French" in prompt
    assert "Medical situation" in prompt


def test_mock_task_translation_includes_original_description():
    translation = fan_agent._mock_task_translation("Respond to: Medical situation", "Hindi")
    assert "Medical situation" in translation
    assert "[MOCK" in translation
    assert "Hindi" in translation


def test_translate_task_description_runs_in_mock_mode_without_a_key():
    description = "Redirect or assist foot traffic at Gate_A (82/100 congestion)"
    translated = fan_agent.translate_task_description(description, "Spanish")
    assert isinstance(translated, str) and len(translated) > 0
    assert "[MOCK" in translated
    assert description in translated


if __name__ == "__main__":
    # Allows running directly with `python tests/test_agents.py` without pytest installed
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
