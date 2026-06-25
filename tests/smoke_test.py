from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import main


class FakeSearchResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


def make_event(title: str, summary: str = "AI cloud event for founders in Miami", date_text: str = "July 10, 2026", url: str | None = None) -> main.Event:
    event = main.Event(
        title=title,
        url=url or f"https://example.com/{title.lower().replace(' ', '-')}",
        source="Smoke Test",
        date_text=date_text,
        location="Miami, FL",
        summary=summary,
        parsed_date=main.parse_date(date_text),
    )
    event.score = main.score_event(event)
    return event


def test_recurring_events_are_deduplicated() -> None:
    events = [
        make_event("Miami AI Founder Meetup - 7/10/2026"),
        make_event("Miami AI Founder Meetup - 7/17/2026"),
    ]
    deduped = main.deduplicate_recurring_events(events)
    assert len(deduped) == 1
    assert deduped[0].recurring_count == 2


def test_generic_non_event_pages_are_filtered_out() -> None:
    generic = main.Event(
        title="Submit an event to the events calendar",
        url="https://example.com/events",
        source="Smoke Test",
        date_text="",
        location="",
        summary="Submit an event or view all events on this tech hub events calendar.",
    )
    generic.score = 10
    assert not main.keep_event(generic)


def test_ranking_prioritizes_executive_and_ai_events_over_generic_networking() -> None:
    generic = make_event(
        "Crowded Mondays — Network • Discuss • Connect",
        summary="Weekly recurring meetup for broad community networking and connecting with local professionals.",
        date_text="July 6, 2026",
    )
    generic.recurring_count = 4
    generic.score = main.score_event(generic)

    breakfast = make_event(
        "CTO/CPO Breakfast",
        summary="Breakfast for CTOs, CPOs, product leaders, and engineering leaders discussing cloud modernization and AI adoption.",
        date_text="July 8, 2026",
    )
    fintech = make_event(
        "Fort Lauderdale Tech Meetup • Building an AI-first Fintech Startup",
        summary="Founders and builders discuss AI-first fintech startup architecture, cloud platforms, SaaS growth, and engineering decisions.",
        date_text="July 9, 2026",
    )
    agentic = make_event(
        "Agentic Workflow Automation on AWS",
        summary="Technical discussion of agentic AI workflows, cloud deployment, data readiness, and AWS modernization.",
        date_text="July 11, 2026",
    )
    fintech.location = "Fort Lauderdale, FL"
    fintech.score = main.score_event(fintech)
    agentic.score = main.score_event(agentic)

    top_titles = [event.title for event in main.top_recommendations([generic, breakfast, fintech, agentic])]

    assert "Crowded Mondays — Network • Discuss • Connect" not in top_titles
    assert top_titles[0] == "CTO/CPO Breakfast"
    assert "Fort Lauderdale Tech Meetup • Building an AI-first Fintech Startup" in top_titles
    assert generic.score <= 6
    assert main.suggested_action(generic) in {"Send AE", "Track only"}
    assert main.suggested_action(generic) != "Attend personally"


def test_why_this_matters_uses_natural_executive_language() -> None:
    event = make_event(
        "Fort Lauderdale Tech Meetup • Building an AI-first Fintech Startup",
        summary="Founders discuss AI, fintech, cloud architecture, SaaS product delivery, and startup growth.",
    )
    event.location = "Fort Lauderdale, FL"
    rationale = main.why_this_matters(event)

    assert "around ai" not in rationale.lower()
    assert "matches priority services" not in rationale.lower()
    assert "signals buyer-adjacent" not in rationale.lower()
    assert "This should rank highly" in rationale


def test_fallback_cache_works_when_all_sources_fail(tmp_path, monkeypatch) -> None:
    cache_file = tmp_path / "last_successful_events.json"
    output_file = tmp_path / "weekly_digest.md"
    monkeypatch.setattr(main, "LAST_SUCCESSFUL_EVENTS_FILE", cache_file)
    monkeypatch.setattr(main, "OUTPUT_FILE", output_file)

    cached_event = make_event("Cached Miami Cloud Leadership Summit")
    main.save_last_successful_events([cached_event])
    fallback_events = main.load_last_successful_events()
    diagnostics = main.RunDiagnostics(
        sources_fetched_successfully=[],
        sources_skipped=["Refresh Miami Events"],
        raw_events_found=0,
        events_after_filtering=0,
        events_after_deduplication=0,
        fallback_cache_used=bool(fallback_events),
        fallback_reason="Smoke test simulated source failure.",
    )
    main.write_digest([], ["Refresh Miami Events was skipped."], diagnostics, fallback_events)

    digest = output_file.read_text(encoding="utf-8")
    assert "Fallback: last known relevant events" in digest
    assert "previous successful run" in digest
    assert "Cached Miami Cloud Leadership Summit" in digest
    assert "Fallback cache was used:** Yes" in digest


