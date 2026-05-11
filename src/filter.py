"""
filter.py — keyword scoring + optional Gemini AI summaries.
Gemini runs only if GEMINI_API_KEY is set.
Any failure (bad key, quota 429, timeout, network) → silent fallback to static comment.
"""
import json
import os
import time
import requests
from pathlib import Path

RELEVANCE_THRESHOLD = 0.25
MATCH_SATURATION = 3  # 3 channel keyword matches = full relevance

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)
GEMINI_TIMEOUT = 20
GEMINI_MAX_RETRIES = 2

CHANNEL_KEYWORDS: dict[str, list[str]] = {
    "certification": [
        "certification", "exam", "certified", "study", "trailhead",
        "badge", "prepare", "preparation", "administrator", "platform developer",
        "superbadge", "focus on force", "pass", "tips",
    ],
    "playground": [
        "apex", "lwc", "lightning web component", "developer", "code",
        "api", "soql", "trigger", "class", "component", "visualforce",
        "sandbox", "debug", "deploy", "metadata", "cli", "vscode",
    ],
    "salesforce-rss": [
        "salesforce", "release", "update", "new feature", "spring", "summer",
        "winter", "admin", "flow", "automation", "einstein", "crm",
        "platform", "announcement",
    ],
    "need-help": [
        "error", "issue", "problem", "help", "how to", "solution",
        "governor limit", "debug", "fix", "workaround", "best practice",
        "question", "stack", "overflow",
    ],
    "meetup-events": [
        "event", "meetup", "conference", "webinar", "dreamin", "world tour",
        "trailblazer", "community", "user group", "virtual", "live", "register",
    ],
    "topic-of-the-day": [
        "salesforce", "crm", "cloud", "trailblazer",
        "spring", "summer", "winter", "release notes", "new features",
        "agentforce", "einstein", "platform update",
    ],
}

RELEASE_KEYWORDS = [
    "spring '", "summer '", "winter '", "release notes", "new features",
    "'26", "'27", "spring 2", "summer 2", "winter 2", "release highlights",
    "what's new",
]

GENERIC_SF_KEYWORDS = [
    "salesforce", "sfdc", "sf", "trailhead", "trailblazer", "appexchange",
]

CHANNEL_COMMENTS: dict[str, str] = {
    "certification":    "📚 Useful resource for your certification journey!",
    "playground":       "🛠️ Worth checking out for your dev work!",
    "salesforce-rss":   "📰 Latest from the Salesforce world.",
    "need-help":        "💡 This might help with common issues.",
    "meetup-events":    "📅 Upcoming Salesforce event — mark your calendar!",
    "topic-of-the-day": "🔥 Interesting Salesforce topic for today.",
}

CHANNEL_PROMPTS: dict[str, str] = {
    "certification":    "certification preparation and Salesforce exam tips",
    "playground":       "Salesforce developer tools, Apex, LWC, or APIs",
    "salesforce-rss":   "Salesforce platform news and updates",
    "need-help":        "solving Salesforce development or admin problems",
    "meetup-events":    "Salesforce community events and meetups",
    "topic-of-the-day": "Salesforce release notes or platform updates",
}

_gemini_key: str | None = None
_gemini_quota_hit = False


def _get_key() -> str | None:
    global _gemini_key
    if _gemini_key is None:
        _gemini_key = os.getenv("GEMINI_API_KEY", "").strip() or None
    return _gemini_key


