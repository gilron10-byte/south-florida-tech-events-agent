from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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
EASTERN_TZ = ZoneInfo("America/New_York")
SEEN_EVENTS_FILE = ROOT / "data" / "seen_events.json"

TARGET_CITIES = {
    "miami": 4,
    "miami beach": 4,
    "fort lauderdale": 4,
    "boca raton": 4,
    "west palm beach": 4,
    "palm beach": 2,
    "south florida": 2,
}
STRATEGIC_TERMS = {
    "aws": 8,
    "amazon web services": 8,
    "azure": 8,
    "cloud": 7,
    "cloud computing": 7,
    "agentic": 7,
    "agent": 4,
    "ai": 6,
    "artificial intelligence": 6,
    "cybersecurity": 6,
    "cyber security": 6,
    "devops": 6,
    "data": 5,
    "analytics": 4,
    "saas": 5,
    "startup": 5,
    "startups": 5,
    "founder": 5,
    "vc": 5,
    "venture capital": 5,
    "cto": 5,
    "cio": 5,
    "cpo": 5,
    "ciso": 5,
    "enterprise": 5,
    "product": 4,
    "engineering": 4,
    "engineer": 3,
}
AUDIENCE_TERMS = {
    "executive": 4,
    "leadership": 4,
    "c-level": 4,
    "decision maker": 4,
    "founder": 4,
    "investor": 4,
    "enterprise": 4,
    "cto": 5,
    "cio": 5,
    "cpo": 5,
    "ciso": 5,
    "vp": 3,
    "director": 3,
}
BUSINESS_VALUE_TERMS = {
    "partner": 4,
    "partnership": 4,
    "customer": 4,
    "client": 4,
    "networking": 3,
    "summit": 3,
    "conference": 3,
    "roundtable": 3,
    "workshop": 2,
    "meetup": 2,
    "aws": 4,
    "azure": 4,
}
LOW_VALUE_TERMS = {
    "social": -5,
    "party": -5,
    "happy hour": -4,
    "consumer": -5,
    "concert": -8,
    "festival": -6,
    "yoga": -8,
    "market": -4,
    "student only": -8,
    "students only": -8,
    "for students": -5,
    "career fair": -3,
    "unclear": -3,
}
KEYWORDS = list(STRATEGIC_TERMS)
USER_AGENT = "SouthFloridaTechEventsAgent/0.2 (+https://github.com/)"


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
        summary = text_or_empty(card)[:700]
        events.append(Event(title, link, source.get("name", url), date_text, location, summary, parse_date(date_text)))
        if len(events) >= max_events:
            break
    return events


def matching_terms(haystack: str, weighted_terms: dict[str, int]) -> list[tuple[str, int]]:
    return [(term, weight) for term, weight in weighted_terms.items() if term in haystack]


def score_event(event: Event) -> int:
    """Return a simple 1-10 business-development relevance score."""
    haystack = " ".join([event.title, event.location, event.summary]).lower()
    raw_score = 18
    raw_score += sum(weight for _, weight in matching_terms(haystack, STRATEGIC_TERMS))
    raw_score += sum(weight for _, weight in matching_terms(haystack, TARGET_CITIES))
    raw_score += sum(weight for _, weight in matching_terms(haystack, AUDIENCE_TERMS))
    raw_score += sum(weight for _, weight in matching_terms(haystack, BUSINESS_VALUE_TERMS))
    raw_score += sum(weight for _, weight in matching_terms(haystack, LOW_VALUE_TERMS))

    senior_terms = ["cto", "cpo", "cio", "ciso", "vp", "director", "founder", "executive", "leadership", "investor"]
    cloud_relationship_terms = ["aws", "amazon web services", "azure", "partner", "partnership", "enterprise", "customer", "client"]
    hot_delivery_terms = ["ai", "artificial intelligence", "agentic", "agent", "cloud", "cybersecurity", "cyber security", "devops", "data", "engineering", "product", "saas"]

    if any(term in haystack for term in senior_terms):
        raw_score += 8
    if any(term in haystack for term in cloud_relationship_terms):
        raw_score += 7
    if any(term in haystack for term in hot_delivery_terms):
        raw_score += 6
    if not event.location.strip():
        raw_score -= 8
    if not event.summary or len(event.summary) < 80:
        raw_score -= 4
    if not any(term in haystack for term in BUSINESS_VALUE_TERMS):
        raw_score -= 3
    if event.parsed_date:
        now = datetime.now(timezone.utc)
        if now <= event.parsed_date <= now + timedelta(days=21):
            raw_score += 4
        elif event.parsed_date < now - timedelta(days=1):
            raw_score -= 8

    return max(1, min(10, round(raw_score / 10)))


def keep_event(event: Event) -> bool:
    haystack = " ".join([event.title, event.location, event.summary]).lower()
    has_strategic_term = any(term in haystack for term in STRATEGIC_TERMS)
    has_target_city = any(city in haystack for city in TARGET_CITIES)
    return event.score >= 3 and has_strategic_term and (has_target_city or event.score >= 6)


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


def format_date(event: Event) -> str:
    if event.parsed_date:
        return event.parsed_date.astimezone(EASTERN_TZ).strftime("%Y-%m-%d %I:%M %p %Z").strip()
    return event.date_text or "Date/time not listed"