if __name__ == "__main__":
    test_recurring_events_are_deduplicated()
    test_generic_non_event_pages_are_filtered_out()
    test_ranking_prioritizes_executive_and_ai_events_over_generic_networking()
    test_why_this_matters_uses_natural_executive_language()

    class MonkeyPatch:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        test_fallback_cache_works_when_all_sources_fail(Path(tmp), MonkeyPatch())
    print("smoke tests passed")


def test_eventbrite_search_candidates_survive_failed_page_fetch(monkeypatch) -> None:
    monkeypatch.setenv("SEARCH_API_KEY", "test-key")

    def fake_search_api_results(query: str, max_results: int) -> list[dict[str, str]]:
        return [
            {
                "title": "Miami AI Startup Cloud Summit",
                "url": "https://www.eventbrite.com/e/miami-ai-startup-cloud-summit-tickets-123",
                "snippet": "Miami founders discuss AI, startup cloud architecture, AWS, Azure, and SaaS growth.",
            },
            {
                "title": "Eventbrite directory page",
                "url": "https://www.eventbrite.com/d/fl--miami/technology--events/",
                "snippet": "Directory page should be ignored.",
            },
        ]

    def fake_fetch_eventbrite_event_page(candidate: main.Event) -> main.Event:
        raise main.requests.HTTPError("blocked")

    monkeypatch.setattr(main, "search_api_results", fake_search_api_results)
    monkeypatch.setattr(main, "fetch_eventbrite_event_page", fake_fetch_eventbrite_event_page)
    events = main.fetch_search_discovery_source({"queries": ["site:eventbrite.com/e/ Miami AI startup cloud"], "max_events": 10})

    assert len(events) == 1
    assert events[0].source == "Eventbrite via Search"
    assert events[0].confidence == "low"
    assert "eventbrite.com/e/" in events[0].url
    events[0].score = main.score_event(events[0])
    assert main.keep_event(events[0])


def test_search_discovery_reports_safe_serpapi_errors(monkeypatch) -> None:
    monkeypatch.setenv("SEARCH_API_KEY", "super-secret-key")
    monkeypatch.setenv("SEARCH_API_URL", "https://serpapi.com/search.json")

    def fake_get(url: str, **kwargs: object) -> FakeSearchResponse:
        assert kwargs["params"]["api_key"] == "super-secret-key"  # type: ignore[index]
        return FakeSearchResponse(429, {"error": "Account rate limit reached for this search."})

    monkeypatch.setattr(main.requests, "get", fake_get)
    diagnostics = main.RunDiagnostics(sources_fetched_successfully=[], sources_skipped=[])

    try:
        main.search_api_results("site:eventbrite.com/e/ Miami AI", 10, diagnostics)
    except main.SearchDiscoveryError as exc:
        note = main.source_note({"name": "Eventbrite Search Discovery", "type": "search_discovery"}, exc)
    else:
        raise AssertionError("SearchDiscoveryError was not raised")

    assert "HTTP 429" in note
    assert "Account rate limit reached" in note
    assert "super-secret-key" not in note
    assert diagnostics.search_api_endpoint_host == "serpapi.com"
    assert diagnostics.search_queries_attempted == 1
    assert diagnostics.search_api_responses_received == 1


