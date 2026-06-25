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
- Does **not** use email, Slack, paid APIs, or secrets.

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

The script increases scores for:

- CTO, CPO, CIO, CISO, founder, investor, VC, executive, VP, director, startup, SaaS, enterprise, product, engineering, AI, agentic, cloud, AWS, Azure, cybersecurity, DevOps, and data signals.
- Events likely to include senior decision makers or buyer-adjacent audiences.
- Events in Miami, Fort Lauderdale, Boca Raton, West Palm Beach, and nearby South Florida locations.
- Events useful for partnerships, customer networking, AWS/Azure ecosystem relationships, or local founder relationships.

The script lowers scores for:

- Generic social events, parties, consumer events, concerts, festivals, student-only events, and career fairs.
- Events with no clear technology/business audience.
- Events with missing locations unless the title and audience are highly relevant.

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

## Running with GitHub Actions

A GitHub Actions workflow is included at `.github/workflows/weekly-digest.yml`.

To run it manually:

1. Go to the repository on GitHub.
2. Click **Actions**.
3. Select **Generate weekly event digest**.
4. Click **Run workflow**.
5. Download the generated `weekly-digest` artifact from the workflow run.

The workflow runs manually and on a weekly Monday schedule. Each run uploads `output/weekly_digest.md` as the `weekly-digest` artifact.

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
