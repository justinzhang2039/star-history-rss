"""Tests for fuliba123.com latest sites RSS feed generator."""
import copy
from contextlib import redirect_stdout
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import fuliba_latest_feed as feed

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 12, 8, 0, 0, tzinfo=UTC)

SAMPLE_HTML = '''
<div class="url-card col-6">
    <div class="url-body default">
        <a href="https://picktests.com/zh/" target="_blank" rel="external nofollow noopener" 
           data-id="4368" data-url="https://picktests.com/zh" 
           class="card no-c is-views mb-4 site-4368" data-toggle="tooltip" 
           title="免费在线人类基准测试，包含反应测试、舒尔特方格、记忆力和注意力挑战，打开即可体验。">
            <div class="card-body url-content d-flex align-items-center">
                <div class="url-img rounded-circle mr-2 d-flex align-items-center justify-content-center">
                    <img alt="人类基准测试">
                </div>
                <div class="url-info flex-fill">
                    <div class="text-sm overflowClip_1">
                        <strong>人类基准测试</strong>
                    </div>
                    <p class="overflowClip_1 m-0 text-muted text-xs">免费在线人类基准测试简介</p>
                </div>
            </div>
        </a>
    </div>
</div>
<div class="url-card col-6">
    <div class="url-body default">
        <a href="https://usemagpie.ai/" target="_blank" rel="external nofollow noopener" 
           data-id="4380" data-url="https://usemagpie.ai" 
           class="card no-c is-views mb-4 site-4380" data-toggle="tooltip" 
           title="所有 Agent 的模型，一处搞定。">
            <div class="card-body url-content d-flex align-items-center">
                <div class="url-info flex-fill">
                    <div class="text-sm overflowClip_1">
                        <strong>magpie</strong>
                    </div>
                    <p class="overflowClip_1 m-0 text-muted text-xs">所有 Agent 的模型</p>
                </div>
            </div>
        </a>
    </div>
</div>
<div class="url-card col-6">
    <div class="url-body default">
        <a href="https://todayai.cn/login?utm_source=invitation&amp;utm_id=OY5fC3MSA_IU" 
           target="_blank" rel="external nofollow noopener" 
           data-id="4379" data-url="https://todayai.cn/login" 
           class="card no-c is-views mb-4 site-4379" data-toggle="tooltip" 
           title="国内版的Muse，创始人前豆包员工创业作品">
            <div class="card-body url-content d-flex align-items-center">
                <div class="url-info flex-fill">
                    <div class="text-sm overflowClip_1">
                        <strong>Today</strong>
                    </div>
                    <p class="overflowClip_1 m-0 text-muted text-xs">国内版的Muse</p>
                </div>
            </div>
        </a>
    </div>
</div>
'''


def sample_sites():
    """Return sample parsed sites matching SAMPLE_HTML."""
    return [
        {
            "id": "4368",
            "name": "人类基准测试",
            "description": "免费在线人类基准测试，包含反应测试、舒尔特方格、记忆力和注意力挑战，打开即可体验。",
            "external_url": "https://picktests.com/zh/",
            "page_url": "https://fuliba123.com/sites/4368.html",
        },
        {
            "id": "4380",
            "name": "magpie",
            "description": "所有 Agent 的模型，一处搞定。",
            "external_url": "https://usemagpie.ai/",
            "page_url": "https://fuliba123.com/sites/4380.html",
        },
        {
            "id": "4379",
            "name": "Today",
            "description": "国内版的Muse，创始人前豆包员工创业作品",
            "external_url": "https://todayai.cn/login?utm_source=invitation&utm_id=OY5fC3MSA_IU",
            "page_url": "https://fuliba123.com/sites/4379.html",
        },
    ]


