#!/usr/bin/env python3
"""Observe Star History's published seven-day ranking without repeating events."""
import argparse
import copy
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request
from email.utils import format_datetime

BASE = "https://www.star-history.com"
TOPN = 5
MAXITEMS = 100
UTC = dt.timezone.utc
DATE = r"[A-Z][a-z]{2} \d{1,2}, \d{4}"
IDENT = r"[A-Za-z_$][\w$]*"


def get(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 star-weekly-feed",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def parse_weekly(bundle):
    # Require the from/to/repos binding used by the deployed Weekly component.
    # Ambiguous or changed layouts must fail instead of choosing an arbitrary list.
    pattern = (
        rf'(?P<from_var>{IDENT})="(?P<frm>{DATE})",'
        rf'(?P<to_var>{IDENT})="(?P<to>{DATE})",'
        rf'(?P<repos_var>{IDENT})=(?P<rows>\[\{{name:".*?\}}\]),'
        rf'{IDENT}=\{{from:(?P=from_var),to:(?P=to_var),repos:(?P=repos_var)\}}'
    )
    matches = list(re.finditer(pattern, bundle, re.S))
    if len(matches) != 1:
        raise ValueError(f"expected one Weekly block, found {len(matches)} (site layout changed?)")
    match = matches[0]
    rows = re.sub(r'([{,])(\w+):', r'\1"\2":', match["rows"])
    rows = rows.replace("void 0", "null")
    return match["frm"], match["to"], json.loads(rows)


def fetch_weekly():
    home = get(BASE + "/")
    assets = re.findall(r'src=[\"\'](/assets/index-[^\"\']+\.js)[\"\']', home)
    if len(assets) != 1:
        raise ValueError("expected one homepage index asset (site layout changed?)")
    asset_url = BASE + assets[0]
    return (*parse_weekly(get(asset_url)), asset_url)


def parse_date(value):
    return dt.datetime.strptime(value, "%b %d, %Y").date()


def validate_weekly(frm, to, repos, today):
    start, end = parse_date(frm), parse_date(to)
    if end - start != dt.timedelta(days=6):
        raise ValueError("Weekly window must contain exactly seven days")
    if end > today:
        raise ValueError("Weekly window ends in the future")
    if not isinstance(repos, list) or len(repos) != 20:
        raise ValueError("expected a complete Weekly Top20")
    names = set()
    for row in repos:
        if not isinstance(row, dict):
            raise ValueError("invalid Weekly row")
        name = row.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[\w.-]+/[\w.-]+", name):
            raise ValueError("invalid repository name")
        if name.lower() in names:
            raise ValueError("duplicate repository in Weekly ranking")
        names.add(name.lower())
        for key in ("new_stars", "stars_total"):
            if type(row.get(key)) is not int or row[key] < 0:
                raise ValueError(f"invalid {key} for {name}")
        if "rank_change" not in row or (row["rank_change"] is not None and type(row["rank_change"]) is not int):
            raise ValueError(f"invalid rank_change for {name}")
    return start, end


def freshness(end, now, max_age_hours=48):
    if max_age_hours <= 0 or not float(max_age_hours) < float("inf"):
        raise ValueError("MAX_SOURCE_AGE_HOURS must be finite and positive")
    # Measure from the END of the covered day, not its beginning.
    covered_until = dt.datetime.combine(end + dt.timedelta(days=1), dt.time(), UTC)
    age = max(0, (now - covered_until).total_seconds() / 3600)
    return {
        "status": "stale" if age > max_age_hours else "fresh",
        "source_age_hours": round(age, 2),
        "max_source_age_hours": max_age_hours,
    }


def update_state(st, frm, to, repos, now):
    _, end = validate_weekly(frm, to, repos, now.astimezone(UTC).date())
    st = copy.deepcopy(st)
    win = f"{frm} – {to}"
    old_window = st.get("window")
    if old_window:
        old_start, old_end = old_window.split(" – ")
        if end < parse_date(old_end):
            raise ValueError(f"source window regressed: {old_window} -> {win}")
        if end == parse_date(old_end) and parse_date(frm) != parse_date(old_start):
            raise ValueError("source changed the start of an already accepted window")
    st.setdefault("items", [])
    if not isinstance(st["items"], list):
        raise ValueError("invalid saved items; refusing to reset history")
    first = st.get("top20") is None
    if not first and (not isinstance(st.get("top20"), list) or not isinstance(st.get("top5"), list)):
        raise ValueError("invalid saved ranking; refusing to reset baseline")

    names = [row["name"] for row in repos]
    top = names[:TOPN]
    previous20 = {n.lower() for n in (st.get("top20") or [])}
    previous5 = {n.lower() for n in (st.get("top5") or [])}
    events = []
    for rank, row in enumerate(repos, 1):
        entered = row["rank_change"] is None if first else row["name"].lower() not in previous20
        if entered:
            events.append(("new", rank, row))
    if not first:
        for rank, row in enumerate(repos[:TOPN], 1):
            if row["name"].lower() not in previous5:
                events.append(("top5", rank, row))

    # Keep the current window's IDs even if its events age out of the RSS cap.
    seen = {i["guid"].lower() for i in st["items"]}
    window_guids = set(st.get("window_guids", [])) if old_window == win else set()
    window_guids.update(i["guid"] for i in st["items"] if i["guid"].startswith(win + "|"))
    seen.update(g.lower() for g in window_guids)
    added = 0
    for kind, rank, row in events:
        name = row["name"]
        guid = f"{win}|{kind}|{name}"
        if guid.lower() in seen:
            continue
        label = "🆕 新进榜单 Top20" if kind == "new" else f"🔥 新进前{TOPN}"
        t5 = " / ".join(f"{x['name'].split('/')[-1]} +{x['new_stars']:,}" for x in repos[:TOPN])
        title = (f"{label} #{rank} {name}（+{row['new_stars']:,} ★）" if kind == "new"
                 else f"{label} #{rank} {name}｜前{TOPN}：{t5}")
        desc = ""
        if kind == "top5":
            desc = f"当前前{TOPN}（统计期内新增星）：<br>" + "<br>".join(
                f"#{j} <a href='https://github.com/{x['name']}'>{x['name']}</a> +{x['new_stars']:,} ★"
                + (" ← 新进" if x["name"] == name else "")
                for j, x in enumerate(repos[:TOPN], 1)
            ) + "<br><br>"
        desc += (f"统计窗口：{win}<br>当前排名：#{rank}<br>统计期内新增星：+{row['new_stars']:,}"
                 f"<br>总星数：{row['stars_total']:,}<br>"
                 f"<a href='https://www.star-history.com/#{name}&amp;Date'>Star History 曲线</a> · "
                 f"<a href='https://github.com/{name}'>GitHub</a>")
        st["items"].insert(0, {
            "title": title, "link": f"https://github.com/{name}", "guid": guid,
            "pubDate": format_datetime(now), "desc": desc,
        })
        window_guids.add(guid)
        seen.add(guid.lower())
        added += 1
    payload = [{key: row[key] for key in ("name", "new_stars", "stars_total", "rank_change")} for row in repos]
    digest = hashlib.sha256(json.dumps([frm, to, payload], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    st.update(window=win, top20=names, top5=top, items=st["items"][:MAXITEMS],
              source_hash=digest, window_guids=sorted(window_guids))
    st.pop("week", None)
    return st, added


def render_feed(st):
    e = html.escape
    items = "".join(
        f"<item><title>{e(i['title'])}</title><link>{e(i['link'])}</link>"
        f"<guid isPermaLink='false'>{e(i['guid'])}</guid><pubDate>{i['pubDate']}</pubDate>"
        f"<description>{e(i['desc'])}</description></item>" for i in st["items"]
    )
    # Preserve the established channel and historical item bytes during migration.
    return (f"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>"
            f"<title>Star History 周榜（滚动）：新上榜 &amp; 新进前{TOPN}</title><link>{BASE}</link>"
            f"<description>只在滚动周榜前20出现新项目或有新项目进入前{TOPN}时更新</description>"
            f"{items}</channel></rss>")


def atomic_write(path, content):
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def run(state_path, out_path, health_path, now=None, max_age_hours=48):
    now = now or dt.datetime.now(UTC)
    now = now.astimezone(UTC)
    state_path, out_path, health_path = map(Path, (state_path, out_path, health_path))
    try:
        previous_health = read_json(health_path, {})
        if not isinstance(previous_health, dict):
            previous_health = {}
    except (ValueError, OSError):
        # Diagnostics can be rebuilt; never apply this fallback to feed state.
        previous_health = {}
    report = {
        "checked_at": now.isoformat(), "status": "error", "source_url": BASE + "/",
        "last_successful_fetch_at": previous_health.get("last_successful_fetch_at"),
        "source_window": previous_health.get("source_window"),
        "window_first_observed_at": previous_health.get("window_first_observed_at"),
    }
    code = 0
    try:
        st = read_json(state_path, {"window": None, "top20": None, "top5": None, "items": []})
        report["accepted_window"] = st.get("window")
        frm, to, repos, asset_url = fetch_weekly()
        _, end = validate_weekly(frm, to, repos, now.date())
        report.update(source_window=f"{frm} – {to}", source_asset_url=asset_url)
        # Record valid observations even when state acceptance rejects a regression.
        if report["source_window"] != previous_health.get("source_window") or not report["window_first_observed_at"]:
            report["window_first_observed_at"] = now.isoformat()
        health = freshness(end, now, max_age_hours)
        updated, count = update_state(st, frm, to, repos, now)
        same_window = st.get("window") == updated["window"]
        content_changed = st.get("source_hash") != updated["source_hash"]
        # State is authoritative; a retry can rebuild the feed after an interrupted write.
        atomic_write(state_path, json.dumps(updated, ensure_ascii=False, indent=1))
        atomic_write(out_path, render_feed(updated))
        report.update(health, last_successful_fetch_at=now.isoformat(),
                      accepted_window=updated["window"], source_hash=updated["source_hash"],
                      window_unchanged=same_window, content_changed=content_changed,
                      new_items=count, item_count=len(updated["items"]), error=None)
        print(f"{report['source_window']}: {count} new items; content_changed={content_changed}; "
              f"freshness={report['status']}; age={report['source_age_hours']}h")
        if report["status"] == "stale":
            print(f"::warning::Published Weekly window exceeds the local {max_age_hours}h freshness policy")
    except Exception as error:
        code = 1
        report.update(status="error", error=str(error))
        print(f"::error::{error}")
    atomic_write(health_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write("### Star History source health\n\n```json\n" + json.dumps(report, ensure_ascii=False, indent=2) + "\n```\n")
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Compatibility option; every run now checks content and deduplicates")
    parser.parse_args()
    return run(Path(os.environ.get("STATE", "state.json")),
               Path(os.environ.get("OUT", "star-history-weekly.xml")),
               Path(os.environ.get("HEALTH", "health.json")),
               max_age_hours=float(os.environ.get("MAX_SOURCE_AGE_HOURS", "48")))


if __name__ == "__main__":
    raise SystemExit(main())
