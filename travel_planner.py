from __future__ import annotations

import json
import html
import math
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import requests


USER_AGENT = "SmartTravelPlanner/1.0"
REQUEST_TIMEOUT = 15


@dataclass(frozen=True)
class TravelRequest:
    destination: str
    starting_location: str
    start_date: date
    end_date: date
    budget: float
    activities: list[str]
    travelers: int = 2

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def nights(self) -> int:
        return max(0, self.duration_days - 1)

    def validate(self) -> None:
        if not self.destination.strip():
            raise ValueError("Enter a travel destination.")
        if not self.starting_location.strip():
            raise ValueError("Enter a starting location.")
        if self.end_date < self.start_date:
            raise ValueError("The return date must be on or after the departure date.")
        if self.budget <= 0:
            raise ValueError("The total budget must be greater than zero.")
        if self.travelers < 1:
            raise ValueError("At least one traveler is required.")
        if not self.activities:
            raise ValueError("Choose at least one preferred activity.")


def _get_json(url: str, *, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return response.json()


def search_destination(destination: str, activities: list[str]) -> dict[str, Any]:
    """Search Wikipedia's full-text API for activity-specific destination ideas."""
    activity_terms = {
        "sightseeing": "attractions",
        "shopping": "shopping",
        "adventure": "hiking",
        "relaxation": "parks",
        "food": "cuisine",
    }
    topics = list(
        dict.fromkeys(activity_terms.get(activity.lower(), "attractions") for activity in activities)
    ) or ["attractions"]
    results: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for topic in topics[:3]:
        query = f"{destination} {topic}"
        payload = _get_json(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 5,
                "srnamespace": 0,
                "srprop": "snippet",
                "format": "json",
            },
        )
        for item in payload.get("query", {}).get("search", []):
            title = item.get("title", "").strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            snippet = html.unescape(re.sub(r"<[^>]+>", "", item.get("snippet", ""))).strip()
            results.append(
                {
                    "title": title,
                    "description": snippet,
                    "url": f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                }
            )
            if len(results) == 8:
                break
        if len(results) == 8:
            break
    return {
        "status": "ok" if results else "no_results",
        "query": f"{destination}: {', '.join(topics[:3])}",
        "results": results,
        "source": "Wikipedia Search API",
        "source_url": "https://www.mediawiki.org/wiki/API:Search",
    }


def _geocode(place: str) -> dict[str, Any]:
    results = _get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": place, "count": 1, "language": "en", "format": "json"},
    ).get("results", [])
    if not results:
        raise ValueError(f"Could not find coordinates for “{place}”.")
    result = results[0]
    return {
        "name": ", ".join(
            part for part in (result.get("name"), result.get("admin1"), result.get("country")) if part
        ),
        "latitude": result["latitude"],
        "longitude": result["longitude"],
    }


def get_weather(destination: str, start_date: date, end_date: date) -> dict[str, Any]:
    """Get a daily forecast when the dates fall within Open-Meteo's forecast window."""
    today = date.today()
    latest = today + timedelta(days=15)
    if start_date > latest or end_date < today:
        return {
            "status": "unavailable",
            "message": f"Forecasts are only available for current dates through {latest.isoformat()}.",
            "source": "Open-Meteo",
            "source_url": "https://open-meteo.com/en/docs",
        }
    forecast_start = max(start_date, today)
    forecast_end = min(end_date, latest)
    location = _geocode(destination)
    payload = _get_json(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "start_date": forecast_start.isoformat(),
            "end_date": forecast_end.isoformat(),
        },
    )
    daily = payload.get("daily", {})
    forecast = [
        {
            "date": day,
            "weather_code": daily.get("weather_code", [])[index],
            "high_c": daily.get("temperature_2m_max", [])[index],
            "low_c": daily.get("temperature_2m_min", [])[index],
            "precipitation_probability_percent": daily.get(
                "precipitation_probability_max", []
            )[index],
        }
        for index, day in enumerate(daily.get("time", []))
    ]
    return {
        "status": "ok",
        "location": location["name"],
        "forecast": forecast,
        "message": (
            "Forecast covers the trip dates."
            if forecast_start == start_date and forecast_end == end_date
            else f"Forecast is partial; available dates: {forecast_start} through {forecast_end}."
        ),
        "source": "Open-Meteo",
        "source_url": "https://open-meteo.com/en/docs",
    }


