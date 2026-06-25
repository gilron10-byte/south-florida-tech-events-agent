# Tech Events Intelligence Agent

This agent finds public technology events and writes weekly Markdown digests for separate markets. It started as a South Florida Tech Events Agent and now supports multiple markets without mixing their recommendations.

## 1. What the agent does

- Finds events from trusted public event pages and optional web search discovery.
- Scores events for a cloud services / technology business-development audience.
- Creates a separate digest for each market:
  - Top 3 Recommendations
  - Recommended next steps
  - Prioritized Events
  - Candidates to review
  - Source notes
  - Run diagnostics
- Creates an optional global summary with only each market's Top 3 and a path to the full digest.
- Keeps Eventbrite direct scraping disabled by default because Eventbrite often blocks automated city/category pages.
- Uses Eventbrite only through `SEARCH_API_KEY`-backed search discovery.
- Does **not** send Slack messages or email.

## 2. Configured markets

Markets live in `markets.yaml`.

The initial markets are:

1. **South Florida**
   - Miami
   - Miami Beach
   - Fort Lauderdale
   - Boca Raton
   - West Palm Beach
   - Palm Beach
   - South Florida
2. **New York**
   - New York
   - Manhattan
   - Brooklyn
   - Queens
   - Jersey City
3. **Tel Aviv**
   - Tel Aviv
   - Herzliya
   - Ramat Gan
   - Givatayim
   - Ra'anana
   - Petah Tikva
   - Israel

Generated files:

```text
output/south_florida_weekly_digest.md
output/new_york_weekly_digest.md
output/tel_aviv_weekly_digest.md
output/global_weekly_summary.md
```

## 3. How to add a new market

Open `markets.yaml` and copy one existing market block.

Change these fields:

```yaml
- id: boston
  name: Boston
  timezone: America/New_York
  cities: [Boston, Cambridge, Somerville]
  output_file: output/boston_weekly_digest.md
  cache_file: data/boston_last_successful_events.json
  primary_sources: []
  discovery_groups: []
```

Use a unique `id`, output file, and cache file for each market.

## 4. How to add cities to a market

Edit the market's `cities` list in `markets.yaml`:

```yaml
cities:
  - Miami
  - Fort Lauderdale
  - Boca Raton
```

The agent uses these cities for market matching, filtering, and scoring.

## 5. How to add primary sources

Primary sources are clean public event pages that can be fetched directly.

Example:

```yaml
primary_sources:
  - name: Example Events
    url: https://example.com/events/
    event_selector: article
    max_events: 20
```

Optional selectors can improve parsing:

```yaml
title_selector: h2
 date_selector: time
location_selector: .location
link_selector: a
```

South Florida keeps **Refresh Miami Events** and **Tech Hub South Florida Events** as high-confidence primary sources because they are local, relevant, public South Florida tech calendars.

## 6. How to add discovery queries

Discovery groups use web search and should be used for broad sources such as Luma, Meetup, Eventbrite, cloud providers, universities, cybersecurity, Israeli/Jewish business communities, and startup ecosystems.

Example:

```yaml
discovery_groups:
  - name: Luma / lu.ma Discovery
    type: search_discovery
    category: Luma
    max_events: 25
    results_per_query: 10
    queries:
      - site:lu.ma Miami AI startup founder cloud
      - site:lu.ma Miami founders VC AI
```

If one query returns no results, the group continues and keeps partial results from successful queries.

## 7. How `SEARCH_API_KEY` enables search discovery

Set `SEARCH_API_KEY` to enable `type: search_discovery` groups. The default endpoint is SerpAPI-compatible.

Without `SEARCH_API_KEY`:

- Primary sources still run.
- Search discovery groups are skipped gracefully.
- The workflow still succeeds.

## 8. `SEARCH_API_URL` is optional

`SEARCH_API_URL` can point to a compatible JSON search API endpoint. If it is missing or invalid, the agent uses the default SerpAPI endpoint:

```text
https://serpapi.com/search.json
```

The agent redacts API keys in logs and never writes secrets to the digest.

## 9. Why South Florida primary sources are high confidence

Refresh Miami and Tech Hub South Florida are high-confidence for South Florida because they are direct local technology event calendars. Search results are lower confidence because they may point to directory pages, stale pages, generic webinars, or pages without a clear date/location.

## 10. Why search-discovered results are lower confidence

Search-discovered results must be verified before they can be trusted. A search snippet may have a relevant title but no confirmed event date or location. Those items go into **Candidates to review** unless the agent can identify a clear title, URL, date or event-like snippet, market relevance, and relevance score of at least 6.

Low-confidence results do not enter the Top 3 unless they are promoted with clear date, location, strong relevance, and market match.

## 11. How to run locally

```bash
python -m pip install -r requirements.txt
python src/main.py
```

Then open the files in `output/`.

## 12. How to run the workflow manually

1. Go to the repository on GitHub.
2. Click **Actions**.
3. Select **Generate weekly event digest**.
4. Click **Run workflow**.
5. Wait for the run to finish.

## 13. Where to download artifacts

The GitHub Actions workflow uploads all Markdown digests as one artifact named `weekly-digest` using:

```text
output/*.md
```

Open the completed workflow run and download the artifact.

## 14. How to interpret the digest

- **Top 3 Recommendations**: Best market-specific events for action. Each market has its own Top 3.
- **Recommended next steps**: Suggested coverage plan such as attend personally, send senior AE, send technical person, send AE, track only, or review manually.
- **Prioritized Events**: Higher-confidence events that passed filtering and scoring.
- **Candidates to review**: Lower-confidence search results grouped by source/category. Review manually before using.
- **Confidence**:
  - `high`: direct source or verified date/location.
  - `medium`: useful but partially verified.
  - `low`: search-discovered and missing important details.
- **Diagnostics**: Shows sources, skipped groups, search queries, candidate counts, cloud provider counts, fallback cache usage, and Eventbrite status.

## 15. How to add AWS / GCP / Microsoft event queries

Add queries to a market's `Cloud Provider Events` discovery group:

```yaml
- name: Cloud Provider Events
  type: search_discovery
  category: Cloud / Hyperscaler
  queries:
    - site:aws.amazon.com/events Miami AWS startup
    - site:cloud.google.com/events Miami Google Cloud AI startup
    - site:events.microsoft.com Miami Azure AI
```

The agent gives extra scoring weight to AWS, Google Cloud, GCP, Microsoft, Azure, Microsoft for Startups, Google for Startups, AWS Startups, GenAI, AI, startup, ISV, SaaS, partner, migration, modernization, security, data, and DevOps.

## 16. How to add Israeli / Jewish business and tech queries

Add queries to the market's Israeli/Jewish business and tech discovery group:

```yaml
- name: Israeli / Jewish Business & Tech Discovery
  type: search_discovery
  category: Israeli / Jewish Business & Tech
  queries:
    - Israeli founders New York tech events
    - Jewish business networking Miami tech
    - Israeli tech startup events Tel Aviv
```

These events rank well only when they have clear business, founder, investor, cloud, cybersecurity, AI, SaaS, or enterprise technology relevance.

## Project structure

```text
src/main.py                              Main Python script
markets.yaml                            Multi-market configuration
sources.yaml                            Legacy South Florida source config fallback
data/*_last_successful_events.json      Per-market fallback caches
output/*_weekly_digest.md               Per-market generated digests
output/global_weekly_summary.md         Combined Top 3 summary
.github/workflows/weekly-digest.yml     Weekly/manual GitHub Actions workflow
tests/smoke_test.py                     Smoke tests
requirements.txt                        Python dependencies
```
