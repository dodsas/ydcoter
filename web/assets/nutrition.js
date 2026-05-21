/* ydocter — Nutrition Ledger
 * Daily food log + per-nutrient totals against RDA / UL.
 * Vanilla JS, same-origin fetch.
 */

const MEAL_ORDER = ["breakfast", "lunch", "dinner", "snack", "supplement"];
const MEAL_LABEL = {
  breakfast:  { ko: "아침",   en: "Breakfast" },
  lunch:      { ko: "점심",   en: "Lunch" },
  dinner:     { ko: "저녁",   en: "Dinner" },
  snack:      { ko: "간식",   en: "Snack" },
  supplement: { ko: "영양제", en: "Supplement" },
};

const CATEGORY_LABEL = {
  macro:   "Macros & Energy",
  mineral: "Minerals",
  vitamin: "Vitamins",
  other:   "Fatty acids & Other",
};

const state = {
  dates: [],
  byDate: new Map(),     // 'YYYY-MM-DD' -> { entry_count, kcal }
  selectedDate: null,
  cursorYear: null,      // currently displayed month
  cursorMonth: null,     // 1..12
  day: null,             // DailyNutrition payload
  profiles: [],          // list of all profiles (with sex/birth_year/height_cm)
};

const SEX_LABEL = { male: "성인 남성", female: "성인 여성" };

const WEEKDAYS_KO = ["일", "월", "화", "수", "목", "금", "토"];
const MONTH_NAMES = [
  "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec",
];

document.addEventListener("DOMContentLoaded", boot);

async function boot() {
  try {
    await Profile.init({ onChange: reload });
    bindCompose();
    await reload();
  } catch (err) {
    console.error(err);
    document.getElementById("grid").innerHTML =
      `<p class="empty-state">Failed to load — is the server running?<br><code>${err}</code></p>`;
  }
}

async function reload() {
  const slug = Profile.current();
  const qs = slug ? `?profile=${encodeURIComponent(slug)}` : "";

  const [dates, profiles] = await Promise.all([
    fetch(`/nutrition/dates${qs}`).then(must),
    fetch(`/profiles`).then(must),
  ]);
  state.dates = dates;
  state.profiles = profiles;

  state.byDate = new Map();
  state.dates.forEach((d) => state.byDate.set(d.log_date, d));

  renderProfileSummary();

  /* default selection: latest logged date, or today */
  const latest = state.dates[0]?.log_date ?? null;
  state.selectedDate = latest;

  /* default month: latest logged month, or current month */
  const seed = latest ? parseISO(latest) : new Date();
  state.cursorYear  = seed.getFullYear();
  state.cursorMonth = seed.getMonth() + 1;

  renderCalendar();

  if (state.selectedDate) {
    await loadDay(state.selectedDate);
  } else {
    state.day = null;
    document.getElementById("meals").innerHTML = "";
    document.getElementById("totals").innerHTML =
      `<p class="empty-state">No nutrition logs yet — add entries via <code>app/nutrition_data.py</code>, or pick a date on the calendar to view an empty day.</p>`;
    renderRail();
  }
}

async function loadDay(date) {
  state.selectedDate = date;

  const slug = Profile.current();
  const qs = slug ? `?profile=${encodeURIComponent(slug)}` : "";
  if (state.byDate.has(date)) {
    try {
      state.day = await fetch(`/nutrition/${date}${qs}`).then(must);
    } catch (err) {
      state.day = null;
    }
  } else {
    state.day = null;
  }

  renderCalendar();
  renderCompose();
  if (state.day) {
    renderMeals();
    renderTotals();
  } else {
    document.getElementById("meals").innerHTML =
      `<p class="empty-state">No food entries logged on ${escape(prettyDate(date))}.</p>`;
    document.getElementById("totals").innerHTML = "";
  }
  renderRail();
}

