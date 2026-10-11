#!/usr/bin/env python3
"""Fetch AI news from the RSS/Atom feeds in feeds.json and write docs/data/news.json.

Standard library only, so it runs anywhere Python 3.9+ is installed.
Previously collected items are kept (up to max_age_days) so the dashboard
builds up history even when a feed only exposes its latest few entries.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "ai-news-dashboard/1.0 (+https://github.com/)"

# Topic tags are assigned by keyword match on title + summary.
TOPICS: dict[str, list[str]] = {
    "Models": [r"\bgpt-?\d", r"\bclaude\b", r"\bgemini\b", r"\bllama\b", r"\bmistral\b", r"\bqwen\b",
               r"\bdeepseek\b", r"\bgrok\b", r"\bmodel(s)?\b", r"\bllms?\b", r"\bmultimodal\b"],
    "Research": [r"\bpaper\b", r"\bresearch\b", r"\barxiv\b", r"\bbenchmark", r"\bdataset", r"\bstudy\b"],
    "Policy": [r"\bregulat", r"\bpolicy\b", r"\blaw\b", r"\bcongress\b", r"\beu\b", r"\bcopyright",
               r"\blawsuit", r"\bgovernment", r"\bsafety\b", r"\bethic"],
    "Business": [r"\bfunding\b", r"\braises?\b", r"\bvaluation", r"\bacquir", r"\bipo\b", r"\binvest",
                 r"\brevenue\b", r"\bstartup", r"\bpartnership"],
    "Tools": [r"\bapi\b", r"\bsdk\b", r"\bopen[- ]source\b", r"\brelease[sd]?\b", r"\blaunch", r"\bagents?\b",
              r"\bcopilot\b", r"\bplugin", r"\bapp\b"],
    "Hardware": [r"\bgpus?\b", r"\bnvidia\b", r"\bchips?\b", r"\btpus?\b", r"\bdata ?cent", r"\bsemiconductor"],
}
_TOPIC_RES = {t: re.compile("|".join(p), re.I) for t, p in TOPICS.items()}


def local(tag: str) -> str:
    """Strip an XML namespace: '{http://www.w3.org/2005/Atom}entry' -> 'entry'."""
    return tag.rsplit("}", 1)[-1]


def child(el: ET.Element, *names: str) -> ET.Element | None:
    for c in el:
        if local(c.tag) in names:
            return c
    return None


def text_of(el: ET.Element | None) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def clean(raw: str, limit: int = 280) -> str:
    """HTML -> plain text, collapsed and truncated on a word boundary."""
    txt = re.sub(r"<[^>]+>", " ", raw)
    txt = re.sub(r"\s+", " ", html.unescape(txt)).strip()
    if len(txt) > limit:
        txt = txt[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return txt


def parse_date(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)  # RFC 822 (RSS)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))  # RFC 3339 (Atom)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def entry_link(el: ET.Element) -> str:
    for c in el:
        if local(c.tag) != "link":
            continue
        href = c.get("href")
        if href and c.get("rel", "alternate") == "alternate":
            return href.strip()
        if not href and (c.text or "").strip():
            return c.text.strip()
    guid = child(el, "guid", "id")
    return text_of(guid) if guid is not None and text_of(guid).startswith("http") else ""


def parse_feed(xml_bytes: bytes, source: str, kind: str) -> list[dict]:
    """Parse RSS 2.0, RSS 1.0 (RDF) or Atom into normalized item dicts."""
    root = ET.fromstring(xml_bytes)
    entries = [e for e in root.iter() if local(e.tag) in ("item", "entry")]
    items = []
    for e in entries:
        title = clean(text_of(child(e, "title")), 300)
        link = entry_link(e)
        if not title or not link.startswith(("http://", "https://")):
            continue
        summary_el = child(e, "description", "summary", "encoded", "content")
        date_el = child(e, "pubDate", "published", "updated", "date", "issued")
        published = parse_date(text_of(date_el))
        summary = clean(text_of(summary_el))
        items.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:16],
            "title": title,
            "link": link,
            "source": source,
            "kind": kind,
            "summary": summary,
            "published": published.astimezone(timezone.utc).isoformat() if published else None,
            "topics": tag_topics(f"{title} {summary}"),
        })
    return items


def tag_topics(text: str) -> list[str]:
    return [t for t, rx in _TOPIC_RES.items() if rx.search(text)]


def fetch(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_feed(feed: dict, limit: int) -> tuple[dict, list[dict], str | None]:
    try:
        items = parse_feed(fetch(feed["url"]), feed["name"], feed.get("kind", "press"))
        return feed, items[:limit], None
    except Exception as exc:  # one broken feed must not sink the whole run
        return feed, [], f"{type(exc).__name__}: {exc}"


def merge(old: list[dict], new: list[dict], now: datetime, max_age_days: int) -> list[dict]:
    """Union by id (new wins, but keep first-seen time), drop stale items, newest first."""
    by_id = {i["id"]: i for i in old}
    for item in new:
        prev = by_id.get(item["id"])
        item["first_seen"] = prev.get("first_seen") if prev else now.isoformat()
        by_id[item["id"]] = item
    cutoff = now - timedelta(days=max_age_days)

    def when(i: dict) -> datetime:
        return parse_date(i.get("published") or "") or parse_date(i.get("first_seen") or "") or now

    kept = [i for i in by_id.values() if when(i) >= cutoff]
    kept.sort(key=when, reverse=True)
    return kept


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=ROOT / "feeds.json")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "data" / "news.json")
    args = ap.parse_args(argv)

    cfg = json.loads(args.config.read_text())
    limit = cfg.get("max_items_per_feed", 40)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    old_items: list[dict] = []
    if args.out.exists():
        try:
            old_items = json.loads(args.out.read_text()).get("items", [])
        except (json.JSONDecodeError, AttributeError):
            pass

    new_items, sources = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for feed, items, err in pool.map(lambda f: fetch_feed(f, limit), cfg["feeds"]):
            new_items.extend(items)
            sources.append({"name": feed["name"], "url": feed["url"], "kind": feed.get("kind", "press"),
                            "ok": err is None, "count": len(items), "error": err})
            print(f"{'ok ' if err is None else 'ERR'} {feed['name']:<24} {len(items):>3} items"
                  + (f"  ({err})" if err else ""), file=sys.stderr)

    items = merge(old_items, new_items, now, cfg.get("max_age_days", 30))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"updated": now.isoformat(), "sources": sources, "items": items},
                                   ensure_ascii=False, indent=1))
    print(f"wrote {len(items)} items to {args.out}", file=sys.stderr)
    # Fail only if every feed failed, so a single flaky site doesn't break the schedule.
    return 0 if any(s["ok"] for s in sources) else 1


if __name__ == "__main__":
    sys.exit(main())
