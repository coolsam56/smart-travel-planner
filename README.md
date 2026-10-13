# Smart Travel Planner

A Streamlit travel-planning prototype using a sequential CrewAI workflow with five collaborating roles: Travel Coordinator, Destination Research, Hotel and Transport, Budget Analyst, and Itinerary Planner.

## Features

- Collects destination, starting location, dates, budget, interests, and traveler count.
- Uses the Wikipedia Search API for destination research, Open-Meteo for forecasts, and OpenStreetMap Nominatim/OSRM for geocoding and a driving-route estimate.
- Includes CrewAI tools for research, weather, route/transport, cost calculation, and date-safe schedule generation.
- Passes task outputs through the sequential CrewAI workflow and assembles a deterministic itinerary and cost comparison.
- Provides clearly labeled mock hotel and transport price allowances because no booking provider is configured.
- Recommends the least expensive combination if the plan exceeds the budget; estimates include contingency.
- Supports Ollama or OpenRouter as the LLM provider.
- The researched itinerary and cost comparison are displayed before the optional CrewAI summary is run, so slow model responses do not block the usable trip plan.
- If the LLM is unavailable, the researched results, dated itinerary, and cost comparison remain available, with an explicit warning that the CrewAI-generated summary could not be completed.
- CrewAI tasks use bounded execution time, retries, and iteration counts so a slow or unresponsive model does not retry indefinitely.
- On slower machines, a local model may still reach its per-task timeout; select OpenRouter in the sidebar for the AI-generated summary if a hosted model is available.

## Run locally

```bash
cd smart_travel_planner
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

Select a provider in the sidebar. For Ollama, make sure the server is running and the selected model has been pulled (for example, `ollama pull llama3.1`). For OpenRouter, provide an API key in the sidebar or in `.env`.

## Deploy to Render

This folder contains a Render Blueprint at `render.yaml`. It pins Render to Python 3.13.4 because CrewAI does not yet support Python 3.14. Push this project folder to a GitHub repository, then in Render choose **New + → Blueprint** and connect that repository. If you add this folder to a repository whose root is the parent directory, move/copy `render.yaml` to the repository root and set the service `rootDir` to `smart_travel_planner`.

When Render requests the `OPENROUTER_API_KEY` environment variable, enter the key in Render's secure Blueprint prompt or add it under the service's **Environment** settings. Do not put the key in `render.yaml` or commit it. The Blueprint defaults the deployed app to OpenRouter because a Render service cannot access an Ollama server running on your computer. The Streamlit app remains usable for the sourced itinerary and budget if an API key is not configured, but the AI-generated agent summary requires a valid OpenRouter key.

The Blueprint uses Render's free instance. Free instances may spin down when idle and can take time to start again. After deployment, open the `onrender.com` URL shown on the Render service page.

## Price and data notes

Hotel options, transport fares, meals, activity costs, and contingency are estimates for planning only. They are not live prices, availability, quotes, or reservations. The transport estimates are not a substitute for flight, rail, or bus search. The public routing service provides a driving-distance/time estimate only. Forecasts are limited to the forecast window provided by Open-Meteo; historical dates and dates beyond that window are marked unavailable. Verify all details with providers before booking.

Public API access is subject to each service's terms, rate limits, and availability. Network lookup failures are shown in the app, and no credentials are required for the public data sources used here.

## Tests

Run the standard-library tests with:

```bash
python -m unittest discover -s tests -v
```
