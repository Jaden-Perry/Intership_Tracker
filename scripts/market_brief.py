"""Daily job: build and send the markets brief email.

Usage: python market_brief.py [morning|evening]
Env vars: RESEND_API_KEY, ALERT_EMAIL, ALERT_FROM_EMAIL (optional),
          ANTHROPIC_API_KEY
"""
import datetime
import json
import sys
from pathlib import Path

from brief_writer import generate_brief_html
from emailer import send_market_brief
from market_calendar import is_us_market_holiday
from market_data import fetch_index_data
from market_news import fetch_headlines

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "market_brief.json"
FIRMS_PATH = ROOT / "config" / "firms.json"

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


def main() -> None:
    run_type = sys.argv[1] if len(sys.argv) > 1 else "morning"
    if run_type not in ("morning", "evening"):
        run_type = "morning"

    today = datetime.date.today()
    if is_us_market_holiday(today):
        print(f"market_brief: {today} is a US market holiday, skipping")
        return

    config = json.loads(CONFIG_PATH.read_text())
    market_data = fetch_index_data(config["tickers"])
    headlines = fetch_headlines(config["feeds"])

    if not market_data and not headlines:
        print("market_brief: no market data or headlines fetched, skipping send")
        return

    date_str = datetime.date.today().strftime("%A, %B %d, %Y")
    recruiting_context = build_recruiting_context()

    html = generate_brief_html(
        run_type, date_str, market_data, headlines, recruiting_context
    )

    label = "Morning" if run_type == "morning" else "Evening"
    subject = f"{label} Markets Brief — {date_str}"
    send_market_brief(html, subject)
    print(f"market_brief: sent {run_type} brief for {date_str}")


if __name__ == "__main__":
    main()
