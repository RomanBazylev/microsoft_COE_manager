"""
tip_generator.py — picks the best article from topic-of-the-day and asks Gemini
to structure it into a LinkedIn-style tip card (BEFORE/AFTER code, use cases, benefit).

Output dict has source="generated_tip" and is compatible with poster.run().
Falls back gracefully if Gemini is unavailable.
"""
import json
import os
import re
import time
import requests
from datetime import datetime, timezone

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)
GEMINI_TIMEOUT = 30
GITHUB_PAGES_BASE = "https://romanbazylev.github.io/microsoft_COE_manager"

GEMINI_PROMPT_TEMPLATE = """\
You are a Salesforce educator creating a daily visual tip card for a developer/admin team channel.

Based on the article below, extract or infer a concrete, practical Salesforce tip.
Respond ONLY with valid JSON (no markdown fences, no commentary).

Article title: {title}
Article summary: {summary}
Article URL: {url}

Return this exact JSON structure:
{{
  "title": "Short punchy feature/tip title (max 8 words)",
  "subtitle": "One sentence explaining what this tip is about",
  "label": "Category label e.g. Apex / Flow / LWC / Admin / Agentforce / Security",
  "before_code": "The old/verbose/wrong way — 3-6 lines of Salesforce code or config (Apex/SOQL/JSON/XML). Use \\n for newlines.",
  "before_label": "BEFORE — The Old Way",
  "after_code": "The new/better/cleaner way — 3-6 lines. Use \\n for newlines.",
  "after_label": "AFTER — Summer '26",
  "use_cases": ["Use case 1 (concrete)", "Use case 2", "Use case 3"],
  "benefit": "One sentence: why developers/admins will love this",
  "source_url": "{url}",
  "source_domain": "{domain}"
}}

Rules:
- before_code and after_code MUST be actual code or config, not prose
- If the article is not about a specific code feature, make a realistic before/after comparing an old admin approach vs new
- Keep code snippets short (3-6 lines) and readable
- Do not hallucinate — base content on the article
"""


def _get_gemini_key() -> str | None:
    return os.getenv("GEMINI_API_KEY", "").strip() or None


def _domain_from_url(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return "salesforce.com"


def pick_best_article(approved_items: list[dict]) -> dict | None:
    """Return the highest-scoring topic-of-the-day item, preferring RSS over YouTube."""
    candidates = [i for i in approved_items if i.get("channel") == "topic-of-the-day"]
    if not candidates:
        return None
    # Prefer RSS (has actual article text), deprioritize youtube
    candidates.sort(key=lambda x: (
        0 if x.get("source") == "youtube" else 1,
        x.get("relevance_score", 0),
    ), reverse=True)
    return candidates[0]


def _call_gemini(article: dict) -> dict | None:
    key = _get_gemini_key()
    if not key:
        return None

    prompt = GEMINI_PROMPT_TEMPLATE.format(
        title=article.get("title", ""),
        summary=(article.get("summary") or "")[:800],
        url=article.get("url", ""),
        domain=_domain_from_url(article.get("url", "")),
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 600,
            "temperature": 0.3,
            "responseMimeType": "application/json",
        },
    }

    for attempt in range(2):
        try:
            resp = requests.post(
                GEMINI_API_URL,
                headers={"x-goog-api-key": key},
                json=payload,
                timeout=GEMINI_TIMEOUT,
            )
            if resp.status_code == 429:
                print("[TipGen] Gemini quota hit — using fallback")
                return None
            if not resp.ok:
                print(f"[TipGen] Gemini HTTP {resp.status_code} — using fallback")
                return None

            raw_text = (
                resp.json()
                .get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            # Strip markdown fences if model ignored responseMimeType
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

            data = json.loads(raw_text)
            # Validate required keys
            required = {"title", "before_code", "after_code", "use_cases", "benefit"}
            if not required.issubset(data.keys()):
                print("[TipGen] Gemini JSON missing keys — using fallback")
                return None
            print(f"[TipGen] Gemini tip generated: {data['title']}")
            return data

        except json.JSONDecodeError as e:
            print(f"[TipGen] JSON parse error (attempt {attempt+1}): {e}")
            if attempt == 0:
                time.sleep(1)
        except requests.exceptions.Timeout:
            print(f"[TipGen] Timeout (attempt {attempt+1})")
            if attempt == 0:
                time.sleep(2)
        except Exception as e:
            print(f"[TipGen] Error: {e}")
            return None
    return None


def _fallback_tip(article: dict) -> dict:
    """Build a minimal tip dict from the article without BEFORE/AFTER code."""
    title = article.get("title", "Salesforce Tip of the Day")
    summary = (article.get("summary") or "")[:300]
    url = article.get("url", "")
    return {
        "title": title[:60],
        "subtitle": summary[:120] if summary else "Check out this Salesforce resource.",
        "label": "Tip of the Day",
        "before_code": None,
        "before_label": None,
        "after_code": None,
        "after_label": None,
        "use_cases": [],
        "benefit": summary[:200] if summary else "",
        "source_url": url,
        "source_domain": _domain_from_url(url),
    }


def generate_tip_item(article: dict) -> dict:
    """
    Returns an item dict ready for poster.run():
    - source="generated_tip"
    - tip_data: structured tip (with or without BEFORE/AFTER)
    - png_url: will be filled in by tip_renderer after rendering
    """
    tip_data = _call_gemini(article) or _fallback_tip(article)
    has_code = bool(tip_data.get("before_code") and tip_data.get("after_code"))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    png_filename = f"tip_{today}.png"
    png_url = f"{GITHUB_PAGES_BASE}/{png_filename}"

    return {
        # poster-compatible fields
        "channel": "topic-of-the-day",
        "source": "generated_tip",
        "title": tip_data["title"],
        "url": tip_data.get("source_url", article.get("url", "")),
        "summary": tip_data.get("benefit", ""),
        "published": article.get("published"),
        "id": article.get("id", ""),
        "relevance_score": article.get("relevance_score", 1.0),
        "suggested_comment": tip_data.get("benefit", ""),
        "feed_domain": tip_data.get("source_domain", ""),
        # tip-specific fields
        "tip_data": tip_data,
        "has_code": has_code,
        "png_filename": png_filename,
        "png_url": png_url,
    }


if __name__ == "__main__":
    # Quick smoke test — simulate an article
    test_article = {
        "channel": "topic-of-the-day",
        "source": "rss",
        "title": "Apex Multiline Strings in Salesforce Summer '26",
        "url": "https://salesforcemonday.com/2026/05/01/apex-multiline-strings/",
        "summary": (
            "Salesforce Summer '26 introduces Apex Text Blocks — triple-quoted multiline strings. "
            "Developers no longer need to concatenate strings with \\n. Clean, readable code "
            "for SOQL, JSON payloads, HTML templates, and debug logs."
        ),
        "published": "Mon, 01 May 2026 08:00:00 +0000",
        "id": "test123",
        "relevance_score": 0.9,
    }
    item = generate_tip_item(test_article)
    print("\n--- Generated tip item ---")
    print(json.dumps({k: v for k, v in item.items() if k != "tip_data"}, indent=2))
    print("\n--- tip_data ---")
    print(json.dumps(item["tip_data"], indent=2))
