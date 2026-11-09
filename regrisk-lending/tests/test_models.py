"""
TESTS - do the calculations behave the way finance says they should?

Run with:   python -m pytest -q
Each test checks one fact that must always be true. If you change the model
and a test fails, you have probably broken something.
"""

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import event_study as es          # noqa: E402
from src import integration as ig          # noqa: E402
from src import lending_model as lm        # noqa: E402


# ---------------- lending model ----------------
def test_loan_is_fully_repaid():
    balances = lm.loan_balances(0.24, 12)
    assert balances[0] == 1.0
    assert balances[-1] == 0.0
    assert all(np.diff(balances) < 0)            # balance falls every month


def test_emi_matches_textbook_formula():
    # Rs 1 at 24% for 12 months: EMI = r / (1 - (1+r)^-n) = 0.09456
    balances = lm.loan_balances(0.24, 12)
    first_principal = balances[0] - balances[1]
    emi = first_principal + 0.02                 # interest in month 1 is 2% of Rs 1
    assert abs(emi - 0.0945596) < 1e-6


def test_no_defaults_means_no_guarantee_paid():
    res = lm.cohort_economics(replace(lm.DealInputs(), default_rate=0.0))
    assert res["net_credit_loss"] == 0.0
    assert res["guarantee_used"] == 0.0


def test_guarantee_never_exceeds_cover_or_cap():
    inp = replace(lm.DealInputs(), default_rate=0.30, dlg_pct=0.08, dlg_cap=0.05)
    res = lm.cohort_economics(inp)
    assert res["effective_dlg"] == 0.05                       # cap applies
    assert abs(res["guarantee_used"] - 0.05) < 1e-12          # fully used, not more
    assert res["net_credit_loss"] > 0.05


def test_guarantee_is_a_pure_transfer():
    # what the fintech pays is exactly what the lender receives
    res = lm.cohort_economics(lm.DealInputs())
    assert abs(res["fintech"]["guarantee_paid"] + res["lender"]["guarantee_received"]) < 1e-12


def test_fintech_cashflows_add_up_to_profit_before_capital_charge():
    res = lm.cohort_economics(lm.DealInputs())
    f = res["fintech"]
    assert abs(res["fintech_cashflows"].sum() - (f["profit"] - f["capital_charge"])) < 1e-12


def test_more_defaults_never_help_anyone():
    low = lm.cohort_economics(replace(lm.DealInputs(), default_rate=0.03))
    high = lm.cohort_economics(replace(lm.DealInputs(), default_rate=0.09))
    assert high["fintech"]["profit"] <= low["fintech"]["profit"]
    assert high["lender_roa"] <= low["lender_roa"]


def test_breakeven_is_where_profit_hits_the_target():
    inp = lm.DealInputs()
    rate = lm.lender_breakeven(inp)
    roa = lm.cohort_economics(replace(inp, default_rate=rate))["lender_roa"]
    assert abs(roa - inp.lender_hurdle_roa) < 1e-6
    rate = lm.fintech_breakeven(inp)
    profit = lm.cohort_economics(replace(inp, default_rate=rate))["fintech"]["profit"]
    assert abs(profit - inp.fintech_min_margin) < 1e-6


def test_ignoring_guarantee_in_buffers_hurts_the_lender():
    counted = lm.cohort_economics(lm.DealInputs())["lender_roa"]
    ignored = lm.cohort_economics(replace(lm.DealInputs(), dlg_counts_for_provisioning=False))["lender_roa"]
    assert ignored < counted


def test_repricing_puts_lender_back_on_hurdle():
    inp = replace(lm.DealInputs(), dlg_cap=0.0)               # guarantees banned
    fee = lm.repriced_sourcing_fee(inp)
    assert fee < inp.sourcing_fee
    roa = lm.cohort_economics(replace(inp, sourcing_fee=fee))["lender_roa"]
    assert abs(roa - inp.lender_hurdle_roa) < 1e-9


def test_npv_of_cash_today_is_itself():
    assert lm.npv(np.array([5.0]), 0.18) == 5.0
    # Rs 118 in exactly 12 months at 18% is worth Rs 100 today
    cash = np.zeros(13)
    cash[12] = 118.0
    assert abs(lm.npv(cash, 0.18) - 100.0) < 1e-9


