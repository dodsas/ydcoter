/* Footer build stamp: fills #footer-version with "<short sha> · <deploy time>".
 * Each Render deploy ships a fresh container, so process start == deploy time. */
(function () {
  const el = document.getElementById("footer-version");
  if (!el) return;

  fetch("/version")
    .then((r) => (r.ok ? r.json() : null))
    .then((v) => {
      if (!v) return;
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
    })
    .catch(() => {});
})();
