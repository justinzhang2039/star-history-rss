"""Regression coverage for source freshness and preservation of RSS history."""
import copy
from contextlib import redirect_stdout
import datetime as dt
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import star_weekly_feed as feed


UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 21, 12, tzinfo=UTC)
FROM, TO = "Oct 12, 2026", "Oct 18, 2026"
ASSET = "https://www.star-history.com/assets/index-regression.js"

# Frozen copies of the real pre-fix 2026-10-19 state and RSS. Reading the live
# repository files would make dated regression cases fail after a source update.
LEGACY_STATE = {'window': 'Oct 12, 2026 – Oct 18, 2026',
 'top20': ['morluto/rea',
           'storytold/photocraft',
           'debpalash/VoiceStudio',
           'storytold/artcraft',
           'boykopovar/AnyPS5',
           'mattpocock/skills',
           'MadsLorentzen/ai-job-search',
           'storytold/wordcraft',
           'NationalSecurityAgency/ghidra',
           'stablyai/orca',
           'cathrynlavery/diagram-design',
           'affaan-m/ECC',
           'DietrichGebert/ponytail',
           'deepseek-ai/deepseek-harness',
           'ifixai-ai/iFixAi',
           'storytold/pdfcraft',
           'bilawalsidhu/gods-eye-view',
           'heygen-com/hyperframes',
           'vxcontrol/pentagi',
           'xtool-org/xtool'],
 'top5': ['morluto/rea',
          'storytold/photocraft',
          'debpalash/VoiceStudio',
          'storytold/artcraft',
          'boykopovar/AnyPS5'],
 'items': [{'title': '🆕 新进榜单 Top20 #7 MadsLorentzen/ai-job-search（+8,192 ★）',
            'link': 'https://github.com/MadsLorentzen/ai-job-search',
            'guid': 'Oct 12, 2026 – Oct 18, 2026|new|MadsLorentzen/ai-job-search',
            'pubDate': 'Mon, 19 Oct 2026 19:23:34 +0000',
            'desc': '统计窗口：Oct 12, 2026 – Oct 18, '
                    '2026（每日滚动）<br>当前排名：#7<br>近7天新增星：+8,192<br>总星数：56,091<br><a '
                    "href='https://www.star-history.com/#MadsLorentzen/ai-job-search&amp;Date'>Star "
                    'History 曲线</a> · <a '
                    "href='https://github.com/MadsLorentzen/ai-job-search'>GitHub</a>"}]}
LEGACY_RSS = "<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>Star History 周榜（滚动）：新上榜 &amp; 新进前5</title><link>https://www.star-history.com</link><description>只在滚动周榜前20出现新项目或有新项目进入前5时更新</description><item><title>🆕 新进榜单 Top20 #7 MadsLorentzen/ai-job-search（+8,192 ★）</title><link>https://github.com/MadsLorentzen/ai-job-search</link><guid isPermaLink='false'>Oct 12, 2026 – Oct 18, 2026|new|MadsLorentzen/ai-job-search</guid><pubDate>Mon, 19 Oct 2026 19:23:34 +0000</pubDate><description>统计窗口：Oct 12, 2026 – Oct 18, 2026（每日滚动）&lt;br&gt;当前排名：#7&lt;br&gt;近7天新增星：+8,192&lt;br&gt;总星数：56,091&lt;br&gt;&lt;a href=&#x27;https://www.star-history.com/#MadsLorentzen/ai-job-search&amp;amp;Date&#x27;&gt;Star History 曲线&lt;/a&gt; · &lt;a href=&#x27;https://github.com/MadsLorentzen/ai-job-search&#x27;&gt;GitHub&lt;/a&gt;</description></item></channel></rss>"


def legacy_state():
    return copy.deepcopy(LEGACY_STATE)


def sample_repos():
    return [
        {"name": name, "new_stars": 20000 - rank * 100,
         "stars_total": 100000 + rank, "rank_change": -1 if rank else None}
        for rank, name in enumerate(legacy_state()["top20"])
    ]


