"""
events_fetcher.py — fetches upcoming Salesforce community events.

Sources:
  1. Trailblazer Community Groups (RSS feeds for Polish cities)
  2. Salesforce official events page (scrape/RSS fallback)
  3. lu.ma / Eventbrite API (if keys provided)

Returns items compatible with the main pipeline (same dict format as fetcher.py).
"""
import hashlib
import re
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

MAX_AGE_DAYS = 60  # events within the next 60 days are relevant

# Trailblazer Community Group event pages to scrape
TRAILBLAZER_EVENT_URLS = [
    "https://trailblazercommunitygroups.com/events/#702Sb000009OfIUIAU",  # Krakow area
    "https://trailblazercommunitygroups.com/events/#702Sb000009OfNFIA0",  # Warsaw area
]

# Lu.ma calendars for Salesforce events in Europe
LUMA_CALENDARS = [
    "https://lu.ma/salesforce-poland",
    "https://lu.ma/salesforce-cee",
]


def _strip_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\s+', ' ', text).strip()


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return url


def fetch_trailblazer_events() -> list[dict]:
    """
    Attempt to fetch events from Trailblazer Community Groups.
    Uses their public pages — parses JSON-LD or event markup if available.
    Falls back gracefully if the page structure changes.
    """
    items = []
    base_url = "https://trailblazercommunitygroups.com"

    # Try fetching the main events feed
    events_rss_url = f"{base_url}/events/feed/"
    try:
        feed = feedparser.parse(events_rss_url)
        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            summary = _strip_html(entry.get("summary", "") or "")
            published = entry.get("published") or entry.get("updated")

            if not link:
                continue

            items.append({
                "channel": "meetup-events",
                "source": "rss",
                "feed_domain": "trailblazercommunitygroups.com",
                "feed_url": events_rss_url,
                "title": title,
                "url": link,
                "summary": summary[:400],
                "published": published,
                "id": hashlib.md5(link.encode()).hexdigest(),
            })
    except Exception as e:
        print(f"[Events] Trailblazer RSS error: {e}")

    return items


def fetch_luma_events() -> list[dict]:
    """
    Fetch events from lu.ma calendars (if public API available).
    lu.ma provides .ics calendar feeds for public calendars.
    """
    items = []
    for cal_url in LUMA_CALENDARS:
        try:
            # lu.ma calendars have a public .ics endpoint
            ics_url = cal_url.rstrip("/") + ".ics"
            resp = requests.get(ics_url, timeout=10, headers={
                "User-Agent": "SFCoE-EventFetcher/1.0"
            })
            if resp.status_code != 200:
                continue

            # Simple ICS parsing for VEVENT blocks
            text = resp.text
            events = text.split("BEGIN:VEVENT")
            for event_block in events[1:]:  # skip preamble
                title_match = re.search(r"SUMMARY:(.+)", event_block)
                url_match = re.search(r"URL:(.+)", event_block)
                dtstart_match = re.search(r"DTSTART[^:]*:(\d{8})", event_block)
                desc_match = re.search(r"DESCRIPTION:(.+?)(?=\r?\n[A-Z])", event_block, re.DOTALL)

                if not title_match:
                    continue

                title = title_match.group(1).strip()
                link = url_match.group(1).strip() if url_match else cal_url
                summary = desc_match.group(1).strip()[:300] if desc_match else ""
                # Clean ICS line folding
                summary = re.sub(r"\r?\n\s", "", summary)

                published = None
                if dtstart_match:
                    dt_str = dtstart_match.group(1)
                    try:
                        dt = datetime.strptime(dt_str, "%Y%m%d")
                        # Only future events
                        if dt.date() < datetime.now().date():
                            continue
                        published = dt.strftime("%a, %d %b %Y 00:00:00 +0000")
                    except ValueError:
                        pass

                items.append({
                    "channel": "meetup-events",
                    "source": "rss",
                    "feed_domain": _domain(link),
                    "feed_url": cal_url,
                    "title": f"📅 {title}",
                    "url": link,
                    "summary": summary,
                    "published": published,
                    "id": hashlib.md5(link.encode()).hexdigest(),
                })
        except Exception as e:
            print(f"[Events] lu.ma error for {cal_url}: {e}")

    return items


def run() -> list[dict]:
    """Fetch all event sources and return combined items."""
    all_items = []

    tb_items = fetch_trailblazer_events()
    print(f"[Events] Trailblazer: {len(tb_items)} events")
    all_items.extend(tb_items)

    luma_items = fetch_luma_events()
    print(f"[Events] lu.ma: {len(luma_items)} events")
    all_items.extend(luma_items)

    return all_items


if __name__ == "__main__":
    import json
    from pathlib import Path
    items = run()
    print(f"\nTotal events found: {len(items)}")
    for item in items:
        print(f"  - {item['title'][:60]} ({item['feed_domain']})")
