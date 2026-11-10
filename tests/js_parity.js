// Runs the JavaScript model and prints its answers as JSON.
// tests/test_js_parity.py calls this and compares the answers with Python.
//
// Usage: node tests/js_parity.js '<inputs as JSON>'

const model = require("../web/model.js");

const inp = JSON.parse(process.argv[2]);
const volumes = model.monthlyVolumes(100, 36, 0.02);
const res = model.cohortEconomics(inp);
const curve = model.capacityCurve(inp);
const damages = [0.02, 0.05, 0.11];
const sims = model.simulateNpv(inp, volumes, 1.2, damages, 1, 20000, 3);

console.log(JSON.stringify({
  fintech: res.fintech,
  lender: res.lender,
  lender_roa: res.lender_roa,
  net_credit_loss: res.net_credit_loss,
  fintech_cashflows: res.fintech_cashflows,
  fintech_breakeven: model.fintechBreakeven(inp),
  lender_breakeven: model.lenderBreakeven(inp),
  curve_fintech: curve.fintech_breakeven,
  curve_lender: curve.lender_breakeven,
  best_capped: model.bestDlg(inp, true, curve),
  best_free: model.bestDlg(inp, false, curve),
  repriced_fee: model.repricedSourcingFee(Object.assign({}, inp, { dlg_cap: 0 })),
  partnership_npv: model.partnershipNpv(inp, volumes),
  risk_adjusted_npv: model.riskAdjustedNpv(inp, volumes, 1.2, 0.06, 1.5),
  scenarios: model.scenarioTable(inp, volumes),
  simulation_mean: sims.reduce((s, v) => s + v, 0) / sims.length,
  simulation_formula: model.riskAdjustedNpv(inp, volumes, 1.2, 0.06),
}));
