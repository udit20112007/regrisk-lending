"""
MODULE 2 - LENDING PARTNERSHIP ECONOMICS
========================================

The business being modelled
---------------------------
A fintech (for example Paytm) finds borrowers and collects repayments.
A bank or NBFC (the "lender") actually gives the money.

To make the lender comfortable, the fintech can promise to cover the first
slice of losses. RBI calls this a Default Loss Guarantee (DLG).
RBI's rule (8 June 2023): the guarantee cannot be more than 5% of the
amount disbursed, and it must be invoked within 120 days of a missed payment.

This file answers four questions:
  1. For every Rs 100 lent, how much does the fintech earn? How much the lender?
  2. At what default rate does each side stop making money? (break-even)
  3. Which guarantee level lets the deal survive the highest default rate?
  4. What is the whole partnership worth today? (NPV)

Everything is calculated "per Rs 1 disbursed", so 0.03 means 3% of the loan
amount. All rates are written as decimals: 0.24 means 24% a year.
"""

from dataclasses import dataclass, replace

import numpy as np


# ---------------------------------------------------------------------------
# 1. THE INPUTS
# ---------------------------------------------------------------------------
@dataclass
class DealInputs:
    """Every assumption of the deal lives here, so it is easy to change one."""

    # --- The loan product ---
    apr: float = 0.24              # interest rate charged to the borrower, per year
    tenor_months: int = 12         # loan length in months
    processing_fee: float = 0.02   # one-time fee paid by borrower, kept by the lender

    # --- Credit quality ---
    default_rate: float = 0.045    # share of loans that stop paying at some point
    lgd: float = 0.90              # "loss given default": share of the unpaid
                                   # balance that is never recovered
    dlg_lag_months: int = 4        # guarantee is invoked 120 days after the miss

    # --- The lender (bank / NBFC) ---
    cost_of_funds: float = 0.10            # what the lender pays for its money, per year
    lender_opex: float = 0.02              # lender running costs, per year, on the balance
    lender_hurdle_roa: float = 0.04        # minimum return on assets the lender accepts
    lender_cost_of_equity: float = 0.15    # cost of the lender's own capital, per year
    stress_multiple: float = 2.0           # lender plans for losses this many times normal
    dlg_counts_for_provisioning: bool = True
    # ^ May 2025: RBI told NBFCs to ignore the guarantee when setting aside
    #   loss buffers. 13 Feb 2026: RBI allowed it again. This switch models that.

    # --- The fintech ---
    sourcing_fee: float = 0.045        # paid by lender per loan sourced (share of loan)
    servicing_fee: float = 0.030       # paid by lender per year on the performing balance
    acquisition_cost: float = 0.015    # fintech's cost to find and onboard the borrower
    collection_cost: float = 0.005     # fintech's yearly cost of collecting repayments
    fintech_cost_of_capital: float = 0.18  # return the fintech's investors expect
    fd_rate: float = 0.065             # interest earned on the guarantee deposit
    fintech_min_margin: float = 0.0    # minimum profit the fintech accepts per Rs 1 lent

    # --- The guarantee ---
    dlg_pct: float = 0.05   # guarantee offered, as a share of the amount disbursed
    dlg_cap: float = 0.05   # RBI's ceiling on the guarantee

    @property
    def effective_dlg(self) -> float:
        """The guarantee actually in force: never more than the RBI cap."""
        return max(0.0, min(self.dlg_pct, self.dlg_cap))


# ---------------------------------------------------------------------------
# 2. THE LOAN SCHEDULE
# ---------------------------------------------------------------------------
def loan_balances(apr: float, tenor_months: int) -> np.ndarray:
    """
    Balance still owed on a Rs 1 loan after each monthly instalment (EMI).

    Returns an array of length tenor_months + 1:
        position 0 = 1.0 (nothing repaid yet)
        last position = 0.0 (fully repaid)
    """
    r = apr / 12.0  # monthly interest rate
    n = tenor_months

    # Standard EMI formula. If the rate is zero, just split the loan evenly.
    emi = 1.0 / n if r == 0 else r / (1.0 - (1.0 + r) ** (-n))

    balances = np.zeros(n + 1)
    balances[0] = 1.0
    for month in range(1, n + 1):
        interest = balances[month - 1] * r
        principal_repaid = emi - interest
        balances[month] = balances[month - 1] - principal_repaid

    balances[-1] = 0.0  # remove tiny rounding leftovers
    return balances