function must(r) {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

/* -------------------- profile summary -------------------- */
function renderProfileSummary() {
  const el = document.getElementById("profile-summary");
  if (!el) return;

  const slug = Profile.current();
  const p = state.profiles.find((x) => x.slug === slug) || state.profiles[0];
  if (!p || !p.sex) {
    el.hidden = true;
    return;
  }

  const today = new Date();
  const age = p.birth_year ? today.getFullYear() - p.birth_year : null;
  const sexLabel = SEX_LABEL[p.sex] || p.sex;

  const bits = [];
  bits.push(`<span class="profile-summary-name">${escape(p.display_name)}</span>`);
  bits.push(`<span class="profile-summary-meta">${escape(sexLabel)}</span>`);
  if (p.birth_year) bits.push(`<span class="profile-summary-meta">${p.birth_year}년생 · ${age}세</span>`);
  if (p.height_cm)  bits.push(`<span class="profile-summary-meta">${p.height_cm.toFixed(0)} cm</span>`);

  el.hidden = false;
  el.innerHTML = `
    <span class="profile-summary-label">RDA basis</span>
    ${bits.join('<span class="profile-summary-dot">·</span>')}
  `;
}

/* -------------------- rail -------------------- */
function renderRail() {
  const d = state.day;
  document.getElementById("rail-date").textContent =
    state.selectedDate ? prettyDate(state.selectedDate) : "—";
  document.getElementById("rail-foods").textContent =
    d ? String(d.logs.length) : "—";
  const kcal = d?.totals?.find((t) => t.code === "kcal")?.total;
  document.getElementById("rail-kcal").textContent =
    kcal != null ? Math.round(kcal).toLocaleString() : "—";
}

/* -------------------- calendar -------------------- */
function renderCalendar() {
  const el = document.getElementById("cal");
  const y = state.cursorYear;
  const m = state.cursorMonth;          // 1..12
  const today = new Date();
  const todayISO = isoDate(today);

  const firstWeekday = new Date(y, m - 1, 1).getDay();     // 0=Sun
  const daysInMonth  = new Date(y, m, 0).getDate();
  const prevMonthDays = new Date(y, m - 1, 0).getDate();

  /* logged-day stats for current month */
  const monthEntries = state.dates.filter((d) =>
    d.log_date.startsWith(monthKey(y, m)),
  );
  const monthKcal = monthEntries.reduce((s, d) => s + (d.kcal || 0), 0);

  /* build 6 rows × 7 cols of cells, padded with prev/next month days */
  const cells = [];
  const prevY = m === 1 ? y - 1 : y;
  const prevM = m === 1 ? 12 : m - 1;
  const nextY = m === 12 ? y + 1 : y;
  const nextM = m === 12 ? 1 : m + 1;

  for (let i = 0; i < firstWeekday; i++) {
    cells.push({
      y: prevY, m: prevM,
      d: prevMonthDays - firstWeekday + 1 + i,
      dim: true,
    });
  }
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({ y, m, d, dim: false });
  }
  let nd = 1;
  while (cells.length < 42) {
    cells.push({ y: nextY, m: nextM, d: nd++, dim: true });
  }

  /* compose */
  el.innerHTML = `
    <div class="cal-head">
      <div class="cal-meta">
        <span class="cal-meta-label">Month</span>
        <span class="cal-meta-value">${MONTH_NAMES[m - 1]} ${y}</span>
      </div>
      <div class="cal-summary">
        <span class="cal-summary-cell">
          <span class="cal-summary-label">Logged days</span>
          <span class="cal-summary-value">${monthEntries.length}</span>
        </span>
        <span class="cal-summary-cell">
          <span class="cal-summary-label">Total kcal</span>
          <span class="cal-summary-value">${Math.round(monthKcal).toLocaleString()}</span>
        </span>
      </div>
      <div class="cal-nav">
        <button class="cal-nav-btn" id="cal-prev" aria-label="Previous month">‹</button>
        <button class="cal-nav-btn" id="cal-today" aria-label="Today">Today</button>
        <button class="cal-nav-btn" id="cal-next" aria-label="Next month">›</button>
      </div>
    </div>

    <div class="cal-weekrow">
      ${WEEKDAYS_KO.map((w, i) =>
        `<div class="cal-weekday${i === 0 ? " is-sun" : ""}${i === 6 ? " is-sat" : ""}">${w}</div>`,
      ).join("")}
    </div>

    <div class="cal-grid">
      ${cells.map((c) => renderCalCell(c, todayISO)).join("")}
    </div>
  `;

  el.querySelector("#cal-prev").addEventListener("click", () => stepMonth(-1));
  el.querySelector("#cal-next").addEventListener("click", () => stepMonth(+1));
  el.querySelector("#cal-today").addEventListener("click", () => {
    const t = new Date();
    state.cursorYear = t.getFullYear();
    state.cursorMonth = t.getMonth() + 1;
    loadDay(isoDate(t));
  });

  el.querySelectorAll(".cal-cell[data-date]").forEach((cell) => {
    cell.addEventListener("click", () => {
      const date = cell.dataset.date;
      if (date && date !== state.selectedDate) loadDay(date);
    });
  });
}

