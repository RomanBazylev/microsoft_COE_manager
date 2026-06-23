#!/usr/bin/env python3
"""
main.py — entrypoint for the SF Auto-Poster pipeline.
Run locally:   python src/main.py
Run in CI:     same (GitHub Actions calls this directly)

Env vars:
  DRY_RUN=true          — log only, no Teams posts
  CHANNELS_FILTER=a,b   — only process listed channels (comma-separated)
"""
import sys
from pathlib import Path

# Add src/ to path when running from repo root
sys.path.insert(0, str(Path(__file__).parent))

import fetcher
import filter as content_filter
import poster
import tip_generator
import tip_renderer
import events_fetcher


def _channels_filter() -> set[str] | None:
    """Return a set of channel names to process, or None to process all."""
    import os
    val = os.getenv("CHANNELS_FILTER", "").strip()
    if not val:
        return None
    return {c.strip() for c in val.split(",") if c.strip()}


def main():
    print("=" * 50)
    print("SF Auto-Poster — starting pipeline")
    print("=" * 50)

    channels = _channels_filter()
    if channels:
        print(f"[Config] CHANNELS_FILTER = {channels}")

    # Step 1: Fetch
    print("\n[1/5] Fetching content...")
    items = fetcher.run()

    # Also fetch dedicated events if meetup-events channel is active
    events_running = channels is None or "meetup-events" in channels
    if events_running:
        event_items = events_fetcher.run()
        items.extend(event_items)

    if channels:
        items = [i for i in items if i.get("channel") in channels]
    print(f"      Total fetched: {len(items)}")

    if not items:
        print("No items fetched, exiting.")
        return

    # Save raw topic-of-the-day items BEFORE filter marks them as seen.
    # Tip card generation needs the best RECENT article regardless of seen_ids
    # (blogs don't publish daily; seen_ids would starve the tip queue after the first run).
    tip_running = channels is None or "topic-of-the-day" in channels
    raw_topic_items = (
        [i for i in items if i.get("channel") == "topic-of-the-day"]
        if tip_running else []
    )

    # Step 2: Filter + score
    print("\n[2/5] Filtering with AI...")
    approved = content_filter.run(items)
    print(f"      Approved: {len(approved)}")

    # Step 3: Generate daily tip card (topic-of-the-day only)
    print("\n[3/5] Generating tip card...")
    if tip_running:
        # Score raw topic items independently of seen_ids
        scored_topic = [content_filter.score_item(i) for i in raw_topic_items]
        scored_topic = [
            i for i in scored_topic
            if i.get("relevance_score", 0) >= content_filter.RELEVANCE_THRESHOLD
        ]
        print(f"      Topic-of-the-day candidates: {len(scored_topic)} (from feed, incl. seen)")
        best_article = tip_generator.pick_best_article(scored_topic)
        if best_article:
            print(f"      Best article: {best_article['title'][:70]}")
            tip_item = tip_generator.generate_tip_item(best_article)

            # Remove the original article from approved if it happened to be new this run
            approved = [i for i in approved if i.get("id") != best_article.get("id")]

            # Render PNG
            png_path = tip_renderer.render_tip(tip_item)
            if png_path:
                print(f"      PNG rendered → {tip_item['png_url']}")
            else:
                print("      PNG render failed — tip will post as text card (no image)")
                tip_item["png_url"] = ""

            approved.append(tip_item)
        else:
            print("      No topic-of-the-day article found — skipping tip card")
    else:
        print("      Skipped (CHANNELS_FILTER excludes topic-of-the-day)")

    if not approved:
        print("Nothing to post, exiting.")
        return

    # Step 4: Post to Teams
    print("\n[4/5] Posting to Teams...")
    results = poster.run(approved)
    poster.append_to_log(results)

    posted_count = sum(1 for r in results if r["status"] == "posted")
    failed_count = sum(1 for r in results if r["status"] == "failed")
    dry_count    = sum(1 for r in results if r["status"] == "dry_run")

    print("\n" + "=" * 50)
    if dry_count:
        print(f"DRY RUN: {dry_count} items would have been posted.")
    else:
        print(f"Done! Posted {posted_count} | Failed {failed_count} | Total processed {len(results)}")
    print("=" * 50)


if __name__ == "__main__":
    main()

