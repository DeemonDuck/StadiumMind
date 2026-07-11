"""
core/crowd_sim.py

Simulates real-time crowd density at each node of the venue graph.

WHY THIS EXISTS:
A real stadium deployment would plug in actual sensor/camera/ticket-scan data
here instead of random numbers. For the hackathon MVP, this class stands in
for that data feed so the rest of the system (agents, UI) can be built and
demoed without needing physical sensors.

Both agents read from this same simulator:
    - Organizer Agent reads congestion (and now trend/prediction) to
      recommend actions.
    - Fan Agent reads congestion to avoid crowded routes.

PREDICTION NOTE: each tick is treated as one simulated time-step (not a
real elapsed-time measurement). For demo narration we describe a tick as
"~1 minute", which is a documented simplifying assumption, not a real
sensor sampling rate.
"""

from __future__ import annotations  # allows `int | None` etc. on Python < 3.10

import random
from collections import deque


class CrowdSimulator:
    """
    Tracks a congestion score (0-100) for every node in the venue graph,
    plus a short rolling history per node used for trend/prediction.
    0 = empty, 100 = dangerously overcrowded.
    """

    HISTORY_LENGTH = 6  # how many past ticks to remember per node, for trend estimation

    def __init__(self, graph, seed: int | None = None):
        """
        Args:
            graph: the venue graph (from core.venue.build_venue_graph)
            seed: optional random seed, useful for reproducible demos
        """
        self.graph = graph
        if seed is not None:
            random.seed(seed)
        # Every location starts at a random low-to-moderate congestion level
        self.congestion = {node: random.randint(10, 30) for node in graph.nodes}
        # Rolling history per node - starts with just the initial value
        self.history = {
            node: deque([score], maxlen=self.HISTORY_LENGTH)
            for node, score in self.congestion.items()
        }

    def tick(self) -> None:
        """
        Advance the simulation by one time step.
        Each node's congestion randomly drifts, clamped to [0, 100], and
        the new value is recorded in that node's history.

        The drift range is slightly biased upward (-8 to +12) to mimic a
        stadium filling up over the course of an event, which makes for a
        more interesting live demo than pure random noise.
        """
        for node in self.congestion:
            drift = random.randint(-8, 12)
            self.congestion[node] = max(0, min(100, self.congestion[node] + drift))
            self.history[node].append(self.congestion[node])

    def trigger_incident(self, node: str, spike: int = 40) -> None:
        """
        Manually spike congestion at a specific node.
        Used to simulate a sudden crowd surge for demo purposes
        (e.g. "everyone rushes the exit after the match ends").

        Args:
            node: name of the node to spike (must exist in the graph)
            spike: how much to add to current congestion (default 40)
        """
        if node in self.congestion:
            self.congestion[node] = min(100, self.congestion[node] + spike)
            self.history[node].append(self.congestion[node])

    def get_congestion(self, node: str) -> int:
        """Return the current congestion score (0-100) for a single node."""
        return self.congestion.get(node, 0)

    def get_all(self) -> dict:
        """Return a snapshot of congestion for every node, as {node: score}."""
        return dict(self.congestion)

    def get_congestion_label(self, node: str) -> str:
        """
        Convert a numeric score into a human-readable label.
        Used both in the UI (color-coded metrics) and in LLM prompts,
        since "high" reads more naturally to a model than a raw number.
        """
        score = self.get_congestion(node)
        if score >= 75:
            return "critical"
        elif score >= 50:
            return "high"
        elif score >= 25:
            return "moderate"
        return "low"

    def get_trend(self, node: str) -> int:
        """
        Percentage change over the recorded history window (oldest vs
        newest recorded value). Positive = increasing, negative = decreasing.

        This is a simple synthetic trend, not a real forecasting model -
        it's meant to make the dashboard feel predictive rather than purely
        reactive, using the same data already being tracked.
        """
        hist = self.history.get(node)
        if not hist or len(hist) < 2:
            return 0
        oldest, newest = hist[0], hist[-1]
        if oldest == 0:
            return 100 if newest > 0 else 0
        return round(((newest - oldest) / oldest) * 100)

    def estimate_ticks_to_critical(self, node: str, critical_threshold: int = 75):
        """
        Linearly extrapolate the recent trend to estimate how many more
        ticks until this node crosses the critical threshold.

        Returns:
            0 if already at/above critical, an int estimate if trending
            upward, or None if flat/decreasing (no meaningful ETA).
        """
        current = self.get_congestion(node)
        if current >= critical_threshold:
            return 0

        hist = self.history.get(node)
        if not hist or len(hist) < 2:
            return None

        avg_step_per_tick = (hist[-1] - hist[0]) / (len(hist) - 1)
        if avg_step_per_tick <= 0:
            return None  # flat or decreasing - no ETA to critical

        remaining = critical_threshold - current
        return max(1, round(remaining / avg_step_per_tick))


if __name__ == "__main__":
    # Quick manual check: python core/crowd_sim.py
    from venue import build_venue_graph

    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    print("Initial congestion:", sim.get_all())

    for _ in range(4):
        sim.tick()
    print("After 4 ticks:", sim.get_all())
    print("Gate_A trend:", sim.get_trend("Gate_A"), "%")
    print("Gate_A ETA to critical:", sim.estimate_ticks_to_critical("Gate_A"))

    sim.trigger_incident("Gate_A")
    print("After incident at Gate_A:", sim.get_all())
    print("Gate_A trend after incident:", sim.get_trend("Gate_A"), "%")
    print("Gate_A ETA to critical after incident:", sim.estimate_ticks_to_critical("Gate_A"))