function renderCalCell(c, todayISO) {
  const iso = `${c.y}-${String(c.m).padStart(2, "0")}-${String(c.d).padStart(2, "0")}`;
  const data = state.byDate.get(iso);
  const isSelected = iso === state.selectedDate;
  const isToday    = iso === todayISO;
  const weekday    = new Date(c.y, c.m - 1, c.d).getDay();

  const classes = ["cal-cell"];
  if (c.dim)     classes.push("is-dim");
  if (data)      classes.push("has-data");
  if (isSelected)classes.push("is-selected");
  if (isToday)   classes.push("is-today");
  if (weekday === 0) classes.push("is-sun");
  if (weekday === 6) classes.push("is-sat");

  const kcal = data ? Math.round(data.kcal || 0).toLocaleString() : "";

  return `
    <button class="${classes.join(" ")}" data-date="${iso}" aria-pressed="${isSelected}" type="button">
      <span class="cal-day">${c.d}</span>
      ${data ? `<span class="cal-kcal">${kcal}</span>` : `<span class="cal-kcal-placeholder"></span>`}
      ${data ? `<span class="cal-dot" aria-hidden="true"></span>` : ""}
    </button>
  `;
}

function stepMonth(delta) {
  let m = state.cursorMonth + delta;
  let y = state.cursorYear;
  if (m < 1)  { m = 12; y -= 1; }
  if (m > 12) { m = 1;  y += 1; }
  state.cursorMonth = m;
  state.cursorYear  = y;
  renderCalendar();
}

function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function parseISO(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function monthKey(y, m) {
  return `${y}-${String(m).padStart(2, "0")}`;
}

/* -------------------- compose (free-text -> Claude) -------------------- */
function bindCompose() {
  const toggle = document.getElementById("compose-toggle");
  const body   = document.getElementById("compose-body");
  const cancel = document.getElementById("compose-cancel");
  const submit = document.getElementById("compose-submit");

  toggle.addEventListener("click", () => setComposeOpen(body.hidden));
  cancel.addEventListener("click", () => setComposeOpen(false));
  submit.addEventListener("click", () => submitCompose());

  /* Cmd/Ctrl + Enter inside the textarea submits */
  document.getElementById("compose-text").addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      submitCompose();
    }
  });
}

function renderCompose() {
  const compose = document.getElementById("compose");
  if (!state.selectedDate) {
    compose.hidden = true;
    return;
  }
  compose.hidden = false;
  document.getElementById("compose-date").textContent = prettyDate(state.selectedDate);

  /* existing-entry chip — shows count + flips toggle label */
  const existingEl = document.getElementById("compose-existing");
  const count = state.day?.logs?.length || 0;
  if (count > 0) {
    existingEl.hidden = false;
    existingEl.textContent = `${count}개 기록됨`;
  } else {
    existingEl.hidden = true;
  }

  /* toggle label hints at append vs first entry */
  const body = document.getElementById("compose-body");
  const toggle = document.getElementById("compose-toggle");
  const open = !body.hidden;
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  toggle.querySelector(".compose-toggle-label").textContent =
    open ? "✕ Close" : (count > 0 ? "+ 추가 입력" : "+ Add entries");
}

function setComposeOpen(open) {
  const body = document.getElementById("compose-body");
  const toggle = document.getElementById("compose-toggle");
  body.hidden = !open;
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  toggle.querySelector(".compose-toggle-label").textContent =
    open ? "✕ Close" : "+ Add entries";
  if (open) {
    document.getElementById("compose-text").focus();
  }
}

