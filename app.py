"""
app.py

StadiumMind's Streamlit dashboard - the single entry point tying everything
together. Two tabs, sharing one venue graph, one crowd simulator, and one
cached layout, used by BOTH tabs:

  - Organizer Dashboard: live visual congestion map + predictive trend
    metrics + structured incident log + "Ask Stadium Brain"
  - Fan Assistant: pick start/destination/language, see the chosen route
    highlighted on the same map, with an explanation of why it was chosen

AUTO-TICK NOTE: the live congestion panel runs inside an st.fragment, which
lets it auto-refresh on a timer WITHOUT rerunning the whole page - so the
incident report form below it never gets wiped out mid-typing.

Run with: streamlit run app.py
"""

import streamlit as st

from agents.fan_agent import get_fan_directions, get_transit_directions, translate_task_description
from agents.organizer_agent import GROQ_API_KEY, get_organizer_recommendation
from core.crowd_sim import CrowdSimulator
from core.graph_layout import compute_layout
from core.incidents import Incident, sort_by_urgency
from core.tasks import TASK_STATUSES, generate_tasks_from_state, sort_tasks_by_priority
from core.venue import build_venue_graph
from core.visualization import build_congestion_figure

st.set_page_config(page_title="StadiumMind", page_icon="🏟️", layout="wide")

# --- Shared state: one graph + one simulator + one cached layout + one
# incident log, used by BOTH tabs. This is intentional - it's what makes
# the "shared intelligence layer" story real instead of just a slide.
# st.session_state persists these across reruns within a single session.
if "graph" not in st.session_state:
    st.session_state.graph = build_venue_graph()
if "simulator" not in st.session_state:
    st.session_state.simulator = CrowdSimulator(st.session_state.graph, seed=42)
if "incidents" not in st.session_state:
    st.session_state.incidents = []
if "positions" not in st.session_state:
    # Computed once and reused - keeps the map visually stable instead of
    # re-laying-out (and jumping around) on every rerun.
    st.session_state.positions = compute_layout(st.session_state.graph)
if "volunteer_tasks" not in st.session_state:
    # {task_id: Task} - keyed by id (not a plain list) so refreshing the
    # board merges in new tasks without wiping out an existing
    # assignment/status for a task that's still open.
    st.session_state.volunteer_tasks = {}
if "task_translations" not in st.session_state:
    # {(task_id, language): translated_description} - cached so the
    # Volunteer & Staff Board's language selector (tab 3) doesn't re-call
    # the LLM for a task already translated on every rerun (Streamlit
    # reruns the whole script on every widget interaction, e.g. typing an
    # assignee name or changing a status).
    st.session_state.task_translations = {}
if "total_co2_saved_grams" not in st.session_state:
    # Session-level sustainability counter, updated each time a fan uses
    # the "Getting to the Stadium" transit comparison in the Fan Assistant
    # tab and a greener-than-driving option is recommended.
    st.session_state.total_co2_saved_grams = 0.0
if "total_green_trips" not in st.session_state:
    st.session_state.total_green_trips = 0

graph = st.session_state.graph
simulator = st.session_state.simulator
positions = st.session_state.positions

st.title("🏟️ StadiumMind")
_mode_note = (
    "Live AI mode - responses are generated in real time by Groq."
    if GROQ_API_KEY
    else "Running in mock mode until a real GROQ_API_KEY is configured "
         "(.env locally, or Secrets on Streamlit Cloud)."
)
st.caption(
    "One shared crowd-intelligence layer powering organizer decisions "
    f"and fan navigation. {_mode_note}"
)

tab1, tab2, tab3 = st.tabs(
    ["📊 Organizer Dashboard", "🧭 Fan Assistant", "🦺 Volunteer & Staff Board"]
)