def _gemini_summary(item: dict) -> str | None:
    """Call Gemini for a 2-sentence Teams post comment. Returns None on any error."""
    global _gemini_quota_hit
    key = _get_key()
    if not key or _gemini_quota_hit:
        return None

    channel = item.get("channel", "")
    topic = CHANNEL_PROMPTS.get(channel, "Salesforce")
    prompt = (
        f"You are writing a short Teams message for a Salesforce CoE channel about {topic}.\n"
        f"Content title: {item.get('title', '')}\n"
        f"Content snippet: {item.get('summary', '')[:400]}\n"
        f"Source type: {item.get('source', 'article')}\n\n"
        f"Write exactly 2 sentences (max 60 words total) that explain why this is useful "
        f"for a Salesforce developer or admin team. Be specific, no generic filler. "
        f"No hashtags. No emojis. Plain text only."
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 120, "temperature": 0.4},
    }

    for attempt in range(GEMINI_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                GEMINI_API_URL, headers={"x-goog-api-key": key}, json=payload, timeout=GEMINI_TIMEOUT
            )
            if resp.status_code == 429:
                print("[Gemini] Quota exceeded — fallback for this run")
                _gemini_quota_hit = True
                return None
            if resp.status_code in (400, 403):
                print(f"[Gemini] HTTP {resp.status_code} — check API key settings")
                return None
            if not resp.ok:
                print(f"[Gemini] HTTP {resp.status_code} — skipping")
                return None
            data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            return text or None
        except requests.exceptions.Timeout:
            print(f"[Gemini] Timeout (attempt {attempt + 1}) — skipping")
            if attempt < GEMINI_MAX_RETRIES:
                time.sleep(1)
        except Exception as e:
            print(f"[Gemini] Error: {e} — skipping")
            return None
    return None


def score_item(item: dict) -> dict:
    channel = item.get("channel", "")
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()

    keywords = CHANNEL_KEYWORDS.get(channel, [])
    matches = sum(1 for kw in keywords if kw in text)
    generic_matches = sum(1 for kw in GENERIC_SF_KEYWORDS if kw in text)

    score = min(matches / MATCH_SATURATION + generic_matches * 0.05, 1.0)

    if item.get("source") == "youtube":
        score = min(score + 0.15, 1.0)

    # Release notes boost for topic-of-the-day
    if channel == "topic-of-the-day":
        release_matches = sum(1 for kw in RELEASE_KEYWORDS if kw in text)
        if release_matches > 0:
            score = min(score + 0.3, 1.0)

    return {
        **item,
        "relevance_score": round(score, 2),
        "reason": f"Matched {matches} channel keywords, {generic_matches} generic SF keywords",
        "suggested_comment": CHANNEL_COMMENTS.get(channel, "🔗 Check this out!"),
        "ai_summary": None,
    }


def load_seen_ids() -> set:
    seen_file = Path("data/seen_ids.json")
    if seen_file.exists():
        return set(json.loads(seen_file.read_text(encoding="utf-8-sig")))
    return set()


def save_seen_ids(ids: set):
    Path("data/seen_ids.json").write_text(json.dumps(list(ids), indent=2), encoding="utf-8")


def run(items: list[dict]) -> list[dict]:
    seen_ids = load_seen_ids()

    new_items = [i for i in items if i["id"] not in seen_ids]
    print(f"[Filter] {len(new_items)} new (skipped {len(items)-len(new_items)} duplicates)")

    # Within-run dedup: same URL may appear for multiple channels — keep highest-priority channel only
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for i in new_items:
        url = i.get("url", "")
        if url and url in seen_urls:
            print(f"  [DEDUP] {i['channel']} / {i['title'][:60]}")
            continue
        if url:
            seen_urls.add(url)
        deduped.append(i)
    new_items = deduped

    scored = [score_item(i) for i in new_items]
    approved = [i for i in scored if i.get("relevance_score", 0) >= RELEVANCE_THRESHOLD]
    rejected = [i for i in scored if i.get("relevance_score", 0) < RELEVANCE_THRESHOLD]
    print(f"[Filter] Approved: {len(approved)}/{len(scored)} (threshold={RELEVANCE_THRESHOLD})")
    for i in rejected:
        print(f"  [SKIP {i['relevance_score']:.2f}] {i['title'][:70]}")

    gemini_key = _get_key()
    print(f"[Filter] Gemini: {'enabled' if gemini_key else 'no key — using static comments'}")

    for i in approved:
        print(f"  [OK   {i['relevance_score']:.2f}] {i['title'][:60]}")
        if gemini_key and not _gemini_quota_hit:
            ai = _gemini_summary(i)
            if ai:
                i["suggested_comment"] = ai
                i["ai_summary"] = ai
                print(f"         AI: {ai[:80]}...")

    new_seen = {i["id"] for i in new_items}
    save_seen_ids(seen_ids | new_seen)

    return approved


if __name__ == "__main__":
    raw = json.loads(Path("data/fetched.json").read_text())
    approved = run(raw)
    Path("data/approved.json").write_text(json.dumps(approved, indent=2, ensure_ascii=False))
    print(f"\nApproved → data/approved.json ({len(approved)} items)")
