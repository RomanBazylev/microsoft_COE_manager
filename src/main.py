#!/usr/bin/env python3
"""
main.py — entrypoint for the SF Auto-Poster pipeline.
Run locally:   python src/main.py
Run in CI:     same (GitHub Actions calls this directly)
"""
import sys
from pathlib import Path

# Add src/ to path when running from repo root
sys.path.insert(0, str(Path(__file__).parent))

import fetcher
import filter as content_filter
import poster


def main():
    print("=" * 50)
    print("SF Auto-Poster — starting pipeline")
    print("=" * 50)

    # Step 1: Fetch
    print("\n[1/3] Fetching content...")
    items = fetcher.run()
    print(f"      Total fetched: {len(items)}")

    if not items:
        print("No items fetched, exiting.")
        return

    # Step 2: Filter + score
    print("\n[2/3] Filtering with AI...")
    approved = content_filter.run(items)
    print(f"      Approved: {len(approved)}")

    if not approved:
        print("Nothing passed the filter, exiting.")
        return

    # Step 3: Post to Teams
    print("\n[3/3] Posting to Teams...")
    results = poster.run(approved)
    poster.append_to_log(results)

    posted_count = sum(1 for r in results if r["status"] == "posted")
    failed_count = sum(1 for r in results if r["status"] == "failed")
    dry_count = sum(1 for r in results if r["status"] == "dry_run")

    print("\n" + "=" * 50)
    if dry_count:
        print(f"DRY RUN: {dry_count} items would have been posted.")
    else:
        print(f"Done! Posted {posted_count} | Failed {failed_count} | Total processed {len(results)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
