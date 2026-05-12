"""
poster.py — sends approved items to Microsoft Teams channels.

Supports BOTH webhook formats automatically:
  - New Teams (Workflows): https://prod-xx.logic.azure.com/...  → simple JSON
  - Old Teams (Connectors): https://xxx.webhook.office.com/...  → Adaptive Card

The URL format is detected automatically, no config needed.
"""
import os
import json
import re
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict


def _strip_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') \
               .replace('&nbsp;', ' ').replace('&quot;', '"').replace('&#39;', "'")
    return re.sub(r'\s+', ' ', text).strip()

MAX_PER_CHANNEL = 2  # max posts per channel per run (anti-spam)

CHANNEL_WEBHOOKS = {
    "certification":    "TEAMS_WEBHOOK_CERTIFICATION",
    "playground":       "TEAMS_WEBHOOK_PLAYGROUND",
    "salesforce-rss":   "TEAMS_WEBHOOK_SALESFORCE_RSS",
    "need-help":        "TEAMS_WEBHOOK_NEED_HELP",
    "meetup-events":    "TEAMS_WEBHOOK_MEETUP_EVENTS",
    "topic-of-the-day": "TEAMS_WEBHOOK_TOPIC_OF_THE_DAY",
}

SOURCE_EMOJI = {"rss": "📰", "youtube": "▶️"}


def is_new_teams_webhook(url: str) -> bool:
    """Only logic.azure.com uses simple text payload.
    powerplatform.com (Power Automate instant flows) expect Adaptive Card format."""
    return "logic.azure.com" in url


def build_new_teams_payload(item: dict) -> dict:
    """
    Payload for NEW Teams (Workflows / Power Automate).
    The workflow template expects a simple JSON body —
    we send plain text so it works with any workflow setup.
    """
    emoji = SOURCE_EMOJI.get(item["source"], "🔗")
    comment = item.get("suggested_comment", "")
    score_pct = int(item.get("relevance_score", 0.8) * 100)
    posted = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Simple text payload — works with the default Workflows webhook template
    text = (
        f"{emoji} **{item['title']}**\n\n"
        f"{comment}\n\n"
        f"🔗 {item['url']}\n\n"
        f"_Source: {item['source'].capitalize()} · Relevance: {score_pct}% · {posted}_"
    )
    return {"text": text}


def build_old_teams_payload(item: dict) -> dict:
    """Adaptive Card payload for OLD Teams (Incoming Webhook Connector)."""
    emoji = SOURCE_EMOJI.get(item["source"], "🔗")
    score_pct = int(item.get("relevance_score", 0.8) * 100)
    comment = item.get("suggested_comment", item["title"])
    posted = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary = _strip_html(item.get("summary") or "")[:500]

    body_blocks = [
        {
            "type": "TextBlock",
            "text": f"{emoji} {item['title']}",
            "weight": "Bolder",
            "size": "Medium",
            "wrap": True,
        },
    ]
    if summary:
        body_blocks.append({
            "type": "TextBlock",
            "text": summary,
            "wrap": True,
            "spacing": "Small",
            "isSubtle": True,
        })
    body_blocks += [
        {
            "type": "TextBlock",
            "text": comment,
            "wrap": True,
            "spacing": "Small",
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "Source",    "value": item.get("feed_domain") or item["source"].capitalize()},
                {"title": "Type",      "value": item["source"].capitalize()},
                {"title": "Relevance", "value": f"{score_pct}%"},
                {"title": "Posted",    "value": posted},
            ],
            "spacing": "Medium",
        },
    ]

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": body_blocks,
                "actions": [{
                    "type": "Action.OpenUrl",
                    "title": "Read more →",
                    "url": item["url"],
                }],
            },
        }],
    }