# ---------------------------------------------------------------------------
# 3. ONE BATCH OF LOANS ("COHORT"), PER RS 1 DISBURSED
# ---------------------------------------------------------------------------
def cohort_economics(inp: DealInputs) -> dict:
    """
    Follow Rs 1 of loans from the day it is lent until the last rupee is settled.

    Returns a dictionary with:
      - 'fintech' : profit breakdown for the fintech
      - 'lender'  : profit breakdown for the lender
      - 'fintech_cashflows' : month-by-month cash for the fintech (used for NPV)
      - 'net_credit_loss'   : total loss as a share of the amount disbursed
    """
    n = inp.tenor_months
    lag = inp.dlg_lag_months
    r = inp.apr / 12.0
    months = n + lag + 1                      # month 0 ... month n + lag
    bal = loan_balances(inp.apr, n)           # balance per Rs 1 of a healthy loan

    # --- Who is still paying? -------------------------------------------
    # Simple assumption: defaults are spread evenly over the life of the loan.
    # So each month, (default_rate / n) of the original loans stop paying.
    defaults_per_month = inp.default_rate / n
    # share of loans still paying their instalment in month t (t = 1..n)
    paying_share = np.array([1.0 - defaults_per_month * t for t in range(0, n + 1)])

    # --- Month-by-month series (index = month number) --------------------
    interest_income = np.zeros(months)   # interest collected by the lender
    performing_bal = np.zeros(months)    # balance of healthy loans at the START of month t
    defaulted_amt = np.zeros(months)     # balance that goes bad in month t
    loss = np.zeros(months)              # loss booked (after the 120-day wait)
    stuck_bal = np.zeros(months)         # bad loans still on the books, waiting to be settled

    for t in range(1, n + 1):
        performing_bal[t] = paying_share[t] * bal[t - 1]
        interest_income[t] = performing_bal[t] * r
        defaulted_amt[t] = defaults_per_month * bal[t - 1]
        loss[t + lag] = defaulted_amt[t] * inp.lgd
        # the lender keeps funding a bad loan until it is settled `lag` months later
        stuck_bal[t: t + lag] += defaulted_amt[t]

    total_loss = loss.sum()

    # --- The guarantee pool ---------------------------------------------
    # The fintech deposits the guarantee on day 0. Each loss eats into it.
    # Once it is used up it is NOT refilled.
    g = inp.effective_dlg
    cover_left = np.zeros(months)        # deposit remaining at the START of month t
    dlg_payout = np.zeros(months)        # what the fintech pays the lender in month t
    remaining = g
    for t in range(months):
        cover_left[t] = remaining
        pay = min(loss[t], remaining)
        dlg_payout[t] = pay
        remaining -= pay
    deposit_returned = remaining          # whatever is left comes back at the end
    total_dlg_paid = dlg_payout.sum()

    # --- FINTECH --------------------------------------------------------
    servicing_income = performing_bal * inp.servicing_fee / 12.0
    collection_costs = performing_bal * inp.collection_cost / 12.0
    fd_interest = cover_left * inp.fd_rate / 12.0     # deposit earns bank interest
    fd_interest[0] = 0.0                              # deposited at the end of day 0

    # Cash in and out for the fintech, month by month
    f_cash = servicing_income - collection_costs + fd_interest
    f_cash[0] += inp.sourcing_fee - inp.acquisition_cost - g   # deposit goes out
    f_cash[-1] += deposit_returned                             # leftover comes back

    # The deposit is locked money. Investors expect `fintech_cost_of_capital`
    # on it, so we charge that as a cost.
    capital_charge = (cover_left[1:] * inp.fintech_cost_of_capital / 12.0).sum()

    fintech = {
        "sourcing_fee": inp.sourcing_fee,
        "servicing_fee": servicing_income.sum(),
        "acquisition_cost": -inp.acquisition_cost,
        "collection_cost": -collection_costs.sum(),
        "guarantee_paid": -total_dlg_paid,
        "deposit_interest": fd_interest.sum(),
        "capital_charge": -capital_charge,
    }
    fintech["profit"] = sum(fintech.values())

    # --- LENDER ---------------------------------------------------------
    funded_bal = performing_bal + stuck_bal           # everything the lender is funding
    funding_cost = (funded_bal * inp.cost_of_funds / 12.0).sum()
    opex = (performing_bal * inp.lender_opex / 12.0).sum()

    # Safety buffer: the lender plans for losses `stress_multiple` times normal.
    # The guarantee reduces the buffer only if RBI lets the lender count it.
    counted_cover = g if inp.dlg_counts_for_provisioning else 0.0
    buffer_needed = max(0.0, inp.stress_multiple * total_loss - counted_cover)
    asset_years = performing_bal.sum() / 12.0         # "rupee-years" of loans outstanding
    buffer_cost = buffer_needed * inp.lender_cost_of_equity * asset_years

    lender = {
        "interest_income": interest_income.sum(),
        "processing_fee": inp.processing_fee,
        "funding_cost": -funding_cost,
        "opex": -opex,
        "sourcing_fee_paid": -inp.sourcing_fee,
        "servicing_fee_paid": -servicing_income.sum(),
        "credit_loss": -total_loss,
        "guarantee_received": total_dlg_paid,
        "buffer_cost": -buffer_cost,
    }
    lender["profit"] = sum(lender.values())
    # Return on assets: yearly profit per rupee of loans outstanding
    lender_roa = lender["profit"] / asset_years if asset_years > 0 else 0.0

    return {
        "fintech": fintech,
        "lender": lender,
        "lender_roa": lender_roa,
        "net_credit_loss": total_loss,
        "guarantee_used": total_dlg_paid,
        "effective_dlg": g,
        "asset_years": asset_years,
        "fintech_cashflows": f_cash,
    }