def get_route(starting_location: str, destination: str) -> dict[str, Any]:
    """Estimate a driving route using OpenStreetMap geocoding and OSRM."""
    origin = _geocode(starting_location)
    time.sleep(1)
    target = _geocode(destination)
    route = _get_json(
        "https://router.project-osrm.org/route/v1/driving/"
        f"{origin['longitude']},{origin['latitude']};"
        f"{target['longitude']},{target['latitude']}",
        params={"overview": "false", "alternatives": "false"},
    )
    if route.get("code") != "Ok" or not route.get("routes"):
        raise ValueError(f"Routing service returned no route ({route.get('code', 'unknown error')}).")
    first = route["routes"][0]
    return {
        "status": "ok",
        "origin": origin["name"],
        "destination": target["name"],
        "distance_km": round(first["distance"] / 1000, 1),
        "driving_hours": round(first["duration"] / 3600, 1),
        "source": "OpenStreetMap Nominatim and OSRM",
        "source_url": "https://project-osrm.org/",
    }


def get_mock_hotel_options(destination: str, nights: int, travelers: int = 2) -> list[dict[str, Any]]:
    """Return explicitly labeled prototype hotel estimates (not live availability)."""
    rooms = math.ceil(travelers / 2)
    rates = [
        ("Value guesthouse", 55),
        ("Comfort hotel", 110),
        ("Premium hotel", 210),
    ]
    return [
        {
            "name": name,
            "destination": destination,
            "nightly_rate_usd": rate,
            "estimated_total_usd": rate * nights * rooms,
            "nights": nights,
            "rooms": rooms,
            "type": "mock planning estimate — not a live quote or booking",
        }
        for name, rate in rates
    ]


def get_transport_options(distance_km: float | None, travelers: int) -> list[dict[str, Any]]:
    """Estimate transport costs; these are allowances, not carrier availability or quotes."""
    distance = distance_km if distance_km and distance_km > 0 else None
    if distance is None:
        options = [
            ("Flexible transport allowance", 250.0 * travelers, "Distance unavailable; provisional allowance"),
            ("Budget transport allowance", 160.0 * travelers, "Distance unavailable; provisional allowance"),
        ]
    else:
        options = [
            ("Flight allowance", (95 + distance * 0.12) * travelers, "Distance-based mock estimate"),
            ("Rail allowance", (35 + distance * 0.065) * travelers, "Distance-based mock estimate"),
            ("Bus allowance", (20 + distance * 0.04) * travelers, "Distance-based mock estimate"),
        ]
    return sorted([
        {
            "name": name,
            "estimated_total_usd": round(cost, 2),
            "type": f"mock estimate — {basis}; not a live fare",
        }
        for name, cost, basis in options
    ], key=lambda option: option["estimated_total_usd"])


def calculate_trip_budget(
    *,
    nights: int,
    travelers: int,
    budget: float,
    hotel_nightly_rate: float,
    transport_total: float,
    activities_daily_per_person: float = 25.0,
    meals_daily_per_person: float = 45.0,
    contingency_percent: float = 10.0,
) -> dict[str, Any]:
    """Calculate a transparent trip estimate using the supplied per-trip rates."""
    rooms = math.ceil(travelers / 2)
    hotel = nights * hotel_nightly_rate * rooms
    activities = travelers * (nights + 1) * activities_daily_per_person
    meals = travelers * (nights + 1) * meals_daily_per_person
    subtotal = hotel + transport_total + activities + meals
    contingency = subtotal * contingency_percent / 100
    total = subtotal + contingency
    return {
        "budget_usd": round(budget, 2),
        "hotel_usd": round(hotel, 2),
        "transport_usd": round(transport_total, 2),
        "activities_usd": round(activities, 2),
        "meals_usd": round(meals, 2),
        "contingency_percent": contingency_percent,
        "contingency_usd": round(contingency, 2),
        "total_usd": round(total, 2),
        "remaining_usd": round(budget - total, 2),
        "within_budget": total <= budget,
        "rooms": rooms,
        "travelers": travelers,
    }


