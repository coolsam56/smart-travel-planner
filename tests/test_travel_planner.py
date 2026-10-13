import unittest
from datetime import date
from unittest.mock import Mock, patch

from travel_planner import (
    TravelRequest,
    build_day_schedule,
    calculate_trip_budget,
    get_mock_hotel_options,
    get_transport_options,
    format_crew_error,
    run_agent_crew,
    search_destination,
)


class TravelPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = TravelRequest(
            destination="Kyoto",
            starting_location="Tokyo",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 4),
            budget=1500,
            activities=["Sightseeing", "Food"],
            travelers=2,
        )

    def test_request_duration_and_validation(self) -> None:
        self.request.validate()
        self.assertEqual(self.request.duration_days, 4)
        self.assertEqual(self.request.nights, 3)

    def test_request_rejects_inverted_dates(self) -> None:
        invalid = TravelRequest(
            destination="Kyoto",
            starting_location="Tokyo",
            start_date=date(2026, 11, 4),
            end_date=date(2026, 11, 1),
            budget=1500,
            activities=["Sightseeing"],
        )
        with self.assertRaisesRegex(ValueError, "return date"):
            invalid.validate()

    def test_crew_timeout_error_does_not_echo_task_prompt(self) -> None:
        message = format_crew_error(
            RuntimeError("Task 'very long private task input' execution timed out after 45 seconds")
        )
        self.assertEqual(message, "CrewAI agent execution timed out after 45 seconds.")

    def test_budget_includes_contingency_and_compares_with_budget(self) -> None:
        result = calculate_trip_budget(
            nights=3,
            travelers=2,
            budget=1000,
            hotel_nightly_rate=55,
            transport_total=200,
        )
        self.assertEqual(result["hotel_usd"], 165)
        self.assertEqual(result["activities_usd"], 200)
        self.assertEqual(result["meals_usd"], 360)
        self.assertEqual(result["contingency_usd"], 92.5)
        self.assertEqual(result["total_usd"], 1017.5)
        self.assertFalse(result["within_budget"])

    def test_itinerary_has_exact_dates_and_rotates_interests(self) -> None:
        days = build_day_schedule(
            self.request.start_date, self.request.duration_days, self.request.activities
        )
        self.assertEqual([day["date"] for day in days], [
            "2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"
        ])
        self.assertIn("landmark", days[0]["morning"])
        self.assertIn("food", days[1]["morning"])

    def test_estimates_are_explicit_and_sorted_by_cost(self) -> None:
        hotels = get_mock_hotel_options("Kyoto", 3)
        transports = get_transport_options(400, 2)
        self.assertIn("mock planning estimate", hotels[0]["type"])
        self.assertEqual(transports, sorted(transports, key=lambda item: item["estimated_total_usd"]))

    def test_hotel_estimate_accounts_for_party_room_count(self) -> None:
        option = get_mock_hotel_options("Kyoto", 2, travelers=3)[0]
        self.assertEqual(option["rooms"], 2)
        self.assertEqual(option["estimated_total_usd"], 220)

    @patch(
        "travel_planner._get_json",
        return_value={
            "query": {
                "search": [
                    {
                        "title": "Kyoto Imperial Palace",
                        "snippet": "<span class=\"searchmatch\">Kyoto</span> attraction",
                    },
                    {"title": "Kyoto Imperial Palace", "snippet": "duplicate"},
                    {"title": "Nishiki Market", "snippet": "Food &amp; shopping"},
                ]
            }
        },
    )
    def test_destination_search_uses_activity_topics_and_returns_cited_results(
        self, get_json: Mock
    ) -> None:
        result = search_destination("Kyoto", ["Sightseeing", "Food"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual([item["title"] for item in result["results"]], [
            "Kyoto Imperial Palace", "Nishiki Market"
        ])
        self.assertEqual(
            result["results"][0]["url"],
            "https://en.wikipedia.org/wiki/Kyoto_Imperial_Palace",
        )
        self.assertEqual(result["results"][0]["description"], "Kyoto attraction")
        self.assertEqual(
            [call.kwargs["params"]["srsearch"] for call in get_json.call_args_list],
            ["Kyoto attractions", "Kyoto cuisine"],
        )

    @patch("travel_planner.run_agent_crew", return_value="Coordinator output")
    @patch(
        "travel_planner.get_route",
        return_value={
            "status": "ok",
            "distance_km": 400,
            "source": "OSRM",
            "source_url": "https://project-osrm.org/",
        },
    )
    @patch(
        "travel_planner.get_weather",
        return_value={
            "status": "ok",
            "forecast": [],
            "source": "Open-Meteo",
            "source_url": "https://open-meteo.com/en/docs",
        },
    )
    @patch(
        "travel_planner.search_destination",
        return_value={
            "status": "ok",
            "results": [],
            "source": "Wikipedia Search API",
            "source_url": "https://www.mediawiki.org/wiki/API:Search",
        },
    )
    def test_plan_chooses_lowest_cost_options_when_over_budget(
        self, _search: Mock, _weather: Mock, _route: Mock, crew: Mock
    ) -> None:
        from travel_planner import create_trip_plan

        request = TravelRequest(
            destination="Kyoto",
            starting_location="Tokyo",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 4),
            budget=100,
            activities=["Sightseeing"],
            travelers=2,
        )
        plan = create_trip_plan(request)
        self.assertFalse(plan["budget"]["within_budget"])
        self.assertEqual(plan["budget"]["status"], "over_budget")
        self.assertEqual(plan["crew_notes"], "Coordinator output")
        self.assertEqual(
            plan["budget"]["total_usd"],
            min(option["total_usd"] for option in plan["budget"]["alternative_options"]),
        )
        crew.assert_called_once()

    @patch("travel_planner.run_agent_crew", side_effect=RuntimeError("LLM endpoint is unavailable"))
    @patch(
        "travel_planner.get_route",
        return_value={
            "status": "ok",
            "distance_km": 400,
            "source": "OSRM",
            "source_url": "https://project-osrm.org/",
        },
    )
    @patch(
        "travel_planner.get_weather",
        return_value={
            "status": "ok",
            "forecast": [],
            "source": "Open-Meteo",
            "source_url": "https://open-meteo.com/en/docs",
        },
    )
    @patch(
        "travel_planner.search_destination",
        return_value={
            "status": "ok",
            "results": [{"title": "Kyoto Imperial Palace", "description": "", "url": "https://example.com"}],
            "source": "Wikipedia Search API",
            "source_url": "https://www.mediawiki.org/wiki/API:Search",
        },
    )
    def test_plan_still_returns_itinerary_when_llm_is_unavailable(
        self, _search: Mock, _weather: Mock, _route: Mock, _crew: Mock
    ) -> None:
        from travel_planner import create_trip_plan

        plan = create_trip_plan(self.request)
        self.assertEqual(len(plan["schedule"]), self.request.duration_days)
        self.assertTrue(plan["research"]["results"])
        self.assertIn("LLM endpoint is unavailable", plan["crew_error"])
        self.assertIn("deterministic planning utilities", plan["crew_notes"])
        self.assertTrue(any("CrewAI could not complete" in warning for warning in plan["warnings"]))

    @patch("travel_planner.run_agent_crew")
    @patch(
        "travel_planner.get_route",
        return_value={"status": "ok", "distance_km": 400, "source": "OSRM", "source_url": "https://project-osrm.org/"},
    )
    @patch(
        "travel_planner.get_weather",
        return_value={"status": "unavailable", "source": "Open-Meteo", "source_url": "https://open-meteo.com/en/docs"},
    )
    @patch(
        "travel_planner.search_destination",
        return_value={"status": "ok", "results": [], "source": "Wikipedia Search API", "source_url": "https://www.mediawiki.org/wiki/API:Search"},
    )
    def test_fast_plan_defers_crew_until_requested(
        self, _search: Mock, _weather: Mock, _route: Mock, crew: Mock
    ) -> None:
        from travel_planner import create_trip_plan

        plan = create_trip_plan(self.request, run_agents=False)
        self.assertTrue(plan["crew_pending"])
        self.assertEqual(len(plan["schedule"]), self.request.duration_days)
        self.assertTrue(plan["budget"]["total_usd"] > 0)
        crew.assert_not_called()

    @patch("crewai.Crew.kickoff", autospec=True, return_value="CrewAI collaboration complete")
    def test_crew_builds_all_agent_tasks_and_starts_workflow(self, kickoff: Mock) -> None:
        research = {"status": "ok", "results": [], "source": "test", "source_url": "https://example.com"}
        weather = {"status": "unavailable", "forecast": []}
        route = {"status": "unavailable"}
        hotels = get_mock_hotel_options(self.request.destination, self.request.nights)
        transports = get_transport_options(None, self.request.travelers)
        budget = calculate_trip_budget(
            nights=self.request.nights,
            travelers=self.request.travelers,
            budget=self.request.budget,
            hotel_nightly_rate=hotels[0]["nightly_rate_usd"],
            transport_total=transports[0]["estimated_total_usd"],
        )
        result = run_agent_crew(
            self.request,
            research,
            weather,
            hotels,
            transports,
            route,
            budget,
            "Ollama",
            "llama3.1",
        )
        self.assertEqual(result, "CrewAI collaboration complete")
        kickoff.assert_called_once()
        crew = kickoff.call_args.args[0]
        self.assertEqual(len(crew.tasks), 5)
        self.assertTrue(all(agent.max_iter == 2 for agent in crew.agents))
        self.assertEqual(crew.agents[0].llm.timeout, 120)


if __name__ == "__main__":
    unittest.main()