# ---------------------------------------------------------------------------
# 4. BREAK-EVEN DEFAULT RATES
# ---------------------------------------------------------------------------
MAX_DEFAULT_RATE = 0.60   # we never search beyond a 60% default rate


def _highest_default_rate_where(condition, inp: DealInputs) -> float:
    """
    Find the highest default rate at which `condition(result)` is still True.

    Uses bisection: keep halving the search range. It works because profits
    only get worse as the default rate goes up.
    """
    def ok(rate: float) -> bool:
        return condition(cohort_economics(replace(inp, default_rate=rate)))

    if not ok(0.0):
        return 0.0                 # loses money even with zero defaults
    if ok(MAX_DEFAULT_RATE):
        return MAX_DEFAULT_RATE    # never breaks within the search range

    low, high = 0.0, MAX_DEFAULT_RATE
    for _ in range(40):            # 40 halvings is far more precision than needed
        mid = (low + high) / 2.0
        if ok(mid):
            low = mid
        else:
            high = mid
    return low


def fintech_breakeven(inp: DealInputs) -> float:
    """Highest default rate at which the fintech still earns its minimum margin."""
    return _highest_default_rate_where(
        lambda res: res["fintech"]["profit"] >= inp.fintech_min_margin, inp
    )


def lender_breakeven(inp: DealInputs) -> float:
    """Highest default rate at which the lender still earns its hurdle return."""
    return _highest_default_rate_where(
        lambda res: res["lender_roa"] >= inp.lender_hurdle_roa, inp
    )


def deal_capacity(inp: DealInputs) -> float:
    """
    Highest default rate at which BOTH sides are still happy.
    A deal needs both, so it is the lower of the two break-evens.
    """
    return min(fintech_breakeven(inp), lender_breakeven(inp))


def capacity_curve(inp: DealInputs, max_dlg: float = 0.10, steps: int = 41) -> dict:
    """
    Deal capacity for a range of guarantee levels (ignoring the cap, so we can
    also see what would happen above it).
    """
    levels = np.linspace(0.0, max_dlg, steps)
    fintech_be, lender_be = [], []
    for level in levels:
        trial = replace(inp, dlg_pct=level, dlg_cap=1.0)   # cap switched off
        fintech_be.append(fintech_breakeven(trial))
        lender_be.append(lender_breakeven(trial))
    fintech_be, lender_be = np.array(fintech_be), np.array(lender_be)
    return {
        "dlg": levels,
        "fintech_breakeven": fintech_be,
        "lender_breakeven": lender_be,
        "capacity": np.minimum(fintech_be, lender_be),
    }


