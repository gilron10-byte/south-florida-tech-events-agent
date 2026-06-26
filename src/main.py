from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

ROOT = Path(__file__).resolve().parents[1]
SOURCES_FILE = ROOT / "sources.yaml"
MARKETS_FILE = ROOT / "markets.yaml"
GLOBAL_SUMMARY_FILE = ROOT / "output" / "global_weekly_summary.md"
EASTERN_TZ = ZoneInfo("America/New_York")
SEEN_EVENTS_FILE = ROOT / "data" / "seen_events.json"
LAST_SUCCESSFUL_EVENTS_FILE = ROOT / "data" / "last_successful_events.json"

TARGET_CITIES = {
    "miami": 4, "miami beach": 4, "fort lauderdale": 4, "boca raton": 4,
    "west palm beach": 4, "palm beach": 2, "south florida": 2,
}
STRATEGIC_TERMS = {
    "aws": 8, "amazon web services": 8, "azure": 8, "microsoft": 5,
    "google cloud": 8, "gcp": 8, "cloud": 7, "cloud computing": 7,
    "agentic": 7, "agent": 4, "genai": 7, "ai": 6, "artificial intelligence": 6,
    "cybersecurity": 6, "cyber security": 6, "security": 4, "devops": 6,
    "data": 5, "analytics": 4, "saas": 5, "isv": 5, "startup": 5,
    "startups": 5, "founder": 5, "vc": 5, "venture capital": 5, "cto": 5,
    "cio": 5, "cpo": 5, "ciso": 5, "enterprise": 5, "product": 4,
    "engineering": 4, "engineer": 3, "partner": 4, "migration": 4,
    "modernization": 4, "microsoft for startups": 7, "google for startups": 7,
    "aws startups": 7, "israeli": 4, "jewish": 3, "israel": 3,
}
AUDIENCE_TERMS = {
    "executive": 4, "leadership": 4, "c-level": 4, "decision maker": 4,
    "founder": 4, "investor": 4, "enterprise": 4, "cto": 5, "cio": 5,
    "cpo": 5, "ciso": 5, "vp": 3, "director": 3,
}
BUSINESS_VALUE_TERMS = {"partner": 4, "partnership": 4, "customer": 4, "client": 4, "networking": 3, "summit": 3, "conference": 3, "roundtable": 3, "workshop": 2, "meetup": 2, "aws": 4, "azure": 4}
LOW_VALUE_TERMS = {"social": -5, "party": -5, "happy hour": -4, "consumer": -5, "concert": -8, "festival": -6, "yoga": -8, "market": -4, "student only": -8, "students only": -8, "for students": -5, "career fair": -3, "unclear": -3, "webinar": -2, "online": -2}
USER_AGENT = "TechEventsIntelligenceAgent/1.0 (+https://github.com/)"
DEFAULT_SEARCH_API_URL = "https://serpapi.com/search.json"
SECRET_QUERY_PARAMS = {"api_key", "apikey", "key", "token", "access_token", "secret", "password"}


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
    market_id: str = "south_florida"
    discovery_group: str = "Primary sources"
    category: str = "Other search discovery"
    missing_fields: list[str] = field(default_factory=list)
    review_reason: str = ""
    is_candidate: bool = False

    @property
    def event_id(self) -> str:
        return hashlib.sha256(f"{self.market_id}|{self.title}|{self.url}".encode()).hexdigest()[:16]


@dataclass
class RunDiagnostics:
    sources_fetched_successfully: list[str]
    sources_skipped: list[str]
    market_name: str = "South Florida"
    raw_events_found: int = 0
    events_after_filtering: int = 0
    events_after_deduplication: int = 0
    fallback_cache_used: bool = False
    fallback_reason: str = ""
    eventbrite_direct_scraping: str = "disabled"
    eventbrite_search_discovery: str = "disabled"
    eventbrite_candidates_found: int = 0
    search_api_endpoint_host: str = "not used"
    search_queries_attempted: int = 0
    search_api_responses_received: int = 0
    eventbrite_urls_found_before_filtering: int = 0
    blocked_missing_invalid_location: int = 0
    blocked_wrong_market: int = 0
    blocked_low_confidence: int = 0
    blocked_generic_page: int = 0
    promoted_to_main_digest: int = 0
    high_priority_candidates_to_verify: int = 0
    discarded_past_date: int = 0
    discarded_stale_year: int = 0
    discarded_uncertain_date: int = 0
    discarded_historical_content: int = 0
    verified_future_events_found: int = 0
    high_priority_future_candidates_found: int = 0
    blocked_only_missing_location: int = 0
    promoted_to_high_priority_verification: int = 0
    high_priority_candidates: list[Event] = field(default_factory=list)
    group_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    cloud_stats: dict[str, int] = field(default_factory=lambda: {"aws_queries": 0, "aws_candidates": 0, "gcp_queries": 0, "gcp_candidates": 0, "azure_queries": 0, "azure_candidates": 0})


def default_market() -> dict[str, Any]:
    return {"id":"south_florida","name":"South Florida","timezone":"America/New_York","cities":["Miami","Miami Beach","Fort Lauderdale","Boca Raton","West Palm Beach","Palm Beach","South Florida"],"output_file":"output/south_florida_weekly_digest.md","cache_file":"data/last_successful_events.json","primary_sources":load_sources(),"discovery_groups":[]}


