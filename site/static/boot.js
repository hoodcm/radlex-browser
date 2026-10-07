// Inlined in every page head: applies saved settings before first paint, then loads the runtime.
(() => {
  const root = document.documentElement;
  const meta = (name) => document.querySelector(`meta[name="${name}"]`)?.content ?? "";
  const base = meta("radlex-base");
  const build = meta("radlex-build");
  const prefix = `radlex:${base}:`;
  const store = {
    get(key) { try { return localStorage.getItem(prefix + key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(prefix + key, value); } catch {} },
  };
  const view = store.get("view");
  if (view === "ontology" || view === "reader") root.dataset.view = view;
  const width = store.get("sidebar");
  if (/^\d+$/.test(width ?? "")) root.style.setProperty("--sidebar", `${width}px`);
  window.RADLEX = { base, build, prefix, store, static: `${base}/static/${build}/`, data: `${base}/data/${build}/` };
  const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1));
  const load = () => {
    for (const name of ["nav.js", "tree.js", "search.js"]) import(window.RADLEX.static + name);
  };
  const afterPaint = () => requestAnimationFrame(() => setTimeout(() => idle(load), 0));
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", afterPaint, { once: true });
  else afterPaint();
})();
