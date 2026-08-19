"""Poll official Salesforce release resources that do not provide RSS."""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests

RELEASES_HUB_URL = "https://www.salesforce.com/releases/"
USER_AGENT = "Salesforce-CoE-Autoposter/1.0"
RESOURCE_PATTERN = re.compile(
    r"(release notes?|release highlights?|release readiness|release resources?|"
    r"prepare for (?:the )?(?:spring|summer|winter)|"
    r"(?:spring|summer|winter)\s*[’'\-]?\s*\d{2}\s+release)",
    re.IGNORECASE,
)
OFFICIAL_HOSTS = {
    "salesforce.com",
    "www.salesforce.com",
    "help.salesforce.com",
    "trailhead.salesforce.com",
    "admin.salesforce.com",
}


def _clean(value: str) -> str:
    value = (value or "").replace("\ufffd", "’")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _canonical_url(url: str, base_url: str) -> str:
    absolute = urljoin(base_url, url)
    parts = urlparse(absolute)
    host = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    if host == "trailhead.salesforce.com":
        path = re.sub(r"(/groups/[A-Za-z0-9]{15})[A-Za-z0-9]{3}$", r"\1", path)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() in {"id", "release", "type"}
    ]
    return urlunparse((
        parts.scheme,
        host,
        path,
        "",
        urlencode(query),
        "",
    ))


class _ReleasePageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.title_parts: list[str] = []
        self.current_href: str | None = None
        self.current_text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        if tag == "a":
            self.current_href = dict(attrs).get("href")
            self.current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.current_href:
            self.links.append((self.current_href, _clean(" ".join(self.current_text))))
            self.current_href = None
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.current_href is not None:
            self.current_text.append(data)


def parse_release_resources(page_html: str, base_url: str = RELEASES_HUB_URL) -> list[dict]:
    """Return stable, mandatory items for the hub and its release resources."""
    parser = _ReleasePageParser()
    parser.feed(page_html)

    page_title = _clean(" ".join(parser.title_parts)) or "Salesforce Releases"
    candidates = [(base_url, page_title), *parser.links]
    by_url: dict[str, dict] = {}

    for href, title in candidates:
        url = _canonical_url(href, base_url)
        host = urlparse(url).netloc.lower()
        searchable = f"{title} {url}"
        if host not in OFFICIAL_HOSTS or not RESOURCE_PATTERN.search(searchable):
            continue

        clean_title = title or "Salesforce release resource"
        # A changed resource label produces a new delivery id while the canonical
        # URL remains the within-run deduplication key.
        fingerprint = f"{url}\n{clean_title.casefold()}"
        item = {
            "channel": (
                "certification"
                if host == "trailhead.salesforce.com" or "release highlight" in clean_title.casefold()
                else "salesforce-rss"
            ),
            "source": "official_release",
            "feed_domain": host.removeprefix("www."),
            "feed_url": base_url,
            "title": clean_title[:240],
            "url": url,
            "summary": "Official Salesforce release resource or Trailhead release highlight.",
            "published": None,
            "id": hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
            "must_post": True,
            "official": True,
            "source_priority": 100,
        }
        previous = by_url.get(url)
        if previous is None or len(item["title"]) > len(previous["title"]):
            by_url[url] = item

    return sorted(by_url.values(), key=lambda item: (item["url"], item["title"]))


def fetch_release_resources(session=requests) -> tuple[list[dict], dict]:
    checked_at = datetime.now(timezone.utc).isoformat()
    health = {
        "source": "Salesforce Releases hub",
        "url": RELEASES_HUB_URL,
        "kind": "official_release",
        "official": True,
        "checked_at": checked_at,
        "status": "error",
        "http_status": None,
        "entries": 0,
        "error": "",
    }
    try:
        response = session.get(
            RELEASES_HUB_URL,
            timeout=25,
            headers={"User-Agent": USER_AGENT},
        )
        health["http_status"] = response.status_code
        response.raise_for_status()
        page_text = response.content.decode("utf-8", errors="replace")
        items = parse_release_resources(page_text, response.url)
        health["entries"] = len(items)
        health["status"] = "ok" if items else "empty"
        if not items:
            health["error"] = "No release resources matched; page structure may have changed"
        return items, health
    except Exception as exc:
        health["error"] = str(exc)[:300]
        return [], health


def run() -> tuple[list[dict], list[dict]]:
    items, health = fetch_release_resources()
    print(f"[Official] Releases hub: {len(items)} resources ({health['status']})")
    return items, [health]