def bundle(repos=None, frm=FROM, to=TO, prefix="a"):
    rows = json.dumps(sample_repos() if repos is None else repos,
                      ensure_ascii=False, separators=(",", ":"))
    rows = re.sub(r'"(name|new_stars|stars_total|rank_change)":', r"\1:", rows)
    return (f'const {prefix}f="{frm}",{prefix}t="{to}",{prefix}r={rows},'
            f'{prefix}w={{from:{prefix}f,to:{prefix}t,repos:{prefix}r}};')


class ParsingTests(unittest.TestCase):
    def test_current_bundle_format_and_null_rank_change(self):
        frm, to, repos = feed.parse_weekly(bundle())
        self.assertEqual((frm, to), (FROM, TO))
        self.assertEqual(repos, sample_repos())
        self.assertIsNone(repos[0]["rank_change"])

    def test_unrelated_date_array_is_not_mistaken_for_weekly(self):
        unrelated = bundle(prefix="x").split(",xw=", 1)[0] + ";"
        self.assertEqual(feed.parse_weekly(unrelated + bundle())[2], sample_repos())
        with self.assertRaises(ValueError):
            feed.parse_weekly(unrelated)

    def test_missing_or_ambiguous_weekly_block_is_visible_failure(self):
        for source in ("const unrelated = [];", bundle() + bundle(prefix="b")):
            with self.subTest(source=source[:50]), self.assertRaises(ValueError):
                feed.parse_weekly(source)


class ValidationTests(unittest.TestCase):
    def test_seven_day_window_and_negative_rank_change_are_valid(self):
        self.assertEqual(
            feed.validate_weekly(FROM, TO, sample_repos(), NOW.date()),
            (dt.date(2026, 10, 12), dt.date(2026, 10, 18)),
        )

    def test_invalid_dates_and_window_lengths(self):
        for frm, to in (("Oct 12, 2026", "Oct 19, 2026"),
                        ("Oct 18, 2026", "Oct 12, 2026"),
                        ("Oct 20, 2026", "Oct 26, 2026"),
                        ("Oct 33, 2026", TO)):
            with self.subTest(frm=frm, to=to), self.assertRaises(ValueError):
                feed.validate_weekly(frm, to, sample_repos(), NOW.date())

    def test_empty_partial_duplicate_and_invalid_rankings(self):
        invalid = [[], sample_repos()[:-1], sample_repos() + [sample_repos()[0]]]
        duplicate = sample_repos()
        duplicate[-1]["name"] = duplicate[0]["name"]
        invalid.append(duplicate)
        for key, value in (("new_stars", -1), ("new_stars", True),
                           ("new_stars", "123"), ("stars_total", -1),
                           ("stars_total", 12.5), ("rank_change", "new"),
                           ("rank_change", False)):
            rows = sample_repos()
            rows[0][key] = value
            invalid.append(rows)
        for rows in invalid:
            with self.subTest(rows=rows[:1]), self.assertRaises(ValueError):
                feed.validate_weekly(FROM, TO, rows, NOW.date())


