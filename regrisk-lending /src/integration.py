"""
MODULE 3 - PUTTING THE TWO TOGETHER
===================================

Module 1 (event study) tells us two things about a business model:
    - how OFTEN RBI shocks hit it            -> shocks per year
    - how much DAMAGE a shock does           -> share of value lost per shock

Module 2 (lending model) tells us what a lending partnership is worth if
nothing goes wrong.

This module joins them. It answers:
    "What is the partnership worth once we allow for regulatory shocks?"

The link between the two (the key assumption, be ready to defend it):
    When a shock hits, the share price falls by X%. We read that as the market
    saying "future business is X% smaller". So in our model each shock cuts
    all FUTURE loan volume by X%. Loans already given are not affected.

Three tools are provided:
    1. risk_adjusted_npv  - one number, using the average shock
    2. simulate_npv       - thousands of possible futures, re-playing real past shocks
    3. scenario_table     - specific "what if RBI does this" rule changes
"""

from dataclasses import replace

import numpy as np
import pandas as pd

from . import event_study as es
from . import lending_model as lm


# ---------------------------------------------------------------------------
# FROM EVENT STUDY TO MODEL INPUTS
# ---------------------------------------------------------------------------
def calibrate(results: pd.DataFrame, events: pd.DataFrame, years: float,
              model: str = "lending_distribution") -> dict:
    """
    Read shock frequency and shock size for one business model from the
    event study results.
    """
    damages = es.damages_for_model(results, events, model)
    shocks_per_year = len(damages) / years if years > 0 else 0.0
    average_damage = float(damages.mean()) if len(damages) else 0.0
    return {
        "model": model,
        "shocks_per_year": shocks_per_year,
        "average_damage": average_damage,
        "damages": damages,                       # the individual past shocks
        # Each year, this share of future business is expected to be lost.
        # It works like an extra discount rate for regulatory risk.
        "regulatory_premium": shocks_per_year * average_damage,
    }


# ---------------------------------------------------------------------------
# TOOL 1: ONE RISK-ADJUSTED NUMBER
# ---------------------------------------------------------------------------
def expected_volumes(volumes: np.ndarray, shocks_per_year: float, average_cut: float) -> np.ndarray:
    """
    Loan volume we should EXPECT each month once shocks are allowed for.

    If shocks arrive at random (a Poisson process) and each one cuts future
    volume by `average_cut`, the expected volume in month t is

        planned volume x exp(-shocks_per_year x average_cut x t / 12)

    In words: the business shrinks a little, on average, every month.
    """
    months = np.arange(len(volumes))
    return volumes * np.exp(-shocks_per_year * average_cut * months / 12.0)


def risk_adjusted_npv(inp: lm.DealInputs, volumes: np.ndarray, shocks_per_year: float,
                      average_damage: float, pass_through: float = 1.0) -> float:
    """
    Partnership value to the fintech after allowing for regulatory shocks.

    pass_through: how much of the share-price damage shows up as lost lending
    volume. 1.0 = the same percentage. Above 1 = lending is hit harder than
    the company as a whole.
    """
    cut = min(1.0, average_damage * pass_through)
    return lm.partnership_npv(inp, expected_volumes(volumes, shocks_per_year, cut))


# ---------------------------------------------------------------------------
# TOOL 2: THOUSANDS OF POSSIBLE FUTURES (MONTE CARLO)
# ---------------------------------------------------------------------------
def value_per_rupee_by_month(inp: lm.DealInputs, months: int) -> np.ndarray:
    """
    Value today of Rs 1 of loans disbursed in each future month.
    Lets us value any volume path with one multiplication.
    """
    pattern = lm.cohort_economics(inp)["fintech_cashflows"]
    value_at_disbursal = lm.npv(pattern, inp.fintech_cost_of_capital)
    monthly_rate = (1.0 + inp.fintech_cost_of_capital) ** (1.0 / 12.0) - 1.0
    return value_at_disbursal * (1.0 + monthly_rate) ** -np.arange(months)


