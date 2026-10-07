// Search worker: loads tree.json and search-en.json, adds an entry at every word start of each
// key, matches prefixes by binary search, and matches substrings from three characters.
const KIND = { label: 0, synonym: 1, acronym: 2, misspelling: 3, unsanctioned: 4, rid: 5, intlLabel: 6, intlSynonym: 7 };
const LIMIT = 50;
const norm = (s) => s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

let data = "";
let tree = null;
const indexes = [];        // loaded search indexes, English first
let intlLoading = null;
let last = null;           // { q, rules, keys: Map(index -> Int32Array of key ids) }

function prepare(bundle, name) {
  const { keys, postings, display } = bundle;
  // Word starts after the first: sorted once, then merged with the keys, which are sorted already.
  const later = [];
  for (let k = 0; k < keys.length; k++) {
    const key = keys[k];
    for (let p = key.indexOf(" "); p >= 0; p = key.indexOf(" ", p + 1)) later.push([key.slice(p + 1), k]);
  }
  later.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  const n = keys.length + later.length;
  const sfx = new Array(n);
  const key = new Int32Array(n);
  let i = 0, j = 0, o = 0;
  while (i < keys.length || j < later.length) {
    if (j >= later.length || (i < keys.length && keys[i] <= later[j][0])) { sfx[o] = keys[i]; key[o++] = i++; }
    else { sfx[o] = later[j][0]; key[o++] = later[j++][1]; }
  }
  return { name, keys, postings, display, sfx, key };
}

function lowerBound(arr, q) {
  let lo = 0, hi = arr.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid] < q) lo = mid + 1; else hi = mid; }
  return lo;
}

// How a key matches: 0 at its start, 1 at a later word start, 2 inside a word, -1 not at all.
function matchType(key, q, substrings) {
  if (key.startsWith(q)) return 0;
  for (let p = key.indexOf(" "); p >= 0; p = key.indexOf(" ", p + 1)) if (key.startsWith(q, p + 1)) return 1;
  return substrings && key.includes(q) ? 2 : -1;
}

function candidates(ix, q, substrings) {
  const found = new Set();
  for (let r = lowerBound(ix.sfx, q); r < ix.sfx.length && ix.sfx[r].startsWith(q); r++) found.add(ix.key[r]);
  if (substrings) for (let k = 0; k < ix.keys.length; k++) if (!found.has(k) && ix.keys[k].includes(q)) found.add(k);
  return found;
}

function tier(kind, type, exact) {
  if (kind === KIND.label || kind === KIND.rid) return exact ? 0 : type === 0 ? 1 : type === 1 ? 3 : 4;
  return type === 0 ? 2 : type === 1 ? 3 : 4;
}

function search(raw) {
  const q = norm(raw);
  if (!q) return { q, results: [], total: 0 };
  const substrings = q.length >= 3;
  const rules = `${substrings}|${indexes.map((ix) => ix.name).join(",")}`;
  const narrow = last && last.rules === rules && q.startsWith(last.q);
  const keysBy = new Map();
  const best = new Map();    // node -> [tier, via]
  // A RID matches only once the query holds a digit, so "r" doesn't list every term by its RID.
  const rids = /\d/.test(q);
  for (const ix of indexes) {
    const pool = narrow ? last.keys.get(ix.name) : candidates(ix, q, substrings);
    const kept = [];
    for (const k of pool) {
      const key = ix.keys[k];
      const type = matchType(key, q, substrings);
      if (type < 0) continue;
      kept.push(k);
      const p = ix.postings[k];
      for (const code of typeof p === "number" ? [p] : p) {
        const node = Math.floor(code / 8), kind = code % 8;
        if (kind === KIND.rid && !rids) continue;
        const t = tier(kind, type, key === q);
        const prev = best.get(node);
        if (!prev || t < prev[0]) {
          const via = kind === KIND.label || kind === KIND.rid || kind === KIND.misspelling ? null : ix.display[k] ?? key;
          best.set(node, [t, via]);
        }
      }
    }
    keysBy.set(ix.name, kept);
  }
  last = { q, rules, keys: keysBy };
  const results = top(best).map((node) => ({
    id: tree.ids[node], label: tree.labels[node], retired: tree.retired[node], tier: best.get(node)[0], via: best.get(node)[1],
  }));
  return { q, results, total: best.size };
}

// The LIMIT best nodes, ranked retired last, then by tier, label length, and label. A histogram
// over the integer part of that order finds the cut in one pass, so only the kept nodes are sorted.
const MAX_LENGTH = 255;
function rank(node, t) {
  return (tree.retired[node] * 5 + t) * (MAX_LENGTH + 1) + Math.min(tree.labels[node].length, MAX_LENGTH);
}
function top(best) {
  const counts = new Uint32Array(2 * 5 * (MAX_LENGTH + 1));
  for (const [node, [t]] of best) counts[rank(node, t)] += 1;
  let cut = 0;
  for (let seen = 0; cut < counts.length && seen < LIMIT; cut++) seen += counts[cut];
  const kept = [];
  for (const [node, [t]] of best) if (rank(node, t) < cut) kept.push(node);
  kept.sort((a, b) => rank(a, best.get(a)[0]) - rank(b, best.get(b)[0]) || (tree.labels[a] < tree.labels[b] ? -1 : 1));
  return kept.slice(0, LIMIT);
}

async function loadIntl() {
  intlLoading ??= fetch(data + "search-intl.json").then((r) => r.json()).then((b) => { indexes.push(prepare(b, "intl")); last = null; });
  return intlLoading;
}

let ready = null;
self.onmessage = async ({ data: msg }) => {
  if (msg.type === "init") {
    data = msg.data;
    ready = Promise.all([fetch(data + "tree.json").then((r) => r.json()), fetch(data + "search-en.json").then((r) => r.json())])
      .then(([t, en]) => { tree = t; indexes.push(prepare(en, "en")); self.postMessage({ type: "ready" }); });
    if (msg.intl) loadIntl();
    return;
  }
  await ready;
  if (msg.type === "intl") { await loadIntl(); self.postMessage({ type: "intl-ready" }); return; }
  if (msg.type === "query") {
    let out = search(msg.q);
    if (out.total === 0 && out.q && !intlLoading) { await loadIntl(); out = search(msg.q); }
    self.postMessage({ type: "results", seq: msg.seq, ...out });
  }
};
