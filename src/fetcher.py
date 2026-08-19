"""
fetcher.py — collects content from RSS feeds and YouTube (via free RSS).
No API keys required — YouTube videos come via public RSS feeds.
All secrets (only webhooks) come from environment variables (GitHub Secrets).
"""
import json
import re
import html
import hashlib
import feedparser
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse


def _strip_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()

MAX_AGE_DAYS = 90
DEFAULT_ENTRY_LIMIT = 10
OFFICIAL_ENTRY_LIMIT = 20

# YouTube public RSS: youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID
# No API key needed — completely free.
FEEDS = {
    "certification": [
        "https://www.sfdc99.com/feed/",
        "https://www.salesforceben.com/feed/",
        "https://www.adminhero.com/feed/",
    ],
    "playground": [
        "https://andyinthecloud.com/feed/",
        "https://unofficialsf.com/feed/",
        "https://developer.salesforce.com/blogs/feed",
    ],
    "salesforce-rss": [
        "https://www.salesforce.com/blog/feed/",
        "https://www.salesforce.com/news/feed/",
        "https://admin.salesforce.com/feed",
        "https://www.salesforceben.com/feed/",
        "https://automationchampion.com/feed/",
    ],
    "need-help": [
        "https://salesforce.stackexchange.com/feeds",
    ],
    "meetup-events": [
        "https://www.salesforceben.com/category/events/feed/",
    ],
    "topic-of-the-day": [
        # Dedicated sources — NOT shared with salesforce-rss to avoid URL dedup
        "https://salesforcemonday.com/feed/",           # deep technical weekly posts
        "https://admin.salesforce.com/feed",            # official Admin topics
        "https://developer.salesforce.com/blogs/feed",  # official developer topics
        "https://www.sfdcstop.com/feeds/posts/default?alt=rss",  # Apex tutorials, LWC, Flows
        # Additional variety — practical tips & best practices
        "https://www.sfdc99.com/feed/",                 # Apex/admin tips for beginners
        "https://nebulaconsulting.co.uk/insights/feed/", # advanced Apex patterns
    ],
}

# Source-level metadata controls routing and mandatory handling. Official RSS
# entries become mandatory only when they contain release/security language;
# the non-RSS Releases hub sets must_post directly for every matched resource.
SOURCE_METADATA: dict[str, dict] = {
    "https://www.salesforce.com/blog/feed/": {
        "official": True,
        "source_priority": 90,
        "mandatory_topics": ("release notes", "security advisory", "critical update", "security update"),
    },
    "https://www.salesforce.com/news/feed/": {
        "official": True,
        "source_priority": 98,
        "mandatory_topics": (
            "release notes", "security advisory", "critical update",
            "security update", "vulnerability",
        ),
    },
    "https://admin.salesforce.com/feed": {
        "official": True,
        "source_priority": 95,
        "mandatory_topics": ("release notes", "release highlights", "security advisory", "critical update"),
    },
    "https://developer.salesforce.com/blogs/feed": {
        "official": True,
        "source_priority": 85,
        "mandatory_topics": ("release notes", "security advisory", "critical security", "breaking change"),
    },
}

_last_health: list[dict] = []


def _domain(url: str) -> str:
    """Extract readable domain label from a URL."""
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if "youtube.com" in host:
            return "youtube.com"
        if "reddit.com" in host:
            return "reddit.com"
        return host
    except Exception:
        return url


def is_fresh(published_str: str | None) -> bool:
    """Returns True if item is younger than MAX_AGE_DAYS."""
    if not published_str:
        return True  # assume fresh if no date
    try:
        import email.utils
        dt = email.utils.parsedate_to_datetime(published_str)
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
        return dt > cutoff
    except Exception:
        return True


def _is_mandatory(text: str, metadata: dict) -> bool:
    if not metadata.get("official"):
        return False
    normalized = text.casefold()
    return any(topic.casefold() in normalized for topic in metadata.get("mandatory_topics", ()))


