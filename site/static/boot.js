// Inlined in every page head. Applies the saved view before first paint, then loads the runtime.
(() => {
  const root = document.documentElement;
  const meta = (name) => document.querySelector(`meta[name="${name}"]`)?.content ?? "";
  const base = meta("radlex-base");
  const prefix = `radlex:${base}:`;
  try {
    const view = localStorage.getItem(prefix + "view");
    if (view === "ontology" || view === "reader") root.dataset.view = view;
  } catch {}
  window.RADLEX = { base, build: meta("radlex-build"), prefix };
})();
