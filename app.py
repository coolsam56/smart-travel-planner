from __future__ import annotations

import os
from datetime import date, timedelta

import streamlit as st
from dotenv import load_dotenv

from travel_planner import (
    TravelRequest,
    create_trip_plan,
    format_crew_error,
    generate_agent_summary,
)

load_dotenv()


st.set_page_config(page_title="Smart Travel Planner", page_icon="✈️", layout="wide")
st.markdown(
    """
    <style>
    .stApp { background: linear-gradient(145deg, #f4f8f6 0%, #edf3f8 100%); }
    .stApp, .stApp p, .stApp li, .stApp label, .stApp [data-testid="stMarkdownContainer"] {
      color: #172b4d;
    }
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {
      color: #123b45;
    }
    .stApp [data-testid="stMetricValue"], .stApp [data-testid="stMetricLabel"] {
      color: #123b45;
    }
    .stApp a { color: #075e73; }
    .stApp a:hover { color: #0b766e; }
    .block-container { max-width: 1180px; padding-top: 2.1rem; }
    .hero { padding: 1.6rem 1.9rem; border-radius: 20px; color: white;
      background: linear-gradient(115deg, #123b45, #197b72); margin-bottom: 1.2rem; }
    .hero h1 { margin: 0; font-size: 2.25rem; }
    .hero p, .hero h1 { color: #fff; }
    .hero p { margin: .55rem 0 0; opacity: .95; }
    .trip-card { padding: 1rem 1.2rem; background: #fff; color: #172b4d;
      border: 1px solid #d7e2e8;
      border-radius: 14px; margin: .45rem 0; }
    .trip-card strong { color: #123b45; }
    .muted { color: #475569; font-size: .9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
      <h1>✈️ Smart Travel Planner</h1>
      <p>Five specialist AI agents collaborate on a personalized, budget-aware itinerary.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("AI setup")
    providers = ["Ollama", "OpenRouter"]
    configured_provider = os.getenv("AI_PROVIDER", "Ollama")
    provider = st.selectbox(
        "LLM provider",
        providers,
        index=providers.index(configured_provider) if configured_provider in providers else 0,
    )
    if provider == "Ollama":
        model = st.text_input("Ollama model", value=os.getenv("OLLAMA_MODEL", "llama3.1"))
        ollama_url = st.text_input(
            "Ollama URL", value=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        )
        api_key = ""
        st.caption("Start Ollama locally and pull the selected model before planning.")
    else:
        model = st.text_input(
            "OpenRouter model",
            value=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free"),
        )
        api_key = st.text_input(
            "OpenRouter API key",
            value=os.getenv("OPENROUTER_API_KEY", ""),
            type="password",
        )
        ollama_url = "http://localhost:11434"
    st.divider()
    st.caption("All trip costs are estimated in USD. Prototype hotel and fare costs are mock estimates.")
    st.caption("Local model speed depends on your hardware; OpenRouter is an alternative for faster AI summaries.")

with st.form("trip_requirements"):
    st.subheader("Tell us about your trip")
    col_a, col_b = st.columns(2)
    with col_a:
        destination = st.text_input("Destination", placeholder="e.g. Kyoto, Japan")
        starting_location = st.text_input("Starting location", placeholder="e.g. Singapore")
        departure = st.date_input("Departure", value=date.today() + timedelta(days=30))
    with col_b:
        travelers = st.number_input("Travelers", min_value=1, max_value=20, value=2, step=1)
        budget = st.number_input(
            "Total budget (USD)", min_value=1.0, value=2500.0, step=100.0, format="%.2f"
        )
        return_date = st.date_input(
            "Return",
            value=max(date.today() + timedelta(days=34), departure + timedelta(days=1)),
            min_value=departure,
        )
    activities = st.multiselect(
        "Preferred activities",
        ["Sightseeing", "Shopping", "Adventure", "Relaxation", "Food"],
        default=["Sightseeing", "Food"],
    )
    submitted = st.form_submit_button("Create my travel plan", type="primary", use_container_width=True)

if submitted:
    try:
        request = TravelRequest(
            destination=destination.strip(),
            starting_location=starting_location.strip(),
            start_date=departure,
            end_date=return_date,
            budget=float(budget),
            activities=activities,
            travelers=int(travelers),
        )
        request.validate()
    except ValueError as exc:
        st.error(str(exc))
    else:
        with st.spinner(
            "Gathering destination, weather and route data, then calculating your itinerary…"
        ):
            try:
                plan = create_trip_plan(
                    request,
                    provider=provider,
                    model=model,
                    api_key=api_key,
                    ollama_url=ollama_url,
                    run_agents=False,
                )
            except Exception as exc:
                st.error(str(exc))
                st.info(
                    "Check that the selected LLM is available and that the public search, weather, "
                    "and routing services are reachable, then try again."
                )
                st.stop()
        st.session_state["travel_plan"] = plan

plan = st.session_state.get("travel_plan")
if plan:
    request = plan["request"]
    budget_result = plan["budget"]
    st.divider()
    st.subheader(f"{request.destination} · {request.duration_days} days")
    top = st.columns(4)
    top[0].metric("Trip dates", f"{request.start_date:%b %d} – {request.end_date:%b %d}")
    top[1].metric("Travelers", request.travelers)
    top[2].metric("Estimated total", f"${budget_result['total_usd']:,.2f}")
    top[3].metric("Budget remaining", f"${budget_result['remaining_usd']:,.2f}")
    if budget_result["within_budget"]:
        st.success(f"Estimated plan is within budget by ${budget_result['remaining_usd']:,.2f}.")
    else:
        st.error(
            f"Even the lowest-cost combination is about "
            f"${abs(budget_result['remaining_usd']):,.2f} over budget."
        )
    if plan["crew_error"]:
        st.warning(
            f"{plan['crew_error']} The researched details and deterministic itinerary are still "
            "available below; configure the selected LLM to enable the agent-generated summary."
        )

    itinerary_tab, options_tab, budget_tab, research_tab, agents_tab = st.tabs(
        ["Itinerary", "Stay & transport", "Budget", "Research & sources", "Agent collaboration"]
    )
    with itinerary_tab:
        st.caption("Suggested schedule; confirm opening hours and local conditions before departure.")
        for day in plan["schedule"]:
            st.markdown(
                f"""
                <div class="trip-card">
                  <strong>Day {day['day']} · {day['date']}</strong><br>
                  <span class="muted">Morning</span> {day['morning']}<br>
                  <span class="muted">Afternoon</span> {day['afternoon']}<br>
                  <span class="muted">Evening</span> {day['evening']}
                </div>
                """,
                unsafe_allow_html=True,
            )
        results = plan["research"].get("results", [])
        if results:
            st.markdown("**Recommended starting points**")
            for result in results:
                title = result["title"]
                st.markdown(f"- [{title}]({result['url']})" + (f" — {result['description']}" if result["description"] else ""))
    with options_tab:
        left, right = st.columns(2)
        with left:
            st.markdown("#### Accommodation")
            st.caption(f"Selected: **{budget_result['selected_hotel']}**")
            for option in plan["hotels"]:
                st.markdown(
                    f"- **{option['name']}** · ${option['nightly_rate_usd']}/room/night · "
                    f"{option['rooms']} room(s) · "
                    f"${option['estimated_total_usd']:,} total ({option['type']})"
                )
        with right:
            st.markdown("#### Transport")
            st.caption(f"Selected: **{budget_result['selected_transport']}**")
            for option in plan["transports"]:
                st.markdown(
                    f"- **{option['name']}** · ${option['estimated_total_usd']:,.2f} "
                    f"({option['type']})"
                )
            route = plan["route"]
            if route["status"] == "ok":
                st.caption(
                    f"OSRM driving estimate: {route['distance_km']} km, "
                    f"{route['driving_hours']} hours. This is not a flight route."
                )
            else:
                st.warning(route["message"])
    with budget_tab:
        st.markdown("#### Estimated cost breakdown")
        for label, key in [
            ("Accommodation", "hotel_usd"),
            ("Transport", "transport_usd"),
            ("Activities", "activities_usd"),
            ("Meals", "meals_usd"),
            ("Contingency", "contingency_usd"),
        ]:
            st.markdown(f"- {label}: **${budget_result[key]:,.2f}**")
        st.markdown(f"**Total: ${budget_result['total_usd']:,.2f} / ${request.budget:,.2f} budget**")
        st.caption("Cost assumptions are planning estimates, not quotes. Contingency is included.")
        if not budget_result["within_budget"]:
            st.markdown("#### Lower-cost combinations")
            for option in budget_result["alternative_options"]:
                st.markdown(
                    f"- {option['hotel']} + {option['transport']}: "
                    f"${option['total_usd']:,.2f}"
                    + (" (within budget)" if option["within_budget"] else "")
                )
    with research_tab:
        weather = plan["weather"]
        if weather["status"] == "ok":
            st.markdown(f"**Weather for {weather['location']}** — {weather['message']}")
            for item in weather["forecast"]:
                rain = item["precipitation_probability_percent"]
                st.markdown(
                    f"- {item['date']}: {item['low_c']}–{item['high_c']}°C; "
                    f"precipitation chance {rain}%"
                )
        else:
            st.warning(weather.get("message", "Weather data is unavailable."))
        st.markdown("#### Sources")
        for source in plan["source_list"]:
            if source["url"]:
                st.markdown(f"- [{source['name']}]({source['url']})")
            else:
                st.markdown(f"- {source['name']} (mock prototype estimates; no booking API)")
        if plan["warnings"]:
            st.markdown("#### Data lookup notes")
            for warning in plan["warnings"]:
                st.warning(warning)
    with agents_tab:
        st.markdown("#### Travel Coordinator's combined response")
        if plan["crew_pending"]:
            st.info(
                "Your researched itinerary and budget are ready. Run the CrewAI workflow here "
                "to generate the additional agent-written summary."
            )
            if st.button("Generate CrewAI agent summary", type="primary"):
                with st.spinner(
                    "The five CrewAI agents are working in sequence. This can take a few minutes…"
                ):
                    try:
                        plan["crew_notes"] = generate_agent_summary(
                            plan,
                            provider=provider,
                            model=model,
                            api_key=api_key,
                            ollama_url=ollama_url,
                        )
                    except Exception as exc:
                        plan["crew_error"] = (
                            "CrewAI could not complete the AI-generated summary: "
                            f"{format_crew_error(exc)}"
                        )
                        plan["warnings"].append(plan["crew_error"])
                        plan["crew_notes"] = (
                            "The CrewAI summary could not be generated. Your sourced itinerary and "
                            "budget are still available in the other tabs."
                        )
                    plan["crew_pending"] = False
                    st.rerun()
        else:
            st.write(plan["crew_notes"])