def build_day_schedule(start_date: date, duration_days: int, activities: list[str]) -> list[dict[str, Any]]:
    """Create a date-safe daily schedule outline, rotating selected activity interests."""
    ideas = {
        "sightseeing": "Visit a major landmark and a nearby cultural site",
        "shopping": "Explore a local market or shopping district",
        "adventure": "Plan an outdoor or active experience",
        "relaxation": "Keep time open for a relaxed local experience",
        "food": "Try a local food market or regional specialty",
    }
    selected = [activity.lower() for activity in activities]
    schedule = []
    for offset in range(duration_days):
        day_date = start_date + timedelta(days=offset)
        interest = selected[offset % len(selected)]
        schedule.append(
            {
                "day": offset + 1,
                "date": day_date.isoformat(),
                "morning": ideas.get(interest, f"Explore an experience related to {interest}"),
                "afternoon": ideas.get(selected[(offset + 1) % len(selected)], "Explore the local area"),
                "evening": "Enjoy dinner and leave time to rest",
            }
        )
    return schedule


def _crew_tools(
    request: TravelRequest,
    research: dict[str, Any],
    weather: dict[str, Any],
    hotels: list[dict[str, Any]],
    transports: list[dict[str, Any]],
    route: dict[str, Any],
) -> tuple[list[Any], list[Any], list[Any], list[Any]]:
    from crewai.tools import tool

    @tool("Destination search")
    def destination_search_tool(query: str) -> str:
        """Provide the destination research gathered from the public Wikipedia Search API."""
        return json.dumps(research, ensure_ascii=False)

    @tool("Destination weather")
    def weather_tool(query: str) -> str:
        """Retrieve a date-bounded weather forecast using Open-Meteo."""
        return json.dumps(weather, ensure_ascii=False)

    @tool("Hotel options")
    def hotel_options_tool(destination: str) -> str:
        """Return clearly labeled mock hotel planning estimates; no booking API is configured."""
        return json.dumps(hotels, ensure_ascii=False)

    @tool("Transport and route options")
    def transport_tool(query: str) -> str:
        """Return route evidence and explicitly labeled mock transport price allowances."""
        return json.dumps({"route": route, "options": transports}, ensure_ascii=False)

    @tool("Trip expense calculator")
    def trip_expense_calculator(
        hotel_nightly_rate: float,
        transport_total: float,
        activities_daily_per_person: float = 25.0,
        meals_daily_per_person: float = 45.0,
    ) -> str:
        """Calculate total trip costs and compare them with the customer's budget in USD."""
        return json.dumps(
            calculate_trip_budget(
                nights=request.nights,
                travelers=request.travelers,
                budget=request.budget,
                hotel_nightly_rate=hotel_nightly_rate,
                transport_total=transport_total,
                activities_daily_per_person=activities_daily_per_person,
                meals_daily_per_person=meals_daily_per_person,
            )
        )

    @tool("Date and schedule utility")
    def date_schedule_tool() -> str:
        """Build one correctly dated itinerary outline for every trip day."""
        return json.dumps(
            build_day_schedule(request.start_date, request.duration_days, request.activities),
            ensure_ascii=False,
        )

    return (
        [destination_search_tool, weather_tool],
        [hotel_options_tool, transport_tool],
        [trip_expense_calculator],
        [date_schedule_tool],
    )


