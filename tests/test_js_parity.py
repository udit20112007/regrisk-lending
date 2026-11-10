"""
TEST - does the website's JavaScript model give the same answers as Python?

The website recalculates in the browser, using web/model.js, a copy of the
Python model. This test runs both on the same inputs and fails if any number
differs. It needs Node.js; if Node is not installed the test is skipped.

Run with:   python -m pytest -q
"""

import json
import shutil
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import integration as ig          # noqa: E402
from src import lending_model as lm        # noqa: E402

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")

# Three different deals, so the comparison is not a fluke of one set of inputs.
CASES = {
    "default deal": lm.DealInputs(),
    "risky borrowers, small guarantee": replace(lm.DealInputs(), default_rate=0.11, dlg_pct=0.02,
                                                tenor_months=18, apr=0.30),
    "guarantee above the cap, not counted": replace(lm.DealInputs(), dlg_pct=0.08,
                                                    dlg_counts_for_provisioning=False, lgd=0.75),
}


def run_javascript(inp: lm.DealInputs) -> dict:
    out = subprocess.run([NODE, str(ROOT / "tests" / "js_parity.js"), json.dumps(asdict(inp))],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def close(a, b, tolerance=1e-9) -> bool:
    return np.allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float), rtol=0, atol=tolerance)


@pytest.mark.parametrize("name", list(CASES))
def test_javascript_matches_python(name):
    inp = CASES[name]
    js = run_javascript(inp)
    volumes = lm.monthly_volumes(100, 36, 0.02)
    res = lm.cohort_economics(inp)
    curve = lm.capacity_curve(inp)

    for key, value in res["fintech"].items():
        assert close(js["fintech"][key], value), f"fintech {key}"
    for key, value in res["lender"].items():
        assert close(js["lender"][key], value), f"lender {key}"
    assert close(js["lender_roa"], res["lender_roa"])
    assert close(js["net_credit_loss"], res["net_credit_loss"])
    assert close(js["fintech_cashflows"], res["fintech_cashflows"])

    assert close(js["fintech_breakeven"], lm.fintech_breakeven(inp))
    assert close(js["lender_breakeven"], lm.lender_breakeven(inp))
    assert close(js["curve_fintech"], curve["fintech_breakeven"])
    assert close(js["curve_lender"], curve["lender_breakeven"])
    assert close(js["best_capped"], lm.best_dlg(inp, True, curve))
    assert close(js["best_free"], lm.best_dlg(inp, False, curve))
    assert close(js["repriced_fee"], lm.repriced_sourcing_fee(replace(inp, dlg_cap=0.0)))

    assert close(js["partnership_npv"], lm.partnership_npv(inp, volumes), 1e-7)
    assert close(js["risk_adjusted_npv"], ig.risk_adjusted_npv(inp, volumes, 1.2, 0.06, 1.5), 1e-7)

    table = ig.scenario_table(inp, volumes)
    assert [row["scenario"] for row in js["scenarios"]] == list(table["scenario"])
    for column in table.columns.drop("scenario"):
        assert close([row[column] for row in js["scenarios"]], table[column], 1e-7), column


def test_javascript_simulation_agrees_with_the_formula():
    # The random numbers differ between the two languages, so we check the
    # simulation's average against the exact formula instead (within 1%).
    js = run_javascript(lm.DealInputs())
    assert abs(js["simulation_mean"] - js["simulation_formula"]) / abs(js["simulation_formula"]) < 0.01
