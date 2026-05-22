/* ydocter — Clinical Ledger UI
 * Vanilla JS. Fetches /items and /measurements (same origin),
 * renders the editorial table + per-row sparklines, and pops
 * a detail panel with a reference-banded trend chart on click.
 */

const ALL_YEARS = [2015, 2019, 2021, 2023, 2024, 2025];

const state = {
  items: [],                // raw list from /items
  byItem: new Map(),        // item_id -> { item, points: Map(year -> measurement) }
  latestYear: 2025,         // recomputed after load
  filter: { major: null, search: "" },
  activeItemId: null,
  layout: null,             // current viewport-dependent layout (see computeLayout)
};

/* Decide which year columns + auxiliary columns to render based on the
 * current viewport width. We choose the *latest* N years so the most
 * relevant readings are always visible. The grid template string is
 * baked in here so each section-table is laid out with no horizontal
 * overflow — and therefore no drag. */
function computeLayout() {
  const w = document.documentElement.clientWidth;
  if (w >= 1100) return {
    years: ALL_YEARS,
    ref: true, spark: true,
    cols: "minmax(220px, 2.4fr) minmax(108px, 1fr) repeat(6, minmax(60px, 1fr)) minmax(90px, 1.2fr)",
  };
  if (w >= 860) return {
    years: ALL_YEARS.slice(-5),
    ref: true, spark: true,
    cols: "minmax(180px, 2fr) minmax(92px, 0.9fr) repeat(5, minmax(54px, 1fr)) minmax(70px, 1fr)",
  };
  if (w >= 680) return {
    years: ALL_YEARS.slice(-4),
    ref: true, spark: true,
    cols: "minmax(150px, 1.7fr) minmax(76px, 0.9fr) repeat(4, minmax(50px, 1fr)) minmax(60px, 0.9fr)",
  };
  if (w >= 520) return {
    years: ALL_YEARS.slice(-3),
    ref: true, spark: false,
    cols: "minmax(140px, 1.6fr) minmax(70px, 0.9fr) repeat(3, minmax(54px, 1fr))",
  };
  if (w >= 380) return {
    years: ALL_YEARS.slice(-3),
    ref: false, spark: false,
    cols: "minmax(118px, 1.5fr) repeat(3, minmax(52px, 1fr))",
  };
  return {
    years: ALL_YEARS.slice(-2),
    ref: false, spark: false,
    cols: "minmax(108px, 1.4fr) repeat(2, minmax(58px, 1fr))",
  };
}

function layoutChanged(a, b) {
  if (!a || !b) return true;
  return a.years.length !== b.years.length
      || a.ref !== b.ref
      || a.spark !== b.spark;
}

document.addEventListener("DOMContentLoaded", boot);

async function boot() {
  try {
    await Profile.init({ onChange: reload });
    bindControls();
    await reload();
  } catch (err) {
    console.error(err);
    document.getElementById("ledger").innerHTML =
      `<p class="empty-state">Failed to load data — is the server running?<br><code>${err}</code></p>`;
  }
}

async function reload() {
  const slug = Profile.current();
  state.items = [];
  state.byItem = new Map();
  state.activeItemId = null;
  closeDetail();

  const qs = slug ? `?profile=${encodeURIComponent(slug)}` : "";
  const [items, measurements] = await Promise.all([
    cachedFetch(`/items${qs}`),
    cachedFetch(`/measurements${qs}`),
  ]);
  state.items = items;

  items.forEach((it) => state.byItem.set(it.id, { item: it, points: new Map() }));
  measurements.forEach((m) => {
    const entry = state.byItem.get(m.item_id);
    if (entry) entry.points.set(m.year, m);
  });
  state.latestYear =
    measurements.reduce((a, b) => Math.max(a, b.year), 0) || 2025;

  renderRail();
  renderHeadlines();
  renderChips();
  renderLedger();
}

