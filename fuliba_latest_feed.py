#!/usr/bin/env python3
"""
Generate RSS feed for fuliba123.com's 最新收录 (latest directory) sites.

Fetches the latest directory entries from OneNav's AJAX endpoint, tracks
seen site IDs to emit only new entries, and maintains a rolling RSS feed.
"""
import argparse
import copy
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import format_datetime

BASE = "https://fuliba123.com"
API_URL = f"{BASE}/wp-admin/admin-ajax.php"
FETCH_COUNT = 20
MAX_ITEMS = 200
MAX_RETRIES = 3
TIMEOUT = 30
UTC = dt.timezone.utc


def post(url, data, timeout=TIMEOUT):
    """POST form data and return response body as string."""
    encoded = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "User-Agent": "Mozilla/5.0 fuliba-latest-feed",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cache-Control": "no-cache",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def fetch_latest_sites(count=FETCH_COUNT, retries=MAX_RETRIES):
    """Fetch latest sites from the AJAX endpoint with retries."""
    data = {
        "action": "load_hot_post",
        "data[type]": "sites",
        "data[order]": "date",
        "data[num]": str(count),
    }
    last_error = None
    for attempt in range(retries):
        try:
            return post(API_URL, data)
        except (urllib.error.URLError, OSError) as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise last_error


def parse_sites(html_content):
    """
    Parse site entries from the AJAX HTML response.
    
    Returns list of dicts with: id, name, description, external_url, page_url
    """
    sites = []
    
    # Find all anchor tags with data-id attribute (site entries)
    # Use a simpler pattern that finds anchors with data-id, then extract attributes
    anchor_pattern = re.compile(r'<a\s+[^>]*data-id="(\d+)"[^>]*>', re.DOTALL)
    
    for match in anchor_pattern.finditer(html_content):
        site_id = match.group(1)
        anchor_tag = match.group(0)
        
        # Extract href attribute
        href_match = re.search(r'href="([^"]*)"', anchor_tag)
        href = html.unescape(href_match.group(1)) if href_match else ""
        
        # Extract data-url attribute
        data_url_match = re.search(r'data-url="([^"]*)"', anchor_tag)
        data_url = html.unescape(data_url_match.group(1)) if data_url_match else ""
        
        # Extract title attribute (description)
        title_match = re.search(r'title="([^"]*)"', anchor_tag)
        title = html.unescape(title_match.group(1)) if title_match else ""
        
        # Find content after this anchor tag (name and short description)
        anchor_end = match.end()
        content_window = html_content[anchor_end:anchor_end + 1000]
        
        # Find the name (in <strong> tag)
        name_match = re.search(r'<strong>([^<]+)</strong>', content_window)
        name = html.unescape(name_match.group(1).strip()) if name_match else ""
        
        # Find the short description (in <p> with text-muted)
        desc_match = re.search(r'<p[^>]*text-muted[^>]*>([^<]+)</p>', content_window)
        short_desc = html.unescape(desc_match.group(1).strip()) if desc_match else ""
        
        # Use title as description, fall back to short_desc
        full_desc = title.strip() if title else short_desc
        
        # Determine external URL
        external_url = href.strip()
        if not external_url.startswith("http"):
            external_url = data_url.strip()
        
        if site_id and name:
            sites.append({
                "id": site_id,
                "name": name,
                "description": full_desc or short_desc,
                "external_url": external_url,
                "page_url": f"{BASE}/sites/{site_id}.html",
            })
    
    return sites


def validate_sites(sites):
    """Validate parsed site data."""
    if not sites:
        raise ValueError("No sites parsed from response (empty or changed layout?)")
    
    seen_ids = set()
    for site in sites:
        if not site.get("id") or not site.get("name"):
            raise ValueError(f"Invalid site entry: {site}")
        if site["id"] in seen_ids:
            raise ValueError(f"Duplicate site ID: {site['id']}")
        seen_ids.add(site["id"])
        if not site.get("page_url", "").startswith("https://"):
            raise ValueError(f"Invalid page URL for site {site['id']}")
    
    return sites


