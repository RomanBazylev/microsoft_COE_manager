# SF CoE Auto-Poster — Project Spec

> **Purpose:** Automatically curate and post relevant Salesforce content to Microsoft Teams channels on a schedule. Zero manual effort after setup.

---

## Overview

The pipeline runs on GitHub Actions, polls official Salesforce RSS, the Releases hub and Events catalog, scores curated articles, and posts to the correct Teams channels. Mandatory official release/security resources bypass ordinary relevance and channel caps.

```
RSS/YouTube feeds
      │
      ▼
  fetchers     ──→  filter.py  ──→  poster.py  ──→  Teams channels
  (collect)         (score +         (send
                    AI summary)    Adaptive Card)
      │                                │
      ▼                                ▼
data/seen_ids.json            data/post_log.json + feed_health.json
(successful deliveries)      (audit/health → GitHub Pages)
```

---

## Repository Structure

```
SalesforceIntCOE/
├── src/
│   ├── main.py          # Entrypoint — orchestrates the 3-step pipeline
│   ├── fetcher.py       # RSS, source metadata, routing and health
│   ├── official_fetcher.py # Salesforce Releases hub poller
│   ├── artifacts.py     # Last-run and feed-health JSON
│   ├── filter.py        # Priority dedup, scoring + Gemini summaries
│   └── poster.py        # Posts to Teams via webhooks
├── data/
│   ├── post_log.json    # Full audit log of all posted/failed items
│   └── seen_ids.json    # Dedup IDs (MD5 of URL) to skip already-posted items
├── docs/
│   └── index.html       # GitHub Pages dashboard (auto-served)
├── .github/
│   └── workflows/
│       └── autoposter.yml  # GitHub Actions schedule + manual trigger
├── requirements.txt
├── README.md
└── PROJECT_SPEC.md      # ← this file
```

---

## Teams Channels & Webhooks

| Channel | Env Secret | Content Focus |
|---|---|---|
| `#certification` | `TEAMS_WEBHOOK_CERTIFICATION` | Exam prep, study guides, certifications |
| `#playground` | `TEAMS_WEBHOOK_PLAYGROUND` | Apex, LWC, developer blogs, code tips |
| `#salesforce-rss` | `TEAMS_WEBHOOK_SALESFORCE_RSS` | General Salesforce news, admin, flows |
| `#need-help` | `TEAMS_WEBHOOK_NEED_HELP` | Q&A, error fixes, Stack Exchange, Dev blog |
| `#meetup-events` | `TEAMS_WEBHOOK_MEETUP_EVENTS` | Events, webinars, conferences |
| `#topic-of-the-day` | `TEAMS_WEBHOOK_TOPIC_OF_THE_DAY` | Release notes, platform updates, Einstein |

**Max curated posts per channel per run:** 2. `must_post` official resources bypass this cap.

---

## Content Sources (fetcher.py)

### `#certification`
| Source | Type |
|---|---|
| sfdc99.com | RSS |
| salesforceben.com | RSS |
| adminhero.com | RSS |
| admin.salesforce.com (credential/Trailhead routing) | Official RSS |
| Salesforce Releases / Trailhead Release Highlights | Official HTML poller |

### `#playground`
| Source | Type |
|---|---|
| andyinthecloud.com | RSS |
| unofficialsf.com | RSS |
| developer.salesforce.com/blogs | Official RSS |

### `#salesforce-rss`
| Source | Type |
|---|---|
| salesforce.com/blog | RSS |
| salesforce.com/news | Official RSS |
| admin.salesforce.com | Official RSS |
| salesforce.com/releases | Official HTML poller |
| salesforceben.com | RSS |
| automationchampion.com | RSS |

### `#need-help`
| Source | Type |
|---|---|
| salesforce.stackexchange.com | RSS |

### `#meetup-events`
| Source | Type |
|---|---|
| salesforce.com/events | Official HTML poller |
| salesforceben.com/category/events | RSS |

### `#topic-of-the-day`
| Source | Type |
|---|---|
| admin.salesforce.com | Official RSS |
| developer.salesforce.com/blogs | Official RSS |
| salesforcemonday.com | RSS |
| sfdcstop.com | RSS |
| sfdc99.com | RSS |
| nebulaconsulting.co.uk | RSS |

**Feed limits:** 20 entries for official feeds, 10 for curated feeds; freshness window = 90 days.
**Reddit guard:** skip entries where `"reddit.com" in link and "/comments/" not in link` (avoids subreddit root URLs).

---

## Scoring & Filtering (filter.py)

### Relevance Score Formula

```
score = min(channel_matches / MATCH_SATURATION + generic_matches * 0.05, 1.0)
```

- `MATCH_SATURATION = 3` → 3 channel keyword hits = score 1.0
- `GENERIC_SF_KEYWORDS` each contribute `+0.05`
- YouTube items: `+0.15` boost
- Mandatory official release/security items bypass the relevance threshold.
- Within-run URL duplicates are selected by `must_post`, source priority, then channel priority.
- `RELEVANCE_THRESHOLD = 0.25` — items below this are skipped (logged as `[SKIP 0.XX]`)

### Gemini AI Summary

- Model: `gemini-2.0-flash`
- API: `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent`
- Auth: header `x-goog-api-key: $GEMINI_API_KEY` (NOT query param)
- Timeout: 20s, max 2 retries
- On quota (429) or any error → silent fallback to static comment
- RSS `entry.summary` is always included in the Teams card regardless of Gemini availability

---

## Webhook Payload Format (poster.py)

Two formats are auto-detected by URL:

