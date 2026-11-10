/*
 * THE MODEL, IN JAVASCRIPT
 * ========================
 *
 * This file is a line-by-line copy of the Python model in
 *     src/lending_model.py   and   src/integration.py
 * so that the website can recalculate instantly when a slider moves.
 *
 * Python is the original. An automated test (tests/test_js_parity.py) runs
 * both and fails if their answers differ, so the two cannot drift apart.
 *
 * Input names match the Python `DealInputs` exactly (default_rate, dlg_pct...).
 */
(function (root) {
  "use strict";

  const MAX_DEFAULT_RATE = 0.6;

  function effectiveDlg(inp) {
    return Math.max(0, Math.min(inp.dlg_pct, inp.dlg_cap));
  }

  // Balance still owed on a Rs 1 loan after each monthly instalment.
  function loanBalances(apr, tenorMonths) {
    const r = apr / 12;
    const n = tenorMonths;
    const emi = r === 0 ? 1 / n : r / (1 - Math.pow(1 + r, -n));
    const bal = new Array(n + 1).fill(0);
    bal[0] = 1;
    for (let m = 1; m <= n; m++) {
      bal[m] = bal[m - 1] - (emi - bal[m - 1] * r);
    }
    bal[n] = 0;
    return bal;
  }

  const sum = (a) => a.reduce((s, v) => s + v, 0);

  // Follow Rs 1 of loans from disbursal until the last rupee is settled.
  function cohortEconomics(inp) {
    const n = inp.tenor_months;
    const lag = inp.dlg_lag_months;
    const r = inp.apr / 12;
    const months = n + lag + 1;
    const bal = loanBalances(inp.apr, n);
    const defaultsPerMonth = inp.default_rate / n;

    const interestIncome = new Array(months).fill(0);
    const performingBal = new Array(months).fill(0);
    const defaultedAmt = new Array(months).fill(0);
    const loss = new Array(months).fill(0);
    const stuckBal = new Array(months).fill(0);

    for (let t = 1; t <= n; t++) {
      const payingShare = 1 - defaultsPerMonth * t;
      performingBal[t] = payingShare * bal[t - 1];
      interestIncome[t] = performingBal[t] * r;
      defaultedAmt[t] = defaultsPerMonth * bal[t - 1];
      loss[t + lag] = defaultedAmt[t] * inp.lgd;
      for (let k = t; k < t + lag; k++) stuckBal[k] += defaultedAmt[t];
    }
    const totalLoss = sum(loss);

    // The guarantee pool: paid in on day 0, used up by losses, never refilled.
    const g = effectiveDlg(inp);
    const coverLeft = new Array(months).fill(0);
    const dlgPayout = new Array(months).fill(0);
    let remaining = g;
    for (let t = 0; t < months; t++) {
      coverLeft[t] = remaining;
      const pay = Math.min(loss[t], remaining);
      dlgPayout[t] = pay;
      remaining -= pay;
    }
    const depositReturned = remaining;
    const totalDlgPaid = sum(dlgPayout);

    // Fintech
    const servicingIncome = performingBal.map((b) => (b * inp.servicing_fee) / 12);
    const collectionCosts = performingBal.map((b) => (b * inp.collection_cost) / 12);
    const fdInterest = coverLeft.map((c) => (c * inp.fd_rate) / 12);
    fdInterest[0] = 0;

    const fCash = servicingIncome.map((v, t) => v - collectionCosts[t] + fdInterest[t]);
    fCash[0] += inp.sourcing_fee - inp.acquisition_cost - g;
    fCash[months - 1] += depositReturned;

    let capitalCharge = 0;
    for (let t = 1; t < months; t++) capitalCharge += (coverLeft[t] * inp.fintech_cost_of_capital) / 12;

    const fintech = {
      sourcing_fee: inp.sourcing_fee,
      servicing_fee: sum(servicingIncome),
      acquisition_cost: -inp.acquisition_cost,
      collection_cost: -sum(collectionCosts),
      guarantee_paid: -totalDlgPaid,
      deposit_interest: sum(fdInterest),
      capital_charge: -capitalCharge,
    };
    fintech.profit = sum(Object.values(fintech));

    // Lender
    let fundingCost = 0;
    for (let t = 0; t < months; t++) fundingCost += ((performingBal[t] + stuckBal[t]) * inp.cost_of_funds) / 12;
    const opex = sum(performingBal.map((b) => (b * inp.lender_opex) / 12));
    const countedCover = inp.dlg_counts_for_provisioning ? g : 0;
    const bufferNeeded = Math.max(0, inp.stress_multiple * totalLoss - countedCover);
    const assetYears = sum(performingBal) / 12;
    const bufferCost = bufferNeeded * inp.lender_cost_of_equity * assetYears;

    const lender = {
      interest_income: sum(interestIncome),
      processing_fee: inp.processing_fee,
      funding_cost: -fundingCost,
      opex: -opex,
      sourcing_fee_paid: -inp.sourcing_fee,
      servicing_fee_paid: -sum(servicingIncome),
      credit_loss: -totalLoss,
      guarantee_received: totalDlgPaid,
      buffer_cost: -bufferCost,
    };
    lender.profit = sum(Object.values(lender));

    return {
      fintech,
      lender,
      lender_roa: assetYears > 0 ? lender.profit / assetYears : 0,
      net_credit_loss: totalLoss,
      guarantee_used: totalDlgPaid,
      effective_dlg: g,
      asset_years: assetYears,
      fintech_cashflows: fCash,
    };
  }

  // Highest default rate at which `condition` still holds (bisection).
  function highestDefaultRateWhere(condition, inp) {
    const ok = (rate) => condition(cohortEconomics(Object.assign({}, inp, { default_rate: rate })));
    if (!ok(0)) return 0;
    if (ok(MAX_DEFAULT_RATE)) return MAX_DEFAULT_RATE;
    let low = 0;
    let high = MAX_DEFAULT_RATE;
    for (let i = 0; i < 40; i++) {
      const mid = (low + high) / 2;
      if (ok(mid)) low = mid;
      else high = mid;
    }
    return low;
  }

  const fintechBreakeven = (inp) =>
    highestDefaultRateWhere((res) => res.fintech.profit >= inp.fintech_min_margin, inp);
  const lenderBreakeven = (inp) =>
    highestDefaultRateWhere((res) => res.lender_roa >= inp.lender_hurdle_roa, inp);
  const dealCapacity = (inp) => Math.min(fintechBreakeven(inp), lenderBreakeven(inp));

  // Deal capacity for a range of guarantee levels, with the cap switched off.
  function capacityCurve(inp, maxDlg = 0.1, steps = 41) {
    const dlg = [];
    const fintech = [];
    const lender = [];
    const capacity = [];
    for (let i = 0; i < steps; i++) {
      const level = (maxDlg * i) / (steps - 1);
      const trial = Object.assign({}, inp, { dlg_pct: level, dlg_cap: 1 });
      const f = fintechBreakeven(trial);
      const l = lenderBreakeven(trial);
      dlg.push(level);
      fintech.push(f);
      lender.push(l);
      capacity.push(Math.min(f, l));
    }
    return { dlg, fintech_breakeven: fintech, lender_breakeven: lender, capacity };
  }

  // Guarantee level that lets the deal survive the highest default rate.
  function bestDlg(inp, respectCap = true, curve = null) {
    const c = curve || capacityCurve(inp);
    let best = -1;
    let bestI = 0;
    for (let i = 0; i < c.dlg.length; i++) {
      const allowed = !respectCap || c.dlg[i] <= inp.dlg_cap + 1e-12;
      const v = allowed ? c.capacity[i] : -1;
      if (v > best) {
        best = v;
        bestI = i;
      }
    }
    return [c.dlg[bestI], best];
  }

  // The sourcing fee that puts the lender back on its minimum return.
  function repricedSourcingFee(inp) {
    const res = cohortEconomics(inp);
    if (res.lender_roa >= inp.lender_hurdle_roa) return inp.sourcing_fee;
    const shortfall = (inp.lender_hurdle_roa - res.lender_roa) * res.asset_years;
    return inp.sourcing_fee - shortfall;
  }

  function monthlyVolumes(startVolume, months, monthlyGrowth = 0) {
    const v = [];
    for (let m = 0; m < months; m++) v.push(startVolume * Math.pow(1 + monthlyGrowth, m));
    return v;
  }

  function partnershipCashflows(inp, volumes) {
    const pattern = cohortEconomics(inp).fintech_cashflows;
    const total = new Array(volumes.length + pattern.length - 1).fill(0);
    for (let m = 0; m < volumes.length; m++) {
      for (let k = 0; k < pattern.length; k++) total[m + k] += volumes[m] * pattern[k];
    }
    return total;
  }

  function npv(cashflows, annualRate) {
    const monthlyRate = Math.pow(1 + annualRate, 1 / 12) - 1;
    let total = 0;
    for (let t = 0; t < cashflows.length; t++) total += cashflows[t] * Math.pow(1 + monthlyRate, -t);
    return total;
  }

  const partnershipNpv = (inp, volumes) =>
    npv(partnershipCashflows(inp, volumes), inp.fintech_cost_of_capital);

  // ---- joining the event study to the deal (src/integration.py) ----
  function expectedVolumes(volumes, shocksPerYear, averageCut) {
    return volumes.map((v, t) => v * Math.exp((-shocksPerYear * averageCut * t) / 12));
  }

  function riskAdjustedNpv(inp, volumes, shocksPerYear, averageDamage, passThrough = 1) {
    const cut = Math.min(1, averageDamage * passThrough);
    return partnershipNpv(inp, expectedVolumes(volumes, shocksPerYear, cut));
  }

  function valuePerRupeeByMonth(inp, months) {
    const pattern = cohortEconomics(inp).fintech_cashflows;
    const valueAtDisbursal = npv(pattern, inp.fintech_cost_of_capital);
    const monthlyRate = Math.pow(1 + inp.fintech_cost_of_capital, 1 / 12) - 1;
    const out = [];
    for (let t = 0; t < months; t++) out.push(valueAtDisbursal * Math.pow(1 + monthlyRate, -t));
    return out;
  }

  // A small repeatable random-number generator, so the page shows the same
  // simulation every time for the same inputs.
  function makeRandom(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // How many shocks arrive in one month (Poisson draw).
  function poisson(rate, random) {
    const limit = Math.exp(-rate);
    let k = 0;
    let p = 1;
    do {
      k++;
      p *= random();
    } while (p > limit);
    return k - 1;
  }

  // Thousands of possible futures; each shock re-plays one past shock.
  function simulateNpv(inp, volumes, shocksPerYear, damages, passThrough = 1, nSims = 3000, seed = 1) {
    const months = volumes.length;
    const weights = valuePerRupeeByMonth(inp, months);
    const results = new Array(nSims);
    if (!damages.length || shocksPerYear <= 0) {
      let base = 0;
      for (let t = 0; t < months; t++) base += volumes[t] * weights[t];
      return results.fill(base);
    }
    const random = makeRandom(seed);
    for (let s = 0; s < nSims; s++) {
      let scale = 1;
      let total = 0;
      for (let t = 0; t < months; t++) {
        const shocks = t === 0 ? 0 : poisson(shocksPerYear / 12, random);
        for (let k = 0; k < shocks; k++) {
          const pick = damages[Math.floor(random() * damages.length)];
          scale *= 1 - Math.min(1, pick * passThrough);
        }
        total += volumes[t] * scale * weights[t];
      }
      results[s] = total;
    }
    return results;
  }

  function percentile(sorted, q) {
    const pos = (sorted.length - 1) * q;
    const lo = Math.floor(pos);
    const hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }

  function summariseSimulation(npvs) {
    const sorted = Array.from(npvs).sort((a, b) => a - b);
    return {
      average: sum(sorted) / sorted.length,
      median: percentile(sorted, 0.5),
      worst_5_percent: percentile(sorted, 0.05),
      chance_of_loss: sorted.filter((v) => v < 0).length / sorted.length,
    };
  }

  // What specific rule changes do to the deal.
  function scenarioTable(inp, volumes, freezeStart = 12, freezeMonths = 6) {
    const frozen = volumes.map((v, t) => (t >= freezeStart && t < freezeStart + freezeMonths ? 0 : v));
    const scenarios = [
      ["Today's rules (5% cap, guarantee counts)", inp, volumes],
      ["Guarantee ignored in lender loss buffers (May 2025 rule)",
        Object.assign({}, inp, { dlg_counts_for_provisioning: false }), volumes],
      ["Guarantee cap cut to 2.5%", Object.assign({}, inp, { dlg_cap: 0.025 }), volumes],
      ["Guarantees banned", Object.assign({}, inp, { dlg_cap: 0 }), volumes],
      ["Lending frozen for " + freezeMonths + " months", inp, frozen],
    ];
    let baseNpv = null;
    return scenarios.map(([name, sInp, sVol]) => {
      const before = cohortEconomics(sInp);
      const newFee = repricedSourcingFee(sInp);
      const afterInp = Object.assign({}, sInp, { sourcing_fee: newFee });
      const after = cohortEconomics(afterInp);
      const value = partnershipNpv(afterInp, sVol);
      if (baseNpv === null) baseNpv = value;
      return {
        scenario: name,
        lender_roa_before_repricing: before.lender_roa,
        sourcing_fee_after: newFee,
        fintech_profit_per_100: after.fintech.profit * 100,
        max_default_rate: dealCapacity(sInp),
        fintech_npv: value,
        npv_change: baseNpv ? value / baseNpv - 1 : NaN,
      };
    });
  }

  const api = {
    effectiveDlg, loanBalances, cohortEconomics, fintechBreakeven, lenderBreakeven, dealCapacity,
    capacityCurve, bestDlg, repricedSourcingFee, monthlyVolumes, partnershipCashflows, npv,
    partnershipNpv, expectedVolumes, riskAdjustedNpv, simulateNpv, summariseSimulation, scenarioTable,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RegRiskModel = api;
})(typeof window !== "undefined" ? window : this);