def best_dlg(inp: DealInputs, respect_cap: bool = True, curve: dict | None = None) -> tuple:
    """
    The guarantee level that lets the deal survive the highest default rate.
    Returns (best guarantee level, deal capacity at that level).

    Pass in a `curve` you already calculated to avoid working it out again.
    """
    if curve is None:
        curve = capacity_curve(inp)
    allowed = curve["dlg"] <= inp.dlg_cap + 1e-12 if respect_cap else np.ones_like(curve["dlg"], bool)
    capacity = np.where(allowed, curve["capacity"], -1.0)
    i = int(np.argmax(capacity))
    return float(curve["dlg"][i]), float(capacity[i])


def viability_grid(inp: DealInputs, dlg_levels, default_rates) -> np.ndarray:
    """
    For every (guarantee, default rate) pair, who is happy?
        3 = both sides   2 = only the lender   1 = only the fintech   0 = nobody
    Rows = default rates, columns = guarantee levels.
    """
    grid = np.zeros((len(default_rates), len(dlg_levels)), dtype=int)
    for j, level in enumerate(dlg_levels):
        for i, rate in enumerate(default_rates):
            res = cohort_economics(replace(inp, dlg_pct=level, dlg_cap=1.0, default_rate=rate))
            fintech_ok = res["fintech"]["profit"] >= inp.fintech_min_margin
            lender_ok = res["lender_roa"] >= inp.lender_hurdle_roa
            grid[i, j] = (2 if lender_ok else 0) + (1 if fintech_ok else 0)
    return grid


# ---------------------------------------------------------------------------
# 5. REPRICING: WHAT FEE CAN THE LENDER STILL AFFORD?
# ---------------------------------------------------------------------------
def repriced_sourcing_fee(inp: DealInputs) -> float:
    """
    If a rule change pushes the lender below its hurdle return, the lender will
    pay the fintech less. This finds the sourcing fee that puts the lender back
    exactly on its hurdle. The fee is only ever cut, never raised.
    """
    res = cohort_economics(inp)
    if res["lender_roa"] >= inp.lender_hurdle_roa:
        return inp.sourcing_fee          # lender is fine, no change

    # Each Rs 1 of fee cut is Rs 1 of extra lender profit, so this is simple algebra.
    shortfall = (inp.lender_hurdle_roa - res["lender_roa"]) * res["asset_years"]
    return inp.sourcing_fee - shortfall  # can go negative: the deal is then dead


# ---------------------------------------------------------------------------
# 6. THE WHOLE PARTNERSHIP OVER TIME
# ---------------------------------------------------------------------------
def monthly_volumes(start_volume: float, months: int, monthly_growth: float = 0.0) -> np.ndarray:
    """Loans disbursed each month (in Rs crore), growing at a steady rate."""
    return start_volume * (1.0 + monthly_growth) ** np.arange(months)


def partnership_cashflows(inp: DealInputs, volumes: np.ndarray) -> np.ndarray:
    """
    Fintech cash flow for the whole partnership.

    Each month a new batch of loans is disbursed. Every batch produces the same
    pattern of cash (from cohort_economics), just scaled by its size and shifted
    in time. Adding all the batches together gives the total.
    """
    pattern = cohort_economics(inp)["fintech_cashflows"]
    total = np.zeros(len(volumes) + len(pattern) - 1)
    for month, volume in enumerate(volumes):
        total[month: month + len(pattern)] += volume * pattern
    return total


def npv(cashflows: np.ndarray, annual_rate: float) -> float:
    """Value today of a stream of monthly cash flows."""
    monthly_rate = (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0
    discount = (1.0 + monthly_rate) ** -np.arange(len(cashflows))
    return float((cashflows * discount).sum())


def partnership_npv(inp: DealInputs, volumes: np.ndarray) -> float:
    """Value today of the partnership to the fintech (in Rs crore)."""
    return npv(partnership_cashflows(inp, volumes), inp.fintech_cost_of_capital)