def _route_channel(default_channel: str, text: str, metadata: dict) -> str:
    """Route narrowly-scoped official announcements to their CoE destination."""
    if not metadata.get("official"):
        return default_channel
    normalized = text.casefold()
    certification_terms = (
        "certification", "credential", "exam guide", "trailhead",
        "superbadge", "release highlights",
    )
    event_terms = ("dreamforce", "world tour", "trailblazerdx", "register for", "salesforce event")
    if any(term in normalized for term in certification_terms):
        return "certification"
    if any(term in normalized for term in event_terms):
        return "meetup-events"
    return default_channel


def fetch_rss(channel: str, urls: list[str]) -> tuple[list[dict], list[dict]]:
    items = []
    health = []
    for url in urls:
        is_youtube = "youtube.com/feeds" in url
        domain = _domain(url)
        metadata = SOURCE_METADATA.get(url, {})
        checked_at = datetime.now(timezone.utc).isoformat()
        source_health = {
            "source": domain,
            "url": url,
            "kind": "youtube" if is_youtube else "rss",
            "official": bool(metadata.get("official")),
            "checked_at": checked_at,
            "status": "error",
            "http_status": None,
            "entries": 0,
            "bozo": False,
            "error": "",
        }
        try:
            response = requests.get(
                url,
                timeout=20,
                headers={"User-Agent": "Salesforce-CoE-Autoposter/1.0"},
            )
            source_health["http_status"] = response.status_code
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            entries = list(getattr(feed, "entries", []))
            source_health["bozo"] = bool(getattr(feed, "bozo", False))
            source_health["entries"] = len(entries)
            if source_health["bozo"]:
                source_health["error"] = str(getattr(feed, "bozo_exception", ""))[:300]
            source_health["status"] = (
                "empty" if not entries else "degraded" if source_health["bozo"] else "ok"
            )

            limit = OFFICIAL_ENTRY_LIMIT if metadata.get("official") else DEFAULT_ENTRY_LIMIT
            for entry in entries[:limit]:
                published = entry.get("published") or entry.get("updated")
                if not is_fresh(published):
                    continue
                link = entry.get("link", "")
                # Skip Reddit entries that point to subreddit root (not a specific post)
                if "reddit.com" in link and "/comments/" not in link:
                    continue
                source = "youtube" if is_youtube else "rss"
                summary = _strip_html(entry.get("summary", "") or "")
                title = entry.get("title", "")
                item_text = f"{title} {summary}"
                mandatory = _is_mandatory(item_text, metadata)
                destination = _route_channel(channel, item_text, metadata)
                items.append({
                    "channel": destination,
                    "source": source,
                    "feed_domain": domain,
                    "feed_url": url,
                    "title": title,
                    "url": link,
                    "summary": summary[:600],
                    "published": published,
                    "id": hashlib.md5(link.encode()).hexdigest(),
                    "must_post": mandatory,
                    "official": bool(metadata.get("official")),
                    "source_priority": metadata.get("source_priority", 20),
                })
        except Exception as e:
            source_health["error"] = str(e)[:300]
            print(f"[RSS] Error fetching {url}: {e}")
        health.append(source_health)
    return items, health


def run(official_only: bool = False) -> list[dict]:
    global _last_health
    all_items = []
    all_health = []
    for channel, urls in FEEDS.items():
        active_urls = [
            url for url in urls
            if not official_only or SOURCE_METADATA.get(url, {}).get("official")
        ]
        if not active_urls:
            continue
        items, health = fetch_rss(channel, active_urls)
        rss_count = sum(1 for i in items if i["source"] == "rss")
        yt_count = sum(1 for i in items if i["source"] == "youtube")
        print(f"[Fetch] {channel}: {rss_count} RSS + {yt_count} YouTube")
        all_items.extend(items)
        all_health.extend(health)
    _last_health = all_health
    return all_items


def get_last_health() -> list[dict]:
    return list(_last_health)


if __name__ == "__main__":
    items = run()
    out = Path("data/fetched.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(items, indent=2, ensure_ascii=False))
    Path("data/feed_health.json").write_text(
        json.dumps(get_last_health(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nTotal fetched: {len(items)} items → {out}")
