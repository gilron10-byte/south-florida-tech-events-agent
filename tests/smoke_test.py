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

    class MonkeyPatch:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        test_fallback_cache_works_when_all_sources_fail(Path(tmp), MonkeyPatch())
    print("smoke tests passed")
