"""Fetch and lightly dedupe finance headlines from public RSS feeds."""
from __future__ import annotations

import calendar
import html as html_lib
import re
import time
from datetime import datetime, timezone

import feedparser
import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _published_str(entry) -> str:
    """Human-readable publish time, so the model can tell a stale
    "expected to happen" headline apart from a newer confirmed-outcome one.
    """
    parsed = entry.get("published_parsed")
    if not parsed:
        return "unknown time"
    dt = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _fomc_statement_text(url: str) -> str | None:
    """The Fed's RSS item for an FOMC statement is just its title, with no
    decision in it - which once led the brief to invent a rate hike on a day
    the Fed held. Pull the actual statement (vote, decision, dissents) from
    the release page so the writer has the real text.
    """
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        page = resp.content.decode("utf-8", errors="replace")
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
        text = re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", text)))
        m = re.search(
            r"The Federal Open Market Committee approved.*?(?=For media inquiries|Implementation Note|$)",
            text,
        )
        if not m or "Committee decided" not in m.group(0):
            return None
        return "OFFICIAL STATEMENT TEXT: " + m.group(0).strip()[:1500]
    except Exception as e:
        print(f"market_news: could not fetch FOMC statement text: {e}")
        return None


STALE_AFTER_DAYS = 3


def _parse_feed(feed: dict):
    """feedparser never raises on HTTP errors; it returns an empty feed. So
    check status/entries ourselves, retry once, and report what went wrong
    (a dead feed once went unnoticed for weeks: Yahoo 404 and a WSJ URL that
    froze in Jan 2025).
    """
    parsed, problem = None, None
    for attempt in (1, 2):
        parsed = feedparser.parse(feed["url"], request_headers={"User-Agent": USER_AGENT})
        status = parsed.get("status")
        if status and status >= 400:
            problem = f"HTTP {status}"
        elif not parsed.entries:
            problem = "no entries returned"
        else:
            problem = None
            break
        time.sleep(2)
    return parsed, problem


def fetch_headlines(
    feeds: list[dict], per_feed: int = 8, total_limit: int = 30
) -> tuple[list[dict], list[str]]:
    """Pull the newest few entries from each feed, deduping near-identical
    titles (the same story often runs on multiple wires) and logging (not
    raising on) any feed that fails so one dead feed doesn't sink the brief.

    Results are sorted newest-first so recency is obvious in the order
    alone, not just the timestamp text.

    A feed with "pin_days" set (e.g. the Fed's press releases) always has its
    items from the last N days included, even if 30 newer headlines from the
    high-volume feeds would otherwise push them out of the window - otherwise
    an official decision from yesterday silently vanishes from the writer's
    inputs by evening.
    """
    seen_titles = set()
    headlines = []
    problems: list[str] = []
    now = time.time()
    for feed in feeds:
        pin_cutoff = now - feed["pin_days"] * 86400 if feed.get("pin_days") else None
        try:
            parsed, problem = _parse_feed(feed)
            if problem:
                problems.append(f"{feed['name']}: {problem}")
            elif not feed.get("pin_days"):
                stamps = [calendar.timegm(e["published_parsed"]) for e in parsed.entries if e.get("published_parsed")]
                if stamps and now - max(stamps) > STALE_AFTER_DAYS * 86400:
                    newest = datetime.fromtimestamp(max(stamps), tz=timezone.utc).strftime("%Y-%m-%d")
                    problems.append(f"{feed['name']}: stale (newest item {newest})")
            for entry in parsed.entries[:per_feed]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                key = title.lower()[:60]
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                summary = entry.get("summary", "")[:220]
                if "FOMC statement" in title:
                    summary = _fomc_statement_text(entry.get("link", "")) or summary
                headlines.append(
                    {
                        "source": feed["name"],
                        "title": title,
                        "summary": summary,
                        "link": entry.get("link", ""),
                        "published": _published_str(entry),
                        "published_parsed": entry.get("published_parsed"),
                        "pinned": bool(
                            pin_cutoff
                            and entry.get("published_parsed")
                            and calendar.timegm(entry["published_parsed"]) >= pin_cutoff
                        ),
                    }
                )
        except Exception as e:
            print(f"market_news: failed to fetch {feed['name']}: {e}")
            problems.append(f"{feed['name']}: {e}")

    headlines.sort(
        key=lambda h: h["published_parsed"] or (), reverse=True
    )
    kept = headlines[:total_limit] + [h for h in headlines[total_limit:] if h["pinned"]]
    for h in kept:
        del h["published_parsed"], h["pinned"]
    for pr in problems:
        print(f"market_news: WARNING source problem - {pr}")
    return kept, problems
