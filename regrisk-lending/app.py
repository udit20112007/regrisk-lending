"""
THE INTERACTIVE APP
===================

Run with:   streamlit run app.py

It has three pages (tabs):
  1. Regulatory shocks  - the event study (Module 1)
  2. Lending deal       - the guarantee economics (Module 2)
  3. Combined view      - the deal valued with regulatory risk included (Module 3)

The sliders on the left change the lending deal. Every chart updates at once.
"""

from dataclasses import replace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import event_study as es
from src import integration as ig
from src import lending_model as lm

# Chart colours: one fixed colour per thing, used the same way on every chart.
BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
ROLE_COLOUR = {"direct": ORANGE, "same_model": BLUE, "other": GREY}
ROLE_LABEL = {"direct": "Company RBI acted against",
              "same_model": "Same business model",
              "other": "Unrelated companies"}
MODEL_LABEL = {"lending_distribution": "Loan distribution (fintech)",
               "lending_nbfc": "NBFC lenders",
               "payments": "Payments and wallets",
               "cards": "Credit cards",
               "bank_digital": "Digital banking"}

st.set_page_config(page_title="Regulatory risk and lending partnerships", layout="wide")


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%"


def crore(x: float) -> str:
    return f"Rs {x:,.1f} cr"


# ---------------------------------------------------------------------------
# DATA (worked out once, then remembered)
# ---------------------------------------------------------------------------
@st.cache_data
def load_everything():
    prices, is_sample = es.load_prices()
    events = es.load_events()
    tickers = es.load_tickers()
    results = es.run_event_study(prices, events, tickers)
    years = es.years_covered(prices)
    return prices, is_sample, events, tickers, results, years


prices, is_sample, events, tickers, results, years = load_everything()

# ---------------------------------------------------------------------------
# SIDEBAR: THE DEAL ASSUMPTIONS
# ---------------------------------------------------------------------------
st.sidebar.header("Lending deal assumptions")
st.sidebar.caption("Illustrative starting values. They are not any company's actual numbers.")

with st.sidebar.expander("Guarantee", expanded=True):
    dlg_pct = st.slider("Guarantee offered (% of loans)", 0.0, 10.0, 5.0, 0.25) / 100
    dlg_cap = st.slider("RBI cap (% of loans)", 0.0, 10.0, 5.0, 0.5) / 100
    counts = st.checkbox("Lender may count the guarantee in its loss buffer", value=True)

with st.sidebar.expander("Loan and credit quality", expanded=True):
    apr = st.slider("Interest rate to borrower (% a year)", 12.0, 40.0, 24.0, 0.5) / 100
    tenor = st.slider("Loan length (months)", 3, 36, 12)
    default_rate = st.slider("Loans that default (%)", 0.0, 20.0, 4.5, 0.25) / 100
    lgd = st.slider("Unrecovered share of a defaulted loan (%)", 50, 100, 90) / 100

with st.sidebar.expander("Fintech"):
    sourcing_fee = st.slider("Sourcing fee (% of loan)", 0.0, 8.0, 4.5, 0.1) / 100
    servicing_fee = st.slider("Servicing fee (% a year)", 0.0, 6.0, 3.0, 0.1) / 100
    acquisition_cost = st.slider("Cost to acquire a borrower (% of loan)", 0.0, 5.0, 1.5, 0.1) / 100
    fintech_coc = st.slider("Fintech cost of capital (% a year)", 8.0, 30.0, 18.0, 0.5) / 100

with st.sidebar.expander("Lender"):
    cost_of_funds = st.slider("Lender cost of funds (% a year)", 5.0, 15.0, 10.0, 0.25) / 100
    hurdle = st.slider("Lender minimum return on assets (% a year)", 0.0, 8.0, 4.0, 0.25) / 100
    stress = st.slider("Lender plans for losses this many times normal", 1.0, 4.0, 2.0, 0.25)

