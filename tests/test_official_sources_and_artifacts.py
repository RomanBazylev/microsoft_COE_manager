import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import artifacts
import events_fetcher
import official_fetcher


RELEASE_HTML = """
<html>
  <head><title>Salesforce Summer ’26 Release | Salesforce</title></head>
  <body>
    <a href="https://help.salesforce.com/s/articleView?id=release-notes.rn&amp;release=258&amp;type=5&amp;language=en_US">
      Summer ’26 Release Notes
    </a>
    <a href="https://help.salesforce.com/s/articleView?id=release-notes.rn&amp;release=258&amp;type=5">
      Summer ’26 Release Notes
    </a>
    <a href="https://trailhead.salesforce.com/trailblazer-community/groups/0F9300000001okuCAA?_ga=tracking">
      Trailhead Summer ’26 Release Highlights
    </a>
    <a href="https://trailhead.salesforce.com/trailblazer-community/groups/0F9300000001oku">
      Trailhead Summer ’26 Release Highlights
    </a>
    <a href="https://example.com/release-notes">Unofficial release notes</a>
  </body>
</html>
"""


class OfficialSourceTests(unittest.TestCase):
    def test_release_parser_is_official_deduplicated_and_mandatory(self):
        items = official_fetcher.parse_release_resources(RELEASE_HTML)
        self.assertEqual(3, len(items))
        self.assertTrue(all(entry["must_post"] for entry in items))
        self.assertTrue(all(entry["official"] for entry in items))
        self.assertEqual(len(items), len({entry["url"] for entry in items}))
        trailhead = next(entry for entry in items if "trailhead.salesforce.com" in entry["url"])
        self.assertEqual("certification", trailhead["channel"])

    def test_changed_release_label_gets_new_delivery_id(self):
        old = official_fetcher.parse_release_resources(RELEASE_HTML)
        changed = official_fetcher.parse_release_resources(
            RELEASE_HTML.replace("Summer ’26 Release Notes", "Summer ’26 Release Notes Updated")
        )
        old_note = next(entry for entry in old if "articleView" in entry["url"])
        changed_note = next(entry for entry in changed if "articleView" in entry["url"])
        self.assertEqual(old_note["url"], changed_note["url"])
        self.assertNotEqual(old_note["id"], changed_note["id"])

    def test_dashboard_artifacts_are_valid_json(self):
        health = [{"status": "ok", "url": "https://admin.salesforce.com/feed"}]
        summary = artifacts.build_run_summary(
            trigger="test",
            dry_run=True,
            fetched=3,
            approved=2,
            results=[{"status": "dry_run"}],
            feed_health=health,
        )
        with tempfile.TemporaryDirectory() as directory:
            last_run, feed_health = artifacts.write_run_artifacts(summary, health, directory)
            self.assertEqual(summary, json.loads(last_run.read_text(encoding="utf-8")))
            self.assertEqual(health, json.loads(feed_health.read_text(encoding="utf-8")))
        self.assertEqual(1, summary["feed_health"]["ok"])
        self.assertEqual(1, summary["results"]["dry_run"])

    def test_official_events_collapse_navigation_pages(self):
        page = b"""
        <a href="/dreamforce/">Register now</a>
        <a href="/dreamforce/faq/">Dreamforce FAQ</a>
        <a href="/connections/why-attend/">Why attend Connections</a>
        <a href="/events/">Find an Agentforce World Tour near you</a>
        """

        class Response:
            status_code = 200
            url = "https://www.salesforce.com/events/"
            content = page

            def raise_for_status(self):
                return None

        class Session:
            @staticmethod
            def get(*args, **kwargs):
                return Response()

        items, health = events_fetcher.fetch_salesforce_events(Session)
        self.assertEqual("ok", health["status"])
        self.assertEqual(3, len(items))
        self.assertEqual(1, sum(entry["title"] == "Dreamforce" for entry in items))


if __name__ == "__main__":
    unittest.main()
