"""Fetch daily index/yield/commodity levels from Yahoo Finance's public chart API.

No API key required, but Yahoo blocks requests without a browser-like User-Agent.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

CHART_URL = "https://{host}/v8/finance/chart/{symbol}"
CHART_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
ET = ZoneInfo("America/New_York")
MAX_ATTEMPTS = 3


def _fetch_chart(symbol: str, attempt: int) -> dict:
    params = {"range": "5d", "interval": "1d"}
    if attempt > 0:
        # Retries use the other host plus a throwaway param so we don't get
        # handed the same stale edge-cached copy again.
        params["_"] = str(time.time_ns())
    resp = requests.get(
        CHART_URL.format(host=CHART_HOSTS[attempt % len(CHART_HOSTS)], symbol=symbol),
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["chart"]["result"][0]


def _fetch_fresh_chart(symbol: str, min_date: date) -> dict | None:
    """Return chart data whose latest quote is from min_date or later, or None.

    Yahoo sometimes serves a stale cached response for one symbol while others
    are fresh (seen with ^DJI: Monday's close reported as Tuesday's, with no
    Tuesday bar). Presenting that as current data is worse than omitting it.
    """
    for attempt in range(MAX_ATTEMPTS):
        try:
            result = _fetch_chart(symbol, attempt)
        except Exception as e:
            print(f"market_data: {symbol} fetch failed (attempt {attempt + 1}): {e}")
            continue
        latest = datetime.fromtimestamp(result["meta"]["regularMarketTime"], tz=ET).date()
        if latest >= min_date:
            return result
        print(
            f"market_data: {symbol} is stale (latest quote {latest}, "
            f"need >= {min_date}), attempt {attempt + 1}/{MAX_ATTEMPTS}"
        )
        time.sleep(2)
    return None


def fetch_index_data(tickers: list[dict], min_date: date) -> list[dict]:
    """Fetch latest price + % change vs. previous close for each ticker.

    min_date is the session whose data we expect (quotes older than that are
    rejected). A ticker that can't be fetched fresh is returned with
    unavailable=True instead of being dropped or reported with stale numbers,
    so the brief can say so explicitly.
    """
    out = []
    for t in tickers:
        symbol = t["symbol"]
        result = _fetch_fresh_chart(symbol, min_date)
        if result is None:
            print(f"market_data: giving up on {symbol}, marking unavailable")
            out.append(
                {
                    "label": t["label"],
                    "symbol": symbol,
                    "price": None,
                    "pct_change": None,
                    "unavailable": True,
                }
            )
            continue

        price = result["meta"]["regularMarketPrice"]

        # meta["chartPreviousClose"] is NOT reliably "yesterday's close" -
        # it shifts depending on the requested range (e.g. the close
        # before a 5d window can be ~6 trading days back). Pull the
        # actual previous session's close from the daily bars instead.
        closes = [
            c for c in result["indicators"]["quote"][0]["close"] if c is not None
        ]
        prev_close = closes[-2] if len(closes) >= 2 else None
        pct_change = (price - prev_close) / prev_close * 100 if prev_close else None
        out.append(
            {
                "label": t["label"],
                "symbol": symbol,
                "price": price,
                "pct_change": pct_change,
                "unavailable": False,
            }
        )
    return out
