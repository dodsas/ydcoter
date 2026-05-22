/* Dashboard data cache.
 *
 * Strategy: each GET response is stored in localStorage under a key that
 * embeds the server's `data_version` token. The token rolls forward on
 * every deploy (new git sha) and on every reference-value edit, so a
 * fresh token == automatic cache miss for every entry. Stale entries
 * keyed on prior tokens are purged once we know the current token.
 *
 * Also stamps the footer build chip when #footer-version exists.
 */
(function () {
  const PREFIX = "ydocter:dash:";
  const VERSION_KEY = "ydocter:dash:_version";

  let versionPromise = null;
  // Optimistically use the last token we saw so the first cachedFetch can
  // resolve from localStorage *without* waiting on /version. We re-check
  // in the background and purge stale keys once the truth lands.
  let dataVersion = localStorage.getItem(VERSION_KEY) || null;

  function fillFooter(v) {
    const el = document.getElementById("footer-version");
    if (!el) return;
    const short = v.commit_short || "dev";
    const when = v.deployed_at
      ? new Date(v.deployed_at).toLocaleString(undefined, {
          year: "2-digit",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "";
    el.textContent = when ? `${short} · ${when}` : short;
    if (v.commit) el.title = `commit ${v.commit}\ndeployed ${v.deployed_at}`;
  }

  function purgeStale(currentVersion) {
    const keep = `:${currentVersion}`;
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k && k.startsWith(PREFIX) && k !== VERSION_KEY && !k.endsWith(keep)) {
        localStorage.removeItem(k);
      }
    }
  }

  function initVersion() {
    if (versionPromise) return versionPromise;
    versionPromise = (async () => {
      try {
        const r = await fetch("/version", { cache: "no-store" });
        if (!r.ok) return null;
        const v = await r.json();
        const next = v.data_version || `unknown.${Date.now()}`;
        if (next !== dataVersion) {
          dataVersion = next;
          localStorage.setItem(VERSION_KEY, next);
        }
        purgeStale(next);
        fillFooter(v);
        return v;
      } catch (e) {
        return null;
      }
    })();
    return versionPromise;
  }

  async function cachedFetch(url) {
    // If we already have a token (from a prior page load), try the cache
    // synchronously while the version check runs in the background.
    if (dataVersion) {
      const key = `${PREFIX}${url}:${dataVersion}`;
      const hit = localStorage.getItem(key);
      if (hit) {
        // Kick off background re-validation so the next visit is current.
        initVersion();
        try {
          return JSON.parse(hit);
        } catch (e) {
          localStorage.removeItem(key);
        }
      }
    } else {
      // First-ever visit: wait for the token so we don't poison the cache
      // with the wrong key.
      await initVersion();
    }

    const r = await fetch(url);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    const json = await r.json();
    if (dataVersion) {
      try {
        localStorage.setItem(`${PREFIX}${url}:${dataVersion}`, JSON.stringify(json));
      } catch (e) {
        // quota or private-mode — silently skip caching
      }
    }
    return json;
  }

  // Boot: always refresh the token + footer in the background.
  initVersion();

  window.cachedFetch = cachedFetch;
})();