def build_tip_image_payload(item: dict) -> dict:
    """
    Adaptive Card that shows the PNG image + a 'Read article' button.
    Used when item["source"] == "generated_tip" and a PNG was rendered.
    Works with both old (Connector) and new (Workflows) webhook formats via the
    caller selecting the right outer wrapper.
    """
    tip = item.get("tip_data", {})
    title   = tip.get("title", item.get("title", "Salesforce Tip of the Day"))
    benefit = tip.get("benefit", item.get("summary", ""))
    png_url = item.get("png_url", "")
    src_url = item.get("url", tip.get("source_url", ""))
    label   = tip.get("label", "Tip of the Day")
    domain  = item.get("feed_domain") or tip.get("source_domain", "")
    posted  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    body_blocks: list = []

    if png_url:
        body_blocks.append({
            "type": "Image",
            "url": png_url,
            "altText": title,
            "size": "Stretch",
            "style": "default",
        })
    else:
        # Fallback text card when no PNG
        body_blocks += [
            {
                "type": "TextBlock",
                "text": f"🔥 {title}",
                "weight": "Bolder",
                "size": "Large",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": benefit,
                "wrap": True,
                "spacing": "Small",
            },
        ]

    body_blocks.append({
        "type": "FactSet",
        "facts": [
            {"title": "Label",  "value": label},
            {"title": "Source", "value": domain},
            {"title": "Posted", "value": posted},
        ],
        "spacing": "Small",
    })

    actions = []
    if src_url:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "Read full article →",
            "url": src_url,
        })
    if png_url:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "Open image ↗",
            "url": png_url,
        })

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": body_blocks,
                "actions": actions,
            },
        }],
    }


def post_to_teams(webhook_url: str, item: dict) -> tuple[bool, str]:
    """Returns (success, error_message)."""
    # Generated tip always uses Adaptive Card with image
    if item.get("source") == "generated_tip":
        payload = build_tip_image_payload(item)
        webhook_type = "Tip Card"
    elif is_new_teams_webhook(webhook_url):
        payload = build_new_teams_payload(item)
        webhook_type = "Workflows (new)"
    else:
        payload = build_old_teams_payload(item)
        webhook_type = "Connector (old)"

    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        resp.raise_for_status()
        print(f"    [{webhook_type}] ✅ posted")
        return True, ""
    except Exception as e:
        err = str(e)
        print(f"    [{webhook_type}] ❌ failed: {err}")
        return False, err


def run(items: list[dict]) -> list[dict]:
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    if dry_run:
        print("[Poster] 🔍 DRY RUN — no posts will be sent to Teams")

    # Apply per-channel cap: sort by score, keep top MAX_PER_CHANNEL per channel
    by_channel: dict[str, list] = defaultdict(list)
    for item in items:
        by_channel[item["channel"]].append(item)
    capped: list[dict] = []
    for ch_items in by_channel.values():
        ch_items.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        capped.extend(ch_items[:MAX_PER_CHANNEL])

    results = []  # all processed items: posted + failed
    warned: set[str] = set()

    for item in capped:
        channel = item["channel"]
        secret_name = CHANNEL_WEBHOOKS.get(channel)
        if not secret_name:
            continue

        webhook_url = (os.getenv(secret_name) or "").strip()
        if not webhook_url:
            if secret_name not in warned:
                print(f"[Poster] ⚠️  {secret_name} not set — skipping #{channel}")
                warned.add(secret_name)
            results.append({
                **item,
                "posted_at": datetime.now(timezone.utc).isoformat(),
                "status": "failed",
                "error": f"{secret_name} secret not configured",
            })
            continue

        print(f"  → #{channel}: {item['title'][:55]}")

        if dry_run:
            print(f"    [DRY RUN] would post to {secret_name}")
            results.append({
                **item,
                "posted_at": datetime.now(timezone.utc).isoformat(),
                "status": "dry_run",
                "error": "",
            })
            continue

        success, error = post_to_teams(webhook_url, item)
        results.append({
            **item,
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "status": "posted" if success else "failed",
            "error": error,
        })
        time.sleep(1)  # rate-limit: avoid hammering Teams webhook API

    return results


def append_to_log(results: list[dict]):
    log_file = Path("data/post_log.json")
    existing = []
    if log_file.exists():
        try:
            existing = json.loads(log_file.read_text())
        except Exception:
            pass
    combined = (existing + results)[-500:]
    log_file.write_text(json.dumps(combined, indent=2, ensure_ascii=False))
    posted_n = sum(1 for r in results if r["status"] == "posted")
    failed_n = sum(1 for r in results if r["status"] == "failed")
    print(f"[Poster] Log updated → {len(combined)} total entries ({posted_n} posted, {failed_n} failed)")


if __name__ == "__main__":
    approved = json.loads(Path("data/approved.json").read_text())
    posted = run(approved)
    append_to_log(posted)
    Path("data/posted.json").write_text(json.dumps(posted, indent=2, ensure_ascii=False))
    print(f"\nPosted: {len(posted)} items")