class StateTests(unittest.TestCase):
    def test_legacy_migration_preserves_history_and_does_not_mutate_input(self):
        original = legacy_state()
        before = copy.deepcopy(original)
        updated, count = feed.update_state(original, FROM, TO, sample_repos(), NOW)
        self.assertEqual(count, 0)
        self.assertEqual(original, before)
        self.assertEqual(updated["items"], before["items"])
        self.assertEqual(updated["top20"], before["top20"])
        self.assertTrue(updated["source_hash"])
        self.assertEqual(len(updated["source_hash"]), 64)

    def test_same_window_revision_detects_new_top20_and_top5(self):
        before = legacy_state()
        rows = sample_repos()
        rows[0]["name"] = "example/new-entry"
        updated, count = feed.update_state(before, FROM, TO, rows, NOW)
        self.assertEqual(count, 2)
        new_guids = {item["guid"] for item in updated["items"]} - {
            item["guid"] for item in before["items"]}
        self.assertEqual(new_guids, {
            f"{before['window']}|new|example/new-entry",
            f"{before['window']}|top5|example/new-entry",
        })
        self.assertEqual(updated["items"][-len(before["items"]):], before["items"])
        repeated, repeated_count = feed.update_state(updated, FROM, TO, rows, NOW)
        self.assertEqual(repeated_count, 0)
        self.assertEqual(repeated, updated)

    def test_same_window_statistics_revision_changes_hash_without_new_items(self):
        baseline, _ = feed.update_state(legacy_state(), FROM, TO, sample_repos(), NOW)
        rows = sample_repos()
        rows[0]["new_stars"] += 1
        updated, count = feed.update_state(baseline, FROM, TO, rows, NOW)
        self.assertEqual(count, 0)
        self.assertNotEqual(updated["source_hash"], baseline["source_hash"])
        self.assertEqual(updated["items"], baseline["items"])

    def test_existing_top20_repo_entering_top5_only_emits_top5(self):
        rows = sample_repos()
        rows.insert(0, rows.pop(6))
        updated, count = feed.update_state(legacy_state(), FROM, TO, rows, NOW)
        self.assertEqual(count, 1)
        self.assertIn("|top5|", updated["items"][0]["guid"])
        self.assertEqual(updated["top5"][0], rows[0]["name"])

    def test_same_window_reentry_remains_deduplicated_after_item_pruning(self):
        rows = sample_repos()
        rows[-1]["name"] = "example/reentry"
        entered, count = feed.update_state(legacy_state(), FROM, TO, rows, NOW)
        self.assertEqual(count, 1)
        emitted_guid = f"{entered['window']}|new|example/reentry"
        self.assertIn(emitted_guid, entered["window_guids"])
        # Simulate RSS retention removing the old item; the window ledger must
        # still remember its GUID after the repository leaves and returns.
        entered["items"] = [i for i in entered["items"] if i["guid"] != emitted_guid]
        exited, _ = feed.update_state(entered, FROM, TO, sample_repos(), NOW)
        returned, count = feed.update_state(exited, FROM, TO, rows, NOW)
        self.assertEqual(count, 0)
        self.assertNotIn(emitted_guid, {i["guid"] for i in returned["items"]})
        self.assertIn(emitted_guid, returned["window_guids"])

    def test_historic_item_guid_is_deduplicated_during_legacy_migration(self):
        before = legacy_state()
        existing = before["items"][0]
        existing_name = existing["guid"].split("|")[-1]
        rows = sample_repos()
        before["top20"] = ["example/absent" if n == existing_name else n
                           for n in before["top20"]]
        updated, count = feed.update_state(before, FROM, TO, rows, NOW)
        self.assertEqual(count, 0)
        self.assertEqual(updated["items"], before["items"])

    def test_new_window_can_emit_same_repo_with_a_new_guid(self):
        before = legacy_state()
        existing_name = before["items"][0]["guid"].split("|")[-1]
        before["top20"] = ["example/absent" if n == existing_name else n
                           for n in before["top20"]]
        updated, count = feed.update_state(
            before, "Oct 19, 2026", "Oct 25, 2026", sample_repos(),
            dt.datetime(2026, 10, 26, 12, tzinfo=UTC))
        self.assertEqual(count, 1)
        self.assertEqual(len({i["guid"] for i in updated["items"]}), len(updated["items"]))
        self.assertEqual(updated["items"][-len(before["items"]):], before["items"])

    def test_older_window_is_rejected_without_mutating_state(self):
        before = legacy_state()
        original = copy.deepcopy(before)
        with self.assertRaises(ValueError):
            feed.update_state(before, "Oct 5, 2026", "Oct 11, 2026", sample_repos(), NOW)
        self.assertEqual(before, original)

    def test_rendered_rss_preserves_legacy_item_identity_and_description(self):
        state = legacy_state()
        channel = ET.fromstring(feed.render_feed(state)).find("channel")
        items = channel.findall("item")
        self.assertEqual(len(items), len(state["items"]))
        for xml_item, historic in zip(items, state["items"]):
            for field in ("title", "link", "guid", "pubDate"):
                self.assertEqual(xml_item.findtext(field), historic[field])
            self.assertEqual(xml_item.findtext("description"), historic["desc"])


