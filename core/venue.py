"""
core/venue.py

Defines the stadium as a graph: gates, sections, and amenities are nodes;
corridors connecting them are edges with a walking-distance weight.

This graph is the single shared data structure used by both agents:
- The Organizer Agent reasons about congestion AT nodes.
- The Fan Agent finds paths ALONG edges between nodes.

In a real deployment, this would be generated from an actual venue floor plan
(e.g. loaded from a JSON file or CAD export). For the hackathon MVP, it's
hardcoded here for one sample stadium layout.
"""

import networkx as nx


def build_venue_graph() -> nx.Graph:
    """
    Construct and return the stadium venue graph.

    Node types:
        "gate"    - entry/exit points
        "section" - seating areas (arranged as a ring/concourse loop)
        "amenity" - restrooms, food courts
        "medical" - medical/first-aid room
        "info"    - information desk
        "parking" - parking lot
        "vip"     - VIP lounge
        "exit"    - dedicated egress point

    Edge weight:
        "weight" - approximate walking distance in meters between two
                   directly connected locations.

    Layout notes:
        The 8 sections form a ring (Section_1 -> ... -> Section_8 -> back to
        Section_1) representing the walking concourse around the stadium.
        A ring topology matters for routing demos: blocking one section
        forces the pathfinder to go the long way around instead of just
        failing, which is what makes congestion-aware rerouting visible.

    Returns:
        networkx.Graph: an undirected graph representing the venue.
    """
    G = nx.Graph()

    # --- Nodes ---
    nodes = {
        # Gates (unchanged from the original MVP layout)
        "Gate_A": "gate",
        "Gate_B": "gate",
        "Gate_C": "gate",
        # Sections 1-3 unchanged; 4-8 added to complete the concourse ring
        "Section_1": "section",
        "Section_2": "section",
        "Section_3": "section",
        "Section_4": "section",
        "Section_5": "section",
        "Section_6": "section",
        "Section_7": "section",
        "Section_8": "section",
        # Amenities: original 2 restrooms + 1 food court, plus more spread around the ring
        "Restroom_1": "amenity",
        "Restroom_2": "amenity",
        "Restroom_3": "amenity",
        "FoodCourt_1": "amenity",
        "FoodCourt_2": "amenity",
        "FoodCourt_3": "amenity",
        # New facility types
        "Medical_Room": "medical",
        "Info_Desk": "info",
        "Parking_Lot": "parking",
        "VIP_Lounge": "vip",
        "Exit_Gate": "exit",
    }
    for name, kind in nodes.items():
        G.add_node(name, type=kind)

    # --- Edges: (node_a, node_b, distance_in_meters) ---
    edges = [
        # Original gate + first-3-sections layout (unchanged)
        ("Gate_A", "Section_1", 40),
        ("Gate_B", "Section_2", 35),
        ("Gate_C", "Section_3", 50),
        ("Section_1", "Restroom_1", 20),
        ("Section_2", "Restroom_1", 25),
        ("Section_2", "FoodCourt_1", 30),
        ("Section_3", "Restroom_2", 20),
        ("Section_1", "Section_2", 60),
        ("Section_2", "Section_3", 60),
        # Ring continues: Section_3 -> ... -> Section_8 -> back to Section_1
        ("Section_3", "Section_4", 55),
        ("Section_4", "Section_5", 55),
        ("Section_5", "Section_6", 55),
        ("Section_6", "Section_7", 55),
        ("Section_7", "Section_8", 55),
        ("Section_8", "Section_1", 55),  # closes the loop
        # More amenities spread around the new sections
        ("Section_6", "Restroom_3", 20),
        ("Section_5", "FoodCourt_2", 25),
        ("Section_8", "FoodCourt_3", 25),
        # Medical room reachable from two different points (redundant access)
        ("Section_4", "Medical_Room", 30),
        ("Section_7", "Medical_Room", 30),
        # Info desk sits right at the main gate
        ("Gate_A", "Info_Desk", 15),
        # Parking feeds all three gates. Weights are intentionally high -
        # this connects vehicles to gates, not a pedestrian shortcut between
        # gates, so it shouldn't be an attractive detour for fan routing.
        ("Parking_Lot", "Gate_A", 150),
        ("Parking_Lot", "Gate_B", 160),
        ("Parking_Lot", "Gate_C", 170),
        # VIP lounge: fast private access from Gate_B, plus a walk-in route via Section_2
        ("Gate_B", "VIP_Lounge", 50),
        ("Section_2", "VIP_Lounge", 20),
        # Dedicated exit on the far side of the ring
        ("Section_6", "Exit_Gate", 30),
        ("Section_8", "Exit_Gate", 30),
    ]
    for a, b, dist in edges:
        G.add_edge(a, b, weight=dist)

    return G


def get_nodes_by_type(graph: nx.Graph, node_type: str) -> list:
    """
    Return all node names of a given type ("gate", "section", or "amenity").
    Useful for populating dropdowns in the UI, e.g. "pick your destination amenity".
    """
    return [n for n, data in graph.nodes(data=True) if data.get("type") == node_type]


if __name__ == "__main__":
    # Quick manual sanity check when running this file directly:
    #   python core/venue.py
    G = build_venue_graph()
    print("All nodes:", list(G.nodes(data=True)))
    print("Amenities only:", get_nodes_by_type(G, "amenity"))
    print(
        "Shortest path Gate_A -> Restroom_2 (unweighted by crowd):",
        nx.shortest_path(G, "Gate_A", "Restroom_2", weight="weight"),
    )
