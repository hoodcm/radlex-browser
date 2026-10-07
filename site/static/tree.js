// The hierarchy sidebar: a virtual list of fixed-height rows over tree.json.
import { navigate, prefetch, currentState } from "./nav.js";

const R = window.RADLEX;
const ROW = 28;
const OVERSCAN = 8;
const MAX_PINS = 5;
const FILTER_LIMIT = 2000;
const CHEVRON = '<svg viewBox="0 0 8 8" aria-hidden="true"><path d="M2 1 6 4 2 7Z" fill="currentColor"/></svg>';
const norm = (s) => s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

const sidebar = document.querySelector(".sidebar");
if (sidebar && getComputedStyle(sidebar).display !== "none") init();

async function init() {
  const tree = await (await fetch(R.data + "tree.json")).json();
  const { ids, labels, children, retired, top } = tree;
  const index = new Map(ids.map((id, i) => [id, i]));
  // The parent each node was first reached from, breadth first: the filter's ancestor chain.
  const firstParent = new Int32Array(ids.length).fill(-1);
  for (let i = 0; i < ids.length; i++) for (const c of children[i]) if (firstParent[c] < 0 && !top.includes(c)) firstParent[c] = i;
  let normLabels = null;

  sidebar.innerHTML =
    '<div class="filter"><input type="search" placeholder="Filter the tree" aria-label="Filter the tree" spellcheck="false"></div>' +
    '<div class="scroller" tabindex="0" role="tree" aria-label="RadLex hierarchy"><div class="pins"></div><div class="rows"></div></div>' +
    '<div class="resizer" role="separator" aria-orientation="vertical" aria-label="Resize the sidebar"></div>';
  const input = sidebar.querySelector("input");
  const scroller = sidebar.querySelector(".scroller");
  const rowsEl = sidebar.querySelector(".rows");
  const pinsEl = sidebar.querySelector(".pins");

  const expanded = new Set();
  let rows = [];            // {node, depth, parent: row index}
  let visible = null;       // filter: the set of nodes to show, or null
  let matches = null;
  let current = null;       // node index of the page's term
  let currentRow = -1;
  let active = 0;           // keyboard row

  function flatten() {
    const out = [];
    const onPath = new Set();
    const walk = (node, depth, parent) => {
      const row = out.length;
      out.push({ node, depth, parent });
      if (!(visible ? true : expanded.has(node))) return;
      onPath.add(node);
      for (const c of children[node]) {
        if (onPath.has(c) || (visible && !visible.has(c))) continue;
        walk(c, depth + 1, row);
      }
      onPath.delete(node);
    };
    for (const t of top) if (!visible || visible.has(t)) walk(t, 0, -1);
    rows = out;
    rowsEl.style.height = `${rows.length * ROW}px`;
  }

  function isOpen(row) {
    return visible ? children[row.node].some((c) => visible.has(c)) : expanded.has(row.node);
  }

  function ancestors(r) {
    const chain = [];
    for (let p = rows[r]?.parent ?? -1; p >= 0; p = rows[p].parent) chain.unshift(p);
    return chain;
  }

  // The rows pinned at the top: the last ancestors of the first row under the pins.
  function pins(first) {
    let k = 0;
    for (let i = 0; i < MAX_PINS + 1; i++) {
      const chain = ancestors(first + k).slice(-MAX_PINS);
      if (chain.length === k) return chain;
      k = chain.length;
    }
    return ancestors(first + k).slice(-MAX_PINS);
  }

  function rowHtml(r, top) {
    const row = rows[r];
    const node = row.node;
    const n = children[node].length;
    const cls = ["row"];
    if (retired[node]) cls.push("retired");
    if (matches?.has(node)) cls.push("match");
    if (r === active) cls.push("active");
    const id = ids[node];
    const href = id === "retired" ? "" : ` href="${R.base}/RID/${id}.html"`;
    const ind = row.depth ? `<span class="ind">${"<i></i>".repeat(row.depth)}</span>` : "";
    const label = labels[node].replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    return `<a class="${cls.join(" ")}" style="top:${top}px" data-row="${r}"${href} role="treeitem" aria-level="${row.depth + 1}"` +
      `${n ? ` aria-expanded="${isOpen(row)}"` : ""}${r === currentRow ? ' aria-current="page"' : ""} title="${label}">` +
      `${ind}<span class="tw">${n ? CHEVRON : ""}</span><span class="lb">${label}</span>${n ? `<span class="ct">${n}</span>` : ""}</a>`;
  }

  function draw() {
    const scrollTop = scroller.scrollTop;
    const first = Math.floor(scrollTop / ROW);
    const pinned = pins(first);
    const height = scroller.clientHeight;
    const from = Math.max(0, first - OVERSCAN);
    const to = Math.min(rows.length, Math.ceil((scrollTop + height) / ROW) + OVERSCAN);
    let html = "";
    for (let r = from; r < to; r++) html += rowHtml(r, r * ROW);
    rowsEl.innerHTML = html;
    pinsEl.innerHTML = pinned.map((r, i) => rowHtml(r, i * ROW)).join("");
  }

  function setActive(r, reveal = true) {
    active = Math.max(0, Math.min(rows.length - 1, r));
    scroller.setAttribute("aria-activedescendant", "");
    if (reveal) revealRow(active, "nearest");
    draw();
  }

  function revealRow(r, mode) {
    const pinnedHeight = Math.min(ancestors(r).length, MAX_PINS) * ROW;
    const top = r * ROW;
    const viewTop = scroller.scrollTop + pinnedHeight;
    const viewBottom = scroller.scrollTop + scroller.clientHeight;
    if (mode === "center") scroller.scrollTop = Math.max(0, top - scroller.clientHeight / 2 + ROW / 2);
    else if (top < viewTop) scroller.scrollTop = top - pinnedHeight;
    else if (top + ROW > viewBottom) scroller.scrollTop = top + ROW - scroller.clientHeight;
  }

  function findRow(path) {
    // The row reached by following the path from the top, or the first row of the node.
    let r = -1;
    for (let depth = 0; depth < path.length; depth++) {
      const node = index.get(path[depth]);
      let next = -1;
      for (let i = r + 1; i < rows.length; i++) {
        if (rows[i].depth < depth) break;
        if (rows[i].depth === depth && rows[i].node === node && rows[i].parent === r) { next = i; break; }
      }
      if (next < 0) return rows.findIndex((row) => row.node === index.get(path[path.length - 1]));
      r = next;
    }
    return r;
  }

  function select({ rid, path }, reveal) {
    current = index.has(rid) ? index.get(rid) : null;
    if (current == null) { currentRow = -1; draw(); return; }
    for (const id of path.slice(0, -1)) if (index.has(id)) expanded.add(index.get(id));
    if (!visible) flatten();
    currentRow = findRow(path.filter((id) => index.has(id)));
    if (currentRow >= 0) {
      active = currentRow;
      const r = currentRow;
      const inView = r * ROW >= scroller.scrollTop + MAX_PINS * ROW && (r + 1) * ROW <= scroller.scrollTop + scroller.clientHeight;
      if (reveal === "center" || !inView) revealRow(r, "center");
    }
    draw();
  }

  function toggle(r) {
    const node = rows[r].node;
    if (!children[node].length || visible) return;
    if (expanded.has(node)) expanded.delete(node); else expanded.add(node);
    flatten();
    currentRow = current == null ? -1 : findRow(currentState().path.filter((id) => index.has(id)));
    draw();
  }

  function applyFilter(text) {
    const q = norm(text);
    if (!q) {
      visible = matches = null;
      flatten();
      select(currentState(), "center");
      return;
    }
    normLabels ??= labels.map(norm);
    matches = new Set();
    for (let i = 0; i < normLabels.length && matches.size < FILTER_LIMIT; i++) if (normLabels[i].includes(q)) matches.add(i);
    visible = new Set();
    for (const m of matches) for (let n = m; n >= 0 && !visible.has(n); n = firstParent[n]) visible.add(n);
    flatten();
    currentRow = -1;
    active = 0;
    scroller.scrollTop = 0;
    draw();
  }

  scroller.addEventListener("scroll", () => requestAnimationFrame(draw), { passive: true });
  new ResizeObserver(() => draw()).observe(scroller);

  scroller.addEventListener("click", (event) => {
    const el = event.target.closest(".row");
    if (!el) return;
    const r = Number(el.dataset.row);
    if (event.target.closest(".tw") || !el.hasAttribute("href")) {
      event.preventDefault();
      setActive(r, false);
      toggle(r);
    }
  });
  scroller.addEventListener("mouseover", (event) => {
    const el = event.target.closest(".row[href]");
    if (el) prefetch(el.href);
  });

  scroller.addEventListener("keydown", (event) => {
    const row = rows[active];
    if (!row) return;
    switch (event.key) {
      case "ArrowDown": setActive(active + 1); break;
      case "ArrowUp": setActive(active - 1); break;
      case "Home": setActive(0); break;
      case "End": setActive(rows.length - 1); break;
      case "ArrowRight":
        if (children[row.node].length && !isOpen(row)) toggle(active);
        else if (children[row.node].length) setActive(active + 1);
        break;
      case "ArrowLeft":
        if (isOpen(row) && !visible) toggle(active);
        else if (row.parent >= 0) setActive(row.parent);
        break;
      case "Enter":
        if (ids[row.node] !== "retired") navigate(`${R.base}/RID/${ids[row.node]}.html`);
        else toggle(active);
        break;
      default:
        if (event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
          input.focus();
          return;
        }
        return;
    }
    event.preventDefault();
  });

  let filterTimer = null;
  input.addEventListener("input", () => {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(() => applyFilter(input.value), 80);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") { event.preventDefault(); scroller.focus(); setActive(0); }
    if (event.key === "Escape") { input.value = ""; applyFilter(""); }
  });

  // Drag the sidebar's edge to resize it, saved per site.
  const resizer = sidebar.querySelector(".resizer");
  resizer.addEventListener("pointerdown", (event) => {
    resizer.setPointerCapture(event.pointerId);
    const left = sidebar.getBoundingClientRect().left;
    const move = (e) => {
      const width = Math.round(Math.max(200, Math.min(640, e.clientX - left)));
      document.documentElement.style.setProperty("--sidebar", `${width}px`);
    };
    const up = () => {
      resizer.removeEventListener("pointermove", move);
      const width = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--sidebar"), 10);
      if (width) R.store.set("sidebar", String(width));
    };
    resizer.addEventListener("pointermove", move);
    resizer.addEventListener("pointerup", up, { once: true });
  });

  document.addEventListener("radlex:navigated", (event) => select(event.detail));
  flatten();
  select(currentState(), "center");
  R.tree = {
    state: () => ({ rows: rows.length, current: currentRow >= 0 ? ids[rows[currentRow].node] : null,
                    expanded: [...expanded].map((i) => ids[i]), filtering: visible !== null }),
  };
}