| URL pattern | Format |
|---|---|
| `logic.azure.com` | Simple JSON `{"text": "..."}` (New Teams Workflows) |
| Everything else (incl. `powerplatform.com`) | **Adaptive Card 1.4** wrapped in `{"type":"message","attachments":[...]}` |

### Adaptive Card structure
1. **TextBlock** — article title (link)
2. **TextBlock** — RSS summary (subtle, max 220 chars) — always shown
3. **TextBlock** — Gemini comment (or static fallback)
4. **FactSet** — Source / Channel / Score / Posted
5. **Action.OpenUrl** — "Read more →" button

**Trailing newline guard:** webhook URL has `.strip()` applied (prevents `%0A` 401 errors from GitHub Secrets).

---

## Schedule (autoposter.yml)

| Cron | UTC | Warsaw (CEST) | Purpose |
|---|---|---|---|
| `0 8 * * 1-5` | 08:00 weekdays | 10:00 | All channels |
| `0 8 * * 0,6` | 08:00 weekends | 10:00 | Official sources only |

**Manual trigger:** `workflow_dispatch` with optional `dry_run: true` (logs only, no posts).

---

## Data Files

### `data/seen_ids.json`
- IDs of successfully posted items (URL hashes for RSS; URL+label fingerprints for release resources)
- Read with `utf-8-sig` encoding (BOM-safe, prevents crash from PowerShell-generated files)
- Written with `utf-8` encoding (no BOM)
- Updated only after Teams returns success; failed, capped and dry-run items remain retryable

### `data/post_log.json`
- Array of objects, most recent appended last
- Fields: `id`, `channel`, `source`, `feed_domain`, `title`, `url`, `status` (`posted`/`failed`/`dry-run`), `relevance_score`, `suggested_comment`, `posted_at`, `error`
- Committed back to repo by GitHub Actions after each run
- Served with `feed_health.json` and `last_run.json` to the GitHub Pages dashboard

---

## GitHub Pages Dashboard (docs/index.html)

Single-file vanilla JS dashboard, served from the `docs/` folder.

### Tabs
| Tab | Content |
|---|---|
| 📊 Overview | 6 stat cards (total, this week, success rate, failed, active channels, last post) + Channel Activity bar chart |
| 📋 Post Log | Filterable table (by status / source / channel) of all posted items |
| 🔌 Sources | Content sources grouped by channel with activity status |

### Features
- Dark/light theme toggle (persisted in `localStorage`)
- "▶ Run Now" button → triggers `workflow_dispatch` via GitHub API (requires Fine-grained PAT with Actions:write)
- Auto-refreshes every 5 minutes
- Channel badges with per-channel colour coding

---

## GitHub Secrets Required

| Secret | Description |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio key (optional — disables AI summaries if absent) |
| `TEAMS_WEBHOOK_CERTIFICATION` | Power Automate webhook URL |
| `TEAMS_WEBHOOK_PLAYGROUND` | Power Automate webhook URL |
| `TEAMS_WEBHOOK_SALESFORCE_RSS` | Power Automate webhook URL |
| `TEAMS_WEBHOOK_NEED_HELP` | Power Automate webhook URL |
| `TEAMS_WEBHOOK_MEETUP_EVENTS` | Power Automate webhook URL |
| `TEAMS_WEBHOOK_TOPIC_OF_THE_DAY` | Power Automate webhook URL |

Webhook URLs come from **Power Automate → Instant Cloud Flow → "When an HTTP request is received"** trigger. They look like:
```
https://<env>.environment.api.powerplatform.com/powerautomate/automations/...
```

---

## Dependencies (requirements.txt)

```
feedparser>=6.0.11
requests>=2.32.0
```

No API keys needed for fetching — YouTube content is consumed via public RSS, not the Data API.

---

## Known Constraints & Decisions

| Topic | Decision |
|---|---|
| Gemini quota | Hits on first article often; subsequent items use static comment. RSS summary always shown. |
| Reddit links | Only `/comments/` URLs are valid posts; subreddit root URLs are filtered out. |
| `MAX_PER_CHANNEL = 2` | Prevents curated spam; mandatory official notices bypass it. |
| BOM encoding | `seen_ids.json` read with `utf-8-sig` to handle files created by PowerShell. |
| YouTube RSS | Free, no API key. Uses `youtube.com/feeds/videos.xml?channel_id=...` |
| Dedup window | Lifetime successful-delivery dedup. Failed/capped items retry. |

---

## How to Extend

### Add a new content source
1. Add the feed URL to the appropriate channel in `FEEDS` dict in `src/fetcher.py`
2. Add the display entry to `SOURCES` array in `docs/index.html`
3. Verify the RSS URL returns entries (feedparser test)

### Add a new Teams channel
1. Create the channel in Teams
2. Create a Power Automate flow with HTTP trigger
3. Add webhook URL as a GitHub Secret
4. Add channel to `CHANNEL_WEBHOOKS` in `src/poster.py`
5. Add keywords to `CHANNEL_KEYWORDS` in `src/filter.py`
6. Add feed URLs to `FEEDS` in `src/fetcher.py`
7. Add channel to `CHANNELS` array and `CH_CSS` / `CH_COLOR_*` objects in `docs/index.html`

### Adjust posting frequency
Edit the `cron` expressions in `.github/workflows/autoposter.yml`.

### Raise/lower sensitivity
- Raise `RELEVANCE_THRESHOLD` in `filter.py` → fewer, more relevant posts
- Lower `MATCH_SATURATION` → easier to score high
- Increase `MAX_PER_CHANNEL` in `poster.py` → more posts per run
