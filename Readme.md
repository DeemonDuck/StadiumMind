# StadiumMind

**GenAI-enabled architecture for Smart Stadiums & Tournament Operations.**
Built for the PromptWars 2026 challenge track: dynamic crowd management, smart indoor navigation, real-time decision support, multi-language assistance.

## The Core Idea

Most solutions to this problem treat "crowd management" and "fan navigation" as two separate features. StadiumMind treats them as **one shared intelligence layer**:

- A single **venue graph** (gates, sections, amenities, corridors) models the stadium.
- A **crowd simulator** writes live congestion data onto that graph (standing in for real sensors/cameras).
- The **Organizer Agent** reads that congestion data + incident reports and gives staff a prioritized action plan (real-time decision support).
- The **Fan Agent** reads the *same* congestion data to route fans through the *least crowded* path to their destination, and answers in their preferred language (navigation + multi-language).

Same data, two agents, one story: the same intelligence that helps organizers make decisions is what quietly reroutes fans away from bottlenecks.

## Architecture

```
stadiummind/
├── core/
│   ├── venue.py         → static graph of the stadium (22 nodes: gates/sections/amenities/etc.)
│   ├── crowd_sim.py     → simulates live congestion + trend prediction per location
│   ├── routing.py       → congestion-aware shortest path + route explanation
│   ├── incidents.py     → structured Incident model + urgency sorting
│   ├── graph_layout.py  → 2D positions for visualizing the venue graph
│   └── visualization.py → Plotly congestion map + route highlighting
├── agents/
│   ├── organizer_agent.py  → LLM decision support (structured, trend-aware) for staff
│   └── fan_agent.py        → LLM navigation + translation + route explanation for fans
├── app.py              → Streamlit dashboard (Organizer tab + Fan tab, auto-refreshing map)
├── requirements.txt
├── .env.example
└── tests/
```

---

## Build Log

