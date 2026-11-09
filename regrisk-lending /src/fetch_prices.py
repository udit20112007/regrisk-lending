"""
DOWNLOAD REAL SHARE PRICES
==========================

Run this once on your own computer (it needs internet):

    python src/fetch_prices.py

It downloads daily closing prices from Yahoo Finance for every company in
data/tickers.csv plus the Nifty 50 index, and saves them to data/prices.csv.
As soon as that file exists, the whole project uses real data automatically.

Prices are "adjusted" for share splits and dividends, so a split does not
look like a crash.
"""

from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
START_DATE = "2021-06-01"
MARKET_SYMBOL = "^NSEI"      # Nifty 50


def download_close(symbol: str) -> pd.Series | None:
    """Download one symbol. Returns None if Yahoo has no data for it."""
    try:
        data = yf.download(symbol, start=START_DATE, auto_adjust=True, progress=False)
    except Exception as error:           # network problem, wrong symbol, etc.
        print(f"  could not download {symbol}: {error}")
        return None
    if data is None or data.empty:
        print(f"  no data returned for {symbol}")
        return None
    close = data["Close"]
    if isinstance(close, pd.DataFrame):  # newer yfinance versions return a table
        close = close.iloc[:, 0]
    return close


def main() -> None:
    tickers = pd.read_csv(DATA_DIR / "tickers.csv")
    columns = {}

    print("Downloading the market index...")
    market = download_close(MARKET_SYMBOL)
    if market is None:
        raise SystemExit("Could not download the Nifty 50 index. Check your internet connection.")
    columns["NIFTY"] = market

    for _, row in tickers.iterrows():
        print(f"Downloading {row['company']}...")
        series = download_close(row["yahoo_symbol"])
        if series is not None:
            columns[row["ticker"]] = series

    # Safety check: if most downloads failed, keep whatever prices we already
    # have instead of replacing them with a nearly empty file.
    downloaded = len(columns) - 1
    if downloaded < len(tickers) / 2:
        raise SystemExit(f"Only {downloaded} of {len(tickers)} stocks downloaded. "
                         "Nothing was saved. Try again later.")

    prices = pd.DataFrame(columns).sort_index()
    prices = prices[prices["NIFTY"].notna()]          # keep only days the market was open
    prices.index.name = "date"
    prices.to_csv(DATA_DIR / "prices.csv")

    missing = [t for t in tickers["ticker"] if t not in prices.columns]
    print(f"\nSaved {len(prices)} days for {len(prices.columns) - 1} stocks to data/prices.csv")
    if missing:
        print("No data for:", ", ".join(missing), "- check the yahoo_symbol in data/tickers.csv")


if __name__ == "__main__":
    main()