def load_sources() -> list[dict[str, Any]]:
    if not SOURCES_FILE.exists():
        return []
    return (yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8")) or {}).get("sources", [])


def load_markets() -> list[dict[str, Any]]:
    if not MARKETS_FILE.exists():
        return [default_market()]
    config = yaml.safe_load(MARKETS_FILE.read_text(encoding="utf-8")) or {}
    return config.get("markets", [])


def source_name(source: dict[str, Any]) -> str:
    return source.get("name", source.get("url", "Unknown source"))


def text_or_empty(node: Any) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def first_text(card: Any, selectors: list[str | None]) -> str:
    for selector in selectors:
        if selector:
            value = text_or_empty(card.select_one(selector))
            if value:
                return value
    return ""


def first_link(card: Any, source_url: str, selector: str | None = None) -> str:
    candidates = [card.select_one(selector)] if selector else []
    candidates.extend(card.select("a[href]"))
    for candidate in candidates:
        if candidate and candidate.get("href"):
            href = candidate.get("href")
            if not href.startswith("#") and not href.startswith("mailto:"):
                return urljoin(source_url, href)
    return source_url


def parse_date(date_text: str, reference: datetime | None = None) -> datetime | None:
    if not date_text:
        return None
    reference = reference or datetime.now(timezone.utc)
    default = reference.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        parsed = date_parser.parse(date_text, fuzzy=True, default=default)
    except (ValueError, OverflowError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def text_has_explicit_year(text: str) -> bool:
    return bool(re.search(r"\b20\d{2}\b", text or ""))


def date_text_has_year(date_text: str) -> bool:
    return text_has_explicit_year(date_text)


def clearly_upcoming_without_year(event: Event, run_date: datetime) -> bool:
    text = f"{event.title} {event.url} {event.summary} {event.date_text}".lower()
    return any(term in text for term in ["upcoming", "register", "tickets", "save the date", "rsvp", "join us", "next ", str(run_date.year + 1)])


def infer_event_date(event: Event, run_date: datetime) -> tuple[datetime | None, bool]:
    parsed = event.parsed_date or parse_date(event.date_text, run_date)
    if not parsed:
        return None, bool(event.date_text)
    if date_text_has_year(event.date_text):
        return parsed, False
    if parsed.date() < run_date.date():
        if clearly_upcoming_without_year(event, run_date):
            return parsed.replace(year=run_date.year + 1), False
        return parsed, True
    return parsed, False


STALE_OR_HISTORICAL_TERMS = ["recap", "highlights from", "lessons learned", "recording", "youtube recap", "agenda 2025"]


def stale_or_historical_reasons(event: Event, run_date: datetime) -> tuple[bool, bool]:
    text = f"{event.title} {event.url} {event.summary}".lower()
    stale_years = [str(y) for y in range(2023, run_date.year) if y != run_date.year]
    return any(y in text for y in stale_years), any(term in text for term in STALE_OR_HISTORICAL_TERMS)


def has_stale_or_historical_content(event: Event, run_date: datetime) -> bool:
    stale_year, historical = stale_or_historical_reasons(event, run_date)
    return stale_year or historical


def is_future_event(event: Event, run_date: datetime | None = None) -> bool:
    run_date = run_date or datetime.now(timezone.utc)
    parsed, uncertain = infer_event_date(event, run_date)
    return bool(parsed and not uncertain and parsed.date() >= run_date.date())



def eligible_for_candidate_review_date(event: Event, run_date: datetime) -> bool:
    if has_stale_or_historical_content(event, run_date):
        return False
    parsed, uncertain = infer_event_date(event, run_date)
    if parsed:
        event.parsed_date = parsed
    if uncertain:
        return True
    return not parsed or parsed.date() >= run_date.date()

def apply_date_quality(event: Event, run_date: datetime, diagnostics: RunDiagnostics | None = None, allow_uncertain_review: bool = False) -> bool:
    stale_year, historical = stale_or_historical_reasons(event, run_date)
    if stale_year or historical:
        if diagnostics:
            if stale_year: diagnostics.discarded_stale_year += 1
            if historical: diagnostics.discarded_historical_content += 1
        return False
    parsed, uncertain = infer_event_date(event, run_date)
    if parsed:
        event.parsed_date = parsed
    if uncertain:
        if diagnostics: diagnostics.discarded_uncertain_date += 1
        return allow_uncertain_review
    if parsed and parsed.date() < run_date.date():
        if diagnostics: diagnostics.discarded_past_date += 1
        return False
    return True


def fetch_source(source: dict[str, Any], market: dict[str, Any] | None = None) -> list[Event]:
    url = source["url"]
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.select(source.get("event_selector") or "article, li, .event, [class*=event]") or soup.select("a[href]")
    events: list[Event] = []
    for card in cards[: int(source.get("max_events", 25)) * 3]:
        title = (first_text(card, [source.get("title_selector", ""), "h1", "h2", "h3", "h4", "a"]) or text_or_empty(card))[:180].strip()
        if len(title) < 6:
            continue
        date_text = first_text(card, [source.get("date_selector", ""), "time", ".date", "[class*=date]", "[datetime]"])
        location = first_text(card, [source.get("location_selector", ""), ".location", "[class*=location]", "[class*=venue]"])
        event = Event(title, first_link(card, url, source.get("link_selector")), source_name(source), date_text, location, text_or_empty(card)[:700], parse_date(date_text))
        if market:
            event.market_id = market["id"]
            event.discovery_group = "Primary sources"
        events.append(normalize_event_location(event))
        if len(events) >= int(source.get("max_events", 25)):
            break
    return events


def is_eventbrite_event_url(url: str) -> bool:
    return "eventbrite.com/e/" in url.lower()


def safe_short_message(value: Any, max_length: int = 180) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_length].rstrip()


def configured_search_api_url() -> str:
    raw = os.environ.get("SEARCH_API_URL", "").strip()
    parsed = urlparse(raw)
    return raw if parsed.scheme in {"http", "https"} and parsed.netloc else DEFAULT_SEARCH_API_URL


def redact_url_query(url: str) -> str:
    parsed = urlparse(url)
    params = [(k, "[REDACTED]" if k.lower() in SECRET_QUERY_PARAMS else v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)]
    return urlunparse(parsed._replace(query=urlencode(params)))


class SearchDiscoveryError(requests.RequestException):
    def __init__(self, message: str, response: requests.Response | None = None) -> None:
        super().__init__(message, response=response)
        self.safe_message = safe_short_message(message)


def search_api_results(query: str, max_results: int, diagnostics: RunDiagnostics | None = None) -> list[dict[str, str]]:
    api_key = os.environ.get("SEARCH_API_KEY", "").strip()
    if not api_key:
        return []
    endpoint = configured_search_api_url()
    if diagnostics:
        diagnostics.search_api_endpoint_host = urlparse(endpoint).netloc or "unknown"
        diagnostics.search_queries_attempted += 1
    params = {"q": query, "api_key": api_key, "num": max_results}
    prepared = requests.Request("GET", endpoint, params=params).prepare()
    print(f"Using search endpoint: {redact_url_query(prepared.url or endpoint)}")
    try:
        response = requests.get(endpoint, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
    except requests.RequestException as exc:
        raise SearchDiscoveryError(safe_short_message(exc)) from exc
    if diagnostics:
        diagnostics.search_api_responses_received += 1
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    msg = safe_short_message((payload or {}).get("error") or (payload or {}).get("error_message") or (payload or {}).get("message") if isinstance(payload, dict) else "")
    if response.status_code >= 400 or msg:
        raise SearchDiscoveryError(msg or "search API returned an error response", response=response)
    containers = [payload.get("organic_results"), payload.get("results"), payload.get("items"), payload.get("webPages", {}).get("value") if isinstance(payload.get("webPages"), dict) else None]
    out: list[dict[str, str]] = []
    for container in containers:
        if isinstance(container, list):
            for item in container:
                if isinstance(item, dict):
                    url = str(item.get("link") or item.get("url") or item.get("displayLink") or "")
                    title = str(item.get("title") or item.get("name") or "")
                    snippet = str(item.get("snippet") or item.get("description") or item.get("summary") or "")
                    if url and title:
                        out.append({"url": url, "title": title, "snippet": snippet})
                if len(out) >= max_results:
                    return out
            if out:
                break
    return out[:max_results]


def fetch_eventbrite_event_page(candidate: Event) -> Event:
    response = requests.get(candidate.url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    meta = soup.select_one('meta[property="og:title"], meta[name="twitter:title"]')
    title = str(meta.get("content", "")).strip() if meta else ""
    title = title or first_text(soup, ["h1", "title"]) or candidate.title
    summary_meta = soup.select_one('meta[property="og:description"], meta[name="description"]')
    summary = str(summary_meta.get("content", "")).strip() if summary_meta else candidate.summary
    date_text = first_text(soup, ["time", "[class*=date]", "[class*=time]"])
    location = first_text(soup, ["[class*=location]", "[class*=venue]", "[data-testid*=location]"])
    candidate.title, candidate.summary, candidate.date_text, candidate.location = title[:180], summary[:700], date_text, clean_location(location)
    candidate.parsed_date = parse_date(date_text)
    candidate.confidence = "high" if date_text and location else "medium" if date_text or location else "low"
    return candidate


def clean_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value or "").strip()
    parts = re.split(r"(?<=[.!?])\s+|\s+[•|]\s+", normalized)
    seen: set[str] = set(); out: list[str] = []
    for part in parts:
        key = re.sub(r"\W+", " ", part.lower()).strip()
        if len(key) >= 3 and key not in seen:
            out.append(part.strip(" -–—•|\t\n")); seen.add(key)
    return " ".join(out)


def clean_summary(event: Event) -> str:
    summary = clean_text(event.summary)
    for dup in [event.title, event.date_text, event.location]:
        if clean_text(dup):
            summary = re.sub(re.escape(clean_text(dup)), " ", summary, flags=re.I)
    return re.sub(r"\s+", " ", summary).strip()[:500]


def contains_term(text: str, term: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])", text.lower()))


def contains_any(text: str, terms: list[str]) -> bool:
    return any(contains_term(text, term) for term in terms)


def matching_terms(haystack: str, weighted_terms: dict[str, int]) -> list[tuple[str, int]]:
    return [(t, w) for t, w in weighted_terms.items() if contains_term(haystack, t)]


def event_text(event: Event) -> str:
    return " ".join([event.title, event.location, clean_summary(event)]).lower()


def clean_location(value: str) -> str:
    return "" if "autocomplete" in (value or "").lower() else re.sub(r"\s+", " ", value or "").strip()


def normalize_event_location(event: Event) -> Event:
    event.location = clean_location(event.location)
    return event


def event_field_text(event: Event) -> tuple[str, str, str]:
    return event.title.lower(), event.location.lower(), clean_summary(event).lower()


def market_city_weights(market: dict[str, Any] | None = None) -> dict[str, int]:
    if not market:
        return TARGET_CITIES
    return {str(c).lower(): 4 if i < 5 else 2 for i, c in enumerate(market.get("cities", []))}

EXECUTIVE_BUYER_TERMS = ["cto", "cpo", "cio", "ciso", "chief", "vp", "vice president", "director", "product leader", "product leaders", "engineering leader", "engineering leaders", "executive", "buyer", "decision maker", "decision makers"]
STRATEGIC_TECHNICAL_TERMS = ["ai", "artificial intelligence", "agentic", "genai", "cloud", "aws", "amazon web services", "azure", "microsoft", "google cloud", "gcp", "devops", "cybersecurity", "cyber security", "data", "saas", "isv", "migration", "modernization"]
STARTUP_FOUNDER_TERMS = ["founder", "startup", "startups", "vc", "venture capital", "fintech", "saas", "investor"]
GENERIC_NETWORKING_TERMS = ["networking", "connect", "happy hour", "mixer", "recurring meetup", "community event", "social"]
CLOUD_PROVIDER_TERMS = ["aws", "amazon web services", "azure", "microsoft", "google cloud", "gcp", "microsoft for startups", "google for startups", "aws startups"]


def has_title_terms(event: Event, terms: list[str]) -> bool: return contains_any(event.title.lower(), terms)
def has_executive_audience(event: Event) -> bool: return contains_any(" ".join(event_field_text(event)[::2]), EXECUTIVE_BUYER_TERMS)
def has_strategic_technical_topic(event: Event) -> bool: return contains_any(" ".join([event.title.lower(), clean_summary(event).lower()]), STRATEGIC_TECHNICAL_TERMS)
def has_startup_founder_topic(event: Event) -> bool: return contains_any(" ".join([event.title.lower(), clean_summary(event).lower()]), STARTUP_FOUNDER_TERMS)
def is_cloud_provider_event(event: Event) -> bool: return contains_any(event_text(event), CLOUD_PROVIDER_TERMS)
def is_generic_networking(event: Event) -> bool:
    return contains_any(" ".join([event.title.lower(), clean_summary(event).lower()]), GENERIC_NETWORKING_TERMS) and not has_title_terms(event, EXECUTIVE_BUYER_TERMS + STRATEGIC_TECHNICAL_TERMS + STARTUP_FOUNDER_TERMS + ["enterprise"])
def is_recurring_generic_networking(event: Event) -> bool:
    return is_generic_networking(event) and (event.recurring_count > 1 or contains_any(event.title.lower(), ["every ", "weekly", "monthly", "recurring", "mondays", "tuesdays", "wednesdays", "thursdays", "fridays"]))


def weighted_field_score(event: Event, terms: dict[str, int]) -> int:
    title, location, summary = event_field_text(event)
    return sum(w*4 for _,w in matching_terms(title, terms)) + sum(w*2 for _,w in matching_terms(location, terms)) + sum(w for _,w in matching_terms(summary, terms))


def score_event(event: Event, market: dict[str, Any] | None = None) -> int:
    raw = 12 + weighted_field_score(event, STRATEGIC_TERMS) + weighted_field_score(event, AUDIENCE_TERMS) + weighted_field_score(event, BUSINESS_VALUE_TERMS) + weighted_field_score(event, LOW_VALUE_TERMS)
    raw += sum(w*2 for _, w in matching_terms(event.location.lower() + " " + event.title.lower() + " " + clean_summary(event).lower(), market_city_weights(market)))
    if has_title_terms(event, EXECUTIVE_BUYER_TERMS): raw += 24
    elif has_executive_audience(event): raw += 14
    if has_title_terms(event, STRATEGIC_TECHNICAL_TERMS): raw += 18
    elif has_strategic_technical_topic(event): raw += 8
    if has_startup_founder_topic(event) and has_strategic_technical_topic(event): raw += 14
    elif has_startup_founder_topic(event): raw += 6
    if is_cloud_provider_event(event): raw += 10
    if is_generic_networking(event): raw -= 18
    if is_recurring_generic_networking(event): raw -= 8
    if not event.location.strip(): raw -= 8
    if not clean_summary(event) or len(clean_summary(event)) < 80: raw -= 3
    if event.parsed_date:
        now = datetime.now(timezone.utc)
        raw += 4 if now <= event.parsed_date <= now + timedelta(days=21) else -8 if event.parsed_date < now - timedelta(days=1) else 0
    raw += {"low": -18, "medium": -6}.get(event.confidence, 0)
    score = max(1, min(10, round(raw / 14)))
    if is_generic_networking(event) and not has_title_terms(event, EXECUTIVE_BUYER_TERMS + STRATEGIC_TECHNICAL_TERMS + STARTUP_FOUNDER_TERMS + ["enterprise"]):
        score = min(score, 6)
    return score


def normalized_title(title: str) -> str:
    s = re.sub(r"\s+", " ", title).strip().lower()
    s = re.sub(r"\s*[-–—|]\s*\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\s*$", "", s)
    return re.sub(r"\s*\(?\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:,\s*\d{4})?\)?\s*$", "", s)


def is_event_page(event: Event) -> bool:
    haystack = event_text(event); url_path = urlparse(event.url).path.strip("/").lower()
    blocked = ["submit an event", "add an event", "events calendar", "view all events", "all events", "search results", "category", "home", "jobs", "careers", "press release", "resource hub", "resources", "directory", "agenda", "recap", "facebook.com", "instagram.com", "linkedin.com/posts"]
    if any(t in haystack for t in blocked): return False
    if url_path in {"", "events", "event", "search", "category", "calendar", "resources"}: return False
    if "eventbrite.com" in event.url.lower() and not is_eventbrite_event_url(event.url): return False
    return bool(event.title.strip() and (event.date_text.strip() or event.location.strip() or clean_summary(event).strip()))


OTHER_MARKET_TERMS = ["paris", "zurich", "zürich", "los angeles", "philadelphia", "san francisco", "sydney", "brisbane", "london", "toronto", "berlin"]
GENERIC_PAGE_TERMS = ["agenda", "official events", "events directory", "resource hub", "resources", "cloud resources", "meetup group", "group homepage", "facebook.com", "instagram.com", "linkedin.com/posts", "recap", "category"]


def source_host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def trusted_primary_source_match(event: Event, market: dict[str, Any]) -> bool:
    host = source_host(event.url)
    if not host:
        return False
    for source in market.get("primary_sources", []):
        source_url = str(source.get("url", ""))
        if source_url and host == source_host(source_url):
            return True
    return False


def market_match(event: Event, market: dict[str, Any]) -> bool:
    title, location, summary = event_field_text(event)
    url = event.url.lower()
    city_terms = [str(city).lower() for city in market.get("cities", [])]
    title_or_location = f"{title} {location}"
    return (
        any(contains_term(title_or_location, city) for city in city_terms)
        or trusted_primary_source_match(event, market)
        or any(contains_term(url, city.replace(" ", "-")) or contains_term(url, city.replace(" ", "")) for city in city_terms)
        or sum(1 for city in city_terms if contains_term(summary, city)) >= 1
    )


def has_wrong_market(event: Event, market: dict[str, Any]) -> bool:
    title_url = f"{event.title} {event.url}".lower()
    target = any(contains_term(title_url, str(city).lower()) for city in market.get("cities", []))
    return not target and any(contains_term(title_url, term) for term in OTHER_MARKET_TERMS if not any(contains_term(str(city).lower(), term) for city in market.get("cities", [])))


def is_generic_directory_or_resource_page(event: Event) -> bool:
    text = f"{event.title} {event.url} {clean_summary(event)}".lower()
    path = urlparse(event.url).path.strip("/").lower()
    if any(term in text for term in GENERIC_PAGE_TERMS):
        return True
    if path in {"", "events", "event", "calendar", "resources", "startup", "startups", "groups"}:
        return True
    if "meetup.com" in event.url.lower() and "/events/" not in event.url.lower():
        return True
    if "aws.amazon.com/events" in event.url.lower() and ("agenda" in text or path.rstrip("/").endswith("events")):
        return True
    if "cloud.google.com" in event.url.lower() and "resources" in path:
        return True
    return False


def keep_event(event: Event, market: dict[str, Any] | None = None, run_date: datetime | None = None) -> bool:
    if run_date and not apply_date_quality(event, run_date): return False
    if not is_event_page(event): return False
    if market and (has_wrong_market(event, market) or not market_match(event, market)): return False
    haystack = event_text(event)
    has_strategic = any(term in haystack for term in STRATEGIC_TERMS)
    has_city = any(city in haystack for city in market_city_weights(market))
    if market and not has_city and event.confidence != "high": return False
    if has_strategic_technical_topic(event) and (has_city or event.score >= 5): return event.score >= 3
    return event.score >= 3 and has_strategic and (has_city or event.score >= 6)


def missing_fields(event: Event) -> list[str]:
    return [name for name, value in [("date", event.date_text or event.parsed_date), ("location", event.location)] if not value]


def review_reason(event: Event) -> str:
    if missing_fields(event):
        return "Relevant search result, but date/location needs manual verification."
    if event.score >= 6:
        return "Potentially relevant local event; verify details before outreach."
    return "Possible event found by broad discovery; review manually before using."


def candidate_block_reasons(event: Event, market: dict[str, Any], run_date: datetime | None = None) -> list[str]:
    reasons: list[str] = []
    if run_date and not is_future_event(event, run_date):
        reasons.append("past, stale, or uncertain date")
    if not event.location:
        reasons.append("missing/invalid location")
    if has_wrong_market(event, market) or not market_match(event, market):
        reasons.append("wrong or unclear market")
    if event.confidence == "low":
        reasons.append("low confidence")
    if is_generic_directory_or_resource_page(event) or not is_event_page(event):
        reasons.append("generic directory/resource page")
    if not (event.date_text or event.parsed_date):
        reasons.append("missing date")
    if event.score < 6:
        reasons.append("relevance score below 6")
    return reasons


def apply_block_diagnostics(reasons: list[str], diagnostics: RunDiagnostics) -> None:
    if reasons == ["missing/invalid location"]:
        diagnostics.blocked_only_missing_location += 1
    if any("location" in r for r in reasons):
        diagnostics.blocked_missing_invalid_location += 1
    if any("market" in r for r in reasons):
        diagnostics.blocked_wrong_market += 1
    if any("low confidence" in r for r in reasons):
        diagnostics.blocked_low_confidence += 1
    if any("directory/resource" in r for r in reasons):
        diagnostics.blocked_generic_page += 1



def strong_market_evidence(event: Event, market: dict[str, Any]) -> bool:
    title = event.title.lower()
    url = event.url.lower()
    summary = clean_summary(event).lower()
    return any(
        contains_term(title, city)
        or contains_term(summary, city)
        or contains_term(url, city.replace(" ", "-"))
        or contains_term(url, city.replace(" ", ""))
        for city in [str(c).lower() for c in market.get("cities", [])]
    )


def high_priority_verification_reason(event: Event, market: dict[str, Any]) -> str:
    evidence = "title" if any(contains_term(event.title.lower(), str(c).lower()) for c in market.get("cities", [])) else "URL or snippet"
    topics = join_naturally(readable_topics(event))
    date_note = "has a listed date/time" if (event.date_text or event.parsed_date) else "appears on an event-specific source page"
    return f"The {evidence} clearly ties this result to {market.get('name', event.market_id)}, it {date_note}, and its {topics} focus scores strongly enough to warrant manual location verification."


def eligible_for_high_priority_verification(event: Event, market: dict[str, Any], run_date: datetime | None = None) -> bool:
    normalize_event_location(event)
    if run_date and not apply_date_quality(event, run_date):
        return False
    if event.location:
        return False
    if event.confidence not in {"high", "medium"}:
        return False
    if event.score < 6 or not event.title or not event.url:
        return False
    if is_generic_directory_or_resource_page(event) or not is_event_page(event):
        return False
    if has_wrong_market(event, market) or not strong_market_evidence(event, market):
        return False
    if not (event.date_text or event.parsed_date or is_eventbrite_event_url(event.url) or is_likely_search_event(event.title, event.url, clean_summary(event))):
        return False
    return True

def candidate_bucket(event: Event) -> str:
    text = (event.category + " " + event.discovery_group + " " + event.source + " " + event.url).lower()
    if "eventbrite" in text: return "Eventbrite"
    if "luma" in text or "lu.ma" in text: return "Luma"
    if "meetup" in text: return "Meetup"
    if "fau" in text or "boca" in text or "palm beach innovation" in text: return "FAU / Boca / Palm Beach Innovation"
    if "cyber" in text: return "Cybersecurity"
    if "aws" in text: return "AWS"
    if "google" in text or "gcp" in text: return "Google Cloud / GCP"
    if "microsoft" in text or "azure" in text: return "Microsoft / Azure"
    if "cloud provider" in text or "hyperscaler" in text or "cloud" in text: return "Cloud / Hyperscaler"
    if "university" in text or "innovation ecosystem" in text: return "University / Innovation Ecosystem"
    if "israeli" in text or "jewish" in text or "israel" in text: return "Israeli / Jewish Business & Tech"
    return "Other search discovery"


def promote_search_event(event: Event, market: dict[str, Any], run_date: datetime | None = None) -> bool:
    normalize_event_location(event)
    if run_date and not apply_date_quality(event, run_date): return False
    if event.confidence == "low": return False
    if event.score < 6 or not is_event_page(event): return False
    if not event.title or not event.url: return False
    if not (event.date_text or event.parsed_date): return False
    if not event.location: return False
    if is_generic_directory_or_resource_page(event): return False
    if has_wrong_market(event, market): return False
    return market_match(event, market)


def eligible_for_top3(event: Event, market: dict[str, Any] | None = None, run_date: datetime | None = None) -> bool:
    normalize_event_location(event)
    if run_date and not is_future_event(event, run_date): return False
    if event.confidence == "low" or event.is_candidate: return False
    if event.source != "Eventbrite via Search" and event.discovery_group == "Primary sources": return True
    if not (event.date_text or event.parsed_date) or not event.location: return False
    if market and (not market_match(event, market) or has_wrong_market(event, market)): return False
    return event.score >= 6 and len(event.title) >= 8


def fetch_search_discovery_source(source: dict[str, Any], diagnostics: RunDiagnostics | None = None, market: dict[str, Any] | None = None) -> list[Event]:
    if not os.environ.get("SEARCH_API_KEY", "").strip(): return []
    group_name = source_name(source); stats = diagnostics.group_stats.setdefault(group_name, {"queries_attempted":0,"queries_with_results":0,"queries_with_no_results":0,"urls_found":0,"kept":0,"main":0,"review":0,"discarded":0}) if diagnostics else None
    events_by_url: dict[str, Event] = {}
    for query in source.get("queries") or []:
        if stats: stats["queries_attempted"] += 1
        try:
            results = search_api_results(str(query), max(1, int(source.get("results_per_query", 10))), diagnostics) if diagnostics is not None else search_api_results(str(query), max(1, int(source.get("results_per_query", 10))))
        except requests.RequestException:
            if stats: stats["queries_with_no_results"] += 1
            continue
        if stats: stats["queries_with_results" if results else "queries_with_no_results"] += 1; stats["urls_found"] += len(results)
        qlower = str(query).lower()
        for key, prefix in [("aws", "aws"), ("google", "gcp"), ("gcp", "gcp"), ("microsoft", "azure"), ("azure", "azure")]:
            if key in qlower and diagnostics: diagnostics.cloud_stats[f"{prefix}_queries"] += 1
        for result in results:
            url = result["url"]
            if "eventbrite.com" in url.lower() and diagnostics: diagnostics.eventbrite_urls_found_before_filtering += 1
            if "eventbrite.com" in url.lower() and not is_eventbrite_event_url(url):
                if stats: stats["discarded"] += 1
                continue
            source_label = "Eventbrite via Search" if "eventbrite.com" in url.lower() else group_name
            event = Event(result["title"][:180].strip(), url, source_label, summary=result.get("snippet", "")[:700], confidence="low", market_id=(market or {}).get("id", "south_florida"), discovery_group=group_name, category=source.get("category", group_name))
            if is_eventbrite_event_url(url):
                try: event = fetch_eventbrite_event_page(event)
                except requests.RequestException: pass
            normalize_event_location(event)
            event.score = score_event(event, market)
            event.missing_fields = missing_fields(event); event.review_reason = review_reason(event)
            if diagnostics and is_cloud_provider_event(event):
                if contains_any(event_text(event), ["aws", "amazon web services"]): diagnostics.cloud_stats["aws_candidates"] += 1
                if contains_any(event_text(event), ["google cloud", "gcp"]): diagnostics.cloud_stats["gcp_candidates"] += 1
                if contains_any(event_text(event), ["microsoft", "azure"]): diagnostics.cloud_stats["azure_candidates"] += 1
            events_by_url.setdefault(url, event)
            if len(events_by_url) >= int(source.get("max_events", 25)): return list(events_by_url.values())
    if diagnostics and "eventbrite" in group_name.lower(): diagnostics.eventbrite_candidates_found = len(events_by_url)
    return list(events_by_url.values())


def is_likely_search_event(title: str, url: str, snippet: str) -> bool:
    text = f"{title} {url} {snippet}".lower(); path = urlparse(url).path.strip("/").lower()
    bad = ["submit an event", "events calendar", "all events", "search", "category", "blog", "press", "jobs", "careers", "course", "training catalog"]
    if any(b in text for b in bad): return False
    if path in {"", "events", "event", "calendar", "search"}: return False
    return any(t in text for t in ["event", "summit", "conference", "meetup", "workshop", "webinar", "roundtable", "breakfast", "founder", "startup", "ai", "cloud", "aws", "azure", "gcp", "cyber"])


def deduplicate_recurring_events(events: list[Event]) -> list[Event]:
    grouped: dict[str, list[Event]] = {}
    for e in events: grouped.setdefault(f"{e.market_id}|{normalized_title(e.title)}", []).append(e)
    out=[]; now=datetime.now(timezone.utc); distant=datetime.max.replace(tzinfo=timezone.utc)
    for instances in grouped.values():
        selected=sorted(instances,key=lambda e:(e.parsed_date is None, e.parsed_date < now if e.parsed_date else False, abs((e.parsed_date-now).total_seconds()) if e.parsed_date else float("inf"), -e.score))[0]
        selected.score=max(i.score for i in instances); selected.recurring_count=len(instances)
        if not selected.parsed_date:
            dated=[i for i in instances if i.parsed_date]
            if dated: selected.parsed_date=min(dated,key=lambda e:e.parsed_date or distant).parsed_date
        out.append(selected)
    return out


def load_seen_event_ids() -> set[str]:
    if not SEEN_EVENTS_FILE.exists(): return set()
    try: data=json.loads(SEEN_EVENTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError: return set()
    return {str(i) for i in data} if isinstance(data, list) else set(data.get("seen_event_ids", [])) if isinstance(data, dict) else set()


def event_to_dict(event: Event) -> dict[str, Any]:
    d=event.__dict__.copy(); d["parsed_date"]=event.parsed_date.isoformat() if event.parsed_date else None; return d


def event_from_dict(data: dict[str, Any]) -> Event:
    parsed=None
    if data.get("parsed_date"):
        try: parsed=datetime.fromisoformat(data["parsed_date"])
        except ValueError: parsed=parse_date(data.get("date_text", ""))
    allowed={f.name for f in Event.__dataclass_fields__.values()} - {"parsed_date"}
    kwargs={k:v for k,v in data.items() if k in allowed}
    return Event(**kwargs, parsed_date=parsed)


def save_last_successful_events(events: list[Event], cache_file: Path | None = None) -> None:
    path=cache_file or LAST_SUCCESSFUL_EVENTS_FILE; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"saved_at":datetime.now(timezone.utc).isoformat(),"events":[event_to_dict(e) for e in events]}, indent=2, sort_keys=True), encoding="utf-8")


