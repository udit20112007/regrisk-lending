"""
MAKE-UP PRICE DATA (for testing only)
=====================================

This script INVENTS share prices so the project can run without internet.
The numbers are NOT real and must never be quoted as findings.

How the fake prices are made:
  - the market moves randomly each day
  - each stock follows the market (its "beta") plus its own random noise
  - on each event's reaction day we add a chosen shock, so we can check that
    the event study finds the shock we planted

For real results run:  python src/fetch_prices.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# made-up listing dates, so the code also has to cope with missing history
LISTED_FROM = {"MOBIKWIK": "2024-12-18"}

# planted shocks (log return on the reaction day), by role
DIRECT_SHOCK = {"tightening": -0.12, "easing": 0.05}
PEER_SHOCK = {"tightening": -0.02, "easing": 0.01}


def main(seed: int = 7) -> None:
    rng = np.random.default_rng(seed)
    tickers = pd.read_csv(DATA_DIR / "tickers.csv")
    events = pd.read_csv(DATA_DIR / "events.csv", parse_dates=["announce_date"])

    days = pd.bdate_range("2021-11-18", "2026-10-30")       # weekdays only
    market = rng.normal(0.0004, 0.009, len(days))
    returns = pd.DataFrame({"NIFTY": market}, index=days)

    for _, row in tickers.iterrows():
        beta = rng.uniform(0.8, 1.4)
        own_noise = rng.normal(0.0, rng.uniform(0.014, 0.024), len(days))
        returns[row["ticker"]] = beta * market + own_noise

    # plant the shocks
    for _, ev in events.iterrows():
        targets = str(ev["target_tickers"]).split(";") if pd.notna(ev["target_tickers"]) else []
        affected = str(ev["affected_models"]).split(";")
        pos = days.searchsorted(ev["announce_date"], side="left")
        if pos < len(days) and days[pos] == ev["announce_date"] and ev["after_hours"] == 1:
            pos += 1
        if pos >= len(days) or ev["direction"] not in DIRECT_SHOCK:
            continue
        for _, row in tickers.iterrows():
            models = row["models"].split(";")
            if row["ticker"] in targets:
                shock = DIRECT_SHOCK[ev["direction"]]
            elif set(models) & set(affected):
                shock = PEER_SHOCK[ev["direction"]]
            else:
                continue
            returns.iloc[pos, returns.columns.get_loc(row["ticker"])] += shock * rng.uniform(0.6, 1.4)

    prices = 100 * np.exp(returns.cumsum())
    for ticker, start in LISTED_FROM.items():
        prices.loc[prices.index < start, ticker] = np.nan

    prices.index.name = "date"
    prices.round(4).to_csv(DATA_DIR / "sample_prices.csv")
    print(f"Wrote made-up prices for {len(prices.columns) - 1} stocks, {len(prices)} days.")


if __name__ == "__main__":
    main()