# ----------------------------------------------------------------------
# TAB 1: Organizer Dashboard
# ----------------------------------------------------------------------
@st.fragment(run_every="3s")
def render_live_panel():
    """
    The auto-refreshing part of the dashboard: the map + trend metrics.
    Isolated in its own fragment so its timer-driven reruns never touch
    the incident form or anything else on the page - only this function's
    output refreshes automatically.
    """
    ctrl1, ctrl2, ctrl3 = st.columns([1.2, 1, 1])
    with ctrl1:
        st.checkbox("🔄 Auto-tick every 3s (for a live demo)", key="auto_tick")
    with ctrl2:
        if st.button("⏱️ Tick once", width="stretch"):
            simulator.tick()
    with ctrl3:
        if st.button("🚨 Spike Gate_A", width="stretch"):
            simulator.trigger_incident("Gate_A")

    if st.session_state.get("auto_tick"):
        simulator.tick()

    congestion = simulator.get_all()
    trends = {
        node: {
            "trend_pct": simulator.get_trend(node),
            "eta_ticks": simulator.estimate_ticks_to_critical(node),
        }
        for node in congestion
    }
    # Stash the latest snapshot so the (non-fragment) "Ask Stadium Brain"
    # button below can read current data without needing its own fragment.
    st.session_state["latest_congestion"] = congestion
    st.session_state["latest_trends"] = trends

    fig = build_congestion_figure(graph, simulator, positions)
    st.plotly_chart(fig, width="stretch", key="organizer_map", config={})
    st.caption("🟢 Low &nbsp;&nbsp; 🟡 Moderate &nbsp;&nbsp; 🟠 High &nbsp;&nbsp; 🔴 Critical", unsafe_allow_html=True)

    # ACCESSIBILITY: the map above is a Plotly canvas, which screen readers
    # generally can't parse meaningfully. This table has the exact same
    # data in a real HTML table Streamlit renders accessibly, so the
    # information isn't locked behind a visual-only chart.
    with st.expander("📋 View congestion data as a text table (screen-reader friendly)"):
        table_rows = [
            {
                "Location": node,
                "Congestion": f"{score}/100",
                "Status": simulator.get_congestion_label(node),
                "Trend": f"{trends[node]['trend_pct']}%",
            }
            for node, score in sorted(congestion.items(), key=lambda x: -x[1])
        ]
        st.dataframe(table_rows, width="stretch", hide_index=True)

    st.markdown("**Top congestion hotspots**")
    top_nodes = sorted(congestion.items(), key=lambda x: -x[1])[:4]
    cols = st.columns(len(top_nodes))
    for col, (node, score) in zip(cols, top_nodes, strict=True):
        trend_pct = trends[node]["trend_pct"]
        eta = trends[node]["eta_ticks"]
        with col:
            st.metric(node, f"{score}/100", delta=f"{trend_pct}%", delta_color="inverse")
            if eta == 0:
                st.caption("⚠️ Already critical")
            elif eta is not None:
                st.caption(f"~{eta} updates to critical")


with tab1:
    render_live_panel()

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Report an Incident")
        with st.form("incident_form", clear_on_submit=True):
            desc = st.text_input("Description", placeholder="e.g. Medical emergency")
            loc = st.selectbox("Location", sorted(graph.nodes))
            severity = st.selectbox("Severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"], index=1)
            submitted = st.form_submit_button("Log Incident")
            if submitted and desc:
                st.session_state.incidents.append(Incident(desc, loc, severity))

        if st.session_state.incidents:
            st.caption("Active incidents (most urgent first):")
            for inc in sort_by_urgency(st.session_state.incidents):
                st.text(str(inc))
            if st.button("Clear all incidents"):
                st.session_state.incidents = []

    with col2:
        st.subheader("Ask Stadium Brain")
        if st.button("Get Recommendation", type="primary"):
            congestion_snapshot = st.session_state.get("latest_congestion", simulator.get_all())
            trends = st.session_state.get("latest_trends", {})
            with st.spinner("Analyzing crowd situation..."):
                recommendation = get_organizer_recommendation(
                    graph, congestion_snapshot, st.session_state.incidents, trends
                )
            st.info(recommendation)

    st.divider()
    st.subheader("🌱 Sustainability Impact")
    _trips = st.session_state.total_green_trips
    _saved_kg = st.session_state.total_co2_saved_grams / 1000
    if _trips:
        st.metric(
            "Estimated CO₂ saved this session",
            f"{_saved_kg:.2f} kg",
            help=(
                "Sum of (driving-alone emissions - chosen transit emissions) for every "
                "'Getting to the Stadium' comparison run in the Fan Assistant tab, using "
                "the greenest recommended option each time. See core/transport.py."
            ),
        )
        st.caption(f"Across {_trips} fan transit comparison{'s' if _trips != 1 else ''} so far this session.")
    else:
        st.caption(
            "No transit comparisons yet - once fans use 'Getting to the Stadium' in the "
            "Fan Assistant tab, estimated CO₂ savings will show up here."
        )

