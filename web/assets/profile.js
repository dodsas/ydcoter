/* Profile switcher — shared by dashboard + settings pages.
 *
 * Exposes a single global `Profile` object:
 *   Profile.init({onChange})  → fetches /profiles, restores choice from
 *                                localStorage (with cookie as fallback),
 *                                paints the switcher.
 *   Profile.current()         → current slug
 *   Profile.list()            → full list of profiles
 *   Profile.set(slug)         → switch and fire onChange
 *
 * Pages should call `Profile.init({onChange: () => reloadEverything()})`
 * during boot and use `?profile=${Profile.current()}` in every fetch.
 */

(function () {
  const STORAGE_KEY    = "ydocter-profile";
  const LIST_KEY       = "ydocter-profiles";
  const FETCHED_AT_KEY = "ydocter-profiles:at";
  const COOKIE_KEY     = "ydocter_profile";
  // 1 year — long enough that returning visitors never lose their pick,
  // short enough that abandoned slugs eventually self-expire.
  const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;
  // Profile metadata (sex/birth_year/height_cm) is set via seed scripts and
  // never edited from the UI — refreshing once a day is plenty.
  const LIST_TTL_MS = 24 * 60 * 60 * 1000;

  // Belt + suspenders: localStorage is the primary store, cookie is a
  // backup that survives localStorage being cleared (private mode, quota
  // eviction, "clear site data") and is also readable by the server in
  // the future if we ever want SSR-side default selection.
  function readCookie() {
    const m = document.cookie.match(
      new RegExp("(?:^|; )" + COOKIE_KEY + "=([^;]*)")
    );
    return m ? decodeURIComponent(m[1]) : null;
  }
  function writeCookie(slug) {
    document.cookie =
      `${COOKIE_KEY}=${encodeURIComponent(slug)}` +
      `; Max-Age=${COOKIE_MAX_AGE}; Path=/; SameSite=Lax`;
  }
  function readStored() {
    try { return localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
  }
  function writeStored(slug) {
    try { localStorage.setItem(STORAGE_KEY, slug); } catch (e) { /* private mode */ }
    writeCookie(slug);
  }
  function readStoredList() {
    try {
      const v = localStorage.getItem(LIST_KEY);
      const parsed = v ? JSON.parse(v) : null;
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) { return []; }
  }
  function writeStoredList(list) {
    try {
      localStorage.setItem(LIST_KEY, JSON.stringify(list));
      localStorage.setItem(FETCHED_AT_KEY, String(Date.now()));
    } catch (e) { /* quota / private mode */ }
  }
  function readFetchedAt() {
    try { return parseInt(localStorage.getItem(FETCHED_AT_KEY), 10) || 0; }
    catch (e) { return 0; }
  }

  const state = {
    // Seed synchronously from cache so Profile.list() returns data on the
    // very first frame — pages can paint the profile chip with no flash.
    profiles: readStoredList(),
    current: null,
    onChange: null,
  };
  let bound = false;

  function resolveCurrent() {
    const stored = readStored() || readCookie();
    const valid = state.profiles.some((p) => p.slug === stored);
    state.current = valid ? stored : (state.profiles[0]?.slug ?? null);
    if (state.current) writeStored(state.current);
  }
  function paint() {
    render();
    if (!bound) { bind(); bound = true; }
  }

  async function init({ onChange } = {}) {
    state.onChange = onChange || (() => {});

    // Optimistic paint from cache — switcher and Profile.current() are
    // usable on the first frame even before the network resolves.
    if (state.profiles.length) {
      resolveCurrent();
      paint();
    }

    // Skip the network entirely when the cache is fresh: profile metadata
    // is effectively static and re-fetching on every page nav is wasteful.
    const fresh = Date.now() - readFetchedAt() < LIST_TTL_MS;
    if (fresh && state.profiles.length) return;

    const res = await fetch("/profiles");
    if (!res.ok) throw new Error(`failed to load profiles (${res.status})`);
    state.profiles = await res.json();
    writeStoredList(state.profiles);
    resolveCurrent();
    paint();
    // Don't fire onChange here — callers await init() and run their own
    // post-init data load, so they'll naturally pick up the fresh list.
  }

  function current() { return state.current; }
  function list()    { return state.profiles; }
  // Sync accessor for the persisted slug — usable before init() resolves so
  // pages can paint cached per-profile data on first frame.
  function storedSlug() { return readStored() || readCookie(); }

  function set(slug) {
    if (slug === state.current) return;
    const found = state.profiles.find((p) => p.slug === slug);
    if (!found) return;
    state.current = slug;
    writeStored(slug);
    render();
    state.onChange();
  }

  function render() {
    const trigger = document.getElementById("profile-trigger");
    const menu    = document.getElementById("profile-menu");
    const nameEl  = document.getElementById("profile-current-name");
    if (!trigger || !menu || !nameEl) return;

    const cur = state.profiles.find((p) => p.slug === state.current);
    nameEl.textContent = cur ? cur.display_name : "—";

    menu.innerHTML = state.profiles.map((p) => {
      const active = p.slug === state.current;
      const tag = p.measurement_count > 0
        ? `${p.measurement_count} records`
        : "no data yet";
      return `
        <li role="option" aria-selected="${active}" data-slug="${p.slug}">
          <button type="button" class="profile-option ${active ? "is-active" : ""}">
            <span class="profile-option-name">${escape(p.display_name)}</span>
            <span class="profile-option-meta">${tag}</span>
          </button>
        </li>
      `;
    }).join("");
  }

  function bind() {
    const wrap    = document.getElementById("profile-switch");
    const trigger = document.getElementById("profile-trigger");
    const menu    = document.getElementById("profile-menu");
    if (!wrap || !trigger || !menu) return;

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      toggle();
    });

    menu.addEventListener("click", (e) => {
      const li = e.target.closest("li[data-slug]");
      if (!li) return;
      set(li.dataset.slug);
      close();
    });

    document.addEventListener("click", (e) => {
      if (!wrap.contains(e.target)) close();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && wrap.dataset.open === "true") close();
    });
  }

  function open() {
    const wrap = document.getElementById("profile-switch");
    const trigger = document.getElementById("profile-trigger");
    if (!wrap) return;
    wrap.dataset.open = "true";
    trigger.setAttribute("aria-expanded", "true");
  }

  function close() {
    const wrap = document.getElementById("profile-switch");
    const trigger = document.getElementById("profile-trigger");
    if (!wrap) return;
    wrap.dataset.open = "false";
    trigger.setAttribute("aria-expanded", "false");
  }

  function toggle() {
    const wrap = document.getElementById("profile-switch");
    if (!wrap) return;
    wrap.dataset.open === "true" ? close() : open();
  }

  function escape(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  window.Profile = { init, current, list, set, storedSlug };
})();
