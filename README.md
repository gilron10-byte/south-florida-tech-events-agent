# South Florida Tech Events Agent

A very simple Python MVP that finds public South Florida tech events and writes a weekly Markdown digest.

The digest is aimed at a cloud services company looking for business-development, partnership, customer, founder, AWS/Azure, and local tech networking opportunities.

## What it does

- Reads public event pages from `sources.yaml`.
- Looks for events around Miami, Miami Beach, Fort Lauderdale, Boca Raton, and West Palm Beach.
- Prioritizes topics such as AI, cloud, AWS, Azure, startups, cybersecurity, SaaS, DevOps, data, product, and engineering.
- Uses a simple 1-10 relevance score and places the best opportunities in a Top 3 Recommendations section.
- Adds event-specific business-development rationale, suggested actions, and short recommended next steps.
- Writes the result to `output/weekly_digest.md`.
- Keeps a placeholder tracking file at `data/seen_events.json` for future deduping/history improvements.
- Does **not** use email or Slack. Eventbrite Search Discovery is optional and is enabled only when `SEARCH_API_KEY` is provided locally or as a GitHub Actions repository secret.

## Quick start for a non-technical user

### 1. Install Python

Install Python 3.11 from [python.org](https://www.python.org/downloads/) if it is not already installed.

### 2. Download this project

Download or clone this repository to your computer.

### 3. Open a terminal in the project folder

On macOS, open Terminal. On Windows, open PowerShell. Navigate to the folder containing this README.

### 4. Install the required packages

```bash
python -m pip install -r requirements.txt
```

### 5. Run the event finder

```bash
python src/main.py
```

### 6. Open the digest

Open this file after the command finishes:

```text
output/weekly_digest.md
```

You can copy the Markdown into a document, email draft, CRM note, or internal planning tool.

## How relevance scoring works

Each event receives a simple **1-10 relevance score** for a cloud consulting company focused on AWS, Azure, AI, DevOps, cybersecurity, SaaS, startups, and enterprise technology.

The score is intentionally directional rather than scientific:

- **8-10:** High-priority business-development opportunity. These events usually combine strong topics such as AWS, Azure, cloud, AI/agentic workflows, cybersecurity, DevOps, data, SaaS, enterprise technology, or product/engineering leadership with signs of senior decision makers, founders, investors, customers, partners, or conference/summit-style networking.
- **5-7:** Worth a targeted follow-up. These events may be good places to send an account executive or technical person, especially when they are in Miami, Fort Lauderdale, Boca Raton, West Palm Beach, or another South Florida market.
- **1-4:** Low priority. These are often generic social events, consumer-oriented events, student-only events, events with unclear technology/business audiences, or listings with missing location/detail.

The script scores separate event fields instead of treating every scraped word equally:

- **Title:** highest weight, because it is usually the cleanest indicator of audience and topic.
- **Location:** moderate weight, especially for Miami, Fort Lauderdale, Boca Raton, West Palm Beach, and nearby South Florida markets.
- **Cleaned summary/description:** lower weight after duplicate title/date/location fragments are removed, which prevents repeated website boilerplate from dominating the score.

The script classifies events into practical sales-coverage types:

- **Executive/buyer:** CTO, CPO, CIO, CISO, chief, VP, director, product leader, engineering leader, and similar senior audience signals.
- **Strategic technical:** AI, agentic workflows, cloud, AWS, Azure, DevOps, cybersecurity, data, SaaS, and related delivery topics.
- **Startup/founder:** founder, startup, VC, fintech, SaaS, and investor-oriented signals.
- **Generic networking:** networking, connect, happy hour, mixer, recurring meetup, broad community event, and similar broad-coverage signals.

The script increases scores for:

- Executive/buyer events, especially when senior audience terms appear in the title.
- Strategic AI, agentic, cloud, AWS, Azure, cybersecurity, DevOps, data, SaaS, product, and engineering events.
- Startup/founder events when they are tied to AI, fintech, SaaS, cloud, or enterprise technology.
- Events in Miami, Fort Lauderdale, Boca Raton, West Palm Beach, and nearby South Florida locations.

The script lowers scores for:

- Generic recurring networking events, broad mixers, generic social events, parties, consumer events, concerts, festivals, student-only events, and career fairs.
- Events with no clear technology/business audience.
- Events with missing locations unless the title and audience are highly relevant.

Generic recurring networking is capped at **6/10** unless the title clearly includes executive/buyer, founder, enterprise, or strategic technical terms. Suggested actions also reflect the classification: executive/buyer events at 7+ recommend personal attendance, focused AI/cloud/startup events at 6+ recommend senior AE or technical coverage, and broad recurring networking recommends AE coverage or tracking rather than personal attendance.

## Changing event sources

Open `sources.yaml` and add or remove public event pages.

Each source needs at least:

```yaml
sources:
  - name: Example Events Page
    url: https://example.com/events/
```

Optional fields let you make scraping more accurate if a site has predictable HTML:

```yaml
sources:
  - name: Example Events Page
    url: https://example.com/events/
    event_selector: article
    title_selector: h2
    date_selector: time
    location_selector: .location
    link_selector: a
    max_events: 20
```

Eventbrite city/category pages are intentionally disabled by default because they often reject automated requests. To supplement the primary sources without scraping Eventbrite search pages directly, configure a `type: search_discovery` source and set `SEARCH_API_KEY` in the environment. The default JSON search endpoint is SerpAPI-compatible, and `SEARCH_API_URL` can point to a compatible provider. If `SEARCH_API_KEY` is missing, Eventbrite search discovery is skipped gracefully.

Search-discovered Eventbrite listings are kept only when their URL contains `eventbrite.com/e/`. If the individual Eventbrite event page can be fetched normally, the script enriches the candidate; if not, it still includes the search title/snippet as a low-confidence candidate.

```yaml
sources:
  - name: Eventbrite Search Discovery
    type: search_discovery
    max_events: 25
    queries:
      - 'site:eventbrite.com/e/ Miami AI startup cloud'
```

## Running with GitHub Actions

A GitHub Actions workflow is included at `.github/workflows/weekly-digest.yml`.

To run it manually:

1. Go to the repository on GitHub.
2. Click **Actions**.
3. Select **Generate weekly event digest**.
4. Click **Run workflow**.
5. Download the generated `weekly-digest` artifact from the workflow run.

The workflow runs manually and on a weekly Monday schedule. Each run uploads `output/weekly_digest.md` as the `weekly-digest` artifact. To enable Eventbrite Search Discovery in GitHub Actions, add `SEARCH_API_KEY` as a repository secret; optionally add `SEARCH_API_URL` to use a SerpAPI-compatible endpoint other than the Python default. If either secret is omitted, the workflow still runs: missing `SEARCH_API_KEY` skips Eventbrite discovery gracefully, and missing `SEARCH_API_URL` leaves the script on its default SerpAPI URL.

## Notes and limitations

This is intentionally a simple MVP:

- Public websites can change their layout, so some sources may occasionally return fewer results.
- Some event cards do not include dates or locations in their listing preview.
- The script fetches only public pages and does not use private APIs or secrets.
- The scoring is keyword-based and can be improved later with better source-specific parsers or enrichment.

## Project structure

```text
src/main.py                 Main Python script
sources.yaml                Configurable public event source list
data/seen_events.json       Placeholder for future event tracking
output/weekly_digest.md     Generated digest
.github/workflows/          GitHub Actions workflow
requirements.txt            Python dependencies
```
