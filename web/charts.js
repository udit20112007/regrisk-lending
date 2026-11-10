/*
 * CHARTS
 * ======
 * Small hand-written SVG charts, so the page needs no chart library:
 *   Charts.bars       horizontal bars around a zero line
 *   Charts.lines      line chart with a crosshair
 *   Charts.histogram  columns with marker lines
 *   Charts.timeline   dots on a time axis that can be selected
 * Colours come from CSS variables, so light and dark mode need no redraw.
 */
(function (root) {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";

  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    for (const key in attrs) node.setAttribute(key, attrs[key]);
    if (parent) parent.appendChild(node);
    return node;
  }

  function text(parent, x, y, content, attrs) {
    const node = el("text", Object.assign({ x, y }, attrs || {}), parent);
    node.textContent = content;
    return node;
  }

  function start(container, height) {
    container.textContent = "";
    const width = Math.max(260, container.clientWidth);
    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, height, role: "img" }, container);
    return { svg, width };
  }

  // Round numbers for axis ticks: 0, 2, 4... or 0, 50, 100...
  function niceTicks(min, max, target) {
    const span = max - min || 1;
    const raw = span / Math.max(1, target);
    const power = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) || raw;
    const ticks = [];
    for (let v = Math.ceil(min / step - 1e-9) * step; v <= max + 1e-9; v += step) ticks.push(Math.abs(v) < 1e-12 ? 0 : v);
    return ticks;
  }

  // ---------- tooltip ----------
  const tipNode = () => document.getElementById("tooltip");

  function showTip(clientX, clientY, title, rows) {
    const tip = tipNode();
    tip.textContent = "";
    if (title) {
      const head = document.createElement("div");
      head.className = "tt-title";
      head.textContent = title;
      tip.appendChild(head);
    }
    rows.forEach((row) => {
      const line = document.createElement("div");
      line.className = "tt-row";
      const label = document.createElement("span");
      if (row.key) {
        const key = document.createElement("i");
        key.className = "tt-key";
        key.style.background = row.key;
        label.appendChild(key);
      }
      label.appendChild(document.createTextNode(row.label));
      const value = document.createElement("b");
      value.textContent = row.value;
      line.appendChild(label);
      line.appendChild(value);
      tip.appendChild(line);
    });
    tip.hidden = false;
    const box = tip.getBoundingClientRect();
    let x = clientX + 14;
    let y = clientY + 14;
    if (x + box.width > window.innerWidth - 8) x = clientX - box.width - 14;
    if (y + box.height > window.innerHeight - 8) y = clientY - box.height - 14;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  }

  function hideTip() {
    tipNode().hidden = true;
  }

  // Show a tooltip on hover and on keyboard focus.
  function attachTip(node, getContent) {
    node.addEventListener("pointermove", (e) => {
      const c = getContent();
      showTip(e.clientX, e.clientY, c.title, c.rows);
    });
    node.addEventListener("pointerleave", hideTip);
    node.addEventListener("focus", () => {
      const box = node.getBoundingClientRect();
      const c = getContent();
      showTip(box.left + box.width / 2, box.top + box.height / 2, c.title, c.rows);
    });
    node.addEventListener("blur", hideTip);
  }

  // A bar with a rounded data end and a square end at the baseline.
  function barPath(x0, x1, y, h) {
    const w = Math.abs(x1 - x0);
    const r = Math.min(4, w, h / 2);
    const d = x1 >= x0 ? 1 : -1;
    return `M${x0},${y} H${x1 - d * r} Q${x1},${y} ${x1},${y + r} V${y + h - r} Q${x1},${y + h} ${x1 - d * r},${y + h} H${x0} Z`;
  }

  // ---------- horizontal bars ----------
  // rows: [{ label, value, color, title, tipRows }]
  function bars(container, opts) {
    const rows = opts.rows;
    const rowH = 30;
    const barH = 14;
    const top = 6;
    const bottom = 30;
    const height = top + rows.length * rowH + bottom;
    const { svg, width } = start(container, height);
    svg.setAttribute("aria-label", opts.ariaLabel || "Bar chart");

    const longest = rows.reduce((m, r) => Math.max(m, r.label.length), 0);
    const labelW = Math.min(150, Math.max(64, longest * 7.4 + 8));
    const x0 = labelW + 10;
    const x1 = width - 8;

    let min = Math.min(0, ...rows.map((r) => r.value));
    let max = Math.max(0, ...rows.map((r) => r.value));
    if (min === max) max = min + 1;
    // leave a fixed gutter at each end so the value labels at the bar tips always fit
    const gutter = 52;
    const b0 = x0 + (min < 0 ? gutter : 0);
    const b1 = x1 - (max > 0 ? gutter : 8);
    const sx = (v) => b0 + ((v - min) / (max - min)) * (b1 - b0);

    const plotBottom = top + rows.length * rowH;
    niceTicks(min, max, Math.max(2, Math.min(6, Math.floor((b1 - b0) / 64)))).forEach((t) => {
      el("line", { x1: sx(t), x2: sx(t), y1: top, y2: plotBottom, class: t === 0 ? "baseline" : "gridline" }, svg);
      text(svg, sx(t), plotBottom + 18, opts.tickFormat(t), { "text-anchor": "middle" });
    });

    rows.forEach((row, i) => {
      const yMid = top + i * rowH + rowH / 2;
      const group = el("g", {}, svg);
      text(group, labelW, yMid + 4, row.label, { "text-anchor": "end", class: "label" });
      const tip = sx(row.value);
      el("path", { d: barPath(sx(0), tip, yMid - barH / 2, barH), class: "mark", style: `fill:${row.color}` }, group);
      const positive = row.value >= 0;
      text(group, tip + (positive ? 6 : -6), yMid + 4, opts.valueFormat(row.value),
        { "text-anchor": positive ? "start" : "end", class: "value" });
      const hit = el("rect", { x: 0, y: yMid - rowH / 2, width, height: rowH, class: "hit", tabindex: 0,
        role: "img", "aria-label": `${row.title}: ${opts.valueFormat(row.value)}` }, group);
      const on = () => { svg.classList.add("dim"); group.querySelector(".mark").classList.add("on"); };
      const off = () => { svg.classList.remove("dim"); group.querySelector(".mark").classList.remove("on"); };
      hit.addEventListener("pointerenter", on);
      hit.addEventListener("pointerleave", off);
      hit.addEventListener("focus", on);
      hit.addEventListener("blur", off);
      attachTip(hit, () => ({ title: row.title, rows: row.tipRows }));
    });
    if (opts.axisTitle) text(svg, (x0 + x1) / 2, height - 0, opts.axisTitle, { "text-anchor": "middle" });
  }

  // ---------- line chart ----------
  // opts: xs, series [{name, color, ys}], yMax, xFormat, yFormat, xTitle, yTitle,
  //       cap {x, label}, hline {y, label}, envelope [ys], points [{x, y, label, hollow}]
  function lines(container, opts) {
    const height = 340;
    const { svg, width } = start(container, height);
    svg.setAttribute("aria-label", opts.ariaLabel || "Line chart");
    const m = { left: 40, right: 14, top: 30, bottom: 44 };
    const px0 = m.left, px1 = width - m.right, py0 = m.top, py1 = height - m.bottom;
    const xMin = opts.xs[0], xMax = opts.xs[opts.xs.length - 1];
    const sx = (v) => px0 + ((v - xMin) / (xMax - xMin)) * (px1 - px0);
    const sy = (v) => py1 - (Math.min(v, opts.yMax * 1.5) / opts.yMax) * (py1 - py0);

    const clipId = "clip" + Math.random().toString(36).slice(2);
    const clip = el("clipPath", { id: clipId }, el("defs", {}, svg));
    el("rect", { x: px0, y: py0 - 4, width: px1 - px0, height: py1 - py0 + 4 }, clip);

    // the part of the chart above the cap is not allowed
    if (opts.cap && opts.cap.x < xMax) {
      el("rect", { x: sx(opts.cap.x), y: py0, width: px1 - sx(opts.cap.x), height: py1 - py0, class: "zone" }, svg);
    }
    niceTicks(0, opts.yMax, 5).forEach((t) => {
      el("line", { x1: px0, x2: px1, y1: sy(t), y2: sy(t), class: t === 0 ? "baseline" : "gridline" }, svg);
      text(svg, px0 - 8, sy(t) + 4, opts.yFormat(t), { "text-anchor": "end" });
    });
    niceTicks(xMin, xMax, width < 520 ? 5 : 10).forEach((t) => {
      text(svg, sx(t), py1 + 18, opts.xFormat(t), { "text-anchor": "middle" });
    });
    text(svg, (px0 + px1) / 2, height - 4, opts.xTitle, { "text-anchor": "middle" });
    text(svg, 0, 12, opts.yTitle, {});

    // shaded area: where the deal works (under both lines, up to the cap)
    if (opts.envelope) {
      const limit = opts.cap ? opts.cap.x : xMax;
      const pts = opts.xs.map((x, i) => [x, opts.envelope[i]]).filter((p) => p[0] <= limit + 1e-9);
      if (pts.length > 1) {
        const d = "M" + pts.map((p) => `${sx(p[0])},${sy(p[1])}`).join(" L") +
          ` L${sx(pts[pts.length - 1][0])},${py1} L${sx(pts[0][0])},${py1} Z`;
        el("path", { d, class: "wash", "clip-path": `url(#${clipId})` }, svg);
        const last = pts[pts.length - 1];
        if (opts.envelopeLabel && last[1] > opts.yMax * 0.14 && sx(last[0]) - px0 > 130) {
          text(svg, sx(last[0]) - 10, py1 - 10, opts.envelopeLabel, { "text-anchor": "end", class: "marker-text halo-text" });
        }
      }
    }
    if (opts.cap && opts.cap.zoneLabel && sx(opts.cap.x) < px1 - 150) {
      text(svg, px1 - 8, py0 + 16, opts.cap.zoneLabel, { "text-anchor": "end", class: "marker-text" });
    }
    if (opts.hline) {
      el("line", { x1: px0, x2: px1, y1: sy(opts.hline.y), y2: sy(opts.hline.y), class: "marker-line" }, svg);
      text(svg, px1 - 4, sy(opts.hline.y) - 6, opts.hline.label, { "text-anchor": "end", class: "marker-text" });
    }
    if (opts.cap) {
      el("line", { x1: sx(opts.cap.x), x2: sx(opts.cap.x), y1: py0 - 8, y2: py1, class: "marker-line" }, svg);
      const nearRight = sx(opts.cap.x) > px1 - 120;
      text(svg, sx(opts.cap.x) + (nearRight ? -6 : 6), py0 - 10, opts.cap.label,
        { "text-anchor": nearRight ? "end" : "start", class: "marker-text" });
    }
    opts.series.forEach((s) => {
      const d = "M" + opts.xs.map((x, i) => `${sx(x)},${sy(s.ys[i])}`).join(" L");
      el("path", { d, fill: "none", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round",
        style: `stroke:${s.color}`, "clip-path": `url(#${clipId})` }, svg);
    });
    (opts.points || []).forEach((p) => {
      const cy = Math.max(py0, sy(p.y));
      el("circle", { cx: sx(p.x), cy, r: 5.5, style: `fill:${p.hollow ? "var(--surface)" : "var(--text)"};stroke:${p.hollow ? "var(--text)" : "var(--surface)"};stroke-width:2` }, svg);
      let left = p.side === "left";
      if (sx(p.x) > px1 - 110) left = true;
      if (sx(p.x) < px0 + 110) left = false;
      const below = cy + 34 < py1;                 // if the point is near the axis, label above instead
      text(svg, sx(p.x) + (left ? -10 : 10), cy + (below ? 20 : -12), p.label,
        { "text-anchor": left ? "end" : "start", class: "value halo-text" });
    });

    // crosshair: snaps to the nearest guarantee level and lists both lines
    const cross = el("g", { style: "display:none" }, svg);
    const crossLine = el("line", { y1: py0, y2: py1, class: "crosshair" }, cross);
    const dots = opts.series.map((s) => el("circle", { r: 4.5, style: `fill:${s.color};stroke:var(--surface);stroke-width:2` }, cross));
    const overlay = el("rect", { x: px0, y: py0, width: px1 - px0, height: py1 - py0, class: "hit" }, svg);
    overlay.addEventListener("pointermove", (e) => {
      const box = svg.getBoundingClientRect();
      const xv = xMin + ((e.clientX - box.left - px0) / (px1 - px0)) * (xMax - xMin);
      let i = 0;
      opts.xs.forEach((x, k) => { if (Math.abs(x - xv) < Math.abs(opts.xs[i] - xv)) i = k; });
      cross.style.display = "";
      crossLine.setAttribute("x1", sx(opts.xs[i]));
      crossLine.setAttribute("x2", sx(opts.xs[i]));
      dots.forEach((dot, k) => {
        const y = opts.series[k].ys[i];
        dot.setAttribute("cx", sx(opts.xs[i]));
        dot.setAttribute("cy", sy(y));
        dot.style.display = y > opts.yMax ? "none" : "";
      });
      showTip(e.clientX, e.clientY, opts.tipTitle(opts.xs[i]),
        opts.series.map((s) => ({ key: s.color, label: s.name, value: opts.tipValue(s.ys[i]) })));
    });
    overlay.addEventListener("pointerleave", () => { cross.style.display = "none"; hideTip(); });
  }

  // ---------- histogram ----------
  // opts: values, bins, markers [{x, label}], xFormat, color
  function histogram(container, opts) {
    const height = 300;
    const { svg, width } = start(container, height);
    svg.setAttribute("aria-label", opts.ariaLabel || "Histogram");
    const m = { left: 40, right: 14, top: 16 + opts.markers.length * 16, bottom: 44 };
    const px0 = m.left, px1 = width - m.right, py0 = m.top, py1 = height - m.bottom;

    let lo = Math.min(...opts.values, ...opts.markers.map((k) => k.x));
    let hi = Math.max(...opts.values, ...opts.markers.map((k) => k.x));
    if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
    const padX = (hi - lo) * 0.03;
    lo -= padX; hi += padX;
    const bins = opts.bins;
    const counts = new Array(bins).fill(0);
    opts.values.forEach((v) => { counts[Math.min(bins - 1, Math.floor(((v - lo) / (hi - lo)) * bins))]++; });
    const top = Math.max(...counts);
    const sx = (v) => px0 + ((v - lo) / (hi - lo)) * (px1 - px0);
    const sy = (c) => py1 - (c / top) * (py1 - py0);

    niceTicks(0, top, 4).forEach((t) => {
      el("line", { x1: px0, x2: px1, y1: sy(t), y2: sy(t), class: t === 0 ? "baseline" : "gridline" }, svg);
      text(svg, px0 - 8, sy(t) + 4, String(Math.round(t)), { "text-anchor": "end" });
    });
    niceTicks(lo, hi, width < 520 ? 4 : 7).forEach((t) => {
      text(svg, sx(t), py1 + 18, opts.xFormat(t), { "text-anchor": "middle" });
    });
    text(svg, (px0 + px1) / 2, height - 4, opts.xTitle, { "text-anchor": "middle" });

    const colW = (px1 - px0) / bins;
    counts.forEach((c, i) => {
      if (!c) return;
      const x = px0 + i * colW + 1;                     // 2px gap between columns
      const w = Math.max(1, colW - 2);
      const y = sy(c);
      const r = Math.min(3, w / 2, py1 - y);
      const d = `M${x},${py1} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${py1} Z`;
      const group = el("g", {}, svg);
      el("path", { d, class: "mark", style: `fill:${opts.color}` }, group);
      const hit = el("rect", { x: px0 + i * colW, y: py0, width: colW, height: py1 - py0, class: "hit" }, group);
      const from = lo + ((hi - lo) * i) / bins;
      const to = lo + ((hi - lo) * (i + 1)) / bins;
      hit.addEventListener("pointerenter", () => { svg.classList.add("dim"); group.firstChild.classList.add("on"); });
      hit.addEventListener("pointerleave", () => { svg.classList.remove("dim"); group.firstChild.classList.remove("on"); });
      attachTip(hit, () => ({
        title: `${opts.xFormat(from)} to ${opts.xFormat(to)}`,
        rows: [{ label: "Simulated futures", value: `${c} (${((100 * c) / opts.values.length).toFixed(1)}%)` }],
      }));
    });

    // marker lines, each with its label on its own row so they never collide
    opts.markers.forEach((k, i) => {
      const x = sx(k.x);
      const labelY = 12 + i * 16;
      el("line", { x1: x, x2: x, y1: labelY + 4, y2: py1, class: "marker-line" }, svg);
      const right = x > (px0 + px1) / 2;
      text(svg, x + (right ? -6 : 6), labelY, k.label, { "text-anchor": right ? "end" : "start", class: "marker-text" });
    });
  }

  // ---------- timeline ----------
  // opts: events [{id, time, direction, title, dateLabel}], selected, onSelect
  function timeline(container, opts) {
    const px0 = 14, px1 = Math.max(260, container.clientWidth) - 14;
    const years = opts.events.map((e) => new Date(e.time).getUTCFullYear());
    const firstYear = Math.min(...years), lastYear = Math.max(...years);
    const t0 = Date.UTC(firstYear, 0, 1), t1 = Date.UTC(lastYear + 1, 0, 1);
    const sx = (t) => px0 + ((t - t0) / (t1 - t0)) * (px1 - px0);

    // dots that would overlap are stacked upwards; work out how tall the stack gets
    const sorted = opts.events.slice().sort((a, b) => a.time - b.time);
    const levels = [];
    let lastX = -Infinity, level = 0;
    sorted.forEach((ev) => {
      const x = sx(ev.time);
      level = x - lastX < 17 ? level + 1 : 0;
      lastX = x;
      levels.push(level);
    });
    const extra = Math.max(0, Math.max(...levels) - 2) * 17;
    const axisY = 62 + extra;
    const { svg } = start(container, 96 + extra);
    svg.setAttribute("role", "group");
    svg.setAttribute("aria-label", "Timeline of RBI actions");

    el("line", { x1: px0, x2: px1, y1: axisY, y2: axisY, class: "baseline" }, svg);
    for (let y = firstYear; y <= lastYear + 1; y++) {
      const x = sx(Date.UTC(y, 0, 1));
      el("line", { x1: x, x2: x, y1: axisY - 4, y2: axisY + 4, class: "baseline" }, svg);
      if (y <= lastYear) text(svg, (x + sx(Date.UTC(y + 1, 0, 1))) / 2, axisY + 24, String(y), { "text-anchor": "middle" });
    }

    sorted.forEach((ev, i) => {
      const x = sx(ev.time);
      const level = levels[i];
      const cy = axisY - 20 - level * 17;
      const cls = ["tl-dot", ev.direction, ev.id === opts.selected ? "selected" : ""].join(" ");
      const group = el("g", { class: cls, tabindex: 0, role: "button", "aria-pressed": ev.id === opts.selected,
        "aria-label": `${ev.dateLabel}: ${ev.title}` }, svg);
      if (level === 0) el("line", { x1: x, x2: x, y1: cy + 7, y2: axisY, class: "gridline" }, group);
      el("circle", { cx: x, cy, r: 13, class: "halo" }, group);
      el("circle", { cx: x, cy, r: 5.5, class: "shape" }, group);
      el("circle", { cx: x, cy, r: 13, class: "hit" }, group);
      group.addEventListener("click", () => opts.onSelect(ev.id));
      group.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); opts.onSelect(ev.id); }
      });
      attachTip(group, () => ({ title: ev.dateLabel, rows: [{ label: ev.title, value: "" }] }));
    });
  }

  root.Charts = { bars, lines, histogram, timeline, hideTip };
})(window);
