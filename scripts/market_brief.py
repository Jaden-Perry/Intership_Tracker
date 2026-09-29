"""Job: build and send the markets brief email.

Runs hourly (weekdays) rather than at one fixed time, because GitHub Actions
noticeably delays infrequent scheduled workflows (observed 2-3.5h drift on a
once-a-day cron) but keeps hourly ones on time within a couple minutes. When
MARKET_BRIEF_GATE=1 (set by the scheduled trigger, not manual runs), this
skips unless it's after market close AND today's brief hasn't been sent yet
(tracked in data/market_brief_state.json) - so whichever hourly check is the
first one after close to actually run is the one that sends it.

Usage: python market_brief.py [morning|evening]
Env vars: RESEND_API_KEY, ALERT_EMAIL, ALERT_FROM_EMAIL (optional),
          ANTHROPIC_API_KEY, MARKET_BRIEF_GATE (optional, "1" to gate)
"""
import datetime
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from brief_writer import generate_brief_html
from emailer import send_market_brief
from market_calendar import is_us_market_holiday, previous_trading_day
from market_data import fetch_index_data
from market_news import fetch_headlines

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "market_brief.json"
FIRMS_PATH = ROOT / "config" / "firms.json"
STATE_PATH = ROOT / "data" / "market_brief_state.json"

MARKET_CLOSE_HOUR_ET = 16  # 4:00pm ET

CATEGORY_LABELS = {
    "bulge_bracket": "bulge bracket banks",
    "eb_mm": "elite boutique / middle-market banks",
    "pe": "private equity firms",
    "wm": "wealth management",
}


def build_recruiting_context() -> str:
    """Describe the reader's target firms, pulled from config/firms.json so
    this stays in sync with whatever the tracker is actually watching.
    """
    try:
        firms = json.loads(FIRMS_PATH.read_text())
    except Exception:
        return "bulge bracket banks, elite boutique/middle-market banks, and private equity firms"

    by_category: dict[str, list[str]] = {}
    for f in firms:
        by_category.setdefault(f["category"], []).append(f["name"])

    parts = []
    for category, names in by_category.items():
        label = CATEGORY_LABELS.get(category, category)
        parts.append(f"{label} ({', '.join(names)})")
    return "; ".join(parts)


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def main() -> None:
    run_type = sys.argv[1] if len(sys.argv) > 1 else "evening"
    if run_type not in ("morning", "evening"):
        run_type = "evening"

    et_now = datetime.datetime.now(ZoneInfo("America/New_York"))
    today = et_now.date()
    gated = os.environ.get("MARKET_BRIEF_GATE") == "1"

    if gated:
        if et_now.hour < MARKET_CLOSE_HOUR_ET:
            print(f"market_brief: {et_now:%H:%M} ET is before market close, skipping")
            return
        if _load_state().get("last_sent_date") == today.isoformat():
            print(f"market_brief: already sent today ({today}), skipping")
            return

    if is_us_market_holiday(today):
        print(f"market_brief: {today} is a US market holiday, skipping")
        return

    config = json.loads(CONFIG_PATH.read_text())
    market_data = fetch_index_data(config["tickers"])
    headlines = fetch_headlines(config["feeds"])

    if not market_data and not headlines:
        print("market_brief: no market data or headlines fetched, skipping send")
        return

    date_str = today.strftime("%A, %B %d, %Y")
    # Evening runs happen after today's close, so today's session is the
    # latest one. Morning runs happen before the open, so the market data
    # actually reflects the most recently completed (prior) session.
    session_date = today if run_type == "evening" else previous_trading_day(today)
    session_date_str = session_date.strftime("%A, %B %d, %Y")
    recruiting_context = build_recruiting_context()

    html = generate_brief_html(
        run_type, date_str, session_date_str, market_data, headlines, recruiting_context
    )

    label = "Morning" if run_type == "morning" else "Evening"
    subject = f"{label} Markets Brief — {date_str}"
    send_market_brief(html, subject)
    if gated:
        _save_state({"last_sent_date": today.isoformat()})
    print(f"market_brief: sent {run_type} brief for {date_str}")


if __name__ == "__main__":
    main()