def load_last_successful_events(cache_file: Path | None = None) -> list[Event]:
    path=cache_file or LAST_SUCCESSFUL_EVENTS_FILE
    if not path.exists(): return []
    try: data=json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError: return []
    items=data.get("events", []) if isinstance(data, dict) else data
    return [event_from_dict(i) for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def format_date(event: Event, market: dict[str, Any] | None = None) -> str:
    note=" (recurring event; next listed instance)" if event.recurring_count > 1 else ""
    tz=ZoneInfo((market or {}).get("timezone", "America/New_York"))
    return event.parsed_date.astimezone(tz).strftime("%Y-%m-%d %I:%M %p %Z").strip()+note if event.parsed_date else (event.date_text or "Date/time not listed")+note


def ranking_key(event: Event) -> tuple[int,int,int,int,int,datetime,str]:
    cat=4 if has_executive_audience(event) else 3 if has_strategic_technical_topic(event) else 2 if has_startup_founder_topic(event) else -1 if is_generic_networking(event) else 0
    bonus=(3 if has_title_terms(event, EXECUTIVE_BUYER_TERMS) else 0)+(2 if has_title_terms(event, STRATEGIC_TECHNICAL_TERMS) else 0)+(2 if has_title_terms(event, STARTUP_FOUNDER_TERMS) and has_strategic_technical_topic(event) else 0)-(3 if is_recurring_generic_networking(event) else 0)
    conf={"high":2,"medium":1,"low":0}.get(event.confidence,2)
    return (-cat,-conf,-event.score,-bonus,event.recurring_count if is_generic_networking(event) else 0,event.parsed_date or datetime.max.replace(tzinfo=timezone.utc),event.title.lower())


def has_real_location(event: Event) -> bool:
    location = clean_location(event.location).lower()
    return bool(location and location != "location not listed")


def top_recommendations(events: list[Event], limit: int = 3, market: dict[str, Any] | None = None, run_date: datetime | None = None) -> list[Event]:
    eligible=[e for e in events if eligible_for_top3(e, market, run_date)]
    strategic=[e for e in eligible if not is_generic_networking(e)]
    pool=strategic or eligible
    ranked=sorted(pool,key=ranking_key)
    selected: list[Event] = []
    for event in ranked:
        if event in selected:
            continue
        if not has_real_location(event):
            location_alternative = next((
                other for other in ranked
                if other not in selected and has_real_location(other) and other.score >= event.score - 1
            ), None)
            if location_alternative is not None:
                selected.append(location_alternative)
                if len(selected)>=limit:
                    break
                continue
        selected.append(event)
        if len(selected)>=limit:
            break
    if len(selected)<limit and pool is not eligible:
        for e in sorted(eligible,key=ranking_key):
            if e not in selected:
                selected.append(e)
            if len(selected)>=limit:
                break
    return selected[:limit]


def readable_topics(event: Event) -> list[str]:
    text=event_text(event); mapping=[("AI adoption",["ai","artificial intelligence","agentic","genai"]),("cloud modernization",["cloud","aws","amazon web services","azure","google cloud","gcp"]),("DevOps and platform engineering",["devops","engineering"]),("cybersecurity",["cybersecurity","cyber security"]),("data strategy",["data","analytics"]),("SaaS growth",["saas"]),("startup growth",["startup","startups","founder","vc","venture capital"]),("Israeli/Jewish business technology",["israeli","jewish","israel"])]
    return [label for label,terms in mapping if contains_any(text,terms)][:3]


def join_naturally(items: list[str]) -> str:
    return "technology priorities" if not items else items[0] if len(items)==1 else f"{items[0]} and {items[1]}" if len(items)==2 else f"{', '.join(items[:-1])}, and {items[-1]}"


def why_this_matters(event: Event, market: dict[str, Any] | None = None) -> str:
    cities=market_city_weights(market); text=event.location.lower()+" "+event.title.lower(); city=next((c.title() for c in cities if c in text), event.location or (market or {}).get("name", "South Florida"))
    topics=join_naturally(readable_topics(event)); recur=" Because it appears to be recurring, treat this as a repeatable coverage opportunity rather than a one-time executive commitment." if event.recurring_count>1 else ""
    if has_executive_audience(event): return f"This is a strong fit because it is likely to bring senior product, technology, or business leaders together in {city}. That audience is well suited for conversations about {topics}, delivery capacity, and modernization priorities.{recur}"
    if has_strategic_technical_topic(event) and has_startup_founder_topic(event): return f"This should rank highly because it combines {topics} with a founder or startup audience in {city}. It is a practical setting for discussing cloud architecture, AI implementation, and engineering support with teams that may be making near-term build decisions.{recur}"
    if has_strategic_technical_topic(event): return f"This is relevant because the agenda is tied to {topics}, which maps directly to cloud consulting, AI delivery, security, data, and platform modernization conversations in {city}.{recur}"
    if has_startup_founder_topic(event): return f"This is useful for founder and startup relationship-building in {city}, especially if attendee conversations point to SaaS, fintech, cloud, AI, or enterprise technology needs.{recur}"
    if is_generic_networking(event): return f"This looks like broad networking in {city}. It can still create local relationships, but it should be covered by an account executive and should not take priority over executive, AI, cloud, or focused startup events.{recur}"
    return "The listing has limited strategic detail. Validate the attendee profile before committing time."


def suggested_action(event: Event) -> str:
    if event.confidence == "low" or event.is_candidate: return "Review manually"
    if is_cloud_provider_event(event) and event.location and event.score >= 6: return "Attend personally" if has_executive_audience(event) else "Send senior AE"
    if is_cloud_provider_event(event) and contains_any(event_text(event), ["deep", "technical", "hands-on", "workshop", "devops", "data", "security"]): return "Send technical person"
    if contains_any(event_text(event), ["webinar", "online", "virtual"]): return "Track only" if event.score < 8 else "Send technical person"
    if contains_any(event_text(event), ["israeli", "jewish", "israel"]) and (has_startup_founder_topic(event) or has_executive_audience(event)): return "Attend personally" if event.score >= 7 else "Send senior AE"
    if is_recurring_generic_networking(event): return "Send AE" if event.score >=5 else "Track only"
    if is_generic_networking(event): return "Send AE"
    if has_executive_audience(event) and event.score >= 7: return "Attend personally"
    if has_strategic_technical_topic(event) or has_startup_founder_topic(event): return "Send technical person" if has_strategic_technical_topic(event) and event.score>=6 else "Send senior AE" if event.score>=6 else "Send AE"
    return "Send AE" if event.score>=5 else "Track only"


def write_event_sections(lines: list[str], events: list[Event], candidates: list[Event] | None = None, high_priority: list[Event] | None = None, fallback: bool = False, market: dict[str, Any] | None = None) -> None:
    if not events and not fallback:
        section_events=[]
    elif fallback:
        lines += ["## Fallback: last known relevant events", "", "Current sources failed or produced no usable events, so this section uses events saved from the previous successful run. Confirm dates and availability before outreach.", ""]
        section_events=events
    elif events:
        top=top_recommendations(events, market=market); lines += ["## Top 3 Recommendations", ""]
        if not top: lines += ["No qualifying Top 3 recommendations were found for this market.", ""]
        for i,e in enumerate(top,1):
            lines += [f"### {i}. {e.title}", f"- **Event name:** {e.title}", f"- **Date and time:** {format_date(e, market)}", f"- **Location:** {e.location or 'Location not listed'}", f"- **Source:** {e.source}", f"- **Confidence:** {e.confidence}", f"- **Relevance score:** {e.score}/10", f"- **Why it matters:** {why_this_matters(e, market)}", f"- **Suggested action:** {suggested_action(e)}", f"- **URL:** {e.url}", ""]
        lines += ["## Recommended next steps", ""] + ([f"- {suggested_action(e)} for {e.title}." for e in top] or ["- Review High-priority candidates to verify for strong manually verifiable events."]) + ["", "## Prioritized Events", ""]
        section_events=events
    for i,e in enumerate(section_events,1):
        lines += [f"### {i}. {e.title}", f"- **Event name:** {e.title}", f"- **Date and time:** {format_date(e, market)}", f"- **Location:** {e.location or 'Location not listed'}", f"- **Source:** {e.source}", f"- **Confidence:** {e.confidence}", f"- **URL:** {e.url}", f"- **Relevance score:** {e.score}/10", f"- **Why this matters for a cloud consulting company:** {why_this_matters(e, market)}", f"- **Suggested action:** {suggested_action(e)}", ""]
    if high_priority is not None:
        lines += ["## High-priority candidates to verify", ""]
        if not high_priority: lines += ["No high-priority candidates require manual location verification.", ""]
        for i,h in enumerate(high_priority[:10],1):
            lines += [f"### {i}. {h.title}", f"- **Title:** {h.title}", f"- **Date and time:** {format_date(h, market)}", "- **Location:** Needs verification", f"- **URL:** {h.url}", f"- **Source / discovery group:** {h.source} / {h.discovery_group}", f"- **Confidence:** {h.confidence}", f"- **Relevance score:** {h.score}/10", f"- **Why it is worth verifying:** {high_priority_verification_reason(h, market or default_market())}", "- **Suggested action:** Verify manually", ""]
    if candidates is not None:
        lines += ["## Candidates to review", ""]
        if not candidates: lines += ["No low-confidence search candidates were retained for manual review.", ""]
        visible_candidates = candidates[:20]
        hidden_for_readability = len(candidates) > len(visible_candidates)
        buckets: dict[str,list[Event]]={}
        for c in visible_candidates: buckets.setdefault(candidate_bucket(c), []).append(c)
        order=["Eventbrite","Luma","Meetup","FAU / Boca / Palm Beach Innovation","Cybersecurity","Cloud / Hyperscaler","AWS","Google Cloud / GCP","Microsoft / Azure","University / Innovation Ecosystem","Israeli / Jewish Business & Tech","Other search discovery"]
        for bucket in order:
            items=buckets.get(bucket, [])
            if not items: continue
            lines += [f"### {bucket}", ""]
            if len(items) > 5:
                hidden_for_readability = True
            for c in items[:5]:
                lines += [f"- **Title:** {c.title}", f"  - **URL:** {c.url}", f"  - **Source / discovery group:** {c.source} / {c.discovery_group}", f"  - **Confidence:** {c.confidence}", f"  - **Market:** {(market or {}).get('name', c.market_id)}", f"  - **Reason to review:** {c.review_reason or review_reason(c)}", f"  - **Missing fields:** {', '.join(c.missing_fields or missing_fields(c)) or 'None'}", "  - **Suggested action:** Review manually", ""]
        if hidden_for_readability:
            lines += ["Additional candidates were found but hidden for readability.", ""]


def write_digest(events: list[Event], errors: list[str], diagnostics: RunDiagnostics, fallback_events: list[Event] | None = None, market: dict[str, Any] | None = None, candidates: list[Event] | None = None) -> None:
    
    if market is None:
        market = default_market()
        output_path = ROOT / market.get("output_file", "output/south_florida_weekly_digest.md")
    else:
        output_path = ROOT / market.get("output_file", "output/south_florida_weekly_digest.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cities=", ".join(market.get("cities", []))
    lines=[f"# {market['name']} Tech Events Weekly Digest", "", f"Generated: {generated_at}", "", f"Executive focus: business-development opportunities for a cloud consulting company across {cities}.", ""]
    if events: write_event_sections(lines, events, candidates or [], diagnostics.high_priority_candidates, market=market)
    elif fallback_events:
        lines += ["## Top 3 Recommendations", "", "No fresh qualifying events were available from this run, but source failures occurred and cached events exist.", ""]
        write_event_sections(lines, fallback_events, candidates or [], diagnostics.high_priority_candidates, fallback=True, market=market)
    else:
        reason="One or more sources failed or were skipped, and no fallback cache was available." if diagnostics.sources_skipped else "All enabled sources were fetched, but no qualifying events were found."
        lines += ["## Run status", "", "No qualifying business-development events were found in this run.", f"Reason: {reason}", ""]
        if candidates:
            lines += [f"No verified events found. {len(candidates)} candidates require manual review.", ""]
        write_event_sections(lines, [], candidates or [], diagnostics.high_priority_candidates, market=market)
    lines += ["## Sources", "", "Edit `markets.yaml` to add or remove market-specific public event pages and search discovery groups."]
    if errors: lines += ["", "## Source notes", ""] + [f"- {e}" for e in errors] + [""]
    lines += ["## Run diagnostics", "", f"- **Market name:** {diagnostics.market_name}", f"- **Sources fetched successfully:** {', '.join(diagnostics.sources_fetched_successfully) if diagnostics.sources_fetched_successfully else 'None'}", f"- **Sources skipped:** {', '.join(diagnostics.sources_skipped) if diagnostics.sources_skipped else 'None'}", f"- **Search discovery groups enabled/disabled:** {'enabled' if os.environ.get('SEARCH_API_KEY','').strip() else 'disabled'}", f"- **Search API endpoint host:** {diagnostics.search_api_endpoint_host}", f"- **Number of search queries attempted:** {diagnostics.search_queries_attempted}", f"- **Number of search API responses received:** {diagnostics.search_api_responses_received}", f"- **Number of Eventbrite URLs found before filtering:** {diagnostics.eventbrite_urls_found_before_filtering}", f"- **Number of Eventbrite candidates found:** {diagnostics.eventbrite_candidates_found}", f"- **Number of raw events found:** {diagnostics.raw_events_found}", f"- **Number of events after filtering:** {diagnostics.events_after_filtering}", f"- **Number of events after deduplication:** {diagnostics.events_after_deduplication}", f"- **Candidates blocked due to missing/invalid location:** {diagnostics.blocked_missing_invalid_location}", f"- **Candidates blocked due to wrong market:** {diagnostics.blocked_wrong_market}", f"- **Candidates blocked due to low confidence:** {diagnostics.blocked_low_confidence}", f"- **Candidates blocked because they were generic directory/resource pages:** {diagnostics.blocked_generic_page}", f"- **Candidates promoted to main digest:** {diagnostics.promoted_to_main_digest}", f"- **High-priority candidates to verify count:** {diagnostics.high_priority_candidates_to_verify}", f"- **Candidates blocked only because of missing location:** {diagnostics.blocked_only_missing_location}", f"- **Candidates promoted to high-priority verification:** {diagnostics.promoted_to_high_priority_verification}", f"- **Eventbrite direct scraping:** {diagnostics.eventbrite_direct_scraping}", f"- **Eventbrite search discovery:** {diagnostics.eventbrite_search_discovery}", f"- **Events discarded because date is in the past:** {diagnostics.discarded_past_date}", f"- **Events discarded because year is stale:** {diagnostics.discarded_stale_year}", f"- **Events discarded because date parsing was uncertain:** {diagnostics.discarded_uncertain_date}", f"- **Events discarded because source looked like recap/historical content:** {diagnostics.discarded_historical_content}", f"- **Verified future events found:** {diagnostics.verified_future_events_found}", f"- **High-priority future candidates found:** {diagnostics.high_priority_future_candidates_found}", f"- **Primary source cache used:** {'Yes' if diagnostics.fallback_cache_used else 'No'}", f"- **Fallback cache was used:** {'Yes' if diagnostics.fallback_cache_used else 'No'}"]
    if diagnostics.fallback_reason: lines.append(f"- **Fallback reason:** {diagnostics.fallback_reason}")
    lines += ["", "### Discovery group diagnostics", ""]
    if diagnostics.group_stats:
        for name, s in diagnostics.group_stats.items(): lines += [f"- **{name}:** queries attempted {s.get('queries_attempted',0)}, with results {s.get('queries_with_results',0)}, no results {s.get('queries_with_no_results',0)}, URLs found {s.get('urls_found',0)}, candidates kept {s.get('kept',0)}, main digest {s.get('main',0)}, review {s.get('review',0)}, discarded {s.get('discarded',0)}"]
    else: lines.append("- No search discovery groups ran.")
    cs=diagnostics.cloud_stats; lines += ["", "### Cloud provider diagnostics", f"- **AWS queries attempted:** {cs['aws_queries']}", f"- **AWS candidates found:** {cs['aws_candidates']}", f"- **GCP queries attempted:** {cs['gcp_queries']}", f"- **GCP candidates found:** {cs['gcp_candidates']}", f"- **Microsoft/Azure queries attempted:** {cs['azure_queries']}", f"- **Microsoft/Azure candidates found:** {cs['azure_candidates']}"]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def source_note(source: dict[str, Any], exc: requests.RequestException) -> str:
    status=getattr(exc.response,"status_code",None); detail=getattr(exc,"safe_message","") or safe_short_message(exc)
    return f"{source_name(source)} search discovery failed with HTTP {status}: {detail}" if source.get("type")=="search_discovery" and status else f"{source_name(source)} search discovery failed: {detail or 'search API could not be reached this run'}" if source.get("type")=="search_discovery" else f"{source_name(source)} was skipped because the public event page was unavailable to the scraper this run (HTTP {status})." if status else f"{source_name(source)} was skipped because it could not be reached this run."


def process_market(market: dict[str, Any], seen_event_ids: set[str]) -> tuple[list[Event], list[Event], RunDiagnostics]:
    run_date=datetime.now(timezone.utc)
    errors=[]; diagnostics=RunDiagnostics([], [], market_name=market["name"]); events_by_id={}; candidates_by_id={}
    sources=list(market.get("primary_sources", [])) + list(market.get("discovery_groups", []))
    for source in sources:
        if source.get("type") == "search_discovery":
            if not os.environ.get("SEARCH_API_KEY", "").strip(): diagnostics.eventbrite_search_discovery="disabled"; diagnostics.sources_skipped.append(f"{source_name(source)} (missing SEARCH_API_KEY)"); continue
            diagnostics.eventbrite_search_discovery="enabled"; diagnostics.search_api_endpoint_host=urlparse(configured_search_api_url()).netloc or "unknown"
            try: fetched=fetch_search_discovery_source(source, diagnostics, market); diagnostics.sources_fetched_successfully.append(source_name(source)); diagnostics.raw_events_found += len(fetched)
            except requests.RequestException as exc: diagnostics.sources_skipped.append(source_name(source)); errors.append(source_note(source, exc)); continue
            stats=diagnostics.group_stats.get(source_name(source), {})
            for e in fetched:
                normalize_event_location(e)
                e.score=score_event(e, market); e.market_id=market["id"]; e.missing_fields=missing_fields(e); e.review_reason=review_reason(e)
                if not apply_date_quality(e, run_date, diagnostics, allow_uncertain_review=True):
                    stats["discarded"]=stats.get("discarded",0)+1
                    continue
                block_reasons = candidate_block_reasons(e, market, run_date)
                if promote_search_event(e, market, run_date) and keep_event(e, market, run_date) and e.event_id not in seen_event_ids:
                    events_by_id[e.event_id]=e; stats["main"]=stats.get("main",0)+1
                    diagnostics.promoted_to_main_digest += 1
                else:
                    e.is_candidate=True; e.confidence=e.confidence or "low"
                    if block_reasons:
                        e.review_reason = "Blocked from Prioritized Events: " + "; ".join(block_reasons) + "."
                        apply_block_diagnostics(block_reasons, diagnostics)
                    if eligible_for_high_priority_verification(e, market, run_date):
                        e.review_reason = high_priority_verification_reason(e, market)
                        diagnostics.promoted_to_high_priority_verification += 1
                    candidates_by_id[e.event_id]=e; stats["review"]=stats.get("review",0)+1
                stats["kept"]=stats.get("kept",0)+1
            continue
        if "eventbrite.com" in str(source.get("url", "")).lower(): diagnostics.eventbrite_direct_scraping = "enabled" if source.get("enabled", True) is not False else "disabled"
        if source.get("enabled", True) is False: diagnostics.sources_skipped.append(f"{source_name(source)} (disabled)"); continue
        try: fetched=fetch_source(source, market); diagnostics.sources_fetched_successfully.append(source_name(source)); diagnostics.raw_events_found += len(fetched)
        except requests.RequestException as exc: diagnostics.sources_skipped.append(source_name(source)); errors.append(source_note(source, exc)); continue
        for e in fetched:
            normalize_event_location(e)
            e.score=score_event(e, market)
            if not apply_date_quality(e, run_date, diagnostics): continue
            if e.score >= 6 and e.confidence in {"high", "medium"} and has_real_location(e) and e.event_id not in seen_event_ids and keep_event(e, market, run_date): events_by_id[e.event_id]=e
    diagnostics.events_after_filtering=len(events_by_id)
    unique=deduplicate_recurring_events(list(events_by_id.values()))
    diagnostics.events_after_deduplication=len(unique)
    events=sorted([e for e in unique if is_future_event(e, run_date) and e.score >= 6 and e.confidence in {"high", "medium"} and has_real_location(e)], key=ranking_key)[:25]
    diagnostics.verified_future_events_found=len(events)
    cache=ROOT / market.get("cache_file", "data/last_successful_events.json"); fallback=[]
    if events: save_last_successful_events([e for e in events if is_future_event(e, run_date)], cache)
    elif errors or diagnostics.sources_skipped:
        fallback=[e for e in load_last_successful_events(cache) if is_future_event(e, run_date)]
        if fallback: diagnostics.fallback_cache_used=True; diagnostics.fallback_reason="No fresh events were found while one or more sources failed or were skipped."
        else: diagnostics.fallback_reason="Primary source failed and no verified fallback cache exists."
    high_priority = sorted([c for c in candidates_by_id.values() if eligible_for_high_priority_verification(c, market, run_date)], key=ranking_key)[:5]
    diagnostics.high_priority_candidates = high_priority
    diagnostics.high_priority_candidates_to_verify = len(high_priority)
    diagnostics.high_priority_future_candidates_found = len(high_priority)
    diagnostics.promoted_to_high_priority_verification = len(high_priority)
    review_candidates = [c for c in candidates_by_id.values() if c.event_id not in {h.event_id for h in high_priority} and eligible_for_candidate_review_date(c, run_date) and c.confidence in {"high", "medium"}]
    write_digest(events, errors, diagnostics, fallback, market, sorted(review_candidates, key=ranking_key)[:20])
    return events, sorted(candidates_by_id.values(), key=ranking_key), diagnostics


def write_global_summary(results: list[tuple[dict[str, Any], list[Event], RunDiagnostics]]) -> None:
    GLOBAL_SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines=["# Global Tech Events Weekly Summary", "", f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", ""]
    for market, events, diag in results:
        lines += [f"## {market['name']}", "", f"Full digest: `{market.get('output_file')}`", "", "### Top 3", ""]
        top=top_recommendations(events, market=market)
        if top:
            for i,e in enumerate(top,1): lines += [f"{i}. **{e.title}** — {format_date(e, market)} — {e.location or 'Location not listed'} — score {e.score}/10 — {e.url}"]
        else:
            lines.append("No verified upcoming events found.")
            if diag.high_priority_candidates:
                lines += ["", "### High-priority candidates to verify", ""]
                for i,e in enumerate(diag.high_priority_candidates[:3],1):
                    lines += [f"{i}. **{e.title}** — {format_date(e, market)} — Needs verification — score {e.score}/10 — {e.url}"]
        lines += ["", "### Diagnostics summary", f"- Sources fetched: {len(diag.sources_fetched_successfully)}", f"- Sources skipped: {len(diag.sources_skipped)}", f"- Search queries attempted: {diag.search_queries_attempted}", f"- Main events: {diag.events_after_deduplication}", f"- Fallback cache used: {'Yes' if diag.fallback_cache_used else 'No'}", ""]
    GLOBAL_SUMMARY_FILE.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    seen=load_seen_event_ids(); results=[]
    for market in load_markets():
        events, _c, diag = process_market(market, seen); results.append((market, events, diag)); print(f"Wrote {market.get('output_file')} with {len(events)} event(s).")
    if len(results) > 1:
        write_global_summary(results); print(f"Wrote {GLOBAL_SUMMARY_FILE.relative_to(ROOT)}.")

if __name__ == "__main__": main()
