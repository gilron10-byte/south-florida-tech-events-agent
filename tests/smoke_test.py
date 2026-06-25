from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import main


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