- [x] **Step 0** — Project skeleton, `.gitignore`, `requirements.txt`
- [x] **Step 1** — `core/venue.py`: static venue graph (gates, sections, amenities + corridor distances). Tested standalone with `python core/venue.py` — shortest path calculation confirmed working.
- [x] **Step 2** — `core/crowd_sim.py`: `CrowdSimulator` class tracking a 0-100 congestion score per node, with `tick()` (random drift), `trigger_incident()` (manual spike for demos), and `get_congestion_label()` (numeric → "low/moderate/high/critical" for LLM prompts and UI). Tested standalone — confirmed drift and incident spike both work correctly.
- [x] **Step 3** — `core/routing.py`: `congestion_weighted_path()` — the key piece connecting crowd data to navigation. Edge weights get inflated based on live congestion, so the fan pathfinder naturally avoids busy corridors. **Tuning note:** first tried a linear congestion penalty (`weight * (1 + congestion% * penalty)`) — needed an unrealistic penalty value (~12) before it actually changed the chosen path. Switched to a squared congestion ratio (`congestion% ^ 2`) so mild congestion barely matters but near-critical congestion is penalized hard — now a moderate default (penalty=3.0) reliably reroutes around a real incident. Verified: with Section_1 + Restroom_1 spiked, the path now goes around them (180m) instead of through them (165m plain shortest path).
- [x] **Step 4** — `agents/organizer_agent.py` and `agents/fan_agent.py`. **PLACEHOLDER NOTE:** neither has a real Groq key yet, so both run in **mock mode** — `_client` stays `None` when `GROQ_API_KEY` is missing/placeholder, and each agent falls back to a rule-based mock function (`_mock_recommendation` / `_mock_directions`) that still reacts to the real congestion/route data, clearly prefixed `[MOCK RESPONSE - ...]`. The real API call path is fully written and will activate automatically the moment a real key is added to `.env` — no code changes needed. Tested both standalone: organizer agent correctly identifies the worst-congested node from real data; fan agent correctly returns the real congestion-avoiding path with an untranslated placeholder phrasing.
- [x] **Step 5** — `app.py`: Streamlit dashboard with two tabs sharing one `graph` + one `simulator` via `st.session_state` (this is what makes "shared intelligence layer" real, not just a slide). Organizer tab: live per-node congestion metrics, tick/incident buttons, incident text box + "Ask Stadium Brain". Fan tab: start/destination/language selectors + routed, phrased directions. Verified end-to-end: actually launched `streamlit run app.py` headlessly — served HTTP 200 with no runtime errors.
- [x] **Step 6** — `.env.example` (documents the required key without ever holding a real value) and `tests/test_core.py` — 8 tests covering the venue graph, crowd simulator bounds/clamping, and the congestion-aware routing logic specifically (including a test that proves rerouting actually happens around a real incident, and one proving it behaves like a normal shortest path when nothing's congested). Deliberately does not test LLM output since that's mocked/non-deterministic. All 8 tests pass.

### Day 2 — feedback-driven upgrades

- [x] **Step 7** — Expanded `core/venue.py` from 9 to **22 nodes**: 3 gates, 8 sections arranged as a concourse ring (Section_1→...→Section_8→back to Section_1, so blocking one section forces a real detour), 6 amenities, plus Medical_Room, Info_Desk, Parking_Lot, VIP_Lounge, Exit_Gate. All original 9 nodes/edges kept unchanged so existing behavior didn't break. **Bug caught & fixed during testing:** initial Parking_Lot edge weights (60-80m) made it a shorter pedestrian "shortcut" between gates than the actual concourse — mathematically valid but unrealistic, since parking lots aren't walking corridors. Bumped those weights to 150-170m; reroute behavior is now realistic again. Verified by re-running `core/routing.py`.
- [x] **Step 8** — `explain_route_choice()` added to `core/routing.py`. Compares the congestion-aware path against the plain shortest path and names exactly which node(s) were avoided and their congestion score, e.g. *"Alternative route chosen to avoid: Restroom_1 (83/100, critical)."* Free to compute (just a graph diff, no extra simulation or LLM call). Wired into `agents/fan_agent.py` so both mock and real LLM output can reference the actual reason instead of a generic "avoids crowds" line.
- [x] **Step 9** — `core/incidents.py`: structured `Incident` dataclass (description, location, severity, timestamp) replacing plain incident strings, plus `sort_by_urgency()` (highest severity first, oldest first among ties). `agents/organizer_agent.py` rewritten to take a list of `Incident` objects and the venue graph, and produce **structured, priority-ranked output** (Priority 1 / Priority 2, with a simulated "estimated congestion reduction %" and real "affected areas" pulled from the worst node's actual graph neighbors) instead of loose sentences. `app.py`'s incident reporting is now a proper form (description/location/severity) instead of one text box, with an urgency-sorted incident log displayed live.
- [x] Test suite expanded to **13 tests** (added coverage for `explain_route_choice` and the `Incident`/`sort_by_urgency` logic). All passing.
- [x] **Step 10** — `core/graph_layout.py`: `compute_layout()` positions all 22 nodes for visualization (has zero effect on routing logic - purely cosmetic). The 8 sections are fixed on a circle to preserve the recognizable concourse-ring shape; everything else (gates, amenities, medical/parking/etc.) is placed automatically via `networkx.spring_layout` anchored around those fixed points, with a fixed seed so the map doesn't jump between reruns. Verified by printing all 22 computed positions - sections form a clean circle, satellites spread out sensibly.
- [x] **Step 11** — `core/visualization.py`: `build_congestion_figure()` - a Plotly network graph with nodes color-coded by the same 🟢/🟡/🟠/🔴 congestion bands used everywhere else, and (on the Fan tab) the chosen route highlighted as a thick blue line on top of the base map. Couldn't render a static PNG preview in this sandbox (no Chrome for kaleido), but that's irrelevant to the actual app - Streamlit renders Plotly directly in-browser via plotly.js, not kaleido.
- [x] **Step 12** — Predictive trends added to `core/crowd_sim.py`: each node now keeps a short rolling history (last 6 ticks), with `get_trend()` (% change over that window) and `estimate_ticks_to_critical()` (linear extrapolation to the critical threshold). **Documented assumption:** a tick is treated as one simulated time-step, described as "~1 minute" in demo narration - not a real elapsed-time measurement. Wired into `agents/organizer_agent.py` so both mock and real LLM recommendations can say things like *"Gate_A is up 22% recently"* instead of just a static number.
- [x] **Step 13** — `app.py` rebuilt around `@st.fragment(run_every="3s")` for the live congestion panel (map + trend metrics + manual tick/incident buttons). This was the key design decision for auto-refresh: because the timer only reruns that fragment, not the whole page, the incident report form sitting right below it is **never** wiped out mid-typing - solving the exact risk flagged yesterday, without needing a workaround toggle. Verified `st.fragment(run_every=...)` has been stable since Streamlit 1.37 (mid-2024), well before the pinned 1.40.0. Top-4 congestion metrics now show a trend arrow (`delta`, `delta_color="inverse"` since rising congestion is bad) plus an ETA-to-critical caption where applicable.
- [x] Fixed a `use_container_width` deprecation warning (Streamlit is phasing it out in favor of `width=`) caught during testing - updated all `st.button`/`st.plotly_chart` calls.
- [x] Test suite expanded to **17 tests** (added coverage for `get_trend` and `estimate_ticks_to_critical`). All passing. Also ran the actual button-click flows through Streamlit's `AppTest` (not just a syntax check) for both tabs - logging a structured incident + getting a recommendation, and getting fan directions with the map - to confirm no runtime exceptions in the real interaction paths, not just on initial load.


## Setup & Run

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up your API key (optional — app works in mock mode without it)
cp .env.example .env
# then edit .env and paste your real GROQ_API_KEY (free, no card - console.groq.com)

# 4. Run it
streamlit run app.py
```

Without a key in `.env`, both agents automatically run in **mock mode** (clearly labeled `[MOCK RESPONSE ...]` in the UI) — the full app, routing, and UI all work, just without live AI-generated phrasing. Add a real key any time and it switches over automatically, no code changes.

Run tests any time with:
```bash
python -m pytest tests/test_core.py -v
# or, without pytest installed:
python tests/test_core.py
```

---
