import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import filter as content_filter
import poster


def item(item_id, *, channel="salesforce-rss", score=0.8, must_post=False, priority=20):
    return {
        "id": item_id,
        "url": f"https://example.com/{item_id}",
        "title": f"Item {item_id}",
        "summary": "Salesforce release update",
        "source": "rss",
        "channel": channel,
        "relevance_score": score,
        "must_post": must_post,
        "source_priority": priority,
    }


class DeliveryPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_cwd = os.getcwd()
        os.chdir(self.temp.name)
        Path("data").mkdir()
        Path("data/seen_ids.json").write_text("[]", encoding="utf-8")
        content_filter._gemini_key = None
        content_filter._gemini_quota_hit = False

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def test_duplicate_url_uses_priority_not_input_order(self):
        low = item("same-low", channel="need-help", priority=10)
        high = item("same-high", channel="salesforce-rss", priority=90)
        high["url"] = low["url"]
        winner = content_filter.deduplicate_items([low, high])
        self.assertEqual([high], winner)
        self.assertEqual([high], content_filter.deduplicate_items([high, low]))

    def test_failed_delivery_remains_retryable_and_success_is_seen(self):
        candidate = item("retry")
        first = content_filter.run([candidate])
        self.assertEqual(1, len(first))
        content_filter.mark_delivered([{**candidate, "status": "failed"}])
        self.assertEqual(1, len(content_filter.run([candidate])))

        content_filter.mark_delivered([{**candidate, "status": "posted"}])
        self.assertEqual([], content_filter.run([candidate]))

    def test_mandatory_bypasses_filter_and_channel_cap(self):
        mandatory = [
            item(f"must-{number}", score=0.0, must_post=True)
            for number in range(3)
        ]
        curated = [item(f"curated-{number}", score=0.9 - number / 10) for number in range(4)]
        approved = content_filter.run(mandatory)
        self.assertEqual(3, len(approved))
        selected = poster.apply_channel_caps(mandatory + curated)
        self.assertEqual(5, len(selected))
        self.assertTrue(all(entry in selected for entry in mandatory))

    def test_dry_run_does_not_acknowledge_delivery(self):
        candidate = item("dry")
        with patch.dict(
            os.environ,
            {
                "DRY_RUN": "true",
                "TEAMS_WEBHOOK_SALESFORCE_RSS": "https://example.com/hook",
            },
            clear=False,
        ), patch.object(poster, "post_to_teams") as post:
            results = poster.run([candidate])
        post.assert_not_called()
        self.assertEqual("dry_run", results[0]["status"])
        content_filter.mark_delivered(results)
        self.assertNotIn("dry", content_filter.load_seen_ids())


if __name__ == "__main__":
    unittest.main()