def why_this_matters(event: Event) -> str:
    haystack = " ".join([event.title, event.location, event.summary]).lower()
    strategic = [term for term, _ in matching_terms(haystack, STRATEGIC_TERMS)[:4]]
    audience = [term for term, _ in matching_terms(haystack, AUDIENCE_TERMS)[:3]]
    value_terms = [term for term, _ in matching_terms(haystack, BUSINESS_VALUE_TERMS)[:3]]
    city = next((city.title() for city in TARGET_CITIES if city in haystack), event.location or "South Florida")
    title_context = event.title.strip()

    reasons: list[str] = []
    if strategic:
        reasons.append(f"matches priority services ({', '.join(strategic)})")
    if audience:
        reasons.append(f"signals a senior or buyer-adjacent audience ({', '.join(audience)})")
    if value_terms:
        reasons.append(f"has BD value cues ({', '.join(value_terms)})")
    if any(city.lower() in haystack for city in TARGET_CITIES):
        reasons.append(f"is in the target South Florida market ({city})")

    if any(term in haystack for term in ["aws", "amazon web services", "azure", "cloud"]):
        angle = "AWS/Azure modernization, migration, and managed-cloud conversations"
    elif any(term in haystack for term in ["agentic", "ai", "artificial intelligence"]):
        angle = "AI delivery, agentic workflow, data readiness, and governance offers"
    elif any(term in haystack for term in ["cybersecurity", "cyber security", "devops"]):
        angle = "secure DevOps, cloud security, and compliance-led consulting conversations"
    elif any(term in haystack for term in ["founder", "startup", "startups", "vc", "venture capital", "saas"]):
        angle = "founder, SaaS, and investor relationships that can create cloud architecture or fractional engineering demand"
    elif any(term in haystack for term in ["enterprise", "cto", "cio", "cpo", "product", "engineering"]):
        angle = "enterprise technology leadership networking and account-development discovery"
    else:
        angle = "local relationship-building, but the buyer fit should be validated before committing senior time"

    if reasons:
        return f"{title_context} {', '.join(reasons)}. Best angle: {angle}."
    return f"{title_context} has limited listing detail. Use it only if the attendee list confirms cloud, AI, SaaS, cybersecurity, startup, or enterprise technology buyers."


def suggested_action(event: Event) -> str:
    haystack = " ".join([event.title, event.location, event.summary]).lower()
    if event.score >= 8 and any(term in haystack for term in ["conference", "summit", "aws", "azure", "enterprise"]):
        return "Explore sponsorship"
    if event.score >= 8 and any(term in haystack for term in ["cto", "cpo", "cio", "founder", "executive", "leadership", "enterprise"]):
        return "Attend personally"
    if event.score >= 7 and any(term in haystack for term in ["ai", "agentic", "cloud", "aws", "azure", "devops", "cybersecurity", "data", "engineering"]):
        return "Send technical person"
    if event.score >= 5:
        return "Send AE"
    return "Ignore"


def write_digest(events: list[Event], errors: list[str]) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# South Florida Tech Events Weekly Digest",
        "",
        f"Generated: {generated_at}",
        "",
        "Executive focus: business-development opportunities for a cloud consulting company across Miami, Fort Lauderdale, Boca Raton, and West Palm Beach.",
        "",
    ]

    if events:
        lines.extend(["## Top 3 Recommendations", ""])
        for index, event in enumerate(events[:3], start=1):
            lines.extend([
                f"### {index}. {event.title}",
                f"- **Event name:** {event.title}",
                f"- **Date and time:** {format_date(event)}",
                f"- **Location:** {event.location or 'Location not listed'}",
                f"- **Relevance score:** {event.score}/10",
                f"- **Why it matters:** {why_this_matters(event)}",
                f"- **Suggested action:** {suggested_action(event)}",
                f"- **URL:** {event.url}",
                "",
            ])

        lines.extend(["## Recommended next steps", ""])
        for event in events[:3]:
            lines.append(f"- {suggested_action(event)} for {event.title}.")
        lines.append("")

        lines.extend(["## Prioritized Events", ""])
        for index, event in enumerate(events, start=1):
            lines.extend([
                f"### {index}. {event.title}",
                f"- **Event name:** {event.title}",
                f"- **Date and time:** {format_date(event)}",
                f"- **Location:** {event.location or 'Location not listed'}",
                f"- **Source:** {event.source}",
                f"- **URL:** {event.url}",
                f"- **Relevance score:** {event.score}/10",
                f"- **Why this matters for a cloud consulting company:** {why_this_matters(event)}",
                f"- **Suggested action:** {suggested_action(event)}",
                "",
            ])
    else:
        lines.extend([
            "## Top 3 Recommendations",
            "",
            "No qualifying business-development events were found in this run.",
            "",
            "## Recommended next steps",
            "",
            "- Add more source pages or rerun later before scheduling outreach.",
            "",
            "## Prioritized Events",
            "",
            "No matching events were found from the configured public sources. Try adding more sources to `sources.yaml` or rerun later.",
            "",
        ])

    lines.extend(["## Sources", "", "Edit `sources.yaml` to add or remove public event pages."])
    if errors:
        lines.extend(["", "## Source notes", ""])
        lines.extend(f"- {error}" for error in errors)
        lines.append("")
    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")


def source_note(source: dict[str, Any], exc: requests.RequestException) -> str:
    name = source.get("name", source.get("url", "Unknown source"))
    status = getattr(exc.response, "status_code", None)
    if status:
        return f"{name} was skipped because the public event page was unavailable to the scraper this run."
    return f"{name} was skipped because it could not be reached this run."


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
            errors.append(source_note(source, exc))

    events = sorted(events_by_id.values(), key=lambda event: (-event.score, event.parsed_date or datetime.max.replace(tzinfo=timezone.utc), event.title.lower()))[:25]
    write_digest(events, errors)
    print(f"Wrote {OUTPUT_FILE.relative_to(ROOT)} with {len(events)} event(s).")


if __name__ == "__main__":
    main()
