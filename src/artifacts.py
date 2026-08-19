"""Build machine-readable run artifacts for GitHub Pages and CI."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def build_run_summary(
    *,
    trigger: str,
    dry_run: bool,
    fetched: int,
    approved: int,
    results: list[dict],
    feed_health: list[dict],
) -> dict:
    statuses = {
        status: sum(1 for result in results if result.get("status") == status)
        for status in ("posted", "failed", "dry_run")
    }
    health_counts = {
        status: sum(1 for source in feed_health if source.get("status") == status)
        for status in ("ok", "degraded", "empty", "error")
    }
    return {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "dry_run": dry_run,
        "fetched": fetched,
        "approved": approved,
        "results": statuses,
        "feed_health": health_counts,
    }


def write_run_artifacts(
    summary: dict,
    feed_health: list[dict],
    output_dir: str | Path = "data",
) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    last_run = destination / "last_run.json"
    health = destination / "feed_health.json"
    last_run.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    health.write_text(json.dumps(feed_health, indent=2, ensure_ascii=False), encoding="utf-8")
    return last_run, health
