import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import tip_generator


def article(article_id, *, published, score=1.0, source="rss"):
    return {
        "id": article_id,
        "channel": "topic-of-the-day",
        "source": source,
        "title": f"Article {article_id}",
        "url": f"https://example.com/{article_id}",
        "summary": "Salesforce integration walkthrough",
        "published": published,
        "relevance_score": score,
    }


def rfc2822(days_ago):
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%a, %d %b %Y %H:%M:%S +0000")


def days_ago_iso(days):
    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()


class TipRotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_cwd = os.getcwd()
        os.chdir(self.temp.name)
        Path("data").mkdir()

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def write_used(self, mapping):
        Path("data/tip_used_ids.json").write_text(json.dumps(mapping), encoding="utf-8")

    def test_used_article_is_not_reposted_after_a_week(self):
        self.write_used({"old": days_ago_iso(8)})
        candidates = [article("old", published=rfc2822(60))]

        self.assertIsNone(tip_generator.pick_best_article(candidates))

    def test_unused_article_wins_over_used_high_scorer(self):
        self.write_used({"old": days_ago_iso(8)})
        candidates = [
            article("old", published=rfc2822(60), score=1.0),
            article("fresh", published=rfc2822(2), score=0.6),
        ]

        self.assertEqual(tip_generator.pick_best_article(candidates)["id"], "fresh")

    def test_freshest_article_wins_when_scores_tie(self):
        candidates = [
            article("stale", published=rfc2822(60)),
            article("recent", published=rfc2822(1)),
        ]

        self.assertEqual(tip_generator.pick_best_article(candidates)["id"], "recent")

    def test_rss_preferred_over_newer_youtube_item(self):
        candidates = [
            article("video", published=rfc2822(1), source="youtube"),
            article("post", published=rfc2822(30)),
        ]

        self.assertEqual(tip_generator.pick_best_article(candidates)["id"], "post")

    def test_reuse_allowed_only_after_long_cooldown(self):
        self.write_used({"old": days_ago_iso(tip_generator.TIP_REUSE_COOLDOWN_DAYS + 1)})
        candidates = [article("old", published=rfc2822(60))]

        self.assertEqual(tip_generator.pick_best_article(candidates)["id"], "old")

    def test_history_is_kept_beyond_the_old_seven_day_window(self):
        tip_generator.mark_tip_delivered("kept")
        self.write_used(
            {
                "kept": days_ago_iso(30),
                "expired": days_ago_iso(tip_generator.TIP_HISTORY_DAYS + 1),
            }
        )
        tip_generator.mark_tip_delivered("new")

        used = json.loads(Path("data/tip_used_ids.json").read_text(encoding="utf-8"))
        self.assertIn("kept", used)
        self.assertIn("new", used)
        self.assertNotIn("expired", used)

    def test_unparseable_used_date_still_blocks_reuse(self):
        self.write_used({"old": "not-a-date"})
        candidates = [article("old", published=rfc2822(10))]

        self.assertIsNone(tip_generator.pick_best_article(candidates))


if __name__ == "__main__":
    unittest.main()
