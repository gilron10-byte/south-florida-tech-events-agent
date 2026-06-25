from __future__ import annotations

import hashlib
import json
import os
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
LAST_SUCCESSFUL_EVENTS_FILE = ROOT / "data" / "last_successful_events.json"

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
    recurring_count: int = 1
    confidence: str = "high"

    @property
    def event_id(self) -> str:
        return hashlib.sha256(f"{self.title}|{self.url}".encode()).hexdigest()[:16]


@dataclass
class RunDiagnostics:
    sources_fetched_successfully: list[str]
    sources_skipped: list[str]
    raw_events_found: int = 0
    events_after_filtering: int = 0
    events_after_deduplication: int = 0
    fallback_cache_used: bool = False
    fallback_reason: str = ""
    eventbrite_direct_scraping: str = "disabled"
    eventbrite_search_discovery: str = "disabled"
    eventbrite_candidates_found: int = 0


def load_sources() -> list[dict[str, Any]]:
    with SOURCES_FILE.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    return config.get("sources", [])


def source_name(source: dict[str, Any]) -> str:
    return source.get("name", source.get("url", "Unknown source"))


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



def is_eventbrite_event_url(url: str) -> bool:
    return "eventbrite.com/e/" in url.lower()


def search_api_results(query: str, max_results: int) -> list[dict[str, str]]:
    """Return normalized web-search results from a JSON search API.

    The default endpoint is SerpAPI's Google Search API because it accepts a
    simple api_key/q contract. SEARCH_API_URL can override that endpoint for
    compatible providers in tests or deployments.
    """
    api_key = os.environ.get("SEARCH_API_KEY", "").strip()
    if not api_key:
        return []
    endpoint = os.environ.get("SEARCH_API_URL", "https://serpapi.com/search.json")
    params = {"q": query, "api_key": api_key, "num": max_results}
    response = requests.get(endpoint, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    containers = [
        payload.get("organic_results"),
        payload.get("results"),
        payload.get("items"),
        payload.get("webPages", {}).get("value") if isinstance(payload.get("webPages"), dict) else None,
    ]
    normalized: list[dict[str, str]] = []
    for container in containers:
        if not isinstance(container, list):
            continue
        for item in container:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or item.get("url") or item.get("displayLink") or "")
            title = str(item.get("title") or item.get("name") or "")
            snippet = str(item.get("snippet") or item.get("description") or item.get("summary") or "")
            if url and title:
                normalized.append({"url": url, "title": title, "snippet": snippet})
            if len(normalized) >= max_results:
                return normalized
        if normalized:
            break
    return normalized[:max_results]