def test_partnership_npv_scales_with_volume():
    inp = lm.DealInputs()
    small = lm.partnership_npv(inp, lm.monthly_volumes(100, 24))
    big = lm.partnership_npv(inp, lm.monthly_volumes(200, 24))
    assert abs(big - 2 * small) < 1e-9


# ---------------- event study ----------------
def _fake_prices(shock: float, n: int = 300, event_pos: int = 200, seed: int = 0):
    """A stock with beta 1.2 and a planted shock on one known day."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2023-01-02", periods=n)
    market = rng.normal(0.0005, 0.01, n)
    stock = 1.2 * market + rng.normal(0, 0.002, n)
    stock[event_pos] += shock
    prices = pd.DataFrame({"NIFTY": 100 * np.exp(np.cumsum(market)),
                           "TEST": 100 * np.exp(np.cumsum(stock))}, index=days)
    return prices, days[event_pos]


def test_event_study_recovers_a_planted_shock():
    prices, event_day = _fake_prices(shock=-0.10)
    returns = es.daily_returns(prices)
    day0 = returns.index.get_loc(event_day)
    res = es.study_one(returns, "TEST", day0)
    assert abs(res["beta"] - 1.2) < 0.05                      # finds the true beta
    assert abs(res["CAR(0,0)"] - (-0.10)) < 0.01              # finds the planted -10%
    assert res["CAR(0,0) p"] < 0.01                           # and calls it significant


def test_event_study_finds_nothing_when_nothing_happened():
    prices, event_day = _fake_prices(shock=0.0)
    returns = es.daily_returns(prices)
    res = es.study_one(returns, "TEST", returns.index.get_loc(event_day))
    assert abs(res["CAR(0,0)"]) < 0.01


def test_after_hours_news_moves_to_next_trading_day():
    days = pd.bdate_range("2024-01-29", "2024-02-09")         # Mon 29 Jan onwards
    wed = pd.Timestamp("2024-01-31")
    assert days[es.reaction_day_position(days, wed, after_hours=False)] == wed
    assert days[es.reaction_day_position(days, wed, after_hours=True)] == pd.Timestamp("2024-02-01")
    # news on a Saturday -> Monday, whether or not it was "after hours"
    sat = pd.Timestamp("2024-02-03")
    assert days[es.reaction_day_position(days, sat, after_hours=True)] == pd.Timestamp("2024-02-05")
    # an event after our data ends cannot be studied
    assert es.reaction_day_position(days, pd.Timestamp("2025-01-01"), False) == -1


def test_too_little_history_is_skipped():
    prices, _ = _fake_prices(shock=0.0)
    returns = es.daily_returns(prices)
    assert es.study_one(returns, "TEST", 20) is None


# ---------------- integration ----------------
def test_no_regulatory_risk_means_no_adjustment():
    inp, vol = lm.DealInputs(), lm.monthly_volumes(100, 36, 0.02)
    base = lm.partnership_npv(inp, vol)
    assert abs(ig.risk_adjusted_npv(inp, vol, 0.0, 0.05) - base) < 1e-9
    assert abs(ig.risk_adjusted_npv(inp, vol, 1.5, 0.0) - base) < 1e-9


def test_more_regulatory_risk_lowers_value():
    inp, vol = lm.DealInputs(), lm.monthly_volumes(100, 36, 0.02)
    mild = ig.risk_adjusted_npv(inp, vol, 0.5, 0.05)
    harsh = ig.risk_adjusted_npv(inp, vol, 2.0, 0.05)
    assert harsh < mild < lm.partnership_npv(inp, vol)


def test_simulation_average_matches_the_formula():
    inp, vol = lm.DealInputs(), lm.monthly_volumes(100, 36, 0.02)
    damages = np.array([0.02, 0.05, 0.11])
    formula = ig.risk_adjusted_npv(inp, vol, 1.2, damages.mean())
    sims = ig.simulate_npv(inp, vol, 1.2, damages, n_sims=20000, seed=3)
    assert abs(sims.mean() - formula) / abs(formula) < 0.01   # within 1%


def test_scenario_table_base_row_is_unchanged():
    inp, vol = lm.DealInputs(), lm.monthly_volumes(100, 36, 0.02)
    table = ig.scenario_table(inp, vol)
    assert table.loc[0, "npv_change"] == 0.0
    assert abs(table.loc[0, "fintech_npv"] - lm.partnership_npv(inp, vol)) < 1e-9
    # a freeze removes six months of profitable lending, so value must fall
    assert table.iloc[-1]["npv_change"] < 0
