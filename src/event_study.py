"""
MODULE 1 - REGULATORY SHOCK EVENT STUDY
=======================================

The question
------------
When RBI announces a rule or an action, how much do fintech share prices move
*because of that news*?

The problem: shares move every day anyway, mostly with the overall market.
So we cannot just look at the price change. We have to remove the part that
the market explains. What is left is called the ABNORMAL RETURN.

The method (the standard "market model" event study)
----------------------------------------------------
  Step 1. Take a calm period BEFORE the event (the "estimation window").
          Fit a straight line:  stock return = alpha + beta x market return
          beta tells us how strongly this stock usually follows the market.
  Step 2. Around the event, predict what the stock "should" have done
          using that line and the actual market return.
  Step 3. Abnormal return (AR) = actual return - predicted return.
  Step 4. Add the abnormal returns over a few days = CUMULATIVE abnormal
          return (CAR). This is our measure of the shock.
  Step 5. Check if the CAR is bigger than normal day-to-day noise (t-statistic).
"""

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MARKET = "NIFTY"            # the column that holds the market index

# Estimation window: 120 trading days, ending 11 days before the event.
# The gap makes sure news leaking just before the event does not spoil the line.
EST_LENGTH = 120
EST_GAP = 10
MIN_EST_DAYS = 60           # skip a stock if it has less history than this

# Event windows we report, as (first day, last day) relative to the reaction day.
# Day 0 = first trading day on which investors could react to the news.
WINDOWS = {
    "CAR(0,0)": (0, 0),     # reaction day only
    "CAR(0,+1)": (0, 1),    # reaction day and the next day
    "CAR(0,+5)": (0, 5),    # about one trading week
    "CAR(-1,+5)": (-1, 5),  # also catches news that came out a day early
}
MAIN_WINDOW = "CAR(0,+5)"


# ---------------------------------------------------------------------------
# LOADING DATA
# ---------------------------------------------------------------------------
def load_prices() -> tuple:
    """
    Load daily closing prices.

    Uses data/prices.csv (REAL prices, created by src/fetch_prices.py) if it
    exists. Otherwise falls back to data/sample_prices.csv, which is MADE-UP
    data that only exists so the code can be run and tested.

    Returns (prices table, True if the data is the made-up sample).
    """
    real = DATA_DIR / "prices.csv"
    sample = DATA_DIR / "sample_prices.csv"
    path, is_sample = (real, False) if real.exists() else (sample, True)
    prices = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    return prices, is_sample


def load_events() -> pd.DataFrame:
    """The list of RBI actions. Lists stored as 'a;b;c' are split into Python lists."""
    events = pd.read_csv(DATA_DIR / "events.csv", parse_dates=["announce_date"])
    # rows marked "ignore" were found by the automatic watch and rejected by a person
    events = events[events["direction"] != "ignore"].reset_index(drop=True)
    if "added_by" not in events.columns:
        events["added_by"] = "manual"
    events["added_by"] = events["added_by"].fillna("manual")
    for col in ("target_tickers", "affected_models"):
        events[col] = events[col].fillna("").apply(lambda s: [x for x in s.split(";") if x])
    return events


def load_tickers() -> pd.DataFrame:
    """The list of companies and the business model(s) each one belongs to."""
    tickers = pd.read_csv(DATA_DIR / "tickers.csv")
    tickers["models"] = tickers["models"].apply(lambda s: s.split(";"))
    return tickers