def fetch_eventbrite_event_page(candidate: Event) -> Event:
    """Best-effort enrichment for an Eventbrite event URL.

    Failures are intentionally allowed to bubble to the caller so the original
    search title/snippet can remain as a low-confidence candidate.
    """
    response = requests.get(candidate.url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    meta = soup.select_one('meta[property="og:title"], meta[name="twitter:title"]')
    title = str(meta.get("content", "")).strip() if meta else ""
    title = title or first_text(soup, ["h1", "title"]) or candidate.title
    summary_meta = soup.select_one('meta[property="og:description"], meta[name="description"]')
    summary = str(summary_meta.get("content", "")).strip() if summary_meta else ""
    summary = summary or candidate.summary
    date_text = first_text(soup, ["time", '[class*=date]', '[class*=time]'])
    location = first_text(soup, ['[class*=location]', '[class*=venue]', '[data-testid*=location]'])
    confidence = "high" if date_text or location else "medium"
    return Event(title[:180].strip(), candidate.url, "Eventbrite via Search", date_text, location, summary[:700], parse_date(date_text), confidence=confidence)


def fetch_search_discovery_source(source: dict[str, Any]) -> list[Event]:
    if not os.environ.get("SEARCH_API_KEY", "").strip():
        return []
    queries = source.get("queries") or []
    max_events = int(source.get("max_events", 25))
    per_query = max(1, int(source.get("results_per_query", 10)))
    events_by_url: dict[str, Event] = {}
    for query in queries:
        for result in search_api_results(str(query), per_query):
            url = result["url"]
            if not is_eventbrite_event_url(url):
                continue
            candidate = Event(
                title=result["title"][:180].strip(),
                url=url,
                source="Eventbrite via Search",
                summary=result.get("snippet", "")[:700],
                confidence="low",
            )
            try:
                candidate = fetch_eventbrite_event_page(candidate)
            except requests.RequestException:
                pass
            events_by_url.setdefault(url, candidate)
            if len(events_by_url) >= max_events:
                return list(events_by_url.values())
    return list(events_by_url.values())

def clean_text(value: str) -> str:
    """Normalize scraped text and remove duplicate fragments that can distort scoring."""
    normalized = re.sub(r"\s+", " ", value or "").strip()
    if not normalized:
        return ""
    parts = re.split(r"(?<=[.!?])\s+|\s+[•|]\s+", normalized)
    cleaned_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        part = part.strip(" -–—•|\t\n")
        if len(part) < 3:
            continue
        key = re.sub(r"\W+", " ", part.lower()).strip()
        if key and key not in seen:
            cleaned_parts.append(part)
            seen.add(key)
    return " ".join(cleaned_parts)


def clean_summary(event: Event) -> str:
    """Return summary text without title/date/location boilerplate."""
    summary = clean_text(event.summary)
    for duplicate in [event.title, event.date_text, event.location]:
        duplicate = clean_text(duplicate)
        if duplicate:
            summary = re.sub(re.escape(duplicate), " ", summary, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", summary).strip()[:500]


def contains_term(text: str, term: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
    return bool(re.search(pattern, text.lower()))


def matching_terms(haystack: str, weighted_terms: dict[str, int]) -> list[tuple[str, int]]:
    return [(term, weight) for term, weight in weighted_terms.items() if contains_term(haystack, term)]


def event_text(event: Event) -> str:
    return " ".join([event.title, event.location, clean_summary(event)]).lower()


def event_field_text(event: Event) -> tuple[str, str, str]:
    return event.title.lower(), event.location.lower(), clean_summary(event).lower()


def normalized_title(title: str) -> str:
    """Normalize titles so recurring instances collapse into one digest item."""
    normalized = re.sub(r"\s+", " ", title).strip().lower()
    normalized = re.sub(r"\s*[-–—|]\s*\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\s*$", "", normalized)
    normalized = re.sub(r"\s*\(?\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:,\s*\d{4})?\)?\s*$", "", normalized)
    return normalized


def is_event_page(event: Event) -> bool:
    """Skip generic source, directory, and submission pages masquerading as cards."""
    haystack = event_text(event)
    generic_page_terms = [
        "submit an event",
        "add an event",
        "events calendar",
        "tech hub events",
        "view all events",
    ]
    if any(term in haystack for term in generic_page_terms):
        return False
    if event.source == "Eventbrite via Search" and is_eventbrite_event_url(event.url):
        return bool(event.title.strip() and clean_summary(event).strip())
    return bool(event.date_text.strip() or event.location.strip())


EXECUTIVE_BUYER_TERMS = [
    "cto", "cpo", "cio", "ciso", "chief", "vp", "vice president", "director",
    "product leader", "product leaders", "engineering leader", "engineering leaders",
    "executive", "buyer", "decision maker", "decision makers",
]
STRATEGIC_TECHNICAL_TERMS = [
    "ai", "artificial intelligence", "agentic", "cloud", "aws", "amazon web services",
    "azure", "devops", "cybersecurity", "cyber security", "data", "saas",
]
STARTUP_FOUNDER_TERMS = ["founder", "startup", "startups", "vc", "venture capital", "fintech", "saas"]
GENERIC_NETWORKING_TERMS = ["networking", "connect", "happy hour", "mixer", "recurring meetup", "community event", "social"]


def contains_any(text: str, terms: list[str]) -> bool:
    return any(contains_term(text, term) for term in terms)


def has_title_terms(event: Event, terms: list[str]) -> bool:
    return contains_any(event.title.lower(), terms)


def has_executive_audience(event: Event) -> bool:
    title, location, summary = event_field_text(event)
    return contains_any(title, EXECUTIVE_BUYER_TERMS) or contains_any(summary, EXECUTIVE_BUYER_TERMS)


def has_strategic_technical_topic(event: Event) -> bool:
    title, location, summary = event_field_text(event)
    return contains_any(title, STRATEGIC_TECHNICAL_TERMS) or contains_any(summary, STRATEGIC_TECHNICAL_TERMS)


def has_startup_founder_topic(event: Event) -> bool:
    title, location, summary = event_field_text(event)
    return contains_any(title, STARTUP_FOUNDER_TERMS) or contains_any(summary, STARTUP_FOUNDER_TERMS)


def is_generic_networking(event: Event) -> bool:
    title, location, summary = event_field_text(event)
    text = " ".join([title, summary])
    clearly_strategic_title = has_title_terms(event, EXECUTIVE_BUYER_TERMS + STRATEGIC_TECHNICAL_TERMS + STARTUP_FOUNDER_TERMS + ["enterprise"])
    return contains_any(text, GENERIC_NETWORKING_TERMS) and not clearly_strategic_title


def is_recurring_generic_networking(event: Event) -> bool:
    title = event.title.lower()
    return is_generic_networking(event) and (event.recurring_count > 1 or contains_any(title, ["every ", "weekly", "monthly", "recurring", "mondays", "tuesdays", "wednesdays", "thursdays", "fridays"]))


def event_category(event: Event) -> str:
    if has_executive_audience(event):
        return "executive/buyer"
    if has_strategic_technical_topic(event):
        if has_title_terms(event, ["agentic", "ai", "artificial intelligence"]):
            return "ai/agentic"
        if has_title_terms(event, ["aws", "amazon web services", "azure", "cloud", "devops"]):
            return "cloud/devops"
        if has_title_terms(event, ["cybersecurity", "cyber security"]):
            return "cybersecurity"
        return "strategic technical"
    if has_startup_founder_topic(event):
        return "startup/founder"
    if is_generic_networking(event):
        return "generic networking"
    return "technology/business"


def weighted_field_score(event: Event, terms: dict[str, int]) -> int:
    title, location, summary = event_field_text(event)
    return (
        sum(weight * 4 for _, weight in matching_terms(title, terms))
        + sum(weight * 2 for _, weight in matching_terms(location, terms))
        + sum(weight for _, weight in matching_terms(summary, terms))
    )


def score_event(event: Event) -> int:
    """Return a directional 1-10 business-development relevance score."""
    title, location, summary = event_field_text(event)
    raw_score = 12
    raw_score += weighted_field_score(event, STRATEGIC_TERMS)
    raw_score += weighted_field_score(event, AUDIENCE_TERMS)
    raw_score += weighted_field_score(event, BUSINESS_VALUE_TERMS)
    raw_score += weighted_field_score(event, LOW_VALUE_TERMS)
    raw_score += sum(weight * 2 for _, weight in matching_terms(location, TARGET_CITIES))

    executive = has_executive_audience(event)
    strategic = has_strategic_technical_topic(event)
    startup = has_startup_founder_topic(event)
    generic = is_generic_networking(event)

    if has_title_terms(event, EXECUTIVE_BUYER_TERMS):
        raw_score += 24
    elif executive:
        raw_score += 14
    if has_title_terms(event, STRATEGIC_TECHNICAL_TERMS):
        raw_score += 18
    elif strategic:
        raw_score += 8
    if startup and strategic:
        raw_score += 14
    elif startup:
        raw_score += 6
    if generic:
        raw_score -= 18
    if is_recurring_generic_networking(event):
        raw_score -= 8
    if not event.location.strip():
        raw_score -= 8
    if not clean_summary(event) or len(clean_summary(event)) < 80:
        raw_score -= 3
    if event.parsed_date:
        now = datetime.now(timezone.utc)
        if now <= event.parsed_date <= now + timedelta(days=21):
            raw_score += 4
        elif event.parsed_date < now - timedelta(days=1):
            raw_score -= 8

    if event.confidence == "low":
        raw_score -= 18
    elif event.confidence == "medium":
        raw_score -= 6

    score = max(1, min(10, round(raw_score / 14)))
    if generic and not has_title_terms(event, EXECUTIVE_BUYER_TERMS + STRATEGIC_TECHNICAL_TERMS + STARTUP_FOUNDER_TERMS + ["enterprise"]):
        score = min(score, 6)
    return score

def keep_event(event: Event) -> bool:
    if not is_event_page(event):
        return False
    haystack = event_text(event)
    has_strategic_term = any(term in haystack for term in STRATEGIC_TERMS)
    has_target_city = any(city in haystack for city in TARGET_CITIES)
    if has_strategic_technical_topic(event) and (has_target_city or event.score >= 5):
        return event.score >= 3
    return event.score >= 3 and has_strategic_term and (has_target_city or event.score >= 6)


def deduplicate_recurring_events(events: list[Event]) -> list[Event]:
    """Keep only the strongest next instance for duplicate recurring titles."""
    grouped: dict[str, list[Event]] = {}
    for event in events:
        grouped.setdefault(normalized_title(event.title), []).append(event)

    deduped: list[Event] = []
    now = datetime.now(timezone.utc)
    distant_future = datetime.max.replace(tzinfo=timezone.utc)
    for instances in grouped.values():
        ranked_instances = sorted(
            instances,
            key=lambda event: (
                event.parsed_date is None,
                event.parsed_date < now if event.parsed_date else False,
                abs((event.parsed_date - now).total_seconds()) if event.parsed_date else float("inf"),
                -event.score,
            ),
        )
        selected = ranked_instances[0]
        selected.score = max(instance.score for instance in instances)
        selected.recurring_count = len(instances)
        if selected.parsed_date is None:
            dated_instances = [instance for instance in instances if instance.parsed_date]
            if dated_instances:
                selected.parsed_date = min(dated_instances, key=lambda event: event.parsed_date or distant_future).parsed_date
        deduped.append(selected)
    return deduped


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


def event_to_dict(event: Event) -> dict[str, Any]:
    return {
        "title": event.title,
        "url": event.url,
        "source": event.source,
        "date_text": event.date_text,
        "location": event.location,
        "summary": event.summary,
        "parsed_date": event.parsed_date.isoformat() if event.parsed_date else None,
        "score": event.score,
        "recurring_count": event.recurring_count,
        "confidence": event.confidence,
    }


def event_from_dict(data: dict[str, Any]) -> Event:
    parsed_date = None
    if data.get("parsed_date"):
        try:
            parsed_date = datetime.fromisoformat(data["parsed_date"])
        except ValueError:
            parsed_date = parse_date(data.get("date_text", ""))
    return Event(
        title=str(data.get("title", "")),
        url=str(data.get("url", "")),
        source=str(data.get("source", "Fallback cache")),
        date_text=str(data.get("date_text", "")),
        location=str(data.get("location", "")),
        summary=str(data.get("summary", "")),
        parsed_date=parsed_date,
        score=int(data.get("score", 0)),
        recurring_count=int(data.get("recurring_count", 1)),
        confidence=str(data.get("confidence", "high")),
    )


def save_last_successful_events(events: list[Event]) -> None:
    LAST_SUCCESSFUL_EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "events": [event_to_dict(event) for event in events],
    }
    LAST_SUCCESSFUL_EVENTS_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_last_successful_events() -> list[Event]:
    if not LAST_SUCCESSFUL_EVENTS_FILE.exists():
        return []
    try:
        data = json.loads(LAST_SUCCESSFUL_EVENTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    events_data = data.get("events", []) if isinstance(data, dict) else data
    if not isinstance(events_data, list):
        return []
    return [event_from_dict(item) for item in events_data if isinstance(item, dict)]


def format_date(event: Event) -> str:
    recurring_note = " (recurring event; next listed instance)" if event.recurring_count > 1 else ""
    if event.parsed_date:
        return event.parsed_date.astimezone(EASTERN_TZ).strftime("%Y-%m-%d %I:%M %p %Z").strip() + recurring_note
    return (event.date_text or "Date/time not listed") + recurring_note


def ranking_key(event: Event) -> tuple[int, int, int, int, int, datetime, str]:
    """Sort strongest buyer/strategic events ahead of generic networking."""
    category_priority = 0
    if has_executive_audience(event):
        category_priority = 4
    elif has_strategic_technical_topic(event):
        category_priority = 3
    elif has_startup_founder_topic(event):
        category_priority = 2
    elif is_generic_networking(event):
        category_priority = -1
    title_bonus = 0
    if has_title_terms(event, EXECUTIVE_BUYER_TERMS):
        title_bonus += 3
    if has_title_terms(event, STRATEGIC_TECHNICAL_TERMS):
        title_bonus += 2
    if has_title_terms(event, STARTUP_FOUNDER_TERMS) and has_strategic_technical_topic(event):
        title_bonus += 2
    if is_recurring_generic_networking(event):
        title_bonus -= 3
    confidence_priority = {"high": 2, "medium": 1, "low": 0}.get(event.confidence, 2)
    return (
        -category_priority,
        -confidence_priority,
        -event.score,
        -title_bonus,
        event.recurring_count if is_generic_networking(event) else 0,
        event.parsed_date or datetime.max.replace(tzinfo=timezone.utc),
        event.title.lower(),
    )


def top_recommendations(events: list[Event], limit: int = 3) -> list[Event]:
    stronger_events = [event for event in events if not is_generic_networking(event)]
    selected = sorted(stronger_events, key=ranking_key)[:limit]
    if len(selected) < limit:
        selected.extend(event for event in sorted(events, key=ranking_key) if event not in selected)
    return selected[:limit]


def readable_topics(event: Event) -> list[str]:
    text = event_text(event)
    topics: list[str] = []
    topic_map = [
        ("AI adoption", ["ai", "artificial intelligence", "agentic"]),
        ("cloud modernization", ["cloud", "aws", "amazon web services", "azure"]),
        ("DevOps and platform engineering", ["devops", "engineering"]),
        ("cybersecurity", ["cybersecurity", "cyber security"]),
        ("data strategy", ["data", "analytics"]),
        ("SaaS growth", ["saas"]),
        ("fintech", ["fintech"]),
        ("startup growth", ["startup", "startups", "founder", "vc", "venture capital"]),
    ]
    for label, terms in topic_map:
        if contains_any(text, terms) and label not in topics:
            topics.append(label)
    return topics[:3]


def join_naturally(items: list[str]) -> str:
    if not items:
        return "technology priorities"
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def why_this_matters(event: Event) -> str:
    city = next((city.title() for city in TARGET_CITIES if city in event.location.lower() or city in event.title.lower()), event.location or "South Florida")
    topics = join_naturally(readable_topics(event))
    recurring_note = " Because it appears to be recurring, treat this as a repeatable coverage opportunity rather than a one-time executive commitment." if event.recurring_count > 1 else ""

    if has_executive_audience(event):
        return f"This is a strong fit because it is likely to bring senior product, technology, or business leaders together in {city}. That audience is well suited for conversations about {topics}, delivery capacity, and modernization priorities.{recurring_note}"
    if has_strategic_technical_topic(event) and has_startup_founder_topic(event):
        return f"This should rank highly because it combines {topics} with a founder or startup audience in {city}. It is a practical setting for discussing cloud architecture, AI implementation, and engineering support with teams that may be making near-term build decisions.{recurring_note}"
    if has_strategic_technical_topic(event):
        return f"This is relevant because the agenda is tied to {topics}, which maps directly to cloud consulting, AI delivery, security, data, and platform modernization conversations in {city}.{recurring_note}"
    if has_startup_founder_topic(event):
        return f"This is useful for founder and startup relationship-building in {city}, especially if attendee conversations point to SaaS, fintech, cloud, AI, or enterprise technology needs.{recurring_note}"
    if is_generic_networking(event):
        return f"This looks like broad networking in {city}. It can still create local relationships, but it should be covered by an account executive and should not take priority over executive, AI, cloud, or focused startup events.{recurring_note}"
    return f"The listing has limited strategic detail. Validate the attendee profile before committing time, and prioritize it only if cloud, AI, SaaS, cybersecurity, startup, or enterprise technology buyers are expected."


def suggested_action(event: Event) -> str:
    if is_recurring_generic_networking(event) and not has_title_terms(event, EXECUTIVE_BUYER_TERMS + STARTUP_FOUNDER_TERMS + ["enterprise"]):
        return "Send AE" if event.score >= 5 else "Track only"
    if is_generic_networking(event):
        return "Send AE"
    if has_executive_audience(event) and event.score >= 7:
        return "Attend personally"
    if has_strategic_technical_topic(event) or has_startup_founder_topic(event):
        if event.score >= 6:
            return "Send technical person" if has_strategic_technical_topic(event) else "Send senior AE"
        return "Send AE"
    if event.score >= 5:
        return "Send AE"
    return "Track only"

def write_event_sections(lines: list[str], events: list[Event], fallback: bool = False) -> None:
    if fallback:
        lines.extend([
            "## Fallback: last known relevant events",
            "",
            "Current sources failed or produced no usable events, so this section uses events saved from the previous successful run. Confirm dates and availability before outreach.",
            "",
        ])
        section_events = events
    else:
        top_events = top_recommendations(events)
        lines.extend(["## Top 3 Recommendations", ""])
        for index, event in enumerate(top_events, start=1):
            lines.extend([
                f"### {index}. {event.title}",
                f"- **Event name:** {event.title}",
                f"- **Date and time:** {format_date(event)}",
                f"- **Location:** {event.location or 'Location not listed'}",
                f"- **Source:** {event.source}",
                f"- **Confidence:** {event.confidence}",
                f"- **Relevance score:** {event.score}/10",
                f"- **Why it matters:** {why_this_matters(event)}",
                f"- **Suggested action:** {suggested_action(event)}",
                f"- **URL:** {event.url}",
                "",
            ])

        lines.extend(["## Recommended next steps", ""])
        for event in top_events:
            lines.append(f"- {suggested_action(event)} for {event.title}.")
        lines.append("")
        lines.extend(["## Prioritized Events", ""])
        section_events = events

    for index, event in enumerate(section_events, start=1):
        lines.extend([
            f"### {index}. {event.title}",
            f"- **Event name:** {event.title}",
            f"- **Date and time:** {format_date(event)}",
            f"- **Location:** {event.location or 'Location not listed'}",
            f"- **Source:** {event.source}",
            f"- **Confidence:** {event.confidence}",
            f"- **URL:** {event.url}",
            f"- **Relevance score:** {event.score}/10",
            f"- **Why this matters for a cloud consulting company:** {why_this_matters(event)}",
            f"- **Suggested action:** {suggested_action(event)}",
            "",
        ])


def write_digest(events: list[Event], errors: list[str], diagnostics: RunDiagnostics, fallback_events: list[Event] | None = None) -> None:
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
        write_event_sections(lines, events)
    elif fallback_events:
        lines.extend([
            "## Top 3 Recommendations",
            "",
            "No fresh qualifying events were available from this run, but source failures occurred and cached events exist.",
            "",
        ])
        write_event_sections(lines, fallback_events, fallback=True)
    else:
        if diagnostics.sources_skipped:
            reason = "One or more sources failed or were skipped, and no fallback cache was available."
        elif diagnostics.raw_events_found and diagnostics.events_after_filtering == 0:
            reason = "Sources returned raw items, but the event filters removed them as non-events, generic pages, duplicates, or low-relevance listings."
        else:
            reason = "All enabled sources were fetched, but they did not expose any raw event cards to the scraper."
        lines.extend([
            "## Top 3 Recommendations",
            "",
            "No qualifying business-development events were found in this run.",
            f"Reason: {reason}",
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
    lines.extend([
        "## Run diagnostics",
        "",
        f"- **Sources fetched successfully:** {', '.join(diagnostics.sources_fetched_successfully) if diagnostics.sources_fetched_successfully else 'None'}",
        f"- **Sources skipped:** {', '.join(diagnostics.sources_skipped) if diagnostics.sources_skipped else 'None'}",
        f"- **Eventbrite direct scraping:** {diagnostics.eventbrite_direct_scraping}",
        f"- **Eventbrite search discovery:** {diagnostics.eventbrite_search_discovery}",
        f"- **Number of Eventbrite candidates found:** {diagnostics.eventbrite_candidates_found}",
        f"- **Number of raw events found:** {diagnostics.raw_events_found}",
        f"- **Number of events after filtering:** {diagnostics.events_after_filtering}",
        f"- **Number of events after deduplication:** {diagnostics.events_after_deduplication}",
        f"- **Fallback cache was used:** {'Yes' if diagnostics.fallback_cache_used else 'No'}",
    ])
    if diagnostics.fallback_reason:
        lines.append(f"- **Fallback reason:** {diagnostics.fallback_reason}")
    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")


def source_note(source: dict[str, Any], exc: requests.RequestException) -> str:
    name = source_name(source)
    status = getattr(exc.response, "status_code", None)
    if status:
        return f"{name} was skipped because the public event page was unavailable to the scraper this run."
    return f"{name} was skipped because it could not be reached this run."


def main() -> None:
    sources = load_sources()
    seen_event_ids = load_seen_event_ids()
    errors: list[str] = []
    diagnostics = RunDiagnostics(sources_fetched_successfully=[], sources_skipped=[])
    events_by_id: dict[str, Event] = {}

    for source in sources:
        if source.get("type") == "search_discovery":
            if not os.environ.get("SEARCH_API_KEY", "").strip():
                diagnostics.eventbrite_search_discovery = "disabled"
                diagnostics.sources_skipped.append(f"{source_name(source)} (missing SEARCH_API_KEY)")
                continue
            diagnostics.eventbrite_search_discovery = "enabled"
            try:
                fetched_events = fetch_search_discovery_source(source)
                diagnostics.sources_fetched_successfully.append(source_name(source))
                diagnostics.raw_events_found += len(fetched_events)
                diagnostics.eventbrite_candidates_found += len(fetched_events)
                for event in fetched_events:
                    event.score = score_event(event)
                    if event.event_id not in seen_event_ids and keep_event(event):
                        events_by_id[event.event_id] = event
            except requests.RequestException as exc:
                diagnostics.sources_skipped.append(source_name(source))
                errors.append(source_note(source, exc))
            continue
        if "eventbrite.com" in str(source.get("url", "")).lower():
            diagnostics.eventbrite_direct_scraping = "enabled" if source.get("enabled", True) is not False else "disabled"
        if source.get("enabled", True) is False:
            diagnostics.sources_skipped.append(f"{source_name(source)} (disabled)")
            continue
        try:
            fetched_events = fetch_source(source)
            diagnostics.sources_fetched_successfully.append(source_name(source))
            diagnostics.raw_events_found += len(fetched_events)
            for event in fetched_events:
                event.score = score_event(event)
                if event.event_id not in seen_event_ids and keep_event(event):
                    events_by_id[event.event_id] = event
        except requests.RequestException as exc:
            diagnostics.sources_skipped.append(source_name(source))
            errors.append(source_note(source, exc))

    diagnostics.events_after_filtering = len(events_by_id)
    unique_events = deduplicate_recurring_events(list(events_by_id.values()))
    diagnostics.events_after_deduplication = len(unique_events)
    events = sorted(unique_events, key=ranking_key)[:25]
    fallback_events: list[Event] = []
    if events:
        save_last_successful_events(events)
    elif errors:
        fallback_events = load_last_successful_events()
        if fallback_events:
            diagnostics.fallback_cache_used = True
            diagnostics.fallback_reason = "No fresh events were found while one or more sources failed or were skipped."
    write_digest(events, errors, diagnostics, fallback_events)
    print(f"Wrote {OUTPUT_FILE.relative_to(ROOT)} with {len(events)} event(s).")


if __name__ == "__main__":
    main()
