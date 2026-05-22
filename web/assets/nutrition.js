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

/* -------------------- per-profile nutrition cache --------------------
 * The shared `cachedFetch` from cache.js keys on `data_version` (git sha
 * + reference epoch) which doesn't roll on user food inserts, so we keep
 * a separate localStorage namespace and update it directly on writes. */
const NUT_CACHE_PREFIX = "ydocter:nut:";
function nutKey(slug, kind, ...rest) {
  const base = `${NUT_CACHE_PREFIX}${slug || "_"}:${kind}`;
  return rest.length ? `${base}:${rest.join(":")}` : base;
}
function nutRead(key) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : null; }
  catch (e) { return null; }
}
function nutWrite(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)); }
  catch (e) { /* quota / private mode — silently skip */ }
}

async function boot() {
  bindCompose();

  /* Phase 1: paint calendar skeleton immediately — grid structure is a
   * pure function of (year, month) so we don't need any server data. */
  const today = new Date();
  state.cursorYear  = today.getFullYear();
  state.cursorMonth = today.getMonth() + 1;
  renderCalendar();

  /* Phase 2: optimistic paint from per-profile cache. The stored slug and
   * profile list are both available synchronously before /profiles
   * resolves, so the RDA-basis chip + calendar dots paint on frame one. */
  const cachedSlug = Profile.storedSlug();
  if (cachedSlug) {
    state.profiles = Profile.list();
    renderProfileSummary();
    paintFromCache(cachedSlug);
  }

  /* Phase 3: fresh fetches in the background, then reconcile. */
  try {
    await Profile.init({ onChange: reload });
    await reload();
  } catch (err) {
    console.error(err);
    document.getElementById("grid").innerHTML =
      `<p class="empty-state">Failed to load — is the server running?<br><code>${err}</code></p>`;
  }
}

/* Render whatever we have in cache for the given profile so the user
 * sees populated dots, kcal, meals, and totals on the first frame. */
function paintFromCache(slug) {
  const dates = nutRead(nutKey(slug, "dates"));
  if (!dates) return false;

  state.dates = dates;
  state.byDate = new Map(dates.map((d) => [d.log_date, d]));

  const latest = dates[0]?.log_date ?? null;
  if (latest) {
    state.selectedDate = latest;
    const seed = parseISO(latest);
    state.cursorYear  = seed.getFullYear();
    state.cursorMonth = seed.getMonth() + 1;
  }
  renderCalendar();

  if (state.selectedDate) {
    const day = nutRead(nutKey(slug, "day", state.selectedDate));
    if (day) {
      state.day = day;
      renderCompose();
      renderMeals();
      renderTotals();
      renderRail();
    }
  }
  return true;
}