def test_malformed_search_api_url_falls_back_to_default(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SEARCH_API_KEY", "super-secret-key")
    monkeypatch.setenv("SEARCH_API_URL", "not a url")

    def fake_get(url: str, **kwargs: object) -> FakeSearchResponse:
        assert url == main.DEFAULT_SEARCH_API_URL
        return FakeSearchResponse(200, {"organic_results": []})

    monkeypatch.setattr(main.requests, "get", fake_get)
    assert main.search_api_results("site:eventbrite.com/e/ Miami AI", 10) == []
    captured = capsys.readouterr()

    assert "https://serpapi.com/search.json" in captured.out
    assert "api_key=%5BREDACTED%5D" in captured.out
    assert "super-secret-key" not in captured.out


def test_low_confidence_eventbrite_does_not_outrank_high_confidence_primary_source() -> None:
    primary = make_event(
        "Miami AI Cloud Executive Summit",
        summary="Executive technology leaders discuss AI, AWS, Azure, cloud modernization, cybersecurity, and SaaS platforms.",
    )
    primary.source = "Refresh Miami Events"
    primary.confidence = "high"
    primary.score = 8

    eventbrite = make_event(
        "Miami AI Cloud Executive Summit on Eventbrite",
        summary="Executive technology leaders discuss AI, AWS, Azure, cloud modernization, cybersecurity, and SaaS platforms.",
        url="https://www.eventbrite.com/e/miami-ai-cloud-executive-summit-tickets-456",
    )
    eventbrite.source = "Eventbrite via Search"
    eventbrite.confidence = "low"
    eventbrite.score = 10

    assert sorted([eventbrite, primary], key=main.ranking_key)[0] is primary


def test_multi_market_outputs_and_global_summary_are_generated(tmp_path, monkeypatch) -> None:
    markets = [
        {"id": "south_florida", "name": "South Florida", "timezone": "America/New_York", "cities": ["Miami"], "output_file": "output/south_florida_weekly_digest.md", "cache_file": "data/sf.json", "primary_sources": [], "discovery_groups": []},
        {"id": "new_york", "name": "New York", "timezone": "America/New_York", "cities": ["New York"], "output_file": "output/new_york_weekly_digest.md", "cache_file": "data/ny.json", "primary_sources": [], "discovery_groups": []},
        {"id": "tel_aviv", "name": "Tel Aviv", "timezone": "Asia/Jerusalem", "cities": ["Tel Aviv"], "output_file": "output/tel_aviv_weekly_digest.md", "cache_file": "data/ta.json", "primary_sources": [], "discovery_groups": []},
    ]
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(main, "GLOBAL_SUMMARY_FILE", tmp_path / "output" / "global_weekly_summary.md")
    results = []
    for market in markets:
        event = main.Event(
            title=f"{market['name']} AI Cloud Executive Summit",
            url=f"https://example.com/{market['id']}",
            source="Smoke Test",
            date_text="July 10, 2026",
            location=market["cities"][0],
            summary="Executive founders discuss AI cloud startup cybersecurity SaaS modernization.",
            parsed_date=main.parse_date("July 10, 2026"),
            confidence="high",
            market_id=market["id"],
        )
        event.score = main.score_event(event, market)
        diagnostics = main.RunDiagnostics([], [], market_name=market["name"], events_after_deduplication=1)
        main.write_digest([event], [], diagnostics, market=market, candidates=[])
        results.append((market, [event], diagnostics))

    main.write_global_summary(results)

    assert (tmp_path / "output" / "south_florida_weekly_digest.md").exists()
    assert (tmp_path / "output" / "new_york_weekly_digest.md").exists()
    assert (tmp_path / "output" / "tel_aviv_weekly_digest.md").exists()
    assert (tmp_path / "output" / "global_weekly_summary.md").exists()
    sf_text = (tmp_path / "output" / "south_florida_weekly_digest.md").read_text()
    assert "New York AI Cloud" not in sf_text


def test_low_confidence_search_candidate_stays_out_of_top3() -> None:
    market = {"id": "new_york", "name": "New York", "timezone": "America/New_York", "cities": ["New York"]}
    candidate = main.Event(
        title="New York AI Startup Cloud Event",
        url="https://example.com/event/ai",
        source="Luma / lu.ma Discovery",
        summary="Relevant AI startup cloud event in New York but missing details.",
        confidence="low",
        market_id="new_york",
        discovery_group="Luma / lu.ma Discovery",
        is_candidate=True,
    )
    candidate.score = 10
    primary = main.Event(
        title="New York CTO AI Cloud Summit",
        url="https://example.com/cto-ai-cloud-summit",
        source="Primary",
        date_text="July 12, 2026",
        location="New York",
        summary="CTO leaders discuss AI cloud modernization and cybersecurity.",
        parsed_date=main.parse_date("July 12, 2026"),
        confidence="high",
        market_id="new_york",
    )
    primary.score = main.score_event(primary, market)
    assert main.top_recommendations([candidate, primary], market=market) == [primary]
    assert main.suggested_action(candidate) == "Review manually"


def test_search_discovered_candidate_can_go_to_review() -> None:
    market = {"id": "south_florida", "name": "South Florida", "timezone": "America/New_York", "cities": ["Miami"]}
    event = main.Event(
        title="Miami AWS Startup Cloud Event",
        url="https://example.com/events/miami-aws-startup",
        source="Cloud Provider Events",
        summary="Miami AWS startup cloud event for SaaS founders.",
        confidence="low",
        market_id="south_florida",
        discovery_group="Cloud Provider Events",
        category="Cloud / Hyperscaler",
    )
    event.score = main.score_event(event, market)
    event.missing_fields = main.missing_fields(event)
    assert main.is_event_page(event)
    assert not main.promote_search_event(event, market) or event.confidence == "low"
    assert main.candidate_bucket(event) in {"AWS", "Cloud / Hyperscaler"}


def test_workflow_uploads_all_markdown_outputs() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "weekly-digest.yml").read_text()
    assert "path: output/*.md" in workflow
