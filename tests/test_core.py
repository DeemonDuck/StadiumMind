"""
tests/test_core.py

Lightweight sanity tests for the non-LLM core logic - the venue graph,
crowd simulator, and congestion-aware routing. Deliberately does NOT test
the agents' LLM output (that's mocked/non-deterministic); it tests the
data and routing logic that everything else depends on.

Run with: pytest tests/test_core.py -v
(or just: python -m pytest)
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.crowd_sim import CrowdSimulator
from core.incidents import Incident, sort_by_urgency
from core.routing import congestion_weighted_path, explain_route_choice
from core.venue import build_venue_graph, get_nodes_by_type


def test_venue_graph_has_expected_nodes():
    G = build_venue_graph()
    assert "Gate_A" in G.nodes
    assert "Restroom_2" in G.nodes
    assert len(G.nodes) == 22  # expanded from the original 9-node MVP layout


def test_get_nodes_by_type_filters_correctly():
    G = build_venue_graph()
    amenities = get_nodes_by_type(G, "amenity")
    assert set(amenities) == {
        "Restroom_1", "Restroom_2", "Restroom_3",
        "FoodCourt_1", "FoodCourt_2", "FoodCourt_3",
    }


def test_crowd_simulator_starts_within_expected_range():
    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    for node in G.nodes:
        score = sim.get_congestion(node)
        assert 0 <= score <= 100


def test_tick_keeps_scores_in_bounds():
    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    for _ in range(50):  # stress-test many ticks
        sim.tick()
    for node in G.nodes:
        assert 0 <= sim.get_congestion(node) <= 100


def test_trigger_incident_increases_congestion_and_caps_at_100():
    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    before = sim.get_congestion("Gate_A")
    sim.trigger_incident("Gate_A", spike=200)  # deliberately huge spike
    after = sim.get_congestion("Gate_A")
    assert after > before
    assert after == 100  # must clamp, never exceed


def test_congestion_label_thresholds():
    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    sim.congestion["Gate_A"] = 10
    assert sim.get_congestion_label("Gate_A") == "low"
    sim.congestion["Gate_A"] = 40
    assert sim.get_congestion_label("Gate_A") == "moderate"
    sim.congestion["Gate_A"] = 60
    assert sim.get_congestion_label("Gate_A") == "high"
    sim.congestion["Gate_A"] = 90
    assert sim.get_congestion_label("Gate_A") == "critical"


def test_congestion_aware_path_reroutes_around_a_real_incident():
    """
    This is the core 'unique hook' of the whole project - proving that
    congestion actually changes the chosen route, not just the display.
    """
    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)

    plain_path = list(__import__("networkx").shortest_path(G, "Gate_A", "Restroom_2", weight="weight"))

    # Heavily congest a node that sits on the plain shortest path
    sim.trigger_incident("Section_1", spike=70)
    sim.trigger_incident("Restroom_1", spike=70)

    aware_path, _ = congestion_weighted_path(G, sim, "Gate_A", "Restroom_2")

    assert aware_path != plain_path, (
        "Congestion-aware path should differ from the plain shortest path "
        "once a node on it is heavily congested"
    )
    assert "Restroom_1" not in aware_path, "Should route around the congested Restroom_1 node"


def test_congestion_aware_path_matches_plain_path_when_uncongested():
    """When nothing is congested, the 'smart' path should behave like a normal shortest path."""
    import networkx as nx

    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    # Force everything to zero congestion for this test
    for node in sim.congestion:
        sim.congestion[node] = 0

    aware_path, _ = congestion_weighted_path(G, sim, "Gate_A", "Restroom_2")
    plain_path = nx.shortest_path(G, "Gate_A", "Restroom_2", weight="weight")

    assert aware_path == plain_path


def test_openai_client_can_be_constructed():
    """
    Regression test for a real deployment bug: with no GROQ_API_KEY set,
    mock mode means agents/organizer_agent.py and agents/fan_agent.py never
    actually import/construct the OpenAI client - so the test suite was
    blind to a real incompatibility between the pinned openai version and
    a newer httpx (older openai versions hard-code a 'proxies' argument
    that httpx 0.28+ removed, causing a TypeError at construction time,
    not just at the API-call stage). This surfaced on Streamlit Cloud,
    where a fresh install pulled the newest httpx against an old openai pin.

    Constructing the client (unlike calling .create()) makes no network
    call, so this can run in any CI environment - no key or network needed,
    just proof the client builds without raising.
    """
    from openai import OpenAI

    client = OpenAI(api_key="dummy-key-for-testing", base_url="https://api.groq.com/openai/v1")
    assert client is not None


def test_explain_route_choice_confirms_direct_route_when_uncongested():
    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    for node in sim.congestion:
        sim.congestion[node] = 0

    path, _ = congestion_weighted_path(G, sim, "Gate_A", "Restroom_2")
    explanation = explain_route_choice(G, sim, path)
    assert "most direct route" in explanation.lower()


def test_explain_route_choice_names_the_avoided_node():
    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    sim.trigger_incident("Section_1", spike=70)
    sim.trigger_incident("Restroom_1", spike=70)

    path, _ = congestion_weighted_path(G, sim, "Gate_A", "Restroom_2")
    explanation = explain_route_choice(G, sim, path)

    assert "Restroom_1" in explanation


def test_incident_severity_rank_orders_correctly():
    low = Incident("Spill", "FoodCourt_1", "LOW")
    high = Incident("Fight", "Section_4", "HIGH")
    assert high.severity_rank() > low.severity_rank()


def test_sort_by_urgency_puts_highest_severity_first():
    low = Incident("Spill", "FoodCourt_1", "LOW")
    critical = Incident("Fire", "Section_4", "CRITICAL")
    medium = Incident("Lost child", "Gate_A", "MEDIUM")

    ranked = sort_by_urgency([low, medium, critical])
    assert ranked[0] is critical
    assert ranked[-1] is low


def test_incident_unknown_severity_falls_back_to_medium_rank():
    weird = Incident("Something odd", "Gate_A", "UNKNOWN_LEVEL")
    medium = Incident("Normal thing", "Gate_B", "MEDIUM")
    assert weird.severity_rank() == medium.severity_rank()


def test_get_trend_is_zero_with_no_history_change():
    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    # Fresh simulator - history only has the initial single value, no change yet
    assert sim.get_trend("Gate_A") == 0


def test_get_trend_reflects_an_increase():
    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    sim.congestion["Gate_A"] = 20
    sim.history["Gate_A"].clear()
    sim.history["Gate_A"].append(20)
    sim.trigger_incident("Gate_A", spike=20)  # 20 -> 40, recorded in history
    assert sim.get_trend("Gate_A") == 100  # doubled = +100%


def test_estimate_ticks_to_critical_returns_zero_when_already_critical():
    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    sim.congestion["Gate_A"] = 80
    assert sim.estimate_ticks_to_critical("Gate_A") == 0


def test_estimate_ticks_to_critical_returns_none_when_flat_or_decreasing():
    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    sim.congestion["Gate_A"] = 30
    sim.history["Gate_A"].clear()
    sim.history["Gate_A"].append(30)
    sim.history["Gate_A"].append(30)  # no change - flat trend
    assert sim.estimate_ticks_to_critical("Gate_A") is None


if __name__ == "__main__":
    # Allows running directly with `python tests/test_core.py` without pytest installed
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
