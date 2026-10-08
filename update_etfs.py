#!/usr/bin/env python3
"""Fetch EUR quotes for two Xetra ETFs. Never fabricate prices."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

TICKERS = {
    "IE00B6R52259": "IUSQ.DE",  # iShares MSCI ACWI UCITS ETF
    "IE00BF4RFH31": "IUSN.DE",  # iShares MSCI World Small Cap UCITS ETF
}
OUTPUT = Path(__file__).resolve().parent / "etf-kurse.json"


def fetch_one(isin, symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?interval=1d&range=5d"
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; MatzePortfolioETFUpdater/1.0)",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=18) as response:
        payload = json.load(response)
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise ValueError(f"No quote data for {symbol}")
    data = result[0]
    meta = data.get("meta") or {}
    currency = meta.get("currency")
    if currency != "EUR":
        raise ValueError(f"Unexpected currency {currency!r} for {symbol}; EUR required")
    price = meta.get("regularMarketPrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or not (0 < price < 100000):
        raise ValueError(f"Invalid price for {symbol}: {price!r}")
    market_timestamp = meta.get("regularMarketTime")
    if not isinstance(market_timestamp, (int, float)) or market_timestamp <= 0:
        raise ValueError(f"Missing market timestamp for {symbol}")
    market_time = datetime.fromtimestamp(market_timestamp, tz=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - market_time).total_seconds()
    if age_seconds < -3600 or age_seconds > 8 * 86400:
        raise ValueError(f"Stale/invalid market timestamp for {symbol}: {market_time.isoformat()}")
    return {
        "isin": isin,
        "symbol": symbol,
        "currency": "EUR",
        "price": round(float(price), 6),
        "marketTime": market_time.isoformat().replace("+00:00", "Z"),
        "source": "Yahoo Finance chart endpoint",
    }


def main():
    quotes = {}
    errors = []
    for isin, symbol in TICKERS.items():
        for attempt in range(3):
            try:
                quotes[isin] = fetch_one(isin, symbol)
                print(f"OK {symbol}: {quotes[isin]['price']} EUR, marketTime={quotes[isin]['marketTime']}")
                break
            except (HTTPError, URLError, TimeoutError, ValueError, KeyError, OSError) as exc:
                print(f"Attempt {attempt + 1}/3 failed for {symbol}: {exc}", file=sys.stderr)
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        if isin not in quotes:
            errors.append(symbol)
    if errors:
        print(f"FAILED: no new file written; unavailable: {', '.join(errors)}", file=sys.stderr)
        return 1
    payload = {
        "schemaVersion": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "quotes": quotes,
    }
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(f"Wrote {OUTPUT.name} with both verified EUR quotes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