async function reload() {
  const slug = Profile.current();
  const qs = slug ? `?profile=${encodeURIComponent(slug)}` : "";

  /* On profile switch, repaint cached data for the new slug before
   * waiting on the fresh fetch. */
  paintFromCache(slug);

  state.dates = await fetch(`/nutrition/dates${qs}`).then(must);
  nutWrite(nutKey(slug, "dates"), state.dates);
  state.profiles = Profile.list();

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
      nutWrite(nutKey(slug, "day", date), state.day);
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
    nutWrite(nutKey(slug, "day", state.selectedDate), state.day);

    /* refresh date index so the calendar dot/kcal appears */
    state.dates = await fetch(`/nutrition/dates${qs}`).then(must);
    nutWrite(nutKey(slug, "dates"), state.dates);
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

  const warning = status === "bad" && t.excess_warning
    ? `<div class="nutri-warning" role="note">
         <span class="warning-glyph" aria-hidden="true">!</span>
         <span class="warning-text">초과 시: ${escape(t.excess_warning)}</span>
       </div>`
    : "";

  /* For beneficial nutrients still under RDA, surface a short list of
   * representative Korean foods so the user knows what to add. We only
   * show on truly-deficient rows (status === "neutral", which for these
   * nutrients implies < 90% RDA) and skip limit/neutral codes whose
   * "more" recommendation isn't healthful. */
  const showHint =
    status === "neutral" &&
    !LIMIT_NUTRIENTS.has(t.code) &&
    !NEUTRAL_NUTRIENTS.has(t.code) &&
    t.rda != null &&
    FOOD_SOURCES[t.code];
  const hint = showHint
    ? `<div class="nutri-hint" role="note">
         <span class="hint-glyph" aria-hidden="true">+</span>
         <span class="hint-text">권장 식품: ${FOOD_SOURCES[t.code].map(escape).join(", ")}</span>
       </div>`
    : "";

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
          ${t.ul != null && t.rda && t.ul <= t.rda * 2 ? `<div class="bar-ul" style="left:${((t.ul / t.rda / 2) * 100).toFixed(1)}%" title="UL"></div>` : ""}
        </div>
        <div class="bar-legend">
          <span class="legend-pct ${pct == null ? "muted" : ""}">${pct == null ? "—" : Math.round(pct) + "%"}</span>
          <span class="legend-rda">RDA ${t.rda != null ? formatAmount(t.rda, t.unit) : "—"}${t.ul != null ? ` · UL ${formatAmount(t.ul, t.unit)}` : ""}</span>
        </div>
      </div>
      ${warning}
      ${hint}
    </div>
  `;
}

/* Classify a nutrient row into one of three health states.
 *
 *   good     — green: nutrient is in a healthy range
 *              · "limit" nutrients (sodium, sat fat, etc.) under target
 *              · "good" nutrients meeting RDA without breaching UL
 *   bad      — red:   nutrient is in an unhealthy range
 *              · "limit" nutrients exceeding target
 *              · "good" nutrients exceeding their UL
 *   neutral  — blue:  purely informational, no good/bad judgement
 *              · energy / macros (kcal, carb, fat, omega-6)
 *              · "good" nutrients still below RDA (not yet a problem,
 *                but not yet sufficient either)
 *   none     — gray:  no data
 *
 * Rule from user: 좋은것이여도 기준치를 넘었을때 안좋아지면 붉은색.
 * UL is the formal "you crossed harm threshold". If a nutrient has no UL
 * (e.g. water-soluble vitamins, fiber, protein, potassium, omega-3),
 * extra intake stays green per spec — "많이 먹어도 문제 없으면 녹색 유지".
 */
const LIMIT_NUTRIENTS = new Set([
  "sodium", "sat_fat", "trans_fat", "chol", "sugar",
]);
const NEUTRAL_NUTRIENTS = new Set([
  "kcal", "carb", "fat", "omega6",
]);

/* Representative Korean foods per nutrient. Surfaced as a hint under any
 * "good" nutrient that hasn't met its RDA, so the user can act on the gap.
 * Kept in JS because the catalog is static reference data (no per-user or
 * per-day variance) and lives close to the rendering code. */
const FOOD_SOURCES = {
  protein: ["닭가슴살", "계란", "두부", "콩", "생선", "그릭요거트"],
  fiber:   ["현미·잡곡밥", "검은콩", "양배추", "사과", "배", "김치", "미역"],
  ca:      ["우유", "치즈", "요거트", "멸치", "두부", "시금치", "깨"],
  p:       ["견과류", "콩", "생선", "유제품", "통곡물"],
  fe:      ["붉은살 소고기", "굴", "시금치", "검은콩", "검은깨", "간"],
  mg:      ["아몬드", "시금치", "검은콩", "현미", "다크초콜릿"],
  zn:      ["굴", "소고기", "호박씨", "캐슈넛", "병아리콩"],
  cu:      ["굴", "간", "견과류", "코코아", "버섯"],
  mn:      ["통곡물", "견과류", "녹차", "시금치", "파인애플"],
  k:       ["바나나", "감자", "고구마", "시금치", "토마토", "아보카도"],
  se:      ["브라질너트", "참치", "정어리", "달걀"],
  iodine:  ["김", "다시마", "미역", "유제품", "달걀"],
  vit_a:   ["당근", "단호박", "시금치", "김", "달걀노른자", "닭·소간"],
  vit_c:   ["딸기", "키위", "오렌지", "파프리카", "브로콜리", "토마토"],
  vit_d:   ["연어", "고등어", "정어리", "달걀노른자", "햇볕 쬔 표고버섯"],
  vit_e:   ["아몬드", "해바라기씨", "올리브유", "시금치", "아보카도"],
  vit_k:   ["시금치", "케일", "브로콜리", "낫토", "양배추"],
  b1:      ["돼지고기", "현미", "콩", "견과류"],
  b2:      ["우유", "계란", "시금치", "아몬드", "버섯"],
  b3:      ["닭가슴살", "참치·고등어", "땅콩", "표고버섯"],
  b5:      ["닭고기", "달걀", "버섯", "아보카도", "고구마"],
  b6:      ["연어", "닭고기", "감자", "바나나"],
  folate:  ["시금치", "아스파라거스", "콩류", "오렌지", "아보카도"],
  b12:     ["조개·굴", "소고기", "연어·고등어", "달걀", "우유"],
  biotin:  ["달걀노른자", "견과류", "통곡물", "연어", "고구마"],
  choline: ["달걀", "소고기", "닭간", "연어", "콜리플라워"],
  omega3:  ["연어", "고등어", "정어리", "들기름", "호두", "아마씨"],
};

function classify(t) {
  if (t.total == null) return "none";

  if (LIMIT_NUTRIENTS.has(t.code)) {
    /* less is better; target is the soft ceiling */
    if (t.rda == null) return "neutral";
    return t.total > t.rda ? "bad" : "good";
  }

  if (NEUTRAL_NUTRIENTS.has(t.code)) {
    return "neutral";
  }

  /* "good" nutrient — beneficial up to UL */
  if (t.ul != null && t.total > t.ul) return "bad";
  if (t.rda == null) return "neutral";
  return t.total >= t.rda * 0.9 ? "good" : "neutral";
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