def update_state(st, sites, now):
    """
    Update state with new site entries.
    
    - First run (no seen_ids): seed with current entries AS RSS items
      so the subscription is immediately useful
    - Subsequent runs: only emit items for genuinely new site IDs
    
    Discovery timestamps (pubDate) reflect when we first saw the site,
    not when the site was originally published (that info is unavailable).
    """
    st = copy.deepcopy(st)
    st.setdefault("seen_ids", [])
    st.setdefault("items", [])
    
    if not isinstance(st["seen_ids"], list):
        raise ValueError("Invalid saved seen_ids; refusing to reset history")
    if not isinstance(st["items"], list):
        raise ValueError("Invalid saved items; refusing to reset history")
    
    first_run = len(st["seen_ids"]) == 0
    seen_set = set(st["seen_ids"])
    
    new_sites = []
    for site in sites:
        if site["id"] not in seen_set:
            new_sites.append(site)
            seen_set.add(site["id"])
    
    # Add new items to feed (including first run - seeds current entries as items)
    added = 0
    for site in new_sites:
        guid = f"fuliba123-site-{site['id']}"
        
        # Build description with site info and external link
        desc_parts = [f"<strong>{html.escape(site['name'])}</strong>"]
        if site.get("description"):
            desc_parts.append(f"<br>{html.escape(site['description'])}")
        if site.get("external_url"):
            desc_parts.append(
                f"<br><br>🔗 外部链接：<a href='{html.escape(site['external_url'])}'>"
                f"{html.escape(site['external_url'])}</a>"
            )
        desc_parts.append(
            f"<br>📄 详情页面：<a href='{html.escape(site['page_url'])}'>"
            f"{html.escape(site['page_url'])}</a>"
        )
        
        st["items"].insert(0, {
            "title": f"🆕 {site['name']}",
            "link": site["page_url"],
            "guid": guid,
            "pubDate": format_datetime(now),
            "desc": "".join(desc_parts),
            "discovered_at": now.isoformat(),
        })
        added += 1
    
    st["seen_ids"] = sorted(seen_set)
    st["items"] = st["items"][:MAX_ITEMS]
    st["last_fetch"] = now.isoformat()
    if first_run:
        st["seeded_count"] = len(sites)
    
    return st, added


def render_feed(st):
    """Render state to RSS XML."""
    e = html.escape
    items = "".join(
        f"<item><title>{e(i['title'])}</title><link>{e(i['link'])}</link>"
        f"<guid isPermaLink='false'>{e(i['guid'])}</guid><pubDate>{i['pubDate']}</pubDate>"
        f"<description>{e(i['desc'])}</description></item>"
        for i in st.get("items", [])
    )
    return (
        f"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>"
        f"<title>福利吧导航 - 最新收录</title>"
        f"<link>{BASE}</link>"
        f"<description>fuliba123.com 最新收录的网站目录，仅在发现新站点时更新</description>"
        f"{items}</channel></rss>"
    )


def atomic_write(path, content):
    """Write content to file atomically."""
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default):
    """Read JSON file or return default if missing."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def run(state_path, out_path, health_path, now=None):
    """Main entry point."""
    now = now or dt.datetime.now(UTC)
    now = now.astimezone(UTC)
    state_path, out_path, health_path = map(Path, (state_path, out_path, health_path))
    
    try:
        previous_health = read_json(health_path, {})
        if not isinstance(previous_health, dict):
            previous_health = {}
    except (ValueError, OSError):
        previous_health = {}
    
    report = {
        "checked_at": now.isoformat(),
        "status": "error",
        "source_url": BASE,
        "last_successful_fetch_at": previous_health.get("last_successful_fetch_at"),
    }
    code = 0
    
    try:
        st = read_json(state_path, {"seen_ids": [], "items": []})
        report["known_site_count"] = len(st.get("seen_ids", []))
        
        raw_html = fetch_latest_sites(FETCH_COUNT)
        sites = validate_sites(parse_sites(raw_html))
        report["fetched_site_count"] = len(sites)
        
        updated, added = update_state(st, sites, now)
        
        # State is authoritative; rebuild feed from state
        atomic_write(state_path, json.dumps(updated, ensure_ascii=False, indent=1))
        atomic_write(out_path, render_feed(updated))
        
        report.update(
            status="ok",
            last_successful_fetch_at=now.isoformat(),
            new_items=added,
            item_count=len(updated.get("items", [])),
            known_site_count=len(updated.get("seen_ids", [])),
            seeded=updated.get("seeded_count"),
            error=None,
        )
        
        if updated.get("seeded_count"):
            print(f"Seeded {updated['seeded_count']} sites as initial feed items (first run)")
        elif added > 0:
            print(f"Added {added} new site(s) to feed")
        else:
            print("No new sites found")
            
    except Exception as error:
        code = 1
        report.update(status="error", error=str(error))
        print(f"::error::{error}")
    
    atomic_write(health_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(
                "### Fuliba Latest Sites Feed\n\n```json\n"
                + json.dumps(report, ensure_ascii=False, indent=2)
                + "\n```\n"
            )
    
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    return run(
        Path(os.environ.get("FULIBA_STATE", "fuliba-latest-state.json")),
        Path(os.environ.get("FULIBA_OUT", "fuliba-latest.xml")),
        Path(os.environ.get("FULIBA_HEALTH", "fuliba-latest-health.json")),
    )


if __name__ == "__main__":
    raise SystemExit(main())
