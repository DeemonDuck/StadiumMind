"""
core/graph_layout.py

Computes 2D positions for the venue graph, used only for visualization -
has zero effect on routing or congestion logic, purely cosmetic.

DEPENDENCY NOTE: this originally used networkx's spring_layout() for the
non-section nodes. That turned out to genuinely require numpy internally
at call time (confirmed by testing - it raises ModuleNotFoundError if
numpy isn't importable, even though networkx itself declares zero hard
dependencies in its own package metadata). Since numpy was real install
weight for a purely cosmetic feature, this was rewritten as a small
hand-rolled BFS-radial layout using only the stdlib `math` module:

  1. The 8 sections are placed on a fixed ring (same as before).
  2. Every other node is placed by expanding outward in "waves": a node
     with at least one already-placed neighbor is positioned at the
     average of those neighbors' positions, pushed slightly further from
     the center, with a small deterministic jitter (derived from a hash
     of the node's name, not Python's randomized str hash) so siblings
     sharing a parent fan out instead of stacking exactly on top of
     each other.

This arguably fits the venue's actual structure better than a generic
spring layout anyway - it's explicitly "ring, with satellites radiating
outward from whatever they connect to," which is exactly the real layout.
"""

from __future__ import annotations

import hashlib
import math

import networkx as nx

# {node_name: (x, y)} - purely for drawing the map; nothing in the routing or
# congestion logic reads these.
Positions = dict[str, tuple[float, float]]


def _deterministic_fraction(s: str) -> float:
    """
    A stable 0.0-1.0 fraction derived from a string, used for jitter.
    Deliberately not using Python's built-in hash() - that's randomized
    per-process by default (for security reasons), which would make the
    layout jitter differently every time the app restarts. This uses a
    fixed hash function so the layout is fully deterministic across runs.
    """
    digest = hashlib.md5(s.encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def compute_layout(graph: nx.Graph) -> Positions:
    """
    Args:
        graph: the venue graph

    Returns:
        {node_name: (x, y)} - fully deterministic, so the map doesn't
        visually jump around between reruns, sessions, or app restarts.
    """
    positions: Positions = {}

    # --- Step 1: place the 8 sections on a fixed ring ---
    sections = [n for n, d in graph.nodes(data=True) if d.get("type") == "section"]
    sections.sort(key=lambda n: int(n.split("_")[1]))
    n = len(sections)
    for i, node in enumerate(sections):
        angle = 2 * math.pi * i / n
        positions[node] = (math.cos(angle), math.sin(angle))

    # --- Step 2: expand outward in waves for everything else ---
    remaining = set(graph.nodes) - set(positions)
    radius_step = 0.45  # how far outward each new wave of nodes sits

    while remaining:
        progressed = False
        for node in sorted(remaining):  # sorted so iteration order is deterministic
            placed_neighbors = [nb for nb in graph.neighbors(node) if nb in positions]
            if not placed_neighbors:
                continue

            avg_x = sum(positions[nb][0] for nb in placed_neighbors) / len(placed_neighbors)
            avg_y = sum(positions[nb][1] for nb in placed_neighbors) / len(placed_neighbors)

            # Push outward from the center along the direction of the average position
            dist = math.hypot(avg_x, avg_y) or 1.0
            direction_x, direction_y = avg_x / dist, avg_y / dist

            # Small deterministic rotation so siblings of the same parent
            # fan out around it instead of overlapping exactly
            jitter_angle = (_deterministic_fraction(node) - 0.5) * 0.6  # radians
            jx = direction_x * math.cos(jitter_angle) - direction_y * math.sin(jitter_angle)
            jy = direction_x * math.sin(jitter_angle) + direction_y * math.cos(jitter_angle)

            positions[node] = (avg_x + jx * radius_step, avg_y + jy * radius_step)
            remaining.discard(node)
            progressed = True

        if not progressed:
            # Safety net for any node with no path to an already-placed
            # node (shouldn't happen in a connected graph) - drop it near
            # the center rather than looping forever.
            for node in remaining:
                positions[node] = (0.0, 0.0)
            break

    return positions


if __name__ == "__main__":
    # Quick manual check: python core/graph_layout.py
    from venue import build_venue_graph

    G = build_venue_graph()
    positions = compute_layout(G)
    for node, (x, y) in positions.items():
        print(f"{node}: ({x:.2f}, {y:.2f})")
