from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

ROOT = Path(__file__).resolve().parents[1]
SOURCES_FILE = ROOT / "sources.yaml"
OUTPUT_FILE = ROOT / "output" / "weekly_digest.md"
SEEN_EVENTS_FILE = ROOT / "data" / "seen_events.json"

TARGET_CITIES = [
    "miami",
    "miami beach",
    "fort lauderdale",
    "boca raton",
    "west palm beach",
]
KEYWORDS = [
    "ai",
    "artificial intelligence",
    "cloud",
    "aws",
    "amazon web services",
    "azure",
    "startup",
    "startups",
    "cybersecurity",
    "cyber security",
    "saas",
    "devops",
    "data",
    "product",
    "engineering",
    "engineer",
    "enterprise tech",
]
BUSINESS_TERMS = [
    "founder",
    "customer",
    "partner",
    "partnership",
    "networking",
    "enterprise",
    "aws",
    "azure",
    "startup",
    "investor",
    "cto",
    "cio",
    "ciso",
]
USER_AGENT = "SouthFloridaTechEventsAgent/0.1 (+https://github.com/)"


@dataclass
class Event:
    title: str
    url: str
    source: str
    date_text: str = ""
    location: str = ""
    summary: str = ""
    parsed_date: datetime | None = None
    score: int = 0

    @property
    def event_id(self) -> str:
        return hashlib.sha256(f"{self.title}|{self.url}".encode()).hexdigest()[:16]


def load_sources() -> list[dict[str, Any]]:
    with SOURCES_FILE.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    return config.get("sources", [])


def text_or_empty(node: Any) -> str:
    if not node:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def first_text(card: Any, selectors: list[str | None]) -> str:
    for selector in selectors:
        if not selector:
            continue
        found = card.select_one(selector)
        value = text_or_empty(found)
        if value:
            return value
    return ""


def first_link(card: Any, source_url: str, selector: str | None = None) -> str:
    candidates = [card.select_one(selector)] if selector else []
    candidates.extend(card.select("a[href]"))
    for candidate in candidates:
        if candidate and candidate.get("href"):
            href = candidate.get("href")
            if href.startswith("#") or href.startswith("mailto:"):
                continue
            return urljoin(source_url, href)
    return source_url


def parse_date(date_text: str) -> datetime | None:
    if not date_text:
        return None
    try:
        parsed = date_parser.parse(date_text, fuzzy=True)
    except (ValueError, OverflowError, TypeError):
        return None
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def fetch_source(source: dict[str, Any]) -> list[Event]:
    url = source["url"]
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    selector = source.get("event_selector")
    cards = soup.select(selector) if selector else soup.select("article, li, .event, [class*=event]")
    if not cards:
        cards = soup.select("a[href]")

    events: list[Event] = []
    max_events = int(source.get("max_events", 25))
    for card in cards[: max_events * 3]:
        title = first_text(card, [source.get("title_selector", ""), "h1", "h2", "h3", "h4", "a"]) or text_or_empty(card)
        title = title[:180].strip()
        if len(title) < 6:
            continue

        date_text = first_text(card, [source.get("date_selector", ""), "time", ".date", "[class*=date]", "[datetime]"])
        location = first_text(card, [source.get("location_selector", ""), ".location", "[class*=location]", "[class*=venue]"])
        link = first_link(card, url, source.get("link_selector"))
        summary = text_or_empty(card)[:500]
        events.append(
            Event(
                title=title,
                url=link,
                source=source.get("name", url),
                date_text=date_text,
                location=location,
                summary=summary,
                parsed_date=parse_date(date_text),
            )
        )
        if len(events) >= max_events:
            break
    return events


def score_event(event: Event) -> int:
    haystack = " ".join([event.title, event.location, event.summary]).lower()
    score = 0
    score += sum(3 for keyword in KEYWORDS if keyword in haystack)
    score += sum(2 for city in TARGET_CITIES if city in haystack)
    score += sum(1 for term in BUSINESS_TERMS if term in haystack)
    if event.parsed_date:
        now = datetime.now(timezone.utc)
        if now <= event.parsed_date <= now + timedelta(days=14):
            score += 4
    return score


def keep_event(event: Event) -> bool:
    haystack = " ".join([event.title, event.location, event.summary]).lower()
    has_keyword = any(keyword in haystack for keyword in KEYWORDS)
    has_city = any(city in haystack for city in TARGET_CITIES)
    # Some event listing pages omit city names in each card. Keep strong keyword matches.
    return has_keyword and (has_city or event.score >= 5)


def load_seen_event_ids() -> set[str]:
    if not SEEN_EVENTS_FILE.exists():
        return set()
    try:
        data = json.loads(SEEN_EVENTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    if isinstance(data, list):
        return {str(item) for item in data}
    return set(data.get("seen_event_ids", [])) if isinstance(data, dict) else set()


def write_digest(events: list[Event], errors: list[str]) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# South Florida Tech Events Weekly Digest",
        "",
        f"Generated: {generated_at}",
        "",
        "Focus: Miami, Miami Beach, Fort Lauderdale, Boca Raton, and West Palm Beach events for AI, cloud, AWS, Azure, startups, cybersecurity, SaaS, DevOps, data, product, and engineering.",
        "",
    ]

    if not events:
        lines.extend([
            "## No matching events found",
            "",
            "No matching events were found from the configured public sources. Try adding more sources to `sources.yaml` or rerun later.",
            "",
        ])
    else:
        lines.extend(["## Prioritized Events", ""])
        for index, event in enumerate(events, start=1):
            date = event.parsed_date.strftime("%Y-%m-%d") if event.parsed_date else event.date_text or "Date not listed"
            location = event.location or "Location not listed"
            lines.extend([
                f"### {index}. [{event.title}]({event.url})",
                f"- **Date:** {date}",
                f"- **Location:** {location}",
                f"- **Source:** {event.source}",
                f"- **Business-development fit score:** {event.score}",
                f"- **Why it may matter:** Relevant to local cloud, AI, DevOps, cybersecurity, SaaS, startup, product, data, or engineering networking.",
                "",
            ])

    if errors:
        lines.extend(["## Source fetch notes", ""])
        lines.extend(f"- {error}" for error in errors)
        lines.append("")

    lines.extend([
        "## Sources",
        "",
        "Edit `sources.yaml` to add or remove public event pages.",
    ])
    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    sources = load_sources()
    seen_event_ids = load_seen_event_ids()
    errors: list[str] = []
    events_by_id: dict[str, Event] = {}

    for source in sources:
        try:
            for event in fetch_source(source):
                event.score = score_event(event)
                if event.event_id not in seen_event_ids and keep_event(event):
                    events_by_id[event.event_id] = event
        except requests.RequestException as exc:
            errors.append(f"Could not fetch {source.get('name', source.get('url'))}: {exc}")

    events = sorted(
        events_by_id.values(),
        key=lambda event: (
            -event.score,
            event.parsed_date or datetime.max.replace(tzinfo=timezone.utc),
            event.title.lower(),
        ),
    )[:25]
    write_digest(events, errors)
    print(f"Wrote {OUTPUT_FILE.relative_to(ROOT)} with {len(events)} event(s).")


if __name__ == "__main__":
    main()
