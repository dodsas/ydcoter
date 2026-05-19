/* ydocter — Reference settings page
 * Editable table of all 99 indicators. Auto-saves on blur via
 * PATCH /items/{id}/reference. Tracks dirty/saving/saved state
 * per row so the user gets clear feedback.
 */

const state = {
  items: [],
  filter: { major: null, search: "" },
  /** id -> 'idle' | 'dirty' | 'saving' | 'saved' | 'error' */
  rowState: new Map(),
  /** id -> last error message */
  rowError: new Map(),
};

document.addEventListener("DOMContentLoaded", boot);

async function boot() {
  try {
    const items = await fetch("/items").then(must);
    state.items = items;

    renderRail();
    renderChips();
    renderTable();
    bindControls();
  } catch (err) {
    document.getElementById("ledger").innerHTML =
      `<p class="empty-state">Failed to load items — is the server running?<br><code>${escape(String(err))}</code></p>`;
  }
}

function must(r) {
  if (!r.ok) return r.text().then((t) => { throw new Error(`${r.status} ${t || r.statusText}`); });
  return r.json();
}

function renderRail() {
  document.getElementById("rail-items").textContent = String(state.items.length);
  updatePendingCount();
}

function updatePendingCount() {
  const pending = [...state.rowState.values()].filter(
    (s) => s === "dirty" || s === "saving",
  ).length;
  document.getElementById("rail-pending").textContent = String(pending);
}

function renderChips() {
  const majors = [...new Set(state.items.map((i) => i.major_category))];
  const chipset = document.getElementById("chipset");
  chipset.innerHTML = "";

  const all = document.createElement("button");
  all.className = "chip";
  all.dataset.major = "";
  all.setAttribute("aria-selected", "true");
  all.textContent = `All · ${state.items.length}`;
  chipset.appendChild(all);

  majors.forEach((m) => {
    const c = document.createElement("button");
    c.className = "chip";
    c.dataset.major = m;
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
    renderTable();
  });
}

function renderTable() {
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

  const groups = new Map();
  items.forEach((it) => {
    if (!groups.has(it.major_category)) groups.set(it.major_category, []);
    groups.get(it.major_category).push(it);
  });

  let gi = 0;
  for (const [major, list] of groups) {
    const section = document.createElement("section");
    section.className = "section rise";
    section.style.animationDelay = `${gi * 30}ms`;
    gi++;

    section.innerHTML = `
      <div class="section-head">
        <h2 class="section-title">${escape(major)}</h2>
        <span class="section-meta">${list.length} ${list.length === 1 ? "indicator" : "indicators"}</span>
      </div>
      <div class="settings-grid">
        <div class="settings-row settings-headrow">
          <div class="cell-indicator">Indicator</div>
          <div class="cell-input-head">Min</div>
          <div class="cell-input-head">Max</div>
          <div class="cell-input-head cell-input-head--note">Reference notes</div>
          <div class="cell-status-head">Status</div>
        </div>
        ${list.map((it) => renderRow(it, major)).join("")}
      </div>
    `;

    ledger.appendChild(section);
  }

  bindRowInputs();
}

function renderRow(item, major) {
  const status = state.rowState.get(item.id) || "idle";
  const errorMsg = state.rowError.get(item.id) || "";
  const sub = item.minor_category && item.minor_category !== major
    ? `${escape(item.code || "")}${item.code ? " · " : ""}${escape(item.minor_category)}`
    : escape(item.code || "");

  return `
    <div class="settings-row" data-item-id="${item.id}" data-status="${status}">
      <div class="cell-indicator">
        <span class="primary">${escape(item.name)}</span>
        <span class="secondary">${sub}</span>
      </div>
      <div class="cell-input">
        <input
          type="number"
          step="any"
          inputmode="decimal"
          class="ref-input"
          data-field="ref_min"
          data-original="${item.ref_min ?? ""}"
          value="${item.ref_min ?? ""}"
          placeholder="—"
          aria-label="Reference minimum"
        />
      </div>
      <div class="cell-input">
        <input
          type="number"
          step="any"
          inputmode="decimal"
          class="ref-input"
          data-field="ref_max"
          data-original="${item.ref_max ?? ""}"
          value="${item.ref_max ?? ""}"
          placeholder="—"
          aria-label="Reference maximum"
        />
      </div>
      <div class="cell-input cell-input--note">
        <input
          type="text"
          class="ref-input ref-input--note"
          data-field="ref_indicator"
          data-original="${escape(item.ref_indicator ?? "")}"
          value="${escape(item.ref_indicator ?? "")}"
          placeholder="Qualitative or descriptive notes"
          aria-label="Reference notes"
        />
      </div>
      <div class="cell-status">
        <span class="row-status row-status--${status}">${statusLabel(status)}</span>
        ${errorMsg ? `<span class="row-error" title="${escape(errorMsg)}">${escape(errorMsg)}</span>` : ""}
      </div>
    </div>
  `;
}

