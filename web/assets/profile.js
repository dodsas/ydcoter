/* Profile switcher — shared by dashboard + settings pages.
 *
 * Exposes a single global `Profile` object:
 *   Profile.init({onChange})  → fetches /profiles, restores choice from
 *                                localStorage, paints the switcher.
 *   Profile.current()         → current slug
 *   Profile.list()            → full list of profiles
 *   Profile.set(slug)         → switch and fire onChange
 *
 * Pages should call `Profile.init({onChange: () => reloadEverything()})`
 * during boot and use `?profile=${Profile.current()}` in every fetch.
 */

(function () {
  const STORAGE_KEY = "ydocter-profile";

  const state = {
    profiles: [],
    current: null,
    onChange: null,
  };

  async function init({ onChange } = {}) {
    state.onChange = onChange || (() => {});
    const res = await fetch("/profiles");
    if (!res.ok) throw new Error(`failed to load profiles (${res.status})`);
    state.profiles = await res.json();

    const stored = localStorage.getItem(STORAGE_KEY);
    const valid = state.profiles.some((p) => p.slug === stored);
    state.current = valid ? stored : (state.profiles[0]?.slug ?? null);
    if (state.current && state.current !== stored) {
      localStorage.setItem(STORAGE_KEY, state.current);
    }

    render();
    bind();
  }

  function current() { return state.current; }
  function list()    { return state.profiles; }

  function set(slug) {
    if (slug === state.current) return;
    const found = state.profiles.find((p) => p.slug === slug);
    if (!found) return;
    state.current = slug;
    localStorage.setItem(STORAGE_KEY, slug);
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

  window.Profile = { init, current, list, set };
})();
