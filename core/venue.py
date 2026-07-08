import networkx as nx

def build_venue_graph():
    G = nx.Graph()

    # Nodes: (name, type) — type helps agents reason later
    nodes = {
        "Gate_A": "gate", "Gate_B": "gate", "Gate_C": "gate",
        "Section_1": "section", "Section_2": "section", "Section_3": "section",
        "Restroom_1": "amenity", "Restroom_2": "amenity",
        "FoodCourt_1": "amenity"
    }
    for name, kind in nodes.items():
        G.add_node(name, type=kind)

    # Edges: (node1, node2, distance_in_meters)
    edges = [
        ("Gate_A", "Section_1", 40),
        ("Gate_B", "Section_2", 35),
        ("Gate_C", "Section_3", 50),
        ("Section_1", "Restroom_1", 20),
        ("Section_2", "Restroom_1", 25),
        ("Section_2", "FoodCourt_1", 30),
        ("Section_3", "Restroom_2", 20),
        ("Section_1", "Section_2", 60),
        ("Section_2", "Section_3", 60),
    ]
    for a, b, dist in edges:
        G.add_edge(a, b, weight=dist)

    return G

if __name__ == "__main__":
    G = build_venue_graph()
    print("Nodes:", G.nodes(data=True))
    print("Shortest path Gate_A -> Restroom_2:", 
          nx.shortest_path(G, "Gate_A", "Restroom_2", weight="weight"))