# ----------------------------------------------------------------------
# TAB 2: Fan Assistant
# ----------------------------------------------------------------------
with tab2:
    fan_mode = st.radio(
        "What do you need help with?",
        ["🧭 Navigate inside the venue", "🚌 Getting to the stadium"],
        horizontal=True,
    )

    if fan_mode == "🧭 Navigate inside the venue":
        st.subheader("Where do you want to go?")

        all_nodes = sorted(graph.nodes)
        col1, col2, col3 = st.columns(3)
        with col1:
            start = st.selectbox("Your current location", all_nodes, index=all_nodes.index("Gate_A"))
        with col2:
            destination = st.selectbox(
                "Destination", all_nodes, index=all_nodes.index("Restroom_2")
            )
        with col3:
            language = st.selectbox("Preferred language", ["English", "Hindi", "Spanish", "French"])

        if st.button("Get Directions", type="primary"):
            if start == destination:
                st.warning("You're already there!")
            else:
                with st.spinner("Finding the best route..."):
                    directions, path, explanation = get_fan_directions(
                        graph, simulator, start, destination, language
                    )
                st.success(directions)
                st.caption(f"Why this route: {explanation}")

                # ACCESSIBILITY: the highlighted line on the map below conveys
                # the same route, but only visually - this numbered list is a
                # real text equivalent, not dependent on seeing/parsing the chart.
                st.markdown("**Route, step by step:**")
                st.markdown("\n".join(f"{i+1}. {stop}" for i, stop in enumerate(path)))

                fig = build_congestion_figure(graph, simulator, positions, highlight_path=path)
                st.plotly_chart(fig, width="stretch", key="fan_map", config={})
                st.caption(
                    "🟢 Low &nbsp;&nbsp; 🟡 Moderate &nbsp;&nbsp; 🟠 High &nbsp;&nbsp; "
                    "🔴 Critical &nbsp;&nbsp; 🔵 Chosen route",
                    unsafe_allow_html=True,
                )

    else:
        st.subheader("Getting to the Stadium")
        st.caption(
            "Compare transit options for reaching your gate, and see the sustainability "
            "impact of each choice (see core/transport.py for the mock transit + CO₂ data)."
        )

        transit_gates = ["Gate_A", "Gate_B", "Gate_C"]
        col1, col2 = st.columns(2)
        with col1:
            transit_gate = st.selectbox("Which gate are you headed to?", transit_gates)
        with col2:
            transit_language = st.selectbox(
                "Preferred language", ["English", "Hindi", "Spanish", "French"], key="transit_language"
            )

        if st.button("Compare Transit Options", type="primary"):
            with st.spinner("Comparing routes..."):
                summary_text, transit_options, recommended = get_transit_directions(
                    transit_gate, transit_language
                )
            st.success(summary_text)

            st.markdown("**Options compared:**")
            for opt in transit_options:
                tag = " 🌱 **Recommended**" if opt.mode == recommended.mode else ""
                st.markdown(f"- {opt.label} — ~{opt.total_minutes} min, ~{opt.co2_grams:.0f}g CO₂{tag}")

            # Update the session-level sustainability counter (shown in the
            # Organizer Dashboard tab) using the greenest option's real
            # savings vs. driving alone - always real data, independent of
            # mock/live AI mode.
            st.session_state.total_co2_saved_grams += recommended.co2_saved_vs_car_grams
            st.session_state.total_green_trips += 1
            st.caption(
                f"🌍 Choosing {recommended.mode} instead of driving alone saves an estimated "
                f"{recommended.co2_saved_vs_car_grams:.0f}g of CO₂ for this trip."
            )

# ----------------------------------------------------------------------
# TAB 3: Volunteer & Staff Board
# ----------------------------------------------------------------------
with tab3:
    st.subheader("Live Task Board")
    st.caption(
        "Assignable task cards generated from the same live congestion data and incident "
        "log the Organizer Agent reads - a dedicated view for volunteers and venue staff "
        "(see core/tasks.py)."
    )

    board_col1, board_col2 = st.columns([2, 1])
    with board_col1:
        if st.button("🔄 Refresh Tasks from Current Conditions"):
            fresh_tasks = generate_tasks_from_state(
                st.session_state.get("latest_congestion", simulator.get_all()),
                st.session_state.incidents,
            )
            added = 0
            for task in fresh_tasks:
                if task.id not in st.session_state.volunteer_tasks:
                    st.session_state.volunteer_tasks[task.id] = task
                    added += 1
            if added:
                st.toast(f"Added {added} new task(s) to the board.")
            else:
                st.toast("Board is already up to date - no new tasks.")
    with board_col2:
        # A FIFA World Cup deploys plenty of international volunteers -
        # reuses the exact same translate-with-mock-fallback pattern as
        # the Fan Assistant tab (agents/fan_agent.translate_task_description)
        # so multilingual support covers this persona too, not just fans.
        task_language = st.selectbox(
            "Task language",
            ["English", "Hindi", "Spanish", "French"],
            key="task_board_language",
        )

    tasks = sort_tasks_by_priority(list(st.session_state.volunteer_tasks.values()))

    if not tasks:
        st.info("No tasks yet - click 'Refresh Tasks from Current Conditions' to generate the board.")
    else:
        priority_badge = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
        for task in tasks:
            with st.container(border=True):
                card_col1, card_col2, card_col3 = st.columns([3, 1.2, 1.2])
                with card_col1:
                    badge = priority_badge.get(task.priority.upper(), "⚪")
                    st.markdown(f"{badge} **{task.description}**")
                    if task_language != "English":
                        cache_key = (task.id, task_language)
                        if cache_key not in st.session_state.task_translations:
                            st.session_state.task_translations[cache_key] = translate_task_description(
                                task.description, task_language
                            )
                        st.caption(f"🌐 {st.session_state.task_translations[cache_key]}")
                    st.caption(f"📍 {task.location} · priority: {task.priority}")
                with card_col2:
                    task.assigned_to = st.text_input(
                        "Assigned to",
                        value=task.assigned_to or "",
                        key=f"assignee_{task.id}",
                        placeholder="Volunteer name",
                    ) or None
                with card_col3:
                    task.status = st.selectbox(
                        "Status",
                        TASK_STATUSES,
                        index=TASK_STATUSES.index(task.status),
                        key=f"status_{task.id}",
                    )

        if st.button("🧹 Clear resolved tasks"):
            st.session_state.volunteer_tasks = {
                task_id: task
                for task_id, task in st.session_state.volunteer_tasks.items()
                if task.status != "RESOLVED"
            }
            st.rerun()