def _build_llm(provider: str, model: str, api_key: str, ollama_url: str) -> Any:
    from crewai import LLM

    settings = {"temperature": 0.2, "timeout": 120, "max_tokens": 256}
    if provider == "OpenRouter":
        if not api_key.strip():
            raise ValueError("An OpenRouter API key is required when OpenRouter is selected.")
        if not model.startswith("openrouter/"):
            model = f"openrouter/{model}"
        return LLM(model=model, api_key=api_key.strip(), **settings)
    if provider == "Ollama":
        if not model.strip():
            raise ValueError("Enter an Ollama model name, such as llama3.1.")
        return LLM(
            model=f"ollama/{model.strip().removeprefix('ollama/')}",
            base_url=ollama_url.strip().rstrip("/"),
            **settings,
        )
    raise ValueError(f"Unsupported LLM provider: {provider}")


def run_agent_crew(
    request: TravelRequest,
    research: dict[str, Any],
    weather: dict[str, Any],
    hotels: list[dict[str, Any]],
    transports: list[dict[str, Any]],
    route: dict[str, Any],
    budget_result: dict[str, Any],
    provider: str,
    model: str,
    api_key: str = "",
    ollama_url: str = "http://localhost:11434",
) -> str:
    from crewai import Agent, Crew, Process, Task

    llm = _build_llm(provider, model, api_key, ollama_url)
    research_tools, stay_tools, budget_tools, schedule_tools = _crew_tools(
        request, research, weather, hotels, transports, route
    )

    coordinator = Agent(
        role="Travel Coordinator",
        goal="Translate customer requirements into a coordinated, feasible and personalized trip plan.",
        backstory="You are an experienced travel operations lead who delegates work and checks every handoff.",
        llm=llm,
        verbose=False,
        max_iter=2,
        max_retry_limit=0,
        max_execution_time=120,
    )
    destination_agent = Agent(
        role="Destination Research Agent",
        goal="Find destination-specific attractions and travel information grounded in cited sources.",
        backstory="You are a careful destination researcher who distinguishes verified information from suggestions.",
        tools=research_tools,
        llm=llm,
        verbose=False,
        max_iter=2,
        max_retry_limit=0,
        max_execution_time=120,
    )
    hotel_transport_agent = Agent(
        role="Hotel and Transport Agent",
        goal="Compare accommodation and transport options and clearly label estimates versus live quotes.",
        backstory="You plan practical stays and transport without inventing availability or bookings.",
        tools=stay_tools,
        llm=llm,
        verbose=False,
        max_iter=2,
        max_retry_limit=0,
        max_execution_time=120,
    )
    budget_agent = Agent(
        role="Budget Analyst",
        goal="Calculate a transparent full-trip estimate and propose lower-cost choices when necessary.",
        backstory="You are a detail-oriented analyst; use the calculator and never hide estimates or exclusions.",
        tools=budget_tools,
        llm=llm,
        max_iter=2,
        max_retry_limit=0,
        max_execution_time=120,
    )
    itinerary_agent = Agent(
        role="Itinerary Planner",
        goal="Build a realistic day-by-day schedule aligned with interests, dates, weather and budget.",
        backstory="You design balanced itineraries with sensible pacing and date-aware activities.",
        tools=schedule_tools,
        llm=llm,
        verbose=False,
        max_iter=2,
        max_retry_limit=0,
        max_execution_time=120,
    )

    research_task = Task(
        description=(
            "Research {destination} for interests {activities}. Customer requirements: {request_json}. "
            "Use the supplied external search and weather tool results; they were already fetched for this "
            "trip, so do not repeat those API calls. Summarize useful attractions and weather caveats. "
            "Research evidence: {research_json}. Weather evidence: {weather_json}."
        ),
        expected_output="A short list of relevant attractions, weather caveats and source URLs.",
        agent=destination_agent,
    )
    stay_task = Task(
        description=(
            "Review the supplied accommodation, transport and route evidence for {destination}; these "
            "options were already gathered for this trip, so do not repeat the lookups. Explicitly say "
            "hotel and fare figures are mock estimates, not live availability or quotes. Options: {stay_json}."
        ),
        expected_output="A practical accommodation and transport comparison with estimates labeled accurately.",
        agent=hotel_transport_agent,
        context=[research_task],
    )
    budget_task = Task(
        description=(
            "Review the supplied Python-calculated estimate: {budget_json}. Identify whether the budget is "
            "met; if not, recommend the least-cost options and do not omit contingency. Do not recalculate "
            "unless the supplied figures are missing."
        ),
        expected_output="A transparent itemized budget assessment and, if necessary, lower-cost alternatives.",
        agent=budget_agent,
        context=[stay_task],
    )
    itinerary_task = Task(
        description=(
            "Use the supplied date-utility output to create exactly {duration} dated days for {destination}. "
            "Incorporate the research, hotel/transport and budget outputs. Avoid repeating date calculations, "
            "unsupported opening hours or real-time availability claims. Schedule: {schedule_json}."
        ),
        expected_output="A balanced day-by-day itinerary with dates and selected activities.",
        agent=itinerary_agent,
        context=[research_task, stay_task, budget_task],
    )
    final_task = Task(
        description=(
            "As Travel Coordinator, reconcile all task findings into a concise customer-ready plan for "
            "{destination}. Include the itinerary, attractions, hotel/transport options, itemized budget, "
            "budget comparison, any lower-cost alternatives, weather limitations, and research sources. "
            "Use the computed estimate {budget_json}; never describe mock prices as live quotes."
        ),
        expected_output="A complete, source-aware travel plan that clearly states whether it fits the budget.",
        agent=coordinator,
        context=[research_task, stay_task, budget_task, itinerary_task],
    )
    crew = Crew(
        agents=[coordinator, destination_agent, hotel_transport_agent, budget_agent, itinerary_agent],
        tasks=[research_task, stay_task, budget_task, itinerary_task, final_task],
        process=Process.sequential,
        verbose=False,
    )
    result = crew.kickoff(
        inputs={
            "request_json": json.dumps(asdict(request), default=str),
            "destination": request.destination,
            "activities": ", ".join(request.activities),
            "duration": request.duration_days,
            "schedule_json": json.dumps(
                build_day_schedule(request.start_date, request.duration_days, request.activities),
                ensure_ascii=False,
            ),
            "research_json": json.dumps(research, ensure_ascii=False),
            "weather_json": json.dumps(weather, ensure_ascii=False),
            "stay_json": json.dumps({"hotels": hotels, "transport": transports, "route": route}),
            "budget_json": json.dumps(budget_result),
        }
    )
    return str(result)


