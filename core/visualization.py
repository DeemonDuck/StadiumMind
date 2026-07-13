"""
core/visualization.py

Builds the visual stadium map: a Plotly network graph where nodes are
color-coded by live congestion (using the same low/moderate/high/critical
bands as everywhere else in the app), and - when a fan route is being
shown - the chosen path is highlighted directly on the map.

Positions are computed once via core.graph_layout.compute_layout() and
passed in here, rather than recomputed - this keeps the map visually
stable across reruns instead of jumping around.

ACCESSIBILITY NOTE: congestion status is never conveyed by color alone.
Every node's visible label includes its numeric score (not just the
color), and app.py additionally renders a plain-text/table view of the
same data alongside the map - Plotly's canvas rendering isn't reliably
readable by screen readers, so the table is the real accessible
equivalent, not just a nice-to-have.
"""

from __future__ import annotations  # allows `list | None` etc. on Python < 3.10

import networkx as nx
import plotly.graph_objects as go

from core.crowd_sim import CrowdSimulator
from core.graph_layout import Positions

CONGESTION_COLORS: dict[str, str] = {
    "low": "#2ecc71",       # green
    "moderate": "#f1c40f",  # yellow
    "high": "#e67e22",      # orange
    "critical": "#e74c3c",  # red
}

# Slightly bigger markers for the more "structural" node types (gates,
# sections) so the ring shape reads clearly at a glance; amenities smaller.
NODE_TYPE_SIZE: dict[str, int] = {
    "gate": 22,
    "section": 26,
    "amenity": 16,
    "medical": 18,
    "info": 16,
    "parking": 16,
    "vip": 18,
    "exit": 18,
}


def build_congestion_figure(
    graph: nx.Graph,
    simulator: CrowdSimulator,
    positions: Positions,
    highlight_path: list[str] | None = None,
) -> go.Figure:
    """
    Args:
        graph: the venue graph
        simulator: CrowdSimulator with live congestion data
        positions: {node_name: (x, y)} from core.graph_layout.compute_layout
        highlight_path: optional list of node names (a fan's chosen route)
            to draw as a thick highlighted line on top of the base map

    Returns:
        A plotly Figure, ready for st.plotly_chart().
    """
    # --- Base edges (every corridor in the venue, drawn faint/gray) ---
    edge_x, edge_y = [], []
    for u, v in graph.edges():
        x0, y0 = positions[u]
        x1, y1 = positions[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    traces = [
        go.Scatter(
            x=edge_x, y=edge_y,
            mode="lines",
            line={"width": 1, "color": "#cccccc"},
            hoverinfo="none",
            showlegend=False,
        )
    ]

    # --- Highlighted route, if a fan path is being shown ---
    if highlight_path and len(highlight_path) > 1:
        hx, hy = [], []
        for a, b in zip(highlight_path, highlight_path[1:], strict=False):
            x0, y0 = positions[a]
            x1, y1 = positions[b]
            hx += [x0, x1, None]
            hy += [y0, y1, None]
        traces.append(go.Scatter(
            x=hx, y=hy,
            mode="lines",
            line={"width": 4, "color": "#2980b9"},
            hoverinfo="none",
            showlegend=False,
        ))

    # --- Nodes, colored by live congestion ---
    node_x, node_y, node_color, node_size, node_text, hover_text = [], [], [], [], [], []
    for node, data in graph.nodes(data=True):
        x, y = positions[node]
        node_x.append(x)
        node_y.append(y)
        score = simulator.get_congestion(node)
        label = simulator.get_congestion_label(node)
        node_color.append(CONGESTION_COLORS[label])
        node_size.append(NODE_TYPE_SIZE.get(data.get("type"), 18))
        # Score is shown in the visible label itself, not just on hover -
        # so it doesn't depend on color perception or a mouseover/tap.
        node_text.append(f"{node.replace('_', ' ')}<br>{score}")
        hover_text.append(f"{node} - {score}/100 ({label})")

    traces.append(
        go.Scatter(
            x=node_x, y=node_y,
            mode="markers+text",
            text=node_text,
            textposition="bottom center",
            textfont={"size": 9},
            hovertext=hover_text,
            hoverinfo="text",
            marker={"size": node_size, "color": node_color, "line": {"width": 1, "color": "#333333"}},
            showlegend=False,
        )
    )

    fig = go.Figure(data=traces)
    fig.update_layout(
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        xaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
        yaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
        height=520,
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


if __name__ == "__main__":
    # Quick manual check: python -m core.visualization
    # (writes an HTML file you can open to visually inspect the map - must
    # run as a module, not `python core/visualization.py` directly, since
    # the module-level `from core.crowd_sim import CrowdSimulator` import
    # above needs the core package resolvable - same convention already
    # used by agents/*.py and core/tasks.py)
    from core.graph_layout import compute_layout
    from core.routing import congestion_weighted_path
    from core.venue import build_venue_graph

    G = build_venue_graph()
    sim = CrowdSimulator(G, seed=1)
    sim.trigger_incident("Section_1", spike=70)
    sim.trigger_incident("Restroom_1", spike=70)

    positions = compute_layout(G)
    path, _ = congestion_weighted_path(G, sim, "Gate_A", "Restroom_2")

    fig = build_congestion_figure(G, sim, positions, highlight_path=path)
    fig.write_html("/tmp/stadiummind_map_preview.html")
    print("Wrote preview to /tmp/stadiummind_map_preview.html")
    print("Highlighted path:", path)