class FreshnessTests(unittest.TestCase):
    def test_grace_period_is_measured_from_end_of_source_day(self):
        end = dt.date(2026, 10, 18)
        for now, hours, status in (
            (dt.datetime(2026, 10, 19, tzinfo=UTC), 0, "fresh"),
            (dt.datetime(2026, 10, 21, tzinfo=UTC), 48, "fresh"),
            (dt.datetime(2026, 10, 21, 0, 0, 1, tzinfo=UTC), 48 + 1 / 3600, "stale"),
        ):
            with self.subTest(now=now):
                result = feed.freshness(end, now)
                self.assertEqual(result["status"], status)
                self.assertAlmostEqual(result["source_age_hours"], hours, places=3)
                self.assertEqual(result["max_source_age_hours"], 48)

    def test_timezone_and_custom_threshold(self):
        shanghai = dt.timezone(dt.timedelta(hours=8))
        result = feed.freshness(dt.date(2026, 10, 18),
                                dt.datetime(2026, 10, 20, 8, tzinfo=shanghai), 24)
        self.assertEqual(result["source_age_hours"], 24)
        self.assertEqual(result["status"], "fresh")
        self.assertEqual(result["max_source_age_hours"], 24)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.state_path = self.directory / "state.json"
        self.out_path = self.directory / "feed.xml"
        self.health_path = self.directory / "health.json"
        self.state_path.write_text(json.dumps(LEGACY_STATE, ensure_ascii=False, indent=1), encoding="utf-8")
        self.out_path.write_text(LEGACY_RSS, encoding="utf-8")

    def run_feed(self, now=NOW, **kwargs):
        # Negative cases deliberately exercise GitHub annotation output; keep
        # successful test runs from appearing to have workflow errors.
        with redirect_stdout(io.StringIO()):
            return feed.run(self.state_path, self.out_path, self.health_path, now=now, **kwargs)

    def test_regressed_window_records_first_observation_and_preserves_it_on_retry(self):
        with patch.object(feed, "fetch_weekly", return_value=(FROM, TO, sample_repos(), ASSET)):
            self.assertEqual(self.run_feed(), 0)
        accepted_health = json.loads(self.health_path.read_text())
        state_before = self.state_path.read_bytes()
        feed_before = self.out_path.read_bytes()
        first_seen = NOW + dt.timedelta(hours=1)
        source = ("Oct 5, 2026", "Oct 11, 2026", sample_repos(), ASSET)
        with patch.object(feed, "fetch_weekly", return_value=source):
            for checked_at in (first_seen, first_seen + dt.timedelta(hours=1)):
                with self.subTest(checked_at=checked_at):
                    self.assertEqual(self.run_feed(now=checked_at), 1)
                    health = json.loads(self.health_path.read_text())
                    self.assertEqual(health["checked_at"], checked_at.isoformat())
                    self.assertEqual(health["source_window"], "Oct 5, 2026 – Oct 11, 2026")
                    self.assertEqual(health["window_first_observed_at"], first_seen.isoformat())
                    self.assertEqual(health["accepted_window"], accepted_health["accepted_window"])
                    self.assertEqual(health["last_successful_fetch_at"],
                                     accepted_health["last_successful_fetch_at"])
                    self.assertEqual(health["status"], "error")
                    self.assertIn("source window regressed", health["error"])
                    self.assertEqual(self.state_path.read_bytes(), state_before)
                    self.assertEqual(self.out_path.read_bytes(), feed_before)

    def test_invalid_window_does_not_replace_previous_observation(self):
        with patch.object(feed, "fetch_weekly", return_value=(FROM, TO, sample_repos(), ASSET)):
            self.assertEqual(self.run_feed(), 0)
        previous_health = json.loads(self.health_path.read_text())
        state_before = self.state_path.read_bytes()
        feed_before = self.out_path.read_bytes()
        source = ("Oct 5, 2026", "Oct 12, 2026", sample_repos(), ASSET)
        with patch.object(feed, "fetch_weekly", return_value=source):
            self.assertEqual(self.run_feed(now=NOW + dt.timedelta(hours=1)), 1)
        health = json.loads(self.health_path.read_text())
        self.assertEqual(health["source_window"], previous_health["source_window"])
        self.assertEqual(health["window_first_observed_at"], previous_health["window_first_observed_at"])
        self.assertEqual(health["status"], "error")
        self.assertIn("exactly seven days", health["error"])
        self.assertEqual(self.state_path.read_bytes(), state_before)
        self.assertEqual(self.out_path.read_bytes(), feed_before)

    def test_repeated_success_does_not_republish_or_duplicate_items(self):
        source = ("Oct 14, 2026", "Oct 20, 2026", sample_repos(), ASSET)
        with patch.object(feed, "fetch_weekly", return_value=source):
            self.assertEqual(self.run_feed(), 0)
            first_state = self.state_path.read_bytes()
            first_feed = self.out_path.read_bytes()
            self.assertEqual(self.run_feed(), 0)
        self.assertEqual(self.state_path.read_bytes(), first_state)
        self.assertEqual(self.out_path.read_bytes(), first_feed)
        state = json.loads(first_state)
        self.assertEqual(state["items"], legacy_state()["items"])
        self.assertEqual(json.loads(self.health_path.read_text())["status"], "fresh")

    def test_stale_source_is_explicit_and_keeps_successful_data(self):
        with patch.object(feed, "fetch_weekly", return_value=(FROM, TO, sample_repos(), ASSET)):
            self.assertEqual(self.run_feed(), 0)
        health = json.loads(self.health_path.read_text())
        self.assertEqual(health["status"], "stale")
        self.assertEqual(health["source_age_hours"], 60)
        self.assertEqual(json.loads(self.state_path.read_text())["items"], legacy_state()["items"])

    def test_malformed_diagnostic_history_recovers_without_resetting_feed_history(self):
        source = ("Oct 14, 2026", "Oct 20, 2026", sample_repos(), ASSET)
        for malformed in ("{unfinished", "[]", "null"):
            with self.subTest(health=malformed), patch.object(feed, "fetch_weekly", return_value=source):
                self.health_path.write_text(malformed, encoding="utf-8")
                self.assertEqual(self.run_feed(), 0)
                self.assertEqual(json.loads(self.health_path.read_text())["status"], "fresh")
                self.assertEqual(json.loads(self.state_path.read_text())["items"], LEGACY_STATE["items"])

    def test_corrupt_saved_state_fails_without_resetting_feed_or_state(self):
        corrupt = b'{"items": ['
        self.state_path.write_bytes(corrupt)
        feed_before = self.out_path.read_bytes()
        with patch.object(feed, "fetch_weekly") as fetch:
            self.assertEqual(self.run_feed(), 1)
            fetch.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), corrupt)
        self.assertEqual(self.out_path.read_bytes(), feed_before)
        self.assertEqual(json.loads(self.health_path.read_text())["status"], "error")

    def test_failures_preserve_both_data_files_and_write_health(self):
        cases = (
            {"side_effect": OSError("network unavailable")},
            {"side_effect": ValueError("weekly block not found")},
            {"return_value": ("Oct 5, 2026", "Oct 11, 2026", sample_repos(), ASSET)},
            {"return_value": (FROM, TO, [], ASSET)},
        )
        state_before = self.state_path.read_bytes()
        feed_before = self.out_path.read_bytes()
        for fetch_result in cases:
            with self.subTest(fetch_result=fetch_result), patch.object(feed, "fetch_weekly", **fetch_result):
                self.assertEqual(self.run_feed(), 1)
                self.assertEqual(self.state_path.read_bytes(), state_before)
                self.assertEqual(self.out_path.read_bytes(), feed_before)
                self.assertEqual(json.loads(self.health_path.read_text())["status"], "error")


if __name__ == "__main__":
    unittest.main()