async function submitCompose() {
  if (!state.selectedDate) return;
  const submit  = document.getElementById("compose-submit");
  const textEl  = document.getElementById("compose-text");
  const replEl  = document.getElementById("compose-replace");
  const statusEl= document.getElementById("compose-status");

  const text = textEl.value.trim();
  if (!text) {
    showStatus("내용을 입력해주세요.", "error");
    return;
  }

  submit.classList.add("is-loading");
  submit.disabled = true;
  showStatus("Claude 분석 중… 보통 10–30초 소요됩니다.", "info");

  const slug = Profile.current();
  const qs = slug ? `?profile=${encodeURIComponent(slug)}` : "";
  try {
    const res = await fetch(`/nutrition/${state.selectedDate}/parse${qs}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, replace: replEl.checked }),
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const j = await res.json();
        if (j.detail) detail = j.detail;
      } catch { /* ignore */ }
      throw new Error(detail);
    }
    const data = await res.json();
    state.day = data.day;

    /* refresh date index so the calendar dot/kcal appears */
    state.dates = await fetch(`/nutrition/dates${qs}`).then(must);
    state.byDate = new Map(state.dates.map((d) => [d.log_date, d]));

    const successMsg =
      data.mode === "replace"
        ? `기존 ${data.existing_before}개 삭제 후 ${data.inserted}개 저장 — 총 ${data.total_after}개`
        : `${data.inserted}개 추가됨 (기존 ${data.existing_before} → 총 ${data.total_after}개)`;
    showStatus(successMsg, "success");

    textEl.value = "";
    replEl.checked = false;
    renderCalendar();
    renderCompose();
    renderMeals();
    renderTotals();
    renderRail();

    /* auto-collapse after a beat so user sees the new data */
    setTimeout(() => setComposeOpen(false), 900);
  } catch (err) {
    console.error(err);
    showStatus(`실패: ${err.message || err}`, "error");
  } finally {
    submit.classList.remove("is-loading");
    submit.disabled = false;
  }

  function showStatus(msg, kind) {
    statusEl.hidden = false;
    statusEl.textContent = msg;
    statusEl.dataset.kind = kind;
  }
}

/* -------------------- meals (left column) -------------------- */
function renderMeals() {
  const meals = document.getElementById("meals");
  meals.innerHTML = "";

  if (!state.day || state.day.logs.length === 0) {
    meals.innerHTML = `<p class="empty-state">No food entries for this date.</p>`;
    return;
  }

  /* group by meal_type, preserving MEAL_ORDER */
  const byMeal = new Map();
  state.day.logs.forEach((entry) => {
    const m = entry.log.meal_type;
    if (!byMeal.has(m)) byMeal.set(m, []);
    byMeal.get(m).push(entry);
  });

  const ordered = [
    ...MEAL_ORDER.filter((m) => byMeal.has(m)),
    ...[...byMeal.keys()].filter((m) => !MEAL_ORDER.includes(m)),
  ];

  ordered.forEach((m, idx) => {
    const list = byMeal.get(m);
    const subtotalKcal = list.reduce((acc, e) => acc + (e.values.kcal || 0), 0);
    const label = MEAL_LABEL[m] || { ko: m, en: m };

    const section = document.createElement("section");
    section.className = "meal-block rise";
    section.style.animationDelay = `${idx * 50}ms`;

    section.innerHTML = `
      <header class="meal-head">
        <div class="meal-head-titles">
          <span class="meal-label">${escape(label.en)}</span>
          <span class="meal-label-ko">${escape(label.ko)}</span>
        </div>
        <span class="meal-kcal">${Math.round(subtotalKcal).toLocaleString()} <span class="unit">kcal</span></span>
      </header>
      <ul class="meal-foods">
        ${list.map((e) => `
          <li>
            <div class="food-row">
              <span class="food-name">${escape(e.log.food_name)}</span>
              <span class="food-serving">${escape(e.log.serving || "")}</span>
              <span class="food-kcal">${e.values.kcal != null ? Math.round(e.values.kcal) : "—"}</span>
            </div>
            ${e.log.note ? `<div class="food-note">${escape(e.log.note)}</div>` : ""}
          </li>
        `).join("")}
      </ul>
    `;
    meals.appendChild(section);
  });
}

/* -------------------- totals (right column) -------------------- */
function renderTotals() {
  const el = document.getElementById("totals");
  el.innerHTML = "";

  if (!state.day || state.day.totals.length === 0) {
    el.innerHTML = `<p class="empty-state">No nutrient totals.</p>`;
    return;
  }

  const grouped = new Map();
  state.day.totals.forEach((t) => {
    if (!grouped.has(t.category)) grouped.set(t.category, []);
    grouped.get(t.category).push(t);
  });

  const categories = ["macro", "mineral", "vitamin", "other"]
    .filter((c) => grouped.has(c));

  categories.forEach((cat, idx) => {
    const list = grouped.get(cat);
    const section = document.createElement("section");
    section.className = "totals-block rise";
    section.style.animationDelay = `${idx * 60}ms`;

    section.innerHTML = `
      <header class="totals-head">
        <h2 class="totals-title">${escape(CATEGORY_LABEL[cat] || cat)}</h2>
        <span class="totals-count">${list.length}</span>
      </header>
      <div class="totals-rows">
        ${list.map(renderNutrientRow).join("")}
      </div>
    `;
    el.appendChild(section);
  });
}

function renderNutrientRow(t) {
  const pct = t.rda != null && t.rda > 0 ? (t.total / t.rda) * 100 : null;
  const status = classify(t);
  const fillWidth = pct == null ? 0 : Math.min(pct, 200); /* cap fill at 200% */

  /* RDA marker is always at 100% — fill is scaled so 100% = halfway across (visual cap at 200%). */
  const fillPercent = (fillWidth / 200) * 100;

  return `
    <div class="nutri-row" data-status="${status}">
      <div class="nutri-row-head">
        <span class="nutri-name">
          <span class="nutri-name-ko">${escape(t.name_ko)}</span>
          ${t.name_en ? `<span class="nutri-name-en">${escape(t.name_en)}</span>` : ""}
        </span>
        <span class="nutri-amount">
          <span class="amount-value">${formatAmount(t.total, t.unit)}</span>
          <span class="amount-unit">${escape(t.unit)}</span>
        </span>
      </div>
      <div class="nutri-bar">
        <div class="bar-track">
          <div class="bar-fill" style="width:${fillPercent.toFixed(1)}%"></div>
          <div class="bar-rda" title="RDA"></div>
          ${t.ul != null && t.rda ? `<div class="bar-ul" style="left:${Math.min((t.ul / t.rda / 2) * 100, 100).toFixed(1)}%" title="UL"></div>` : ""}
        </div>
        <div class="bar-legend">
          <span class="legend-pct ${pct == null ? "muted" : ""}">${pct == null ? "—" : Math.round(pct) + "%"}</span>
          <span class="legend-rda">RDA ${t.rda != null ? formatAmount(t.rda, t.unit) : "—"}${t.ul != null ? ` · UL ${formatAmount(t.ul, t.unit)}` : ""}</span>
        </div>
      </div>
    </div>
  `;
}

/* Map a nutrient total to a status label that controls coloring.
 *  - sodium has a "lower is better" cap → over is bad
 *  - macros (kcal, carb, fat, protein, fiber): only flag low/over by RDA proximity
 *  - micros: flag UL exceedance as the worst, then over/normal/under
 */
function classify(t) {
  if (t.total == null) return "none";
  if (t.ul != null && t.total > t.ul) return "ul";
  if (t.rda == null) return "none";
  const ratio = t.total / t.rda;
  if (ratio < 0.5)  return "under";
  if (ratio < 0.9)  return "low";
  if (ratio <= 1.5) return "ok";
  return "over";
}

/* -------------------- formatting helpers -------------------- */
function formatAmount(v, unit) {
  if (v == null) return "—";
  /* large kcal/integer-friendly values */
  if (unit === "kcal" || Math.abs(v) >= 100) return Math.round(v).toLocaleString();
  if (Math.abs(v) >= 10)  return v.toFixed(1);
  if (Math.abs(v) >= 1)   return v.toFixed(2);
  return v.toFixed(2);
}

function prettyDate(iso) {
  /* "2026-05-20" → "May 20, 2026" */
  const [y, m, d] = iso.split("-").map(Number);
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${months[m-1]} ${d}, ${y}`;
}

function escape(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
