"""Fetch daily index/yield/commodity levels from Yahoo Finance's public chart API.

No API key required, but Yahoo blocks requests without a browser-like User-Agent.
"""
import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def fetch_index_data(tickers: list[dict]) -> list[dict]:
    """Fetch latest price + % change vs. previous close for each ticker.

    Skips (and logs) any symbol that fails rather than failing the whole run -
    one bad Yahoo response shouldn't block the rest of the brief.
    """
    out = []
    for t in tickers:
        symbol = t["symbol"]
        try:
            resp = requests.get(
                CHART_URL.format(symbol=symbol),
                params={"range": "5d", "interval": "1d"},
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()["chart"]["result"][0]
            meta = result["meta"]
            price = meta["regularMarketPrice"]

            # meta["chartPreviousClose"] is NOT reliably "yesterday's close" -
            # it shifts depending on the requested range (e.g. the close
            # before a 5d window can be ~6 trading days back). Pull the
            # actual previous session's close from the daily bars instead.
            closes = [
                c
                for c in result["indicators"]["quote"][0]["close"]
                if c is not None
            ]
            prev_close = closes[-2] if len(closes) >= 2 else None
            pct_change = (
                (price - prev_close) / prev_close * 100 if prev_close else None
            )
            out.append(
                {
                    "label": t["label"],
                    "symbol": symbol,
                    "price": price,
                    "pct_change": pct_change,
                }
            )
        except Exception as e:
            print(f"market_data: failed to fetch {symbol}: {e}")
    return out