function statusLabel(s) {
  return {
    idle:   "—",
    dirty:  "Unsaved",
    saving: "Saving…",
    saved:  "Saved",
    error:  "Error",
  }[s] || "—";
}

function bindRowInputs() {
  document.querySelectorAll(".settings-row[data-item-id]").forEach((row) => {
    const id = Number(row.dataset.itemId);
    row.querySelectorAll(".ref-input").forEach((input) => {
      input.addEventListener("input", () => markDirty(id, row));
      input.addEventListener("blur",  () => maybeSave(id, row));
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") { input.value = input.dataset.original; input.blur(); refreshRowState(id, row); }
      });
    });
  });
}

function markDirty(id, row) {
  if (!isRowDirty(row)) {
    state.rowState.delete(id);
  } else {
    state.rowState.set(id, "dirty");
  }
  refreshRowState(id, row);
  updatePendingCount();
}

function isRowDirty(row) {
  return [...row.querySelectorAll(".ref-input")].some(
    (i) => (i.value ?? "") !== (i.dataset.original ?? ""),
  );
}

function refreshRowState(id, row) {
  const status = state.rowState.get(id) || "idle";
  row.dataset.status = status;
  const badge = row.querySelector(".row-status");
  if (badge) {
    badge.className = `row-status row-status--${status}`;
    badge.textContent = statusLabel(status);
  }
  const errEl = row.querySelector(".row-error");
  const msg = state.rowError.get(id) || "";
  if (errEl) {
    errEl.textContent = msg;
    errEl.title = msg;
    errEl.style.display = msg ? "" : "none";
  } else if (msg) {
    const span = document.createElement("span");
    span.className = "row-error";
    span.textContent = msg;
    span.title = msg;
    row.querySelector(".cell-status").appendChild(span);
  }
}

async function maybeSave(id, row) {
  if (!isRowDirty(row)) return;
  const payload = {};
  row.querySelectorAll(".ref-input").forEach((i) => {
    const field = i.dataset.field;
    const raw = i.value;
    if (raw === "") {
      payload[field] = null;
    } else if (field === "ref_min" || field === "ref_max") {
      const n = Number(raw);
      if (Number.isFinite(n)) payload[field] = n;
    } else {
      payload[field] = raw;
    }
  });

  state.rowState.set(id, "saving");
  state.rowError.delete(id);
  refreshRowState(id, row);
  updatePendingCount();

  try {
    const updated = await fetch(`/items/${id}/reference`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(must);

    /* sync data + originals */
    const idx = state.items.findIndex((it) => it.id === id);
    if (idx !== -1) state.items[idx] = updated;
    row.querySelectorAll(".ref-input").forEach((i) => {
      const field = i.dataset.field;
      const v = updated[field];
      i.dataset.original = v == null ? "" : String(v);
      i.value           = v == null ? "" : String(v);
    });

    state.rowState.set(id, "saved");
    refreshRowState(id, row);
    showToast(`Saved · ${updated.name}`);
    setTimeout(() => {
      if (state.rowState.get(id) === "saved" && !isRowDirty(row)) {
        state.rowState.delete(id);
        refreshRowState(id, row);
      }
    }, 1800);
  } catch (err) {
    state.rowState.set(id, "error");
    state.rowError.set(id, friendlyError(err));
    refreshRowState(id, row);
    showToast(`Error · ${friendlyError(err)}`, true);
  } finally {
    updatePendingCount();
  }
}

function friendlyError(err) {
  const msg = String(err.message || err);
  if (/422/.test(msg)) return "min must be ≤ max";
  return msg.replace(/^Error:\s*/, "").slice(0, 80);
}

function escape(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* -------------------- toast -------------------- */
let toastTimer;
function showToast(msg, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.dataset.kind = isError ? "error" : "ok";
  el.classList.add("toast--visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("toast--visible"), 2200);
}

/* -------------------- bindings -------------------- */
function bindControls() {
  const search = document.getElementById("search");
  let debounce;
  search.addEventListener("input", (e) => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      state.filter.search = e.target.value;
      renderTable();
    }, 80);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement.tagName !== "INPUT") {
      e.preventDefault();
      search.focus();
    }
  });

  window.addEventListener("beforeunload", (e) => {
    const dirty = [...state.rowState.values()].some(
      (s) => s === "dirty" || s === "saving",
    );
    if (dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}