class ParsingTests(unittest.TestCase):
    def test_parse_sites_extracts_correct_fields(self):
        sites = feed.parse_sites(SAMPLE_HTML)
        self.assertEqual(len(sites), 3)
        
        self.assertEqual(sites[0]["id"], "4368")
        self.assertEqual(sites[0]["name"], "人类基准测试")
        self.assertIn("人类基准测试", sites[0]["description"])
        self.assertEqual(sites[0]["external_url"], "https://picktests.com/zh/")
        self.assertEqual(sites[0]["page_url"], "https://fuliba123.com/sites/4368.html")
        
        self.assertEqual(sites[1]["id"], "4380")
        self.assertEqual(sites[1]["name"], "magpie")
        
        self.assertEqual(sites[2]["id"], "4379")
        self.assertEqual(sites[2]["name"], "Today")

    def test_parse_sites_handles_html_entities(self):
        html_with_entities = '''
        <a href="https://example.com/?a=1&amp;b=2" data-id="1234" 
           data-url="https://example.com" class="site-1234" 
           title="Test &amp; Demo &lt;here&gt;">
           <strong>Test &amp; Name</strong>
           <p class="text-muted">Desc &amp; more</p>
        </a>
        '''
        sites = feed.parse_sites(html_with_entities)
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["name"], "Test & Name")
        self.assertEqual(sites[0]["description"], "Test & Demo <here>")
        self.assertIn("&", sites[0]["external_url"])

    def test_parse_sites_empty_response_returns_empty_list(self):
        self.assertEqual(feed.parse_sites(""), [])
        self.assertEqual(feed.parse_sites("<html></html>"), [])

    def test_parse_sites_malformed_html_partial_match(self):
        partial = '''
        <a href="https://example.com" data-id="5555" data-url="https://example.com" 
           class="site-5555" title="Good entry">
           <strong>Good Site</strong>
           <p class="text-muted">Good desc</p>
        </a>
        <a href="missing" data-id="bad" title="Missing data-url">
           <strong>Bad Site</strong>
        </a>
        '''
        sites = feed.parse_sites(partial)
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["id"], "5555")


class ValidationTests(unittest.TestCase):
    def test_validate_sites_accepts_valid_sites(self):
        sites = sample_sites()
        result = feed.validate_sites(sites)
        self.assertEqual(result, sites)

    def test_validate_sites_rejects_empty_list(self):
        with self.assertRaises(ValueError) as ctx:
            feed.validate_sites([])
        self.assertIn("No sites", str(ctx.exception))

    def test_validate_sites_rejects_duplicate_ids(self):
        sites = sample_sites()
        sites.append(sites[0].copy())
        with self.assertRaises(ValueError) as ctx:
            feed.validate_sites(sites)
        self.assertIn("Duplicate site ID", str(ctx.exception))

    def test_validate_sites_rejects_missing_id(self):
        sites = [{"id": "", "name": "Test", "page_url": "https://x.com/sites/1.html"}]
        with self.assertRaises(ValueError):
            feed.validate_sites(sites)

    def test_validate_sites_rejects_invalid_page_url(self):
        sites = [{"id": "1", "name": "Test", "page_url": "http://insecure.com"}]
        with self.assertRaises(ValueError):
            feed.validate_sites(sites)


class StateTests(unittest.TestCase):
    def test_first_run_seeds_with_rss_items(self):
        """First run creates RSS items for all current sites so subscription is useful."""
        st = {"seen_ids": [], "items": []}
        sites = sample_sites()
        updated, added = feed.update_state(st, sites, NOW)
        
        self.assertEqual(added, 3)
        self.assertEqual(len(updated["seen_ids"]), 3)
        self.assertEqual(len(updated["items"]), 3)
        self.assertEqual(updated["seeded_count"], 3)
        self.assertIn("4368", updated["seen_ids"])
        self.assertIn("4380", updated["seen_ids"])
        self.assertIn("4379", updated["seen_ids"])
        
        # Verify items have stable GUIDs and discovery timestamps
        for item in updated["items"]:
            self.assertTrue(item["guid"].startswith("fuliba123-site-"))
            self.assertIn("discovered_at", item)
            self.assertIn(NOW.isoformat()[:10], item["discovered_at"])

    def test_subsequent_run_adds_only_new_sites(self):
        st = {"seen_ids": ["4368", "4379"], "items": []}
        sites = sample_sites()
        updated, added = feed.update_state(st, sites, NOW)
        
        self.assertEqual(added, 1)
        self.assertEqual(len(updated["items"]), 1)
        self.assertEqual(updated["items"][0]["title"], "🆕 magpie")
        self.assertIn("4380", updated["seen_ids"])
        self.assertNotIn("seeded_count", updated)

    def test_no_duplicates_on_reorder(self):
        """Reordering existing sites should not create new items."""
        st = {"seen_ids": ["4368", "4379", "4380"], "items": []}
        sites = list(reversed(sample_sites()))
        updated, added = feed.update_state(st, sites, NOW)
        
        self.assertEqual(added, 0)
        self.assertEqual(len(updated["items"]), 0)

    def test_no_duplicates_on_edit(self):
        """Editing site details should not create new items."""
        st = {"seen_ids": ["4368", "4379", "4380"], "items": []}
        sites = sample_sites()
        sites[0]["description"] = "Updated description"
        sites[0]["name"] = "Updated Name"
        updated, added = feed.update_state(st, sites, NOW)
        
        self.assertEqual(added, 0)
        self.assertEqual(len(updated["items"]), 0)

    def test_state_not_mutated(self):
        """update_state should not mutate input state."""
        st = {"seen_ids": ["4368"], "items": []}
        original = copy.deepcopy(st)
        sites = sample_sites()
        feed.update_state(st, sites, NOW)
        
        self.assertEqual(st, original)

    def test_invalid_state_raises_error(self):
        """Invalid saved state should fail rather than reset."""
        for invalid in [
            {"seen_ids": "not-a-list", "items": []},
            {"seen_ids": [], "items": "not-a-list"},
        ]:
            with self.subTest(state=invalid):
                with self.assertRaises(ValueError):
                    feed.update_state(invalid, sample_sites(), NOW)

    def test_items_limited_to_max(self):
        """Items list should be capped at MAX_ITEMS."""
        st = {"seen_ids": ["old"], "items": [{"title": f"item-{i}", "link": "#", 
              "guid": f"g-{i}", "pubDate": "x", "desc": "x"} for i in range(250)]}
        sites = [{"id": "new", "name": "New", "description": "d", 
                  "external_url": "https://x", "page_url": "https://fuliba123.com/sites/new.html"}]
        updated, added = feed.update_state(st, sites, NOW)
        
        self.assertEqual(added, 1)
        self.assertLessEqual(len(updated["items"]), feed.MAX_ITEMS)

    def test_guid_is_stable(self):
        """Same site ID should always produce same GUID."""
        st = {"seen_ids": ["4368"], "items": []}
        sites = sample_sites()
        updated1, _ = feed.update_state(st, sites, NOW)
        
        st2 = {"seen_ids": ["4368"], "items": []}
        updated2, _ = feed.update_state(st2, sites, NOW + dt.timedelta(hours=1))
        
        guids1 = {i["guid"] for i in updated1["items"]}
        guids2 = {i["guid"] for i in updated2["items"]}
        self.assertEqual(guids1, guids2)


