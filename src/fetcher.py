"""
fetcher.py — collects content from RSS feeds and YouTube (via free RSS).
No API keys required — YouTube videos come via public RSS feeds.
All secrets (only webhooks) come from environment variables (GitHub Secrets).
"""
import json
import re
import hashlib
import feedparser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse


def _strip_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') \
               .replace('&nbsp;', ' ').replace('&quot;', '"').replace('&#39;', "'")
    return re.sub(r'\s+', ' ', text).strip()

MAX_AGE_DAYS = 90

# YouTube public RSS: youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID
# No API key needed — completely free.
FEEDS = {
    "certification": [
        "https://www.salesforce.com/blog/category/certifications/feed/",
        "https://focusonforce.com/feed/",
        "https://www.sfdc99.com/feed/",
        "https://www.salesforceben.com/feed/",
        "https://www.adminhero.com/feed/",
        # YouTube: Salesforce Admins channel (free RSS)
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCvlZKtezcjB5O8B5QKABo5A",
    ],
    "playground": [
        "https://andyinthecloud.com/feed/",
        "https://unofficialsf.com/feed/",
        "https://www.jitendrazaa.com/blog/feed/",
        "https://www.reddit.com/r/salesforcedev/.rss",
        # YouTube: Salesforce Developers channel (free RSS)
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC-OBnBKJdVSTCLkCzj1CRMQ",
    ],
    "salesforce-rss": [
        "https://www.salesforce.com/blog/feed/",
        "https://www.salesforceben.com/feed/",
        "https://automationchampion.com/feed/",
    ],
    "need-help": [
        "https://salesforce.stackexchange.com/feeds",
        "https://www.reddit.com/r/salesforce/.rss",
        "https://developer.salesforce.com/blogs/feed",
    ],
    "meetup-events": [
        "https://www.salesforce.com/blog/category/events/feed/",
    ],
    "topic-of-the-day": [
        # Dedicated sources — NOT shared with salesforce-rss to avoid URL dedup
        "https://salesforcemonday.com/feed/",           # deep technical weekly posts
        "https://admin.salesforce.com/blog/feed",       # official Salesforce admin blog
        "https://developer.salesforce.com/blogs/feed",  # Salesforce developer blog
        "https://www.sfdcstop.com/feeds/posts/default?alt=rss",  # Apex tutorials, LWC, Flows
        "https://www.apexhours.com/feed/",              # developer news, LWC guides, career
        # YouTube: main Salesforce channel (not used in other channels)
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCKORm8sxh3cheBpqs0jkhDA",
    ],
}


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


def fetch_rss(channel: str, urls: list[str]) -> list[dict]:
    items = []
    for url in urls:
        is_youtube = "youtube.com/feeds" in url
        domain = _domain(url)
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:  # max 5 per feed
                published = entry.get("published") or entry.get("updated")
                if not is_fresh(published):
                    continue
                link = entry.get("link", "")
                # Skip Reddit entries that point to subreddit root (not a specific post)
                if "reddit.com" in link and "/comments/" not in link:
                    continue
                source = "youtube" if is_youtube else "rss"
                summary = _strip_html(entry.get("summary", "") or "")
                items.append({
                    "channel": channel,
                    "source": source,
                    "feed_domain": domain,
                    "feed_url": url,
                    "title": entry.get("title", ""),
                    "url": link,
                    "summary": summary[:600],
                    "published": published,
                    "id": hashlib.md5(link.encode()).hexdigest(),
                })
        except Exception as e:
            print(f"[RSS] Error fetching {url}: {e}")
    return items


def run() -> list[dict]:
    all_items = []
    for channel, urls in FEEDS.items():
        items = fetch_rss(channel, urls)
        rss_count = sum(1 for i in items if i["source"] == "rss")
        yt_count = sum(1 for i in items if i["source"] == "youtube")
        print(f"[Fetch] {channel}: {rss_count} RSS + {yt_count} YouTube")
        all_items.extend(items)
    return all_items


if __name__ == "__main__":
    items = run()
    out = Path("data/fetched.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(items, indent=2, ensure_ascii=False))
    print(f"\nTotal fetched: {len(items)} items → {out}")