with st.sidebar.expander("Size of the partnership"):
    start_volume = st.slider("Loans in month 1 (Rs crore)", 10, 500, 100, 10)
    horizon = st.slider("Length of partnership (months)", 12, 60, 36, 6)
    growth = st.slider("Monthly growth in loans (%)", 0.0, 5.0, 2.0, 0.25) / 100

inp = lm.DealInputs(
    apr=apr, tenor_months=tenor, default_rate=default_rate, lgd=lgd,
    dlg_pct=dlg_pct, dlg_cap=dlg_cap, dlg_counts_for_provisioning=counts,
    sourcing_fee=sourcing_fee, servicing_fee=servicing_fee,
    acquisition_cost=acquisition_cost, fintech_cost_of_capital=fintech_coc,
    cost_of_funds=cost_of_funds, lender_hurdle_roa=hurdle, stress_multiple=stress,
)
volumes = lm.monthly_volumes(start_volume, horizon, growth)

# ---------------------------------------------------------------------------
# PAGE HEADER
# ---------------------------------------------------------------------------
st.title("Regulatory risk and fintech lending partnerships")
st.write(
    "How much is a fintech's loan-distribution partnership worth once RBI rule changes "
    "are allowed for? An event study measures how often regulatory shocks arrive and how "
    "much damage they do. A deal model turns that into rupees."
)
if is_sample:
    st.warning(
        "**Sample data.** The share prices in use are made up so the app can run offline. "
        "Every event-study number below is illustrative. Run `python src/fetch_prices.py` "
        "to download real prices, then restart the app."
    )

tab1, tab2, tab3 = st.tabs(["1 · Regulatory shocks", "2 · Lending deal", "3 · Combined view"])

# ---------------------------------------------------------------------------
# TAB 1: EVENT STUDY
# ---------------------------------------------------------------------------
with tab1:
    st.subheader("How did share prices react to each RBI action?")
    st.caption(
        "Abnormal return = the share price move that the overall market does not explain. "
        "It is added up from the first day investors could react to five trading days later."
    )

    studied = events[events["event_id"].isin(results["event_id"])]
    labels = {row["event_id"]: f"{row['announce_date']:%d %b %Y} · {row['title']}"
              for _, row in studied.iterrows()}
    default_event = "E06" if "E06" in labels else list(labels)[0]
    chosen = st.selectbox("RBI action", list(labels), index=list(labels).index(default_event),
                          format_func=labels.get)
    ev_rows = results[results["event_id"] == chosen].sort_values(es.MAIN_WINDOW)

    fig = go.Figure()
    for role in ("direct", "same_model", "other"):          # fixed order, fixed colours
        part = ev_rows[ev_rows["role"] == role]
        if part.empty:
            continue
        fig.add_bar(
            y=part["ticker"], x=part[es.MAIN_WINDOW] * 100, orientation="h",
            name=ROLE_LABEL[role], marker_color=ROLE_COLOUR[role],
            customdata=np.stack([part["company"], part[es.MAIN_WINDOW + " p"]], axis=-1),
            hovertemplate="%{customdata[0]}<br>Abnormal return: %{x:.1f}%"
                          "<br>p-value: %{customdata[1]:.3f}<extra></extra>",
        )
    fig.update_layout(
        height=420, bargap=0.35, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Abnormal return over 6 trading days (%)",
        yaxis=dict(categoryorder="array", categoryarray=list(ev_rows["ticker"])),
        legend=dict(orientation="h", y=1.08),
    )
    fig.add_vline(x=0, line_width=1, line_color=GREY)
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns(2)
    with left:
        st.markdown("**Average reaction across all RBI actions**")
        summary = es.summary_by_role(results)
        show = pd.DataFrame({
            "Type": summary["direction"].str.capitalize(),
            "Companies": summary["role"].map(ROLE_LABEL),
            "N": summary["observations"],
            "Average": summary["average"].map(lambda v: pct(v)),
            "Fell in value": summary["share_negative"].map(lambda v: pct(v, 0)),
            "p-value": summary["p_value"].map(lambda v: "-" if pd.isna(v) else f"{v:.3f}"),
        })
        st.dataframe(show, hide_index=True, width="stretch")
        st.caption("A p-value below 0.05 means the average is unlikely to be chance.")

    with right:
        st.markdown("**Regulatory risk by business model**")
        risk = es.risk_by_model(results, events, tickers, years)
        risk_sorted = risk.sort_values("expected_yearly_drag")
        fig = go.Figure(go.Bar(
            y=risk_sorted["model"].map(MODEL_LABEL), x=risk_sorted["expected_yearly_drag"] * 100,
            orientation="h", marker_color=BLUE,
            text=risk_sorted["expected_yearly_drag"].map(lambda v: pct(v)),
            textposition="outside", cliponaxis=False,
            customdata=np.stack([risk_sorted["shocks_per_year"],
                                 risk_sorted["damage_per_shock"] * 100], axis=-1),
            hovertemplate="%{y}<br>Shocks a year: %{customdata[0]:.2f}"
                          "<br>Damage per shock: %{customdata[1]:.1f}%<extra></extra>",
        ))
        fig.update_layout(height=300, bargap=0.4, margin=dict(l=10, r=40, t=10, b=10),
                          xaxis_title="Expected value lost to regulation each year (%)")
        st.plotly_chart(fig, width="stretch")
        st.caption("Shocks a year x average damage per shock. "
                   f"Based on {years:.1f} years of prices.")

    with st.expander("All RBI actions in the study, with sources"):
        table = pd.DataFrame({
            "Date": events["announce_date"].dt.strftime("%d %b %Y"),
            "Action": events["title"],
            "Type": events["direction"].str.capitalize(),
            "Date status": events["date_check"].map(
                {"verified": "Verified", "check_day": "Check exact day"}),
            "Source": events["source_url"],
        })
        st.dataframe(table, hide_index=True, width="stretch",
                     column_config={"Source": st.column_config.LinkColumn(display_text="Open")})