class RenderFeedTests(unittest.TestCase):
    def test_renders_valid_xml(self):
        st = {
            "seen_ids": ["4368"],
            "items": [{
                "title": "🆕 Test Site",
                "link": "https://fuliba123.com/sites/4368.html",
                "guid": "fuliba123-site-4368",
                "pubDate": "Thu, 12 Nov 2026 08:00:00 +0000",
                "desc": "<strong>Test</strong>",
            }]
        }
        xml = feed.render_feed(st)
        
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "rss")
        self.assertEqual(root.get("version"), "2.0")
        
        channel = root.find("channel")
        self.assertIsNotNone(channel)
        self.assertIn("福利吧导航", channel.findtext("title"))
        
        items = channel.findall("item")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].findtext("title"), "🆕 Test Site")

    def test_xml_escapes_special_characters(self):
        st = {
            "seen_ids": [],
            "items": [{
                "title": "Test <>&\"' Site",
                "link": "https://example.com/?a=1&b=2",
                "guid": "test-guid",
                "pubDate": "x",
                "desc": "Desc <script>alert(1)</script>",
            }]
        }
        xml = feed.render_feed(st)
        root = ET.fromstring(xml)
        
        item = root.find("channel/item")
        self.assertIn("<", item.findtext("title"))
        self.assertIn("&", item.findtext("link"))

    def test_absolute_links_in_feed(self):
        st = {
            "seen_ids": ["4368"],
            "items": [{
                "title": "Test",
                "link": "https://fuliba123.com/sites/4368.html",
                "guid": "test",
                "pubDate": "x",
                "desc": "test",
            }]
        }
        xml = feed.render_feed(st)
        root = ET.fromstring(xml)
        
        link = root.find("channel/item/link").text
        self.assertTrue(link.startswith("https://"))

    def test_empty_items_renders_valid_feed(self):
        st = {"seen_ids": [], "items": []}
        xml = feed.render_feed(st)
        root = ET.fromstring(xml)
        
        items = root.findall("channel/item")
        self.assertEqual(len(items), 0)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.state_path = self.directory / "state.json"
        self.out_path = self.directory / "feed.xml"
        self.health_path = self.directory / "health.json"

    def run_feed(self, now=NOW):
        with redirect_stdout(io.StringIO()):
            return feed.run(self.state_path, self.out_path, self.health_path, now=now)

    def test_first_run_seeds_state_with_items(self):
        """First run populates RSS with current sites so subscription is immediately useful."""
        with patch.object(feed, "fetch_latest_sites", return_value=SAMPLE_HTML):
            result = self.run_feed()
        
        self.assertEqual(result, 0)
        state = json.loads(self.state_path.read_text())
        self.assertEqual(len(state["seen_ids"]), 3)
        self.assertEqual(len(state["items"]), 3)
        self.assertEqual(state["seeded_count"], 3)
        
        # Verify RSS has items with stable GUIDs
        for item in state["items"]:
            self.assertTrue(item["guid"].startswith("fuliba123-site-"))
        
        health = json.loads(self.health_path.read_text())
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["new_items"], 3)
        self.assertEqual(health["seeded"], 3)

    def test_subsequent_run_adds_new_items(self):
        initial_state = {"seen_ids": ["4368", "4379"], "items": []}
        self.state_path.write_text(json.dumps(initial_state))
        
        with patch.object(feed, "fetch_latest_sites", return_value=SAMPLE_HTML):
            result = self.run_feed()
        
        self.assertEqual(result, 0)
        state = json.loads(self.state_path.read_text())
        self.assertEqual(len(state["items"]), 1)
        self.assertEqual(state["items"][0]["title"], "🆕 magpie")
        
        health = json.loads(self.health_path.read_text())
        self.assertEqual(health["new_items"], 1)

    def test_network_error_preserves_state(self):
        initial_state = {"seen_ids": ["4368"], "items": [{"title": "old", "link": "#",
                         "guid": "g", "pubDate": "x", "desc": "x"}]}
        self.state_path.write_text(json.dumps(initial_state))
        initial_bytes = self.state_path.read_bytes()
        
        with patch.object(feed, "fetch_latest_sites", side_effect=OSError("network")):
            result = self.run_feed()
        
        self.assertEqual(result, 1)
        self.assertEqual(self.state_path.read_bytes(), initial_bytes)
        
        health = json.loads(self.health_path.read_text())
        self.assertEqual(health["status"], "error")
        self.assertIn("network", health["error"])

    def test_empty_response_preserves_state(self):
        initial_state = {"seen_ids": ["4368"], "items": []}
        self.state_path.write_text(json.dumps(initial_state))
        initial_bytes = self.state_path.read_bytes()
        
        with patch.object(feed, "fetch_latest_sites", return_value="<html></html>"):
            result = self.run_feed()
        
        self.assertEqual(result, 1)
        self.assertEqual(self.state_path.read_bytes(), initial_bytes)
        
        health = json.loads(self.health_path.read_text())
        self.assertEqual(health["status"], "error")

    def test_malformed_state_fails_gracefully(self):
        self.state_path.write_text("{invalid json")
        
        with patch.object(feed, "fetch_latest_sites", return_value=SAMPLE_HTML):
            result = self.run_feed()
        
        self.assertEqual(result, 1)
        health = json.loads(self.health_path.read_text())
        self.assertEqual(health["status"], "error")

    def test_idempotent_runs(self):
        """Repeated runs with same data produce identical state/feed."""
        with patch.object(feed, "fetch_latest_sites", return_value=SAMPLE_HTML):
            self.run_feed()
            state1 = self.state_path.read_bytes()
            feed1 = self.out_path.read_bytes()
            
            # Second run should find no new sites
            self.run_feed()
            state2 = self.state_path.read_bytes()
            feed2 = self.out_path.read_bytes()
        
        # State may differ in last_fetch timestamp, but items should be same
        s1 = json.loads(state1)
        s2 = json.loads(state2)
        self.assertEqual(s1["items"], s2["items"])
        self.assertEqual(s1["seen_ids"], s2["seen_ids"])
        self.assertEqual(feed1, feed2)

    def test_health_preserves_last_successful_fetch(self):
        with patch.object(feed, "fetch_latest_sites", return_value=SAMPLE_HTML):
            self.run_feed()
        
        health1 = json.loads(self.health_path.read_text())
        last_success = health1["last_successful_fetch_at"]
        
        with patch.object(feed, "fetch_latest_sites", side_effect=OSError("fail")):
            self.run_feed(now=NOW + dt.timedelta(hours=1))
        
        health2 = json.loads(self.health_path.read_text())
        self.assertEqual(health2["status"], "error")
        self.assertEqual(health2["last_successful_fetch_at"], last_success)


class LiveSmokeTest(unittest.TestCase):
    """Optional live test against actual API - skipped by default."""
    
    @unittest.skip("Live test - run manually with: python -m unittest test_fuliba_latest_feed.LiveSmokeTest")
    def test_live_fetch_and_parse(self):
        html_content = feed.fetch_latest_sites(count=12)
        sites = feed.parse_sites(html_content)
        
        self.assertGreater(len(sites), 0)
        for site in sites:
            self.assertTrue(site["id"].isdigit())
            self.assertTrue(len(site["name"]) > 0)
            self.assertTrue(site["page_url"].startswith("https://fuliba123.com/sites/"))


if __name__ == "__main__":
    unittest.main()
