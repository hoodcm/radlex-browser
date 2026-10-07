// In-site navigation: swaps <main> and <title> from prefetched pages, and the page chrome.
const R = window.RADLEX;
const root = document.documentElement;
const TERM = new RegExp(`^${R.base.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/RID/[^/]+\\.html$`);
const CACHE_SIZE = 50;
const PREFETCH_ON_SCREEN = 12;
const cache = new Map();

function termUrl(href) {
  try {
    const url = new URL(href, location.href);
    if (url.origin !== location.origin || !TERM.test(url.pathname)) return null;
    return url;
  } catch { return null; }
}

function fetchPage(path) {
  if (cache.has(path)) {
    const hit = cache.get(path);
    cache.delete(path);
    cache.set(path, hit);
    return hit;
  }
  const pending = fetch(path, { credentials: "same-origin" }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.text();
  });
  pending.catch(() => cache.delete(path));
  cache.set(path, pending);
  while (cache.size > CACHE_SIZE) cache.delete(cache.keys().next().value);
  return pending;
}

export function prefetch(href) {
  const url = termUrl(href);
  if (url) fetchPage(url.pathname).catch(() => {});
}

export function currentState() {
  const article = document.querySelector("main .detail");
  const rid = article?.dataset.rid ?? null;
  const path = [...document.querySelectorAll("main .crumbs a, main .crumbs .group")].map((el) =>
    el.classList.contains("group") ? "retired" : el.getAttribute("href").split("/").pop().replace(/\.html$/, ""));
  return { rid, path: rid ? [...path, rid] : [] };
}

function announce() {
  document.dispatchEvent(new CustomEvent("radlex:navigated", { detail: currentState() }));
}

async function swap(path, push) {
  const text = await fetchPage(path);
  const doc = new DOMParser().parseFromString(text, "text/html");
  const build = doc.querySelector('meta[name="radlex-build"]')?.content;
  const main = doc.querySelector("main");
  if (build !== R.build || !main) throw new Error("build changed");
  document.querySelector("main").replaceChildren(...main.childNodes);
  document.title = doc.title;
  if (push) history.pushState({ path }, "", path);
  const scroller = document.querySelector("main");
  scroller.scrollTop = 0;
  const h1 = scroller.querySelector("h1");
  if (h1) { h1.tabIndex = -1; h1.focus({ preventScroll: true }); }
  announce();
  observeOnScreen();
}

export async function navigate(href, { push = true } = {}) {
  const url = termUrl(href);
  if (!url) { location.href = href; return; }
  if (push && url.pathname === location.pathname) return;
  try { await swap(url.pathname, push); }
  catch { location.href = url.href; }
}

document.addEventListener("click", (event) => {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = event.target.closest("a[href]");
  if (!link || link.target || link.hasAttribute("download")) return;
  if (!termUrl(link.href)) return;
  event.preventDefault();
  navigate(link.href);
});

window.addEventListener("popstate", () => {
  const url = termUrl(location.href);
  if (url) swap(url.pathname, false).catch(() => location.reload());
  else location.reload();
});

// Prefetch on a 100 ms hover and on keyboard focus.
let hoverTimer = null;
document.addEventListener("mouseover", (event) => {
  const link = event.target.closest?.("a[href]");
  if (!link) return;
  clearTimeout(hoverTimer);
  hoverTimer = setTimeout(() => prefetch(link.href), 100);
});
document.addEventListener("mouseout", (event) => {
  if (event.target.closest?.("a[href]")) clearTimeout(hoverTimer);
});
document.addEventListener("focusin", (event) => {
  const link = event.target.closest?.("a[href]");
  if (link) prefetch(link.href);
});

// On coarse pointers, prefetch the first term links that scroll into view.
const coarse = matchMedia("(pointer: coarse)").matches;
let observer = null;
function observeOnScreen() {
  if (!coarse || !("IntersectionObserver" in window)) return;
  observer?.disconnect();
  let budget = PREFETCH_ON_SCREEN;
  observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting || budget <= 0) continue;
      budget -= 1;
      prefetch(entry.target.href);
      observer.unobserve(entry.target);
    }
    if (budget <= 0) observer.disconnect();
  });
  for (const link of document.querySelectorAll("main a[href]")) if (termUrl(link.href)) observer.observe(link);
}

// The view switch and the breadcrumb's hidden levels.
function syncViewSwitch() {
  for (const button of document.querySelectorAll("[data-view-switch]")) {
    button.setAttribute("aria-pressed", String(root.dataset.view === "ontology"));
  }
}
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-view-switch]")) {
    root.dataset.view = root.dataset.view === "ontology" ? "reader" : "ontology";
    R.store.set("view", root.dataset.view);
    syncViewSwitch();
  }
  const more = event.target.closest(".crumbs .more");
  if (more) {
    more.nextElementSibling?.removeAttribute("hidden");
    more.remove();
  }
});

history.replaceState({ path: location.pathname }, "");
syncViewSwitch();
observeOnScreen();
R.navigate = navigate;
R.state = currentState;
announce();