# ---------------------------------------------------------------------------
# TAB 2: LENDING DEAL
# ---------------------------------------------------------------------------
with tab2:
    res = lm.cohort_economics(inp)
    fintech_be, lender_be = lm.fintech_breakeven(inp), lm.lender_breakeven(inp)
    capacity = min(fintech_be, lender_be)

    st.subheader("Who earns what on every Rs 100 lent?")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fintech profit", f"Rs {res['fintech']['profit'] * 100:.2f}")
    c2.metric("Lender return on assets", pct(res["lender_roa"], 2),
              f"{(res['lender_roa'] - inp.lender_hurdle_roa) * 100:+.2f} pts vs minimum")
    c3.metric("Credit loss", f"Rs {res['net_credit_loss'] * 100:.2f}")
    c4.metric("Deal survives defaults up to", pct(capacity),
              f"{(capacity - inp.default_rate) * 100:+.1f} pts vs expected")

    if inp.dlg_pct > inp.dlg_cap:
        st.info(f"The guarantee offered ({pct(inp.dlg_pct, 2)}) is above the RBI cap, "
                f"so only {pct(inp.dlg_cap, 2)} is in force.")

    names_f = {"sourcing_fee": "Sourcing fee", "servicing_fee": "Servicing fee",
               "acquisition_cost": "Cost to acquire borrower", "collection_cost": "Collection cost",
               "guarantee_paid": "Guarantee paid to lender", "deposit_interest": "Interest on guarantee deposit",
               "capital_charge": "Cost of locked-up capital", "profit": "Profit"}
    names_l = {"interest_income": "Interest from borrowers", "processing_fee": "Processing fee",
               "funding_cost": "Cost of funds", "opex": "Running costs",
               "sourcing_fee_paid": "Sourcing fee to fintech", "servicing_fee_paid": "Servicing fee to fintech",
               "credit_loss": "Credit loss", "guarantee_received": "Guarantee received",
               "buffer_cost": "Cost of loss buffer", "profit": "Profit"}
    left, right = st.columns(2)
    with left:
        st.markdown("**Fintech (Rs per Rs 100 lent)**")
        st.dataframe(pd.DataFrame({"Item": [names_f[k] for k in res["fintech"]],
                                   "Rs": [f"{v * 100:+.2f}" for v in res["fintech"].values()]}),
                     hide_index=True, width="stretch")
    with right:
        st.markdown("**Lender (Rs per Rs 100 lent)**")
        st.dataframe(pd.DataFrame({"Item": [names_l[k] for k in res["lender"]],
                                   "Rs": [f"{v * 100:+.2f}" for v in res["lender"].values()]}),
                     hide_index=True, width="stretch")

    st.subheader("Which guarantee level lets the deal survive the most defaults?")
    st.caption(
        "A bigger guarantee protects the lender but exposes the fintech. The deal only works "
        "below BOTH lines, so the lower line is what matters. Where the fintech line leaves the "
        "top of the chart, the guarantee is small enough that the fintech profits at any default rate."
    )
    curve = lm.capacity_curve(inp)
    best_level, best_capacity = lm.best_dlg(inp, respect_cap=True)
    free_level, free_capacity = lm.best_dlg(inp, respect_cap=False)

    fig = go.Figure()
    fig.add_scatter(x=curve["dlg"] * 100, y=curve["lender_breakeven"] * 100, name="Lender still earns its minimum",
                    line=dict(color=BLUE, width=2),
                    hovertemplate="Guarantee %{x:.2f}%<br>Lender copes up to %{y:.1f}% defaults<extra></extra>")
    fig.add_scatter(x=curve["dlg"] * 100, y=curve["fintech_breakeven"] * 100, name="Fintech still makes a profit",
                    line=dict(color=ORANGE, width=2),
                    hovertemplate="Guarantee %{x:.2f}%<br>Fintech copes up to %{y:.1f}% defaults<extra></extra>")
    fig.add_vline(x=inp.dlg_cap * 100, line_dash="dash", line_color=GREY, line_width=1,
                  annotation_text="RBI cap", annotation_position="top")
    fig.add_hline(y=inp.default_rate * 100, line_dash="dot", line_color=GREY, line_width=1,
                  annotation_text="Expected defaults", annotation_position="bottom right")
    top = max(15.0, min(60.0, float(curve["capacity"].max() * 100 * 2.2)))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified",
                      xaxis_title="Guarantee (% of loans disbursed)",
                      yaxis_title="Highest default rate survived (%)",
                      yaxis_range=[0, top], legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, width="stretch")

    cap_cost = free_capacity - best_capacity
    message = (f"Within the RBI cap, the best guarantee is **{pct(best_level, 2)}**: "
               f"the deal then survives a default rate of up to **{pct(best_capacity)}**. ")
    if cap_cost > 0.0005:
        message += (f"Without the cap, a guarantee of {pct(free_level, 2)} would stretch that to "
                    f"{pct(free_capacity)}. So the cap costs **{cap_cost * 100:.1f} percentage points** "
                    "of risk the partnership could otherwise take.")
    else:
        message += "The cap is not what holds this deal back. The fintech's own margin is."
    st.success(message)