# ---------------------------------------------------------------------------
# RETURNS
# ---------------------------------------------------------------------------
def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Daily log returns: ln(today's price / yesterday's price).
    Log returns are used because they can simply be added up across days.
    """
    return np.log(prices / prices.shift(1)).iloc[1:]


# ---------------------------------------------------------------------------
# WHICH DAY DID THE MARKET REACT?
# ---------------------------------------------------------------------------
def reaction_day_position(trading_days: pd.DatetimeIndex, announce_date, after_hours: bool) -> int:
    """
    Position (row number) of the first trading day when investors could react.

    - News during market hours           -> the same day
    - News after the market closed       -> the next trading day
    - News on a weekend or holiday       -> the next trading day
    Returns -1 if the event is after the end of our data.
    """
    announce_date = pd.Timestamp(announce_date)
    # first trading day on or after the announcement
    pos = int(trading_days.searchsorted(announce_date, side="left"))
    if pos >= len(trading_days):
        return -1
    announced_on_trading_day = trading_days[pos] == announce_date
    if after_hours and announced_on_trading_day:
        pos += 1                                   # market had closed: move one day on
    return pos if pos < len(trading_days) else -1


# ---------------------------------------------------------------------------
# ONE STOCK, ONE EVENT
# ---------------------------------------------------------------------------
def study_one(returns: pd.DataFrame, ticker: str, day0: int) -> dict | None:
    """
    Run the event study for one stock around one event.
    `day0` is the row number of the reaction day in `returns`.
    Returns None when there is not enough data.
    """
    first_needed = min(w[0] for w in WINDOWS.values())
    last_needed = max(w[1] for w in WINDOWS.values())
    if day0 + first_needed < 0 or day0 + last_needed >= len(returns):
        return None

    # --- Step 1: fit the line on the calm period before the event ---------
    est_end = day0 - EST_GAP                       # exclusive
    est_start = est_end - EST_LENGTH
    if est_start < 0:
        est_start = 0
    est = returns.iloc[est_start:est_end][[ticker, MARKET]].dropna()
    if len(est) < MIN_EST_DAYS:
        return None                                # e.g. the company listed too recently

    beta, alpha = np.polyfit(est[MARKET], est[ticker], 1)     # slope, intercept
    leftovers = est[ticker] - (alpha + beta * est[MARKET])     # what the line did not explain
    noise = leftovers.std(ddof=2)                              # normal daily "noise"

    # --- Steps 2 and 3: abnormal return on each day around the event ------
    days = range(first_needed, last_needed + 1)
    window = returns.iloc[day0 + first_needed: day0 + last_needed + 1][[ticker, MARKET]]
    if window.isna().any().any():
        return None
    predicted = alpha + beta * window[MARKET]
    abnormal = (window[ticker] - predicted).to_numpy()
    ar_by_day = dict(zip(days, abnormal))

    # --- Steps 4 and 5: add them up and test against the noise ------------
    result = {"ticker": ticker, "alpha": alpha, "beta": beta, "noise": noise,
              "ar_by_day": ar_by_day}
    for name, (start, end) in WINDOWS.items():
        n_days = end - start + 1
        car = sum(ar_by_day[d] for d in range(start, end + 1))
        # Noise adds up over days: for n days it grows with the square root of n.
        t_stat = car / (noise * np.sqrt(n_days))
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(est) - 2))
        result[name] = car
        result[name + " t"] = t_stat
        result[name + " p"] = p_value
    return result


# ---------------------------------------------------------------------------
# ALL STOCKS, ALL EVENTS
# ---------------------------------------------------------------------------
def run_event_study(prices: pd.DataFrame, events: pd.DataFrame, tickers: pd.DataFrame) -> pd.DataFrame:
    """
    Run the study for every stock around every event.
    Returns one row per (event, stock).

    'role' says how the stock relates to the event:
        direct    - the company RBI acted against
        same_model- a different company with a business model the event concerns
        other     - everyone else (a check: these should barely react)
    """
    returns = daily_returns(prices)
    rows = []
    for _, ev in events.iterrows():
        day0 = reaction_day_position(returns.index, ev["announce_date"], bool(ev["after_hours"]))
        if day0 < 0:
            continue
        for _, tk in tickers.iterrows():
            ticker = tk["ticker"]
            if ticker not in returns.columns:
                continue
            res = study_one(returns, ticker, day0)
            if res is None:
                continue
            if ticker in ev["target_tickers"]:
                role = "direct"
            elif set(tk["models"]) & set(ev["affected_models"]):
                role = "same_model"
            else:
                role = "other"
            res.update({
                "event_id": ev["event_id"], "title": ev["title"],
                "direction": ev["direction"], "reaction_date": returns.index[day0],
                "role": role, "company": tk["company"], "models": tk["models"],
            })
            rows.append(res)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# SUMMARIES
# ---------------------------------------------------------------------------
def summary_by_role(results: pd.DataFrame, window: str = MAIN_WINDOW) -> pd.DataFrame:
    """Average shock by direction (tightening / easing) and role (direct / same model / other)."""
    grouped = results.groupby(["direction", "role"])[window]
    table = grouped.agg(observations="count", average="mean", median="median")
    table["share_negative"] = grouped.apply(lambda s: (s < 0).mean())
    # Is the average different from zero? (one-sample t-test across observations)
    table["p_value"] = grouped.apply(
        lambda s: stats.ttest_1samp(s, 0.0).pvalue if len(s) > 1 else np.nan
    )
    return table.reset_index()


def years_covered(prices: pd.DataFrame) -> float:
    """Length of the price history in years."""
    return (prices.index[-1] - prices.index[0]).days / 365.25


def risk_by_model(results: pd.DataFrame, events: pd.DataFrame, tickers: pd.DataFrame,
                  years: float, window: str = MAIN_WINDOW) -> pd.DataFrame:
    """
    Turn the event study into a regulatory risk measure for each business model.

      shocks_per_year = tightening events that concern this business model / years
      damage_per_shock = average loss in value across those events
                         (a share price RISE counts as zero damage)
      expected_yearly_drag = shocks_per_year x damage_per_shock
      risk_index = drag scaled so the riskiest business model = 100

    Stocks hit directly and their peers are both included: a firm in this
    business model can be either one next time.
    """
    tight = results[results["direction"] == "tightening"]
    all_models = sorted({m for models in tickers["models"] for m in models})
    rows = []
    for model in all_models:
        # events that concern this business model
        event_ids = [e["event_id"] for _, e in events.iterrows()
                     if e["direction"] == "tightening" and model in e["affected_models"]]
        # stocks that belong to this business model, on those events
        mask = tight["event_id"].isin(event_ids) & tight["models"].apply(lambda ms: model in ms)
        sub = tight[mask]
        if sub.empty:
            rows.append({"model": model, "events": 0, "shocks_per_year": 0.0,
                         "damage_per_shock": 0.0, "expected_yearly_drag": 0.0, "observations": 0})
            continue
        # average across stocks within each event first, then across events,
        # so an event with many stocks does not count more than others
        damage_per_event = sub.assign(damage=np.maximum(0.0, -sub[window])) \
                              .groupby("event_id")["damage"].mean()
        n_events = len(damage_per_event)
        shocks_per_year = n_events / years
        damage = float(damage_per_event.mean())
        rows.append({"model": model, "events": n_events, "shocks_per_year": shocks_per_year,
                     "damage_per_shock": damage,
                     "expected_yearly_drag": shocks_per_year * damage,
                     "observations": len(sub)})
    table = pd.DataFrame(rows)
    worst = table["expected_yearly_drag"].max()
    table["risk_index"] = 100 * table["expected_yearly_drag"] / worst if worst > 0 else 0.0
    return table.sort_values("risk_index", ascending=False).reset_index(drop=True)


def damages_for_model(results: pd.DataFrame, events: pd.DataFrame, model: str,
                      window: str = MAIN_WINDOW) -> np.ndarray:
    """
    The list of past damages (one number per tightening event) for one business
    model. Module 3 re-plays these at random to simulate future shocks.
    """
    event_ids = [e["event_id"] for _, e in events.iterrows()
                 if e["direction"] == "tightening" and model in e["affected_models"]]
    mask = (results["direction"] == "tightening") & results["event_id"].isin(event_ids) \
        & results["models"].apply(lambda ms: model in ms)
    sub = results[mask]
    if sub.empty:
        return np.array([])
    return sub.assign(damage=np.maximum(0.0, -sub[window])) \
              .groupby("event_id")["damage"].mean().to_numpy()
