"""
filter.py — FREE keyword-based filter for testing.
No API keys needed. Scores items by matching keywords relevant to each channel.

When ready to switch to AI filtering: set ANTHROPIC_API_KEY in GitHub Secrets
and replace this file with filter_ai.py (included in the repo).
"""
import json
from pathlib import Path

RELEVANCE_THRESHOLD = 0.4  # lower threshold since we use simple scoring

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


def score_item(item: dict) -> dict:
    channel = item.get("channel", "")
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()

    keywords = CHANNEL_KEYWORDS.get(channel, [])
    matches = sum(1 for kw in keywords if kw in text)
    generic_matches = sum(1 for kw in GENERIC_SF_KEYWORDS if kw in text)

    max_possible = max(len(keywords), 1)
    score = min(matches / max_possible + generic_matches * 0.05, 1.0)

    if item.get("source") == "youtube":
        score = min(score + 0.15, 1.0)

    # Release notes boost for topic-of-the-day
    if channel == "topic-of-the-day":
        release_matches = sum(1 for kw in RELEASE_KEYWORDS if kw in text)
        if release_matches > 0:
            score = min(score + 0.3, 1.0)

    comment = CHANNEL_COMMENTS.get(channel, "🔗 Check this out!")

    return {
        **item,
        "relevance_score": round(score, 2),
        "reason": f"Matched {matches} channel keywords, {generic_matches} generic SF keywords",
        "suggested_comment": comment,
    }


def load_seen_ids() -> set:
    seen_file = Path("data/seen_ids.json")
    if seen_file.exists():
        return set(json.loads(seen_file.read_text()))
    return set()


def save_seen_ids(ids: set):
    Path("data/seen_ids.json").write_text(json.dumps(list(ids), indent=2))


def run(items: list[dict]) -> list[dict]:
    seen_ids = load_seen_ids()

    new_items = [i for i in items if i["id"] not in seen_ids]
    print(f"[Filter] {len(new_items)} new (skipped {len(items)-len(new_items)} duplicates)")

    scored = [score_item(i) for i in new_items]
    approved = [i for i in scored if i.get("relevance_score", 0) >= RELEVANCE_THRESHOLD]
    print(f"[Filter] Approved: {len(approved)}/{len(scored)}")

    for i in approved:
        print(f"  [{i['relevance_score']:.2f}] {i['title'][:60]}")

    new_seen = {i["id"] for i in new_items}
    save_seen_ids(seen_ids | new_seen)

    return approved


if __name__ == "__main__":
    raw = json.loads(Path("data/fetched.json").read_text())
    approved = run(raw)
    Path("data/approved.json").write_text(json.dumps(approved, indent=2, ensure_ascii=False))
    print(f"\nApproved → data/approved.json ({len(approved)} items)")
