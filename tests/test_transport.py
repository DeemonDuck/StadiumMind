"""
tests/test_transport.py

Tests for core/transport.py - the "getting to the stadium" transit options
and CO2/sustainability scoring. Pure data/logic, no LLM involved, so fully
deterministic.

Run with: pytest tests/test_transport.py -v
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.transport import (
    CO2_GRAMS_PER_KM,
    get_transit_options,
    recommend_greenest_option,
)


def test_known_gate_returns_metro_bus_shuttle_and_car():
    options = get_transit_options("Gate_A")
    modes = {opt.mode for opt in options}
    assert modes == {"metro", "bus", "shuttle", "car"}


def test_unknown_gate_falls_back_to_shuttle_and_car_only():
    options = get_transit_options("Some_Unrecognized_Gate")
    modes = {opt.mode for opt in options}
    assert modes == {"shuttle", "car"}


def test_car_has_zero_co2_saved_vs_itself():
    options = get_transit_options("Gate_A")
    car_option = next(opt for opt in options if opt.mode == "car")
    assert car_option.co2_saved_vs_car_grams == 0.0


def test_every_non_car_option_saves_co2_vs_car():
    """Every mode is cleaner than driving alone, given the rates in
    CO2_GRAMS_PER_KM - this should hold for any gate."""
    for gate in ("Gate_A", "Gate_B", "Gate_C"):
        options = get_transit_options(gate)
        for opt in options:
            if opt.mode == "car":
                continue
            assert opt.co2_saved_vs_car_grams > 0, f"{opt.mode} at {gate} should save CO2 vs driving"


def test_recommend_greenest_option_picks_lowest_co2():
    options = get_transit_options("Gate_A")
    recommended = recommend_greenest_option(options)
    assert recommended.co2_grams == min(opt.co2_grams for opt in options)


def test_recommend_greenest_option_is_metro_when_available():
    """Given the rate ordering (metro < shuttle < bus < car), metro should
    always be the recommended pick whenever a gate has one."""
    options = get_transit_options("Gate_B")
    recommended = recommend_greenest_option(options)
    assert recommended.mode == "metro"


def test_co2_rate_ordering_is_metro_lt_shuttle_lt_bus_lt_car():
    assert CO2_GRAMS_PER_KM["metro"] < CO2_GRAMS_PER_KM["shuttle"]
    assert CO2_GRAMS_PER_KM["shuttle"] < CO2_GRAMS_PER_KM["bus"]
    assert CO2_GRAMS_PER_KM["bus"] < CO2_GRAMS_PER_KM["car"]


def test_total_minutes_is_sum_of_component_times():
    options = get_transit_options("Gate_A")
    metro = next(opt for opt in options if opt.mode == "metro")
    # 6 min walk + 18 min ride, per GATE_TRANSIT_OPTIONS["Gate_A"]["metro"]
    assert metro.total_minutes == 24


def test_longer_distance_increases_co2_proportionally():
    short_trip = get_transit_options("Gate_A", distance_km=4.0)
    long_trip = get_transit_options("Gate_A", distance_km=8.0)
    short_car = next(opt for opt in short_trip if opt.mode == "car")
    long_car = next(opt for opt in long_trip if opt.mode == "car")
    assert long_car.co2_grams == short_car.co2_grams * 2


if __name__ == "__main__":
    # Allows running directly with `python tests/test_transport.py` without pytest installed
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
