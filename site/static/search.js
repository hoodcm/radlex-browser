// The ⌘K search dialog. Queries go to search-worker.js, which starts when this module loads so the
// shard list is in hand before the first keystroke, and results open through nav.js.
import { navigate, prefetch } from "./nav.js";

const R = window.RADLEX;
let dialog = null, input = null, list = null, count = null, intlBox = null, worker = null;
let seq = 0, shown = { q: null, results: [] }, selected = 0, enterPending = false;
R.searchLog = [];

const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function startWorker() {
  worker = new Worker(R.static + "search-worker.js");
  worker.onmessage = ({ data }) => {
    if (data.type === "results") receive(data);
    else if (data.type === "complete") R.searchComplete = true;
  };
  worker.postMessage({ type: "init", data: R.data, intl: R.store.get("langs") === "1" });
}

function build() {
  dialog = document.createElement("dialog");
  dialog.className = "search-dialog";
  dialog.setAttribute("aria-label", "Search RadLex");
  dialog.innerHTML =
    '<form method="dialog" role="search">' +
    '<input type="search" placeholder="Search by name, synonym, or RID" aria-label="Search RadLex" autocomplete="off" spellcheck="false" ' +
    'role="combobox" aria-expanded="true" aria-controls="search-results" aria-autocomplete="list">' +
    '<ul class="results" id="search-results" role="listbox" aria-label="Results"></ul>' +
    '<div class="status"><span class="count" aria-live="polite"></span>' +
    '<label><input type="checkbox" class="intl"> Other languages</label></div></form>';
  document.body.append(dialog);
  input = dialog.querySelector('input[type="search"]');
  list = dialog.querySelector(".results");
  count = dialog.querySelector(".count");
  intlBox = dialog.querySelector(".intl");
  intlBox.checked = R.store.get("langs") === "1";

  input.addEventListener("input", query);
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      move(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Escape") {
      event.preventDefault();
      dialog.close();
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (shown.q === input.value && shown.results.length) open(shown.results[selected]);
      else enterPending = true;
    }
  });
  list.addEventListener("click", (event) => {
    const li = event.target.closest("li[data-id]");
    if (li) open(shown.results[Number(li.dataset.i)]);
  });
  list.addEventListener("mouseover", (event) => {
    const li = event.target.closest("li[data-id]");
    if (li) prefetch(`${R.base}/RID/${li.dataset.id}.html`);
  });
  intlBox.addEventListener("change", () => {
    R.store.set("langs", intlBox.checked ? "1" : "0");
    if (intlBox.checked) worker.postMessage({ type: "intl" });
    query();
  });
}

function query() {
  seq += 1;
  R.searchLog.push({ input: input.value, t: performance.now() });
  worker.postMessage({ type: "query", q: input.value, seq });
}

function receive(data) {
  if (data.seq !== seq) return;
  shown = { q: input.value, results: data.results };
  selected = 0;
  list.innerHTML = data.results.map((r, i) =>
    `<li role="option" id="sr-${i}" data-i="${i}" data-id="${escapeHtml(r.id)}" aria-selected="${i === 0}">` +
    `<span class="lb">${escapeHtml(r.label)}${r.via ? ` <span class="via">${escapeHtml(r.via)}</span>` : ""}</span>` +
    `${r.retired ? '<span class="chip">Retired</span>' : ""}<span class="chip">${escapeHtml(r.id)}</span></li>`).join("");
  input.setAttribute("aria-activedescendant", data.results.length ? "sr-0" : "");
  // Partial results lack substring matches or other languages until the full index loads.
  const terms = `${data.total.toLocaleString()}${data.partial ? "+" : ""} ${data.total === 1 && !data.partial ? "term" : "terms"}`;
  count.textContent = !data.q ? "" : data.partial && !data.total ? "Searching…" : terms;
  list.dataset.query = input.value;
  list.dataset.partial = String(Boolean(data.partial));
  // When the results are in the DOM, and when the next frame paints them.
  R.searchLog.push({ rendered: input.value, t: performance.now() });
  const painted = { painted: input.value, n: data.results.length, partial: Boolean(data.partial) };
  requestAnimationFrame(() => R.searchLog.push({ ...painted, t: performance.now() }));
  if (enterPending) { enterPending = false; if (data.results.length) open(data.results[0]); }
}

function move(step) {
  if (!shown.results.length) return;
  selected = (selected + step + shown.results.length) % shown.results.length;
  for (const li of list.children) li.setAttribute("aria-selected", String(Number(li.dataset.i) === selected));
  input.setAttribute("aria-activedescendant", `sr-${selected}`);
  list.children[selected]?.scrollIntoView({ block: "nearest" });
}

function open(result) {
  if (!result) return;
  dialog.close();
  navigate(`${R.base}/RID/${result.id}.html`);
}

export function openSearch(initial = "") {
  if (!dialog) build();
  if (!dialog.open) dialog.showModal();
  if (initial) { input.value = initial; query(); }
  input.select();
}

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    openSearch();
  }
});
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-search]")) openSearch();
});
R.openSearch = openSearch;
startWorker();
