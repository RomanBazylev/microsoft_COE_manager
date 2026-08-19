"""Fetch working event links from the official Salesforce events catalog."""
import hashlib
import re
import html
import requests
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.parse import urlparse

SALESFORCE_EVENTS_URL = "https://www.salesforce.com/events/"
_last_health: list[dict] = []


class _EventLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.href = None
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.links.append((self.href, _strip_html(" ".join(self.text))))
            self.href = None
            self.text = []

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)


def fetch_salesforce_events(session=requests) -> tuple[list[dict], dict]:
    """Poll the official Salesforce events catalog without relying on dead RSS."""
    health = {
        "source": "Salesforce Events",
        "url": SALESFORCE_EVENTS_URL,
        "kind": "official_events",
        "official": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "error",
        "http_status": None,
        "entries": 0,
        "error": "",
    }
    try:
        response = session.get(
            SALESFORCE_EVENTS_URL,
            timeout=25,
            headers={"User-Agent": "Salesforce-CoE-Autoposter/1.0"},
        )
        health["http_status"] = response.status_code
        response.raise_for_status()
        parser = _EventLinkParser()
        parser.feed(response.content.decode("utf-8", errors="replace"))
        by_url = {}
        event_pattern = re.compile(
            r"dreamforce|world tour|connections|trailblazerdx|webinar|salesforce\+|register",
            re.IGNORECASE,
        )
        for href, title in parser.links:
            url = urljoin(response.url, href)
            host = urlparse(url).netloc.lower()
            if not title or "salesforce.com" not in host:
                continue
            if not event_pattern.search(f"{title} {url}"):
                continue
            path = urlparse(url).path
            if path.startswith("/dreamforce/"):
                url, title = "https://www.salesforce.com/dreamforce/", "Dreamforce"
            elif path.startswith("/connections/"):
                url, title = "https://www.salesforce.com/connections/", "Salesforce Connections"
            elif path in {"/events", "/events/"} and "world tour" not in title.casefold():
                continue
            by_url[url] = {
                "channel": "meetup-events",
                "source": "official_event",
                "feed_domain": host.removeprefix("www."),
                "feed_url": SALESFORCE_EVENTS_URL,
                "title": title[:240],
                "url": url,
                "summary": "Official Salesforce event or webinar.",
                "published": None,
                "id": hashlib.md5(url.encode()).hexdigest(),
                "must_post": False,
                "official": True,
                "source_priority": 85,
            }
        items = sorted(by_url.values(), key=lambda item: item["url"])
        health["entries"] = len(items)
        health["status"] = "ok" if items else "empty"
        if not items:
            health["error"] = "No event links matched; page structure may have changed"
        return items, health
    except Exception as exc:
        health["error"] = str(exc)[:300]
        return [], health


def _strip_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def run() -> list[dict]:
    """Fetch all event sources and return combined items."""
    global _last_health
    all_items = []
    official_items, health = fetch_salesforce_events()
    print(f"[Events] Salesforce official: {len(official_items)} events ({health['status']})")
    all_items.extend(official_items)
    _last_health = [health]

    return all_items


def get_last_health() -> list[dict]:
    return list(_last_health)


if __name__ == "__main__":
    import json
    from pathlib import Path
    items = run()
    print(f"\nTotal events found: {len(items)}")
    for item in items:
        print(f"  - {item['title'][:60]} ({item['feed_domain']})")