def generate_agent_summary(
    plan: dict[str, Any],
    *,
    provider: str,
    model: str,
    api_key: str = "",
    ollama_url: str = "http://localhost:11434",
) -> str:
    """Run the collaborating CrewAI workflow for an already assembled trip plan."""
    return run_agent_crew(
        plan["request"],
        plan["research"],
        plan["weather"],
        plan["hotels"],
        plan["transports"],
        plan["route"],
        plan["budget"],
        provider,
        model,
        api_key,
        ollama_url,
    )


def format_crew_error(exc: Exception) -> str:
    """Keep CrewAI failures readable without echoing full task prompts into the UI."""
    message = str(exc).strip()
    timeout = re.search(r"execution timed out after \d+ seconds", message)
    if timeout:
        return f"CrewAI agent {timeout.group(0)}."
    if len(message) > 400:
        return f"{message[:397]}..."
    return message


def create_trip_plan(
    request: TravelRequest,
    *,
    provider: str = "Ollama",
    model: str = "llama3.1",
    api_key: str = "",
    ollama_url: str = "http://localhost:11434",
    run_agents: bool = True,
) -> dict[str, Any]:
    request.validate()

    errors: list[str] = []
    try:
        research = search_destination(request.destination, request.activities)
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        research = {
            "status": "unavailable",
            "message": f"Destination search failed: {exc}",
            "results": [],
            "source": "Wikipedia Search API",
            "source_url": "https://www.mediawiki.org/wiki/API:Search",
        }
        errors.append(research["message"])

    try:
        weather = get_weather(request.destination, request.start_date, request.end_date)
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        weather = {
            "status": "unavailable",
            "message": f"Weather lookup failed: {exc}",
            "forecast": [],
            "source": "Open-Meteo",
            "source_url": "https://open-meteo.com/en/docs",
        }
        errors.append(weather["message"])

    try:
        route = get_route(request.starting_location, request.destination)
        distance_km = route["distance_km"]
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        route = {
            "status": "unavailable",
            "message": f"Route lookup failed: {exc}",
            "source": "OpenStreetMap Nominatim and OSRM",
            "source_url": "https://project-osrm.org/",
        }
        distance_km = None
        errors.append(route["message"])

    hotels = get_mock_hotel_options(request.destination, request.nights, request.travelers)
    transports = get_transport_options(distance_km, request.travelers)
    activities_per_person = 25.0
    meals_per_person = 45.0
    candidates = [
        calculate_trip_budget(
            nights=request.nights,
            travelers=request.travelers,
            budget=request.budget,
            hotel_nightly_rate=hotel["nightly_rate_usd"],
            transport_total=transport["estimated_total_usd"],
            activities_daily_per_person=activities_per_person,
            meals_daily_per_person=meals_per_person,
        )
        for hotel in hotels
        for transport in transports
    ]
    combinations = [
        {"hotel": hotel, "transport": transport, "budget": budget}
        for hotel in hotels
        for transport in transports
        for budget in candidates
        if budget["hotel_usd"] == hotel["nightly_rate_usd"] * request.nights * math.ceil(request.travelers / 2)
        and budget["transport_usd"] == transport["estimated_total_usd"]
    ]
    fitting = [choice for choice in combinations if choice["budget"]["within_budget"]]
    chosen = min(fitting or combinations, key=lambda choice: choice["budget"]["total_usd"])
    budget_result = chosen["budget"]
    budget_result["status"] = "within_budget" if budget_result["within_budget"] else "over_budget"
    budget_result["selected_hotel"] = chosen["hotel"]["name"]
    budget_result["selected_transport"] = chosen["transport"]["name"]
    budget_result["alternative_options"] = [
        {
            "hotel": choice["hotel"]["name"],
            "transport": choice["transport"]["name"],
            "total_usd": choice["budget"]["total_usd"],
            "within_budget": choice["budget"]["within_budget"],
        }
        for choice in sorted(combinations, key=lambda choice: choice["budget"]["total_usd"])[:3]
    ]

    crew_error = ""
    crew_pending = not run_agents
    crew_notes = (
        "The AI-agent workflow has not been run yet. The itinerary, researched destination "
        "information, and itemized budget below are ready."
    )
    if run_agents:
        try:
            crew_notes = generate_agent_summary(
                {
                    "request": request,
                    "research": research,
                    "weather": weather,
                    "hotels": hotels,
                    "transports": transports,
                    "route": route,
                    "budget": budget_result,
                },
                provider=provider,
                model=model,
                api_key=api_key,
                ollama_url=ollama_url,
            )
        except Exception as exc:
            crew_error = (
                "CrewAI could not complete the AI-generated summary: "
                f"{format_crew_error(exc)}"
            )
            crew_notes = (
                "The AI-agent workflow was unavailable for this request. The itinerary, researched "
                "destination information, and itemized budget below were assembled from the available "
                "data and deterministic planning utilities."
            )
            errors.append(crew_error)

    sources = [
        {"name": research["source"], "url": research["source_url"]},
        {"name": weather["source"], "url": weather["source_url"]},
        {"name": route["source"], "url": route["source_url"]},
        {"name": "Prototype hotel and transport estimates", "url": ""},
    ]
    return {
        "request": request,
        "research": research,
        "weather": weather,
        "route": route,
        "hotels": hotels,
        "transports": transports,
        "budget": budget_result,
        "schedule": build_day_schedule(request.start_date, request.duration_days, request.activities),
        "crew_notes": crew_notes,
        "crew_error": crew_error,
        "crew_pending": crew_pending,
        "source_list": sources,
        "warnings": errors,
    }