# ---------------------------------------------------------------------------
# TAB 3: COMBINED VIEW
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("What is the partnership worth once regulatory risk is included?")

    left, right = st.columns([2, 1])
    with left:
        models_available = [m for m in MODEL_LABEL if m in set(risk["model"])]
        model = st.selectbox("Take regulatory risk from this business model",
                             models_available, format_func=MODEL_LABEL.get)
    with right:
        pass_through = st.slider("Lending is hit this many times harder than the share price",
                                 0.5, 5.0, 1.0, 0.25)

    cal = ig.calibrate(results, events, years, model)
    base_npv = lm.partnership_npv(inp, volumes)
    adj_npv = ig.risk_adjusted_npv(inp, volumes, cal["shocks_per_year"], cal["average_damage"], pass_through)
    sims = ig.simulate_npv(inp, volumes, cal["shocks_per_year"], cal["damages"], pass_through, n_sims=3000)
    sim = ig.summarise_simulation(sims)

    st.markdown("**Step 1. What the event study says about this business model**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Regulatory shocks a year", f"{cal['shocks_per_year']:.2f}")
    c2.metric("Average damage per shock", pct(cal["average_damage"]))
    c3.metric("Yearly regulatory risk premium", pct(cal["regulatory_premium"] * pass_through))

    st.markdown("**Step 2. What that does to the value of the partnership**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Value ignoring regulation", crore(base_npv))
    c2.metric("Value with regulatory risk", crore(adj_npv),
              f"{(adj_npv / base_npv - 1) * 100:+.1f}%" if base_npv else None)
    c3.metric("1-in-20 bad outcome", crore(sim["worst_5_percent"]))
    c4.metric("Chance of losing money", pct(sim["chance_of_loss"], 0))

    fig = go.Figure(go.Histogram(x=sims, nbinsx=40, marker_color=BLUE,
                                 marker_line=dict(color="rgba(0,0,0,0)", width=0),
                                 hovertemplate="Value about Rs %{x:,.0f} cr<br>%{y} of 3,000 futures<extra></extra>"))
    fig.add_vline(x=base_npv, line_dash="dash", line_color=GREY, line_width=1,
                  annotation_text="Ignoring regulation", annotation_position="top")
    fig.update_layout(height=320, bargap=0.08, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis_title="Value of the partnership to the fintech (Rs crore)",
                      yaxis_title="Number of simulated futures")
    st.plotly_chart(fig, width="stretch")
    st.caption("3,000 simulated futures. In each one, shocks arrive at random and each shock "
               "re-plays the damage of one past RBI action.")

    st.markdown("**Step 3. Specific rule changes**")
    scen = ig.scenario_table(inp, volumes)
    show = pd.DataFrame({
        "Scenario": scen["scenario"],
        "Lender return": scen["lender_roa_before_repricing"].map(lambda v: pct(v, 2)),
        "New fee": scen["sourcing_fee_after"].map(lambda v: pct(v, 2)),
        "Fintech profit / Rs 100": scen["fintech_profit_per_100"].map(lambda v: f"Rs {v:.2f}"),
        "Max defaults": scen["max_default_rate"].map(lambda v: pct(v)),
        "Value": scen["fintech_npv"].map(crore),
        "Change": scen["npv_change"].map(lambda v: f"{v * 100:+.1f}%"),
    })
    st.dataframe(show, hide_index=True, width="stretch")
    st.caption(
        "If a rule change pushes the lender below its minimum return, the lender cuts the "
        "fintech's sourcing fee (New fee) until it is back at the minimum. Lender return is shown "
        "before that cut. Max defaults = the highest default rate the deal survives at the original fee."
    )

    worst = scen.iloc[1:].sort_values("npv_change").iloc[0]
    st.markdown("**Reading the result**")
    st.write(
        f"Regulatory risk takes {abs(adj_npv / base_npv - 1) * 100:.1f}% off the value of this partnership "
        f"on average ({crore(base_npv)} to {crore(adj_npv)}). "
        f"The most damaging single rule change tested is \"{worst['scenario'].lower()}\", "
        f"which changes the value by {worst['npv_change'] * 100:+.1f}%. "
        f"The deal currently survives a default rate of {pct(scen.loc[0, 'max_default_rate'])} "
        f"against {pct(inp.default_rate)} expected."
        if base_npv > 0 else
        "At these assumptions the partnership does not make money even before regulatory risk. "
        "Lower the guarantee or the default rate, or raise the fees."
    )