function must(r) {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

/* -------------------- rail (top metadata) -------------------- */
function totalMeasurementCount() {
  return [...state.byItem.values()].reduce((acc, e) => acc + e.points.size, 0);
}

function renderRail() {
  document.getElementById("rail-items").textContent = String(state.items.length);
  const measureCount = totalMeasurementCount();
  document.getElementById("rail-measurements").textContent = String(measureCount);
  document.getElementById("rail-latest").textContent =
    measureCount > 0 ? String(state.latestYear) : "—";
}

/* -------------------- headlines (summary) -------------------- */
function renderHeadlines() {
  const totalMeasurements = totalMeasurementCount();
  const empty = totalMeasurements === 0;
  const y = state.latestYear;
  const tag = empty ? "no data" : `at ’${String(y).slice(2)}`;
  document.getElementById("headline-high-year").textContent = tag;
  document.getElementById("headline-low-year").textContent  = tag;
  document.getElementById("headline-coverage-year").textContent = tag;

  let high = 0, low = 0, coverage = 0;
  if (!empty) {
    for (const { points } of state.byItem.values()) {
      const m = points.get(y);
      if (m) {
        coverage++;
        if (m.status === "HIGH") high++;
        else if (m.status === "LOW") low++;
      }
    }
  }
  document.getElementById("count-high").textContent = empty ? "—" : high;
  document.getElementById("count-low").textContent  = empty ? "—" : low;
  document.getElementById("count-coverage").textContent = empty ? "—" : coverage;
  document.getElementById("count-total").textContent    = state.items.length;

  /* watch list: indicators that have been HIGH or LOW in 2+ of the
     last three measured years */
  const recent = [2025, 2024, 2023, 2021].filter((yr) =>
    [...state.byItem.values()].some((e) => e.points.has(yr)),
  ).slice(0, 3);

  const watch = [];
  for (const [id, e] of state.byItem) {
    const offenses = recent
      .map((yr) => e.points.get(yr))
      .filter((m) => m && (m.status === "HIGH" || m.status === "LOW"));
    if (offenses.length >= 2) {
      const last = offenses[0] ?? offenses[offenses.length - 1];
      watch.push({ id, item: e.item, count: offenses.length, last });
    }
  }
  watch.sort((a, b) =>
    (b.count - a.count) ||
    (Math.abs(b.last?.value_numeric ?? 0) - Math.abs(a.last?.value_numeric ?? 0)),
  );

  const watchEl = document.getElementById("watchlist");
  watchEl.innerHTML = "";
  watch.slice(0, 4).forEach((w) => {
    const li = document.createElement("li");
    const statusClass = w.last?.status === "LOW" ? "value--low" : "value--high";
    li.innerHTML = `
      <div>
        <span class="name">${escape(w.item.name)}</span>
        <span class="name-secondary">${escape(w.item.code || w.item.minor_category)}</span>
      </div>
      <span class="value ${statusClass}">${escape(w.last?.value_text ?? "—")}</span>
      <span class="count">×${w.count}</span>
    `;
    li.addEventListener("click", () => openDetail(w.id));
    watchEl.appendChild(li);
  });

  if (watch.length === 0) {
    const msg = empty
      ? "No measurements yet — start by editing seed_data.py or via the API."
      : "All clear — no recurring anomalies.";
    watchEl.innerHTML = `<li style="grid-template-columns:1fr"><span class="name" style="color:var(--ink-mute);">${msg}</span></li>`;
  }
}

/* -------------------- chips (category filter) -------------------- */
function renderChips() {
  const majors = [...new Set(state.items.map((i) => i.major_category))];
  const chipset = document.getElementById("chipset");
  chipset.innerHTML = "";

  const all = document.createElement("button");
  all.className = "chip";
  all.dataset.major = "";
  all.setAttribute("role", "tab");
  all.setAttribute("aria-selected", "true");
  all.textContent = `All · ${state.items.length}`;
  chipset.appendChild(all);

  majors.forEach((m) => {
    const c = document.createElement("button");
    c.className = "chip";
    c.dataset.major = m;
    c.setAttribute("role", "tab");
    c.setAttribute("aria-selected", "false");
    const count = state.items.filter((i) => i.major_category === m).length;
    c.textContent = `${m} · ${count}`;
    chipset.appendChild(c);
  });

  chipset.addEventListener("click", (e) => {
    const target = e.target.closest(".chip");
    if (!target) return;
    chipset.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-selected", "false"));
    target.setAttribute("aria-selected", "true");
    state.filter.major = target.dataset.major || null;
    renderLedger();
  });
}

/* -------------------- ledger (big table) -------------------- */
function renderLedger() {
  const layout = state.layout || (state.layout = computeLayout());
  const ledger = document.getElementById("ledger");
  ledger.innerHTML = "";

  let items = state.items;
  if (state.filter.major) items = items.filter((i) => i.major_category === state.filter.major);
  if (state.filter.search) {
    const q = state.filter.search.toLowerCase().trim();
    if (q) {
      items = items.filter((i) =>
        (i.name || "").toLowerCase().includes(q) ||
        (i.code || "").toLowerCase().includes(q) ||
        (i.related_diseases || "").toLowerCase().includes(q) ||
        (i.minor_category || "").toLowerCase().includes(q),
      );
    }
  }

  if (items.length === 0) {
    ledger.innerHTML = `<p class="empty-state">No indicators match — try a different keyword.</p>`;
    return;
  }

  /* group by major_category, preserving order of first appearance */
  const groups = new Map();
  items.forEach((it) => {
    if (!groups.has(it.major_category)) groups.set(it.major_category, []);
    groups.get(it.major_category).push(it);
  });

  let gi = 0;
  for (const [major, list] of groups) {
    const section = document.createElement("section");
    section.className = "section rise";
    section.style.animationDelay = `${gi * 40}ms`;
    gi++;

    const head = document.createElement("div");
    head.className = "section-head";
    head.innerHTML = `
      <h2 class="section-title">${escape(major)}</h2>
      <span class="section-meta">${list.length} ${list.length === 1 ? "indicator" : "indicators"}</span>
    `;
    section.appendChild(head);

    const grid = document.createElement("div");
    grid.className = "section-table";
    grid.style.gridTemplateColumns = layout.cols;

    const headrow = document.createElement("div");
    headrow.className = "section-headrow";
    headrow.innerHTML = [
      `<div class="head-indicator">Indicator</div>`,
      layout.ref   ? `<div class="head-ref">Reference</div>` : "",
      ...layout.years.map((y) => `<div>’${String(y).slice(2)}</div>`),
      layout.spark ? `<div class="head-spark">Trend</div>` : "",
    ].filter(Boolean).join("");
    grid.appendChild(headrow);

    list.forEach((it) => {
      const row = document.createElement("div");
      row.className = "section-row";
      row.dataset.itemId = it.id;
      if (state.activeItemId === it.id) row.classList.add("is-active");

      const entry = state.byItem.get(it.id);
      const yearCells = layout.years.map((y) => {
        const m = entry.points.get(y);
        if (!m) return `<div class="cell-year empty">—</div>`;
        const v = m.value_text ?? (m.value_numeric != null ? formatNum(m.value_numeric) : "—");
        return `<div class="cell-year" data-status="${m.status ?? ""}">${escape(v)}</div>`;
      }).join("");

      row.innerHTML = [
        `<div class="cell-indicator">
           <span class="primary">${escape(it.name)}</span>
           <span class="secondary">${escape(it.code || "")}${
             it.minor_category && it.minor_category !== major
               ? ` · ${escape(it.minor_category)}` : ""
           }</span>
         </div>`,
        layout.ref   ? `<div class="cell-ref">${formatRef(it)}</div>` : "",
        yearCells,
        layout.spark ? `<div class="cell-spark">${sparkline(entry, it)}</div>` : "",
      ].filter(Boolean).join("");

      row.addEventListener("click", () => openDetail(it.id));
      [...row.children].forEach((c) => c.addEventListener("click", (e) => {
        e.stopPropagation();
        openDetail(it.id);
      }));
      grid.appendChild(row);
    });

    section.appendChild(grid);
    ledger.appendChild(section);
  }
}

/* -------------------- reference formatting -------------------- */
function formatRef(item) {
  const min = item.ref_min, max = item.ref_max;
  if (min != null && max != null) return `<span>${formatNum(min)}–${formatNum(max)}</span>`;
  if (min != null) return `<span>≥ ${formatNum(min)}</span>`;
  if (max != null) return `<span>≤ ${formatNum(max)}</span>`;
  if (item.ref_indicator) return `<span class="ref-note">see notes</span>`;
  return `<span class="ref-note">—</span>`;
}

function formatNum(v) {
  if (v == null) return "—";
  if (Number.isInteger(v)) return String(v);
  return parseFloat(v.toFixed(3)).toString();
}

function escape(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* -------------------- sparklines (per-row tufte) -------------------- */
function sparkline(entry, item) {
  const numeric = ALL_YEARS
    .map((y) => {
      const m = entry.points.get(y);
      return m && m.value_numeric != null
        ? { year: y, v: m.value_numeric, status: m.status }
        : null;
    })
    .filter(Boolean);

  if (numeric.length < 2) {
    return `<span style="color:var(--ink-faint);font-family:var(--mono);font-size:0.7rem;">—</span>`;
  }

  const W = 100, H = 28, P = 3;
  const vals = numeric.map((p) => p.v);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (item.ref_min != null) lo = Math.min(lo, item.ref_min);
  if (item.ref_max != null) hi = Math.max(hi, item.ref_max);
  if (hi === lo) { hi = lo + 1; lo = lo - 1; }

  const x = (year) => P + (ALL_YEARS.indexOf(year) / (ALL_YEARS.length - 1)) * (W - 2 * P);
  const y = (v)    => H - P - ((v - lo) / (hi - lo)) * (H - 2 * P);

  let band = "";
  if (item.ref_min != null && item.ref_max != null) {
    const y1 = y(item.ref_max), y2 = y(item.ref_min);
    band = `<rect x="${P}" y="${Math.min(y1,y2).toFixed(1)}" width="${(W - 2*P).toFixed(1)}" height="${Math.abs(y2-y1).toFixed(1)}" fill="rgba(30,106,53,0.10)"/>`;
  } else if (item.ref_max != null) {
    const y1 = y(item.ref_max);
    band = `<line x1="${P}" y1="${y1.toFixed(1)}" x2="${W-P}" y2="${y1.toFixed(1)}" stroke="rgba(30,106,53,0.4)" stroke-dasharray="2,2"/>`;
  } else if (item.ref_min != null) {
    const y1 = y(item.ref_min);
    band = `<line x1="${P}" y1="${y1.toFixed(1)}" x2="${W-P}" y2="${y1.toFixed(1)}" stroke="rgba(30,106,53,0.4)" stroke-dasharray="2,2"/>`;
  }

  const path = numeric.map((p, i) => {
    const px = x(p.year).toFixed(1), py = y(p.v).toFixed(1);
    return `${i === 0 ? "M" : "L"}${px},${py}`;
  }).join(" ");

  const dots = numeric.map((p) => {
    const px = x(p.year).toFixed(1), py = y(p.v).toFixed(1);
    const color = p.status === "HIGH" ? "#B83227"
                 : p.status === "LOW" ? "#1F5FA6"
                 : "#0A0A0A";
    const r = p.year === state.latestYear ? 2.2 : 1.5;
    return `<circle cx="${px}" cy="${py}" r="${r}" fill="${color}"/>`;
  }).join("");

  return `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
      ${band}
      <path d="${path}" fill="none" stroke="#1F1E1C" stroke-width="1.1" stroke-linejoin="round" stroke-linecap="round"/>
      ${dots}
    </svg>
  `;
}

/* -------------------- detail panel -------------------- */
async function openDetail(itemId) {
  state.activeItemId = itemId;
  document.querySelectorAll(".section-row").forEach((r) => {
    r.classList.toggle("is-active", Number(r.dataset.itemId) === itemId);
  });

  const detail = document.getElementById("detail");
  const scrim = document.getElementById("detail-scrim");
  detail.setAttribute("aria-hidden", "false");
  scrim.setAttribute("aria-hidden", "false");

  const body = document.getElementById("detail-body");
  body.innerHTML = `<p class="detail-empty">Loading…</p>`;

  try {
    const res = await cachedFetch(`/items/${itemId}/trend`);
    body.innerHTML = renderDetail(res);

    /* animate chart line draw */
    const pathEl = body.querySelector(".chart-path");
    if (pathEl) {
      const len = pathEl.getTotalLength();
      pathEl.style.setProperty("--path-length", len);
    }
  } catch (err) {
    body.innerHTML = `<p class="detail-empty">Failed to load · ${escape(String(err))}</p>`;
  }
}

function closeDetail() {
  state.activeItemId = null;
  document.getElementById("detail").setAttribute("aria-hidden", "true");
  document.getElementById("detail-scrim").setAttribute("aria-hidden", "true");
  document.querySelectorAll(".section-row.is-active").forEach((r) => r.classList.remove("is-active"));
}

function renderDetail({ item, points }) {
  const sorted = [...points].sort((a, b) => a.year - b.year);
  const latest = sorted[sorted.length - 1];

  const statusLabel = {
    HIGH: "High",
    LOW: "Low",
    NORMAL: "Normal",
  }[latest?.status] || "—";

  const statusKey = latest?.status || "NONE";

  const refDisplay = (() => {
    const { ref_min: lo, ref_max: hi } = item;
    if (lo != null && hi != null) return `${formatNum(lo)} <span style="color:var(--ink-faint)">→</span> ${formatNum(hi)}`;
    if (lo != null) return `≥ ${formatNum(lo)}`;
    if (hi != null) return `≤ ${formatNum(hi)}`;
    return `<span style="font-size:0.78rem;letter-spacing:0.12em;text-transform:uppercase;color:var(--ink-mute);">Qualitative</span>`;
  })();

  return `
    <div class="detail-kicker">
      <span>${escape(item.major_category)}</span>
      <span class="dot"></span>
      <span>${escape(item.minor_category)}</span>
    </div>
    <h2 class="detail-title">${escape(item.name)}</h2>
    <div class="detail-code">${escape(item.code || "")}</div>

    <div class="detail-status detail-status--${statusKey}">
      <span>Latest · ’${String(latest?.year ?? "").slice(2)}</span>
      <span>${escape(latest?.value_text ?? "—")}</span>
      <span>${escape(statusLabel)}</span>
    </div>

    <div class="detail-ref">
      <span>Reference</span>
      <span class="ref-value">${refDisplay}</span>
    </div>

    <div class="detail-chart">${detailChart(item, sorted)}</div>

    <div class="detail-table">
      ${sorted.map((p) => `
        <div class="detail-table-row">
          <span class="year">’${String(p.year).slice(2)}</span>
          <span class="value">${escape(p.value_text ?? "—")}</span>
          <span class="pill pill--${p.status ?? "NONE"}">${escape(p.status ?? "—")}</span>
        </div>
      `).join("")}
    </div>

    <div class="detail-info">
      ${section("Related conditions", item.related_diseases)}
      ${section("Reference notes",   item.ref_indicator)}
      ${section("Memo",              item.memo)}
    </div>
  `;
}

function section(label, value) {
  if (!value) return "";
  return `
    <section>
      <dt>${escape(label)}</dt>
      <dd>${escape(value)}</dd>
    </section>
  `;
}

/* -------------------- detail chart (SVG) -------------------- */
function detailChart(item, sorted) {
  const numeric = sorted.filter((p) => p.value_numeric != null);
  if (numeric.length === 0) {
    return `<p class="detail-empty">Qualitative readings only — no numeric trend.</p>`;
  }

  const W = 460, H = 240;
  const padL = 40, padR = 16, padT = 22, padB = 28;

  const xMin = Math.min(...ALL_YEARS);
  const xMax = Math.max(...ALL_YEARS);

  let yMin = Math.min(...numeric.map((p) => p.value_numeric));
  let yMax = Math.max(...numeric.map((p) => p.value_numeric));
  if (item.ref_min != null) yMin = Math.min(yMin, item.ref_min);
  if (item.ref_max != null) yMax = Math.max(yMax, item.ref_max);
  if (yMax === yMin) { yMax = yMin + 1; yMin -= 1; }
  const yPad = (yMax - yMin) * 0.15;
  yMin -= yPad; yMax += yPad;

  const sx = (year) => padL + ((year - xMin) / (xMax - xMin)) * (W - padL - padR);
  const sy = (v)    => padT + ((yMax - v) / (yMax - yMin)) * (H - padT - padB);

  /* y ticks */
  const yTicks = [];
  for (let i = 0; i <= 4; i++) {
    const v = yMin + (i / 4) * (yMax - yMin);
    const y = sy(v);
    yTicks.push(`
      <line x1="${padL}" y1="${y.toFixed(1)}" x2="${W-padR}" y2="${y.toFixed(1)}" stroke="rgba(201,198,190,0.8)" stroke-width="0.5"/>
      <text x="${(padL - 6).toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="end" font-family="JetBrains Mono" font-size="9" font-weight="500" fill="#6E6B66">${formatNum(v)}</text>
    `);
  }

  /* reference band / lines */
  let band = "";
  if (item.ref_min != null && item.ref_max != null) {
    const y1 = sy(item.ref_max), y2 = sy(item.ref_min);
    band = `
      <rect x="${padL}" y="${Math.min(y1,y2).toFixed(1)}" width="${(W-padL-padR).toFixed(1)}" height="${Math.abs(y2-y1).toFixed(1)}" fill="rgba(30,106,53,0.08)" stroke="rgba(30,106,53,0.32)" stroke-dasharray="2,3"/>
      <text x="${W - padR}" y="${(Math.min(y1,y2) - 4).toFixed(1)}" text-anchor="end" font-family="JetBrains Mono" font-size="8.5" font-weight="600" fill="#1E6A35" letter-spacing="0.08em">REF MAX · ${formatNum(item.ref_max)}</text>
      <text x="${W - padR}" y="${(Math.max(y1,y2) + 11).toFixed(1)}" text-anchor="end" font-family="JetBrains Mono" font-size="8.5" font-weight="600" fill="#1E6A35" letter-spacing="0.08em">REF MIN · ${formatNum(item.ref_min)}</text>
    `;
  } else if (item.ref_max != null) {
    const y1 = sy(item.ref_max);
    band = `
      <line x1="${padL}" y1="${y1.toFixed(1)}" x2="${W-padR}" y2="${y1.toFixed(1)}" stroke="rgba(30,106,53,0.55)" stroke-dasharray="3,3"/>
      <text x="${W - padR}" y="${(y1 - 4).toFixed(1)}" text-anchor="end" font-family="JetBrains Mono" font-size="8.5" font-weight="600" fill="#1E6A35" letter-spacing="0.08em">REF MAX · ${formatNum(item.ref_max)}</text>
    `;
  } else if (item.ref_min != null) {
    const y1 = sy(item.ref_min);
    band = `
      <line x1="${padL}" y1="${y1.toFixed(1)}" x2="${W-padR}" y2="${y1.toFixed(1)}" stroke="rgba(30,106,53,0.55)" stroke-dasharray="3,3"/>
      <text x="${W - padR}" y="${(y1 + 11).toFixed(1)}" text-anchor="end" font-family="JetBrains Mono" font-size="8.5" font-weight="600" fill="#1E6A35" letter-spacing="0.08em">REF MIN · ${formatNum(item.ref_min)}</text>
    `;
  }

  /* x ticks */
  const xTicks = ALL_YEARS.map((yr) => {
    const x = sx(yr);
    return `
      <line x1="${x.toFixed(1)}" y1="${(H-padB).toFixed(1)}" x2="${x.toFixed(1)}" y2="${(H-padB+3).toFixed(1)}" stroke="#44423E" stroke-width="0.5"/>
      <text x="${x.toFixed(1)}" y="${(H-padB+15).toFixed(1)}" text-anchor="middle" font-family="JetBrains Mono" font-size="9" font-weight="500" fill="#44423E">’${String(yr).slice(2)}</text>
    `;
  }).join("");

  /* line path */
  numeric.sort((a, b) => a.year - b.year);
  const path = numeric.map((p, i) => {
    const x = sx(p.year).toFixed(1), y = sy(p.value_numeric).toFixed(1);
    return `${i === 0 ? "M" : "L"} ${x},${y}`;
  }).join(" ");

  /* dots with value labels */
  const dots = numeric.map((p) => {
    const x = sx(p.year), y = sy(p.value_numeric);
    const color = p.status === "HIGH" ? "#B83227"
                : p.status === "LOW"  ? "#1F5FA6"
                : "#0A0A0A";
    return `
      <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.8" fill="${color}" stroke="#FFFFFF" stroke-width="1.8"/>
      <text x="${x.toFixed(1)}" y="${(y - 9).toFixed(1)}" text-anchor="middle" font-family="JetBrains Mono" font-size="10" font-weight="600" fill="${color}">${formatNum(p.value_numeric)}</text>
    `;
  }).join("");

  return `
    <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="trend chart">
      ${yTicks.join("")}
      ${band}
      <line x1="${padL}" y1="${padT}" x2="${padL}" y2="${H-padB}" stroke="#0A0A0A" stroke-width="0.8"/>
      <line x1="${padL}" y1="${H-padB}" x2="${W-padR}" y2="${H-padB}" stroke="#0A0A0A" stroke-width="0.8"/>
      ${xTicks}
      <path class="chart-path" d="${path}" fill="none" stroke="#0A0A0A" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
      ${dots}
    </svg>
  `;
}

/* -------------------- bindings -------------------- */
function bindControls() {
  const search = document.getElementById("search");
  let debounce;
  search.addEventListener("input", (e) => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      state.filter.search = e.target.value;
      renderLedger();
    }, 80);
  });

  document.getElementById("detail-close").addEventListener("click", closeDetail);
  document.getElementById("detail-scrim").addEventListener("click", closeDetail);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDetail();
    if (e.key === "/" && document.activeElement !== search) {
      e.preventDefault();
      search.focus();
    }
  });

  /* Recompute layout (year columns + aux columns) when the viewport
     changes. Only re-render when the shape actually changes. */
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const next = computeLayout();
      if (layoutChanged(state.layout, next)) {
        state.layout = next;
        renderLedger();
      }
    }, 120);
  });
}
