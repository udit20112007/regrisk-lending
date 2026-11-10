/*
 * THE PAGE
 * ========
 * Reads the event-study results (data.js, made by Python), keeps track of the
 * slider values, recalculates with the model (model.js) and draws everything.
 *
 *   state    what the visitor has chosen
 *   compute  runs the model for the current choices
 *   render*  one function per part of the page
 */
(function () {
  "use strict";

  const D = window.REGRISK_DATA;
  const M = window.RegRiskModel;
  const C = window.Charts;
  const $ = (id) => document.getElementById(id);

  const DEFAULT_SIZE = { start_volume: 100, horizon: 36, growth: 0.02 };
  const state = {
    inp: Object.assign({}, D.defaults),
    size: Object.assign({}, DEFAULT_SIZE),
    eventId: D.events.some((e) => e.id === "E06") ? "E06" : D.events[0].id,
    window: "6",
    view: "chart",
    model: "lending_distribution",
    passThrough: 1,
  };

  const MODEL_LABEL = {
    lending_distribution: "Loan distribution",
    lending_nbfc: "NBFC lenders",
    payments: "Payments and wallets",
    cards: "Credit cards",
    bank_digital: "Digital banking",
  };
  const ROLE = {
    direct: { label: "Company RBI acted against", color: "var(--series-1)" },
    same_model: { label: "Same business model", color: "var(--series-2)" },
    other: { label: "Unrelated companies", color: "var(--neutral-mark)" },
  };
  const DIRECTION_LABEL = { tightening: "Tightening", easing: "Easing", unclear: "Direction not set" };
  const FINTECH_ROWS = [
    ["sourcing_fee", "Sourcing fee"], ["servicing_fee", "Servicing fee"],
    ["acquisition_cost", "Cost to acquire borrower"], ["collection_cost", "Collection cost"],
    ["guarantee_paid", "Guarantee paid to lender"], ["deposit_interest", "Interest on guarantee deposit"],
    ["capital_charge", "Cost of locked-up capital"], ["profit", "Profit"],
  ];
  const LENDER_ROWS = [
    ["interest_income", "Interest from borrowers"], ["processing_fee", "Processing fee"],
    ["funding_cost", "Cost of funds"], ["opex", "Running costs"],
    ["sourcing_fee_paid", "Sourcing fee to fintech"], ["servicing_fee_paid", "Servicing fee to fintech"],
    ["credit_loss", "Credit loss"], ["guarantee_received", "Guarantee received"],
    ["buffer_cost", "Cost of loss buffer"], ["profit", "Profit"],
  ];

  // ---------- number formats ----------
  const MINUS = "−";
  const fix = (v, d) => (Math.abs(v) < 0.5 * Math.pow(10, -d) ? 0 : v).toFixed(d).replace("-", MINUS);
  const pct = (v, d = 1) => fix(v * 100, d) + "%";
  // Put a plus sign in front of positive numbers. Zero gets no sign.
  const signed = (text) => (text.startsWith(MINUS) || parseFloat(text.replace(/[^\d.]/g, "")) === 0 ? text : "+" + text);
  const crore = (v) => (v < 0 ? MINUS : "") + "₹" +
    Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " cr";
  const dateLabel = (iso) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB",
    { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

  // ---------- small DOM helpers ----------
  function make(tag, className, textContent) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (textContent !== undefined) node.textContent = textContent;
    return node;
  }
  // Write a sentence where **words** become bold. Uses textContent, so it is safe.
  function rich(node, sentence) {
    node.textContent = "";
    sentence.split("**").forEach((part, i) => {
      node.appendChild(i % 2 ? make("strong", "", part) : document.createTextNode(part));
    });
  }
  function chip(node, textContent, tone) {
    node.className = "chip" + (tone ? " " + tone : "");
    node.textContent = textContent;
  }
  function table(container, headers, rows) {
    const t = make("table");
    const head = t.createTHead().insertRow();
    headers.forEach((h) => {
      const th = make("th", h.num ? "num" : "", h.label);
      th.scope = "col";
      head.appendChild(th);
    });
    const body = t.createTBody();
    rows.forEach((row) => {
      const tr = body.insertRow();
      if (row.className) tr.className = row.className;
      row.cells.forEach((cell, i) => {
        const td = tr.insertCell();
        td.className = [headers[i].num ? "num" : "", cell.strong ? "strong" : ""].join(" ").trim();
        if (cell.node) td.appendChild(cell.node);
        else td.textContent = cell.text;
      });
    });
    container.textContent = "";
    container.appendChild(t);
  }

  // ---------- the assumptions panel ----------
  const P = (key, label, min, max, step, digits) =>
    ({ key, label, min, max, step, scale: 100, target: "inp", format: (v) => v.toFixed(digits) + "%" });
  const GROUPS = [
    { title: "Guarantee", open: true, fields: [
      P("dlg_pct", "Guarantee offered", 0, 10, 0.25, 2),
      P("dlg_cap", "RBI cap", 0, 10, 0.5, 2),
      { key: "dlg_counts_for_provisioning", label: "Lender may count the guarantee in its loss buffer", type: "switch", target: "inp" },
    ] },
    { title: "Loan and credit quality", open: true, fields: [
      P("apr", "Interest rate to borrower", 12, 40, 0.5, 1),
      { key: "tenor_months", label: "Loan length", min: 3, max: 36, step: 1, scale: 1, target: "inp", format: (v) => v + " months" },
      P("default_rate", "Loans that default", 0, 20, 0.25, 2),
      P("lgd", "Unrecovered share of a default", 50, 100, 1, 0),
    ] },
    { title: "Fintech", fields: [
      P("sourcing_fee", "Sourcing fee", 0, 8, 0.1, 1),
      P("servicing_fee", "Servicing fee, a year", 0, 6, 0.1, 1),
      P("acquisition_cost", "Cost to acquire a borrower", 0, 5, 0.1, 1),
      P("fintech_cost_of_capital", "Cost of capital, a year", 8, 30, 0.5, 1),
    ] },
    { title: "Lender", fields: [
      P("cost_of_funds", "Cost of funds, a year", 5, 15, 0.25, 2),
      P("lender_hurdle_roa", "Minimum return on assets", 0, 8, 0.25, 2),
      { key: "stress_multiple", label: "Plans for losses", min: 1, max: 4, step: 0.25, scale: 1, target: "inp", format: (v) => v.toFixed(2) + "× normal" },
    ] },
    { title: "Size of the partnership", fields: [
      { key: "start_volume", label: "Loans in month 1", min: 10, max: 500, step: 10, scale: 1, target: "size", format: (v) => "₹" + v + " cr" },
      { key: "horizon", label: "Length of partnership", min: 12, max: 60, step: 6, scale: 1, target: "size", format: (v) => v + " months" },
      { key: "growth", label: "Monthly growth in loans", min: 0, max: 5, step: 0.25, scale: 100, target: "size", format: (v) => v.toFixed(2) + "%" },
    ] },
  ];

  function setFill(input) {
    const share = ((input.value - input.min) / (input.max - input.min)) * 100;
    input.style.setProperty("--fill", share + "%");
  }

  function buildControls() {
    const host = $("controls");
    host.textContent = "";
    GROUPS.forEach((group) => {
      const details = make("details", "group");
      details.open = !!group.open && window.innerWidth > 1080;   // start closed on small screens
      details.appendChild(make("summary", "", group.title));
      const body = make("div", "group-body");
      group.fields.forEach((field) => {
        const id = "f_" + field.key;
        if (field.type === "switch") {
          const label = make("label", "switch");
          label.appendChild(make("span", "", field.label));
          const input = make("input");
          input.type = "checkbox";
          input.id = id;
          input.checked = !!state[field.target][field.key];
          input.addEventListener("change", () => { state[field.target][field.key] = input.checked; scheduleModel(); });
          label.appendChild(input);
          label.appendChild(make("span", "track"));
          body.appendChild(label);
          return;
        }
        const wrap = make("div", "field");
        const label = make("label");
        label.htmlFor = id;
        label.appendChild(make("span", "", field.label));
        const out = make("output");
        label.appendChild(out);
        const input = make("input");
        input.type = "range";
        input.id = id;
        input.min = field.min;
        input.max = field.max;
        input.step = field.step;
        input.value = +(state[field.target][field.key] * field.scale).toFixed(6);
        const show = () => { out.textContent = field.format(+input.value); setFill(input); };
        input.addEventListener("input", () => {
          state[field.target][field.key] = +input.value / field.scale;
          show();
          scheduleModel();
        });
        show();
        wrap.appendChild(label);
        wrap.appendChild(input);
        body.appendChild(wrap);
      });
      details.appendChild(body);
      host.appendChild(details);
    });
  }

  function segmented(host, options, current, onPick) {
    host.textContent = "";
    options.forEach(([value, label]) => {
      const button = make("button", "", label);
      button.type = "button";
      button.setAttribute("aria-pressed", String(value === current));
      button.addEventListener("click", () => onPick(value));
      host.appendChild(button);
    });
  }

  // ---------- the model ----------
  let R = null;      // the latest results

  function compute() {
    const inp = state.inp;
    const res = M.cohortEconomics(inp);
    const curve = M.capacityCurve(inp);
    const fintechBe = M.fintechBreakeven(inp);
    const lenderBe = M.lenderBreakeven(inp);
    const volumes = M.monthlyVolumes(state.size.start_volume, state.size.horizon, state.size.growth);
    const damages = D.damages[state.model] || [];
    const shocks = D.meta.years > 0 ? damages.length / D.meta.years : 0;
    const avgDamage = damages.length ? damages.reduce((s, v) => s + v, 0) / damages.length : 0;
    const sims = M.simulateNpv(inp, volumes, shocks, damages, state.passThrough, 3000, 1);
    R = {
      res, curve, fintechBe, lenderBe,
      capacity: Math.min(fintechBe, lenderBe),
      best: M.bestDlg(inp, true, curve),
      free: M.bestDlg(inp, false, curve),
      baseNpv: M.partnershipNpv(inp, volumes),
      adjNpv: M.riskAdjustedNpv(inp, volumes, shocks, avgDamage, state.passThrough),
      shocks, avgDamage, sims,
      sim: M.summariseSimulation(sims),
      scenarios: M.scenarioTable(inp, volumes),
    };
  }

  // ---------- drawing: things that never change ----------
  function renderStatic() {
    const pill = $("dataPill");
    if (D.meta.is_sample) {
      pill.textContent = "Sample data";
      pill.classList.add("is-sample");
      $("sampleBanner").hidden = false;
    } else {
      pill.textContent = "Prices to " + dateLabel(D.meta.price_end);
    }
    if (D.events.some((e) => e.direction === "unclear")) {
      const entry = make("li");
      entry.appendChild(make("span", "swatch dot unclear"));
      entry.appendChild(document.createTextNode("Direction not set"));
      $("tlLegend").appendChild(entry);
    }
    const years = D.events.map((e) => +e.date.slice(0, 4));
    $("tlRange").textContent = Math.min(...years) + "–" + Math.max(...years);
    $("methodData").textContent = `${D.events.length} RBI actions and ${D.meta.companies} listed companies, ` +
      `with prices from ${dateLabel(D.meta.price_start)} to ${dateLabel(D.meta.price_end)}.`;

    // risk by business model
    const host = $("riskList");
    host.textContent = "";
    const worst = Math.max(...D.risk.map((r) => r.expected_yearly_drag), 1e-9);
    D.risk.slice().sort((a, b) => b.expected_yearly_drag - a.expected_yearly_drag).forEach((r) => {
      const row = make("div", "row");
      row.appendChild(make("span", "name", MODEL_LABEL[r.model] || r.model));
      row.appendChild(make("span", "num", pct(r.expected_yearly_drag)));
      const track = make("div", "track");
      const fill = make("div", "fill");
      fill.style.width = (100 * r.expected_yearly_drag) / worst + "%";
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(make("span", "hint",
        `${r.shocks_per_year.toFixed(2)} shocks a year × ${pct(r.damage_per_shock)} damage per shock`));
      host.appendChild(row);
    });
  }

  // ---------- drawing: regulatory shocks ----------
  function renderTimeline() {
    C.timeline($("timeline"), {
      events: D.events.map((e) => ({ id: e.id, time: Date.parse(e.date + "T00:00:00Z"), direction: e.direction,
        title: e.title, dateLabel: dateLabel(e.date) })),
      selected: state.eventId,
      onSelect: selectEvent,
    });
  }

  function selectEvent(id) {
    const hadFocus = $("timeline").contains(document.activeElement);
    state.eventId = id;
    renderTimeline();
    renderEvent();
    if (hadFocus) {
      const dot = $("timeline").querySelector(".tl-dot.selected");
      if (dot) dot.focus();
    }
  }

  function renderEvent() {
    const ev = D.events.find((e) => e.id === state.eventId);
    const days = +state.window;
    const meta = $("eventMeta");
    meta.textContent = "";
    meta.appendChild(make("span", "", dateLabel(ev.date)));
    meta.appendChild(make("span", "tag", DIRECTION_LABEL[ev.direction] || ev.direction));
    if (ev.date_check !== "verified") meta.appendChild(make("span", "tag", "Exact day to verify"));
    if (ev.added_by === "auto") {
      const auto = make("span", "tag auto", "Auto-detected");
      auto.title = "Found by the automatic RBI watch. Not yet checked by a person.";
      meta.appendChild(auto);
    }
    const link = make("a", "", "Source ↗");
    link.href = ev.source_url;
    link.target = "_blank";
    link.rel = "noopener";
    meta.appendChild(link);
    $("eventTitle").textContent = ev.title;

    segmented($("windowSeg"), [["1", "1 day"], ["2", "2 days"], ["6", "6 days"]], state.window, (w) => {
      state.window = w;
      renderEvent();
      renderSummary();
    });

    const rows = (D.reactions[ev.id] || []).slice().sort((a, b) => a.car[state.window] - b.car[state.window]);
    const chart = $("reactionChart");
    const tableHost = $("reactionTable");
    chart.hidden = state.view !== "chart";
    tableHost.hidden = state.view !== "table";
    $("reactionLegend").hidden = state.view !== "chart" || !rows.length;

    if (!rows.length) {
      $("reactionSub").textContent = "Not analysed yet. The study needs six trading days of prices after the action, and enough history before it.";
      chart.textContent = "";
      tableHost.textContent = "";
      return;
    }
    $("reactionSub").textContent = `Abnormal return over ${days} trading day${days > 1 ? "s" : ""}, ` +
      `starting ${dateLabel(ev.reaction_date)}.`;

    if (state.view === "chart") {
      C.bars(chart, {
        ariaLabel: "Abnormal return by company",
        rows: rows.map((r) => ({
          label: r.ticker, value: r.car[state.window] * 100, color: ROLE[r.role].color, title: r.company,
          tipRows: [
            { key: ROLE[r.role].color, label: ROLE[r.role].label, value: "" },
            { label: "Abnormal return", value: signed(pct(r.car[state.window])) },
            { label: "p-value", value: r.p[state.window].toFixed(3) },
          ],
        })),
        tickFormat: (v) => fix(v, 0) + "%",
        valueFormat: (v) => signed(fix(v, 1) + "%"),
      });
    } else {
      table(tableHost, [{ label: "Company" }, { label: "Group" }, { label: "Abnormal return", num: true }, { label: "p-value", num: true }],
        rows.map((r) => ({ cells: [
          { text: r.company, strong: true }, { text: ROLE[r.role].label },
          { text: signed(pct(r.car[state.window])) }, { text: r.p[state.window].toFixed(3) },
        ] })));
    }
  }

  function renderSummary() {
    const order = { tightening: 0, easing: 1, unclear: 2 };
    const roleOrder = { direct: 0, same_model: 1, other: 2 };
    const rows = D.summary[state.window].slice().sort((a, b) =>
      order[a.direction] - order[b.direction] || roleOrder[a.role] - roleOrder[b.role]);
    table($("summaryTable"),
      [{ label: "Type of action" }, { label: "Companies" }, { label: "Observations", num: true },
        { label: "Average reaction", num: true }, { label: "Fell in value", num: true }, { label: "p-value", num: true }],
      rows.map((r) => {
        const significant = r.p_value !== null && r.p_value < 0.05;
        const p = make("span", significant ? "chip good" : "", r.p_value === null ? "–" : r.p_value.toFixed(3));
        if (significant) p.title = "Unlikely to be chance";
        return { cells: [
          { text: DIRECTION_LABEL[r.direction] || r.direction },
          { text: ROLE[r.role].label, strong: true },
          { text: String(r.observations) },
          { text: signed(pct(r.average)) },
          { text: pct(r.share_negative, 0) },
          { node: p },
        ] };
      }));
  }

  // ---------- drawing: headline numbers ----------
  function renderKpis() {
    const inp = state.inp;
    $("kpiValue").textContent = crore(R.adjNpv);
    const sub = $("kpiValueSub");
    sub.textContent = "";
    if (R.baseNpv > 0) {
      const change = R.adjNpv / R.baseNpv - 1;
      const c = make("span");
      chip(c, signed(pct(change)), change < -0.0005 ? "bad" : "");
      sub.appendChild(c);
      sub.appendChild(document.createTextNode(` vs ${crore(R.baseNpv)} ignoring regulation`));
    } else {
      sub.textContent = "The deal loses money even before regulatory risk";
    }

    $("kpiPremium").textContent = pct(R.shocks * Math.min(1, R.avgDamage * state.passThrough));
    $("kpiPremiumSub").textContent = `${R.shocks.toFixed(2)} shocks a year × ` +
      `${pct(Math.min(1, R.avgDamage * state.passThrough))} lost per shock`;

    $("kpiCapacity").textContent = pct(R.capacity);
    const gap = R.capacity - inp.default_rate;
    const capSub = $("kpiCapacitySub");
    capSub.textContent = "";
    const g = make("span");
    chip(g, signed(fix(gap * 100, 1)) + " pts", gap >= 0 ? "good" : "bad");
    capSub.appendChild(g);
    capSub.appendChild(document.createTextNode(` vs ${pct(inp.default_rate)} expected`));

    $("kpiBest").textContent = pct(R.best[0], 2);
    const capCost = R.free[1] - R.best[1];
    $("kpiBestSub").textContent = capCost > 0.0005
      ? `The cap costs ${fix(capCost * 100, 1)} pts of risk capacity`
      : "The cap is not what limits this deal";
  }

  // ---------- drawing: lending deal ----------
  function renderPnl(host, rowsSpec, values) {
    host.textContent = "";
    const biggest = Math.max(...rowsSpec.map(([key]) => Math.abs(values[key])), 1e-9);
    rowsSpec.forEach(([key, label]) => {
      const v = values[key] * 100;
      const row = make("div", "row" + (key === "profit" ? " total" : ""));
      const name = make("span", "name", label);
      name.title = label;
      row.appendChild(name);
      const bar = make("div", "bar");
      const fill = make("i", v >= 0 ? "pos" : "neg");
      fill.style.width = (50 * Math.abs(values[key])) / biggest + "%";
      bar.appendChild(fill);
      row.appendChild(bar);
      row.appendChild(make("span", "num", signed(fix(v, 2))));
      host.appendChild(row);
    });
  }

  function renderDeal() {
    const inp = state.inp;
    renderPnl($("fintechPnl"), FINTECH_ROWS, R.res.fintech);
    renderPnl($("lenderPnl"), LENDER_ROWS, R.res.lender);
    const profit = R.res.fintech.profit;
    chip($("fintechChip"), profit >= inp.fintech_min_margin ? "Profitable" : "Loss-making",
      profit >= inp.fintech_min_margin ? "good" : "bad");
    const ok = R.res.lender_roa >= inp.lender_hurdle_roa;
    chip($("lenderChip"), `Return ${pct(R.res.lender_roa, 2)} · minimum ${pct(inp.lender_hurdle_roa, 2)}`, ok ? "good" : "bad");

    const capacityPct = R.curve.capacity.map((v) => v * 100);
    const yMax = Math.max(15, Math.min(60, Math.max(...capacityPct) * 2.2));
    const dlg = M.effectiveDlg(inp);
    // the two labels point away from each other so they cannot overlap
    const hasBest = Math.abs(R.best[0] - dlg) > 0.001;
    const bestIsLeft = !hasBest || R.best[0] < dlg;
    const points = [{ x: dlg * 100, y: R.capacity * 100, label: "This deal", side: bestIsLeft ? "right" : "left" }];
    if (hasBest) {
      points.push({ x: R.best[0] * 100, y: R.best[1] * 100, label: "Best within cap", hollow: true,
        side: bestIsLeft ? "left" : "right" });
    }
    C.lines($("capacityChart"), {
      ariaLabel: "Highest default rate survived, by guarantee level",
      xs: R.curve.dlg.map((v) => v * 100),
      series: [
        { name: "Lender", color: "var(--series-2)", ys: R.curve.lender_breakeven.map((v) => v * 100) },
        { name: "Fintech", color: "var(--series-1)", ys: R.curve.fintech_breakeven.map((v) => v * 100) },
      ],
      envelope: capacityPct,
      yMax,
      envelopeLabel: "Deal works here",
      cap: { x: inp.dlg_cap * 100, label: "RBI cap", zoneLabel: "Not allowed above the cap" },
      hline: { y: inp.default_rate * 100, label: "Expected defaults" },
      points,
      xFormat: (v) => fix(v, 0) + "%",
      yFormat: (v) => fix(v, 0) + "%",
      xTitle: "Guarantee, as a share of loans disbursed",
      yTitle: "Highest default rate survived",
      tipTitle: (x) => `Guarantee of ${x.toFixed(2)}%`,
      tipValue: (y) => (y >= 59.9 ? "any default rate" : `up to ${y.toFixed(1)}%`),
    });

    const capCost = R.free[1] - R.best[1];
    let sentence = `Within the RBI cap, the best guarantee is **${pct(R.best[0], 2)}**. ` +
      `The deal then survives a default rate of up to **${pct(R.best[1])}**. `;
    sentence += capCost > 0.0005
      ? `Without the cap, a guarantee of ${pct(R.free[0], 2)} would stretch that to ${pct(R.free[1])}, ` +
        `so the cap costs **${fix(capCost * 100, 1)} percentage points** of risk the partnership could otherwise take.`
      : "The cap is not what holds this deal back. The fintech's own margin is.";
    rich($("capacityFinding"), sentence);
  }

  // ---------- drawing: combined view ----------
  function renderCombined() {
    const models = Object.keys(MODEL_LABEL).filter((m) => D.damages[m]);
    segmented($("modelSeg"), models.map((m) => [m, MODEL_LABEL[m]]), state.model, (m) => {
      state.model = m;
      scheduleModel();
    });
    $("passThroughOut").textContent = state.passThrough.toFixed(2) + "×";
    setFill($("passThrough"));

    C.histogram($("histChart"), {
      ariaLabel: "Simulated partnership values",
      values: R.sims,
      bins: 36,
      color: "var(--series-1)",
      markers: [
        { x: R.baseNpv, label: "Ignoring regulation" },
        { x: R.sim.average, label: "Average" },
        { x: R.sim.worst_5_percent, label: "1-in-20 bad outcome" },
      ],
      xFormat: (v) => (v < 0 ? MINUS : "") + "₹" + Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 1 }),
      xTitle: "Value of the partnership to the fintech (₹ crore)",
    });
    $("simBase").textContent = crore(R.baseNpv);
    $("simMean").textContent = crore(R.sim.average);
    $("simWorst").textContent = crore(R.sim.worst_5_percent);
    $("simLoss").textContent = pct(R.sim.chance_of_loss, 0);

    const profitable = R.baseNpv > 0;
    table($("scenarioTable"),
      [{ label: "Scenario" }, { label: "Lender return", num: true }, { label: "New sourcing fee", num: true },
        { label: "Fintech profit / ₹100", num: true }, { label: "Survives defaults up to", num: true },
        { label: "Value", num: true }, { label: "Change", num: true }],
      R.scenarios.map((s, i) => {
        const change = make("span");
        if (i === 0) chip(change, "Base case", "");
        else if (!profitable) chip(change, "n/a", "");
        else chip(change, signed(pct(s.npv_change)), s.npv_change < -0.0005 ? "bad" : s.npv_change > 0.0005 ? "good" : "");
        const fee = make("span", Math.abs(s.sourcing_fee_after - state.inp.sourcing_fee) > 1e-9 ? "" : "muted",
          pct(s.sourcing_fee_after, 2));
        return { className: i === 0 ? "base" : "", cells: [
          { text: s.scenario, strong: true },
          { text: pct(s.lender_roa_before_repricing, 2) },
          { node: fee },
          { text: "₹" + fix(s.fintech_profit_per_100, 2) },
          { text: pct(s.max_default_rate) },
          { text: crore(s.fintech_npv) },
          { node: change },
        ] };
      }));

    const finding = $("combinedFinding");
    if (!profitable) {
      rich(finding, "At these assumptions the partnership **does not make money** even before regulatory risk. " +
        "Lower the guarantee or the default rate, or raise the fees.");
      return;
    }
    const worst = R.scenarios.slice(1).sort((a, b) => a.npv_change - b.npv_change)[0];
    rich(finding, `Regulatory risk takes **${pct(Math.abs(R.adjNpv / R.baseNpv - 1))}** off the value of this partnership ` +
      `on average (${crore(R.baseNpv)} to ${crore(R.adjNpv)}). The most damaging rule change tested is ` +
      `**${worst.scenario.charAt(0).toLowerCase() + worst.scenario.slice(1)}**, at ${signed(pct(worst.npv_change))}. ` +
      `Lender return is shown before any fee cut, and the default rate survived is measured at the original fee.`);
  }

  // ---------- putting it together ----------
  let pending = false;
  function scheduleModel() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      compute();
      renderKpis();
      renderDeal();
      renderCombined();
    });
  }

  function init() {
    buildControls();
    renderStatic();
    renderTimeline();
    renderEvent();
    renderSummary();
    compute();
    renderKpis();
    renderDeal();
    renderCombined();

    $("resetBtn").addEventListener("click", () => {
      state.inp = Object.assign({}, D.defaults);
      state.size = Object.assign({}, DEFAULT_SIZE);
      buildControls();
      scheduleModel();
    });
    $("passThrough").addEventListener("input", (e) => {
      state.passThrough = +e.target.value;
      scheduleModel();
    });
    $("viewSeg").querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        state.view = button.dataset.view;
        $("viewSeg").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
        renderEvent();
      });
    });
    const ordered = D.events.slice().sort((a, b) => a.date.localeCompare(b.date));
    const step = (by) => {
      const i = ordered.findIndex((e) => e.id === state.eventId);
      selectEvent(ordered[(i + by + ordered.length) % ordered.length].id);
    };
    $("prevEvent").addEventListener("click", () => step(-1));
    $("nextEvent").addEventListener("click", () => step(1));

    $("themeToggle").addEventListener("click", () => {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("regrisk-theme", next); } catch (e) { /* private window: ignore */ }
    });

    // redraw the charts when the page width changes
    let lastWidth = window.innerWidth;
    let timer = null;
    window.addEventListener("resize", () => {
      if (window.innerWidth === lastWidth) return;
      lastWidth = window.innerWidth;
      clearTimeout(timer);
      timer = setTimeout(() => { renderTimeline(); renderEvent(); renderDeal(); renderCombined(); }, 120);
    });
  }

  init();
})();