def simulate_npv(inp: lm.DealInputs, volumes: np.ndarray, shocks_per_year: float,
                 damages: np.ndarray, pass_through: float = 1.0,
                 n_sims: int = 5000, seed: int = 1) -> np.ndarray:
    """
    Simulate many possible futures and return the partnership value in each.

    In each future, for every month:
      - roll the dice: does a shock arrive? (chance = shocks_per_year / 12)
      - if yes, pick one of the PAST shocks at random and cut all future
        volume by that much
    """
    months = len(volumes)
    value_weights = value_per_rupee_by_month(inp, months)
    if len(damages) == 0 or shocks_per_year <= 0:
        return np.full(n_sims, float((volumes * value_weights).sum()))

    rng = np.random.default_rng(seed)
    results = np.zeros(n_sims)
    for s in range(n_sims):
        shocks_each_month = rng.poisson(shocks_per_year / 12.0, months)
        shocks_each_month[0] = 0                     # month 0 has already happened
        scale = 1.0                                  # share of planned volume still alive
        total = 0.0
        for t in range(months):
            for _ in range(shocks_each_month[t]):
                cut = min(1.0, rng.choice(damages) * pass_through)
                scale *= (1.0 - cut)
            total += volumes[t] * scale * value_weights[t]
        results[s] = total
    return results


def summarise_simulation(npvs: np.ndarray) -> dict:
    """The few numbers a decision-maker needs from the simulation."""
    return {
        "average": float(npvs.mean()),
        "median": float(np.median(npvs)),
        "worst_5_percent": float(np.percentile(npvs, 5)),   # 1-in-20 bad outcome
        "chance_of_loss": float((npvs < 0).mean()),
    }


# ---------------------------------------------------------------------------
# TOOL 3: SPECIFIC RULE-CHANGE SCENARIOS
# ---------------------------------------------------------------------------
def scenario_table(inp: lm.DealInputs, volumes: np.ndarray,
                   freeze_start: int = 12, freeze_months: int = 6) -> pd.DataFrame:
    """
    What happens to the deal under specific rule changes?

    For each scenario:
      1. apply the rule change
      2. check the lender's return; if it falls below the lender's minimum,
         the lender cuts the fintech's sourcing fee until it is back at the minimum
      3. re-value the partnership for the fintech
    """
    freeze_volumes = volumes.copy()
    freeze_volumes[freeze_start: freeze_start + freeze_months] = 0.0

    scenarios = [
        ("Today's rules (5% cap, guarantee counts)", inp, volumes),
        ("Guarantee ignored in lender loss buffers (May 2025 rule)",
         replace(inp, dlg_counts_for_provisioning=False), volumes),
        ("Guarantee cap cut to 2.5%", replace(inp, dlg_cap=0.025), volumes),
        ("Guarantees banned", replace(inp, dlg_cap=0.0), volumes),
        (f"Lending frozen for {freeze_months} months", inp, freeze_volumes),
    ]

    base_npv = None
    rows = []
    for name, scenario_inp, scenario_volumes in scenarios:
        before = lm.cohort_economics(scenario_inp)
        new_fee = lm.repriced_sourcing_fee(scenario_inp)
        after_inp = replace(scenario_inp, sourcing_fee=new_fee)
        after = lm.cohort_economics(after_inp)
        value = lm.partnership_npv(after_inp, scenario_volumes)
        if base_npv is None:
            base_npv = value
        rows.append({
            "scenario": name,
            "lender_roa_before_repricing": before["lender_roa"],
            "sourcing_fee_after": new_fee,
            "fintech_profit_per_100": after["fintech"]["profit"] * 100,
            "max_default_rate": lm.deal_capacity(scenario_inp),
            "fintech_npv": value,
            "npv_change": value / base_npv - 1.0 if base_npv else np.nan,
        })
    return pd.DataFrame(rows)
