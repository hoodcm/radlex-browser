// Search worker. A query is answered first from one small shard of the English index, named by
// the query's leading characters in search/index.json, and then from the full index, tree.json
// and search-en.json, which loads in the background from the first query on. A shard answers
// prefix and word-prefix matches in full. Substring matches, from three characters, names in
// other languages, and a query too short to name a shard need the full index, so results are
// marked partial until it lands. Word starts are each key's start and every later word that
// isn't a stop word, and prefixes match by binary search over them.
const KIND = { label: 0, synonym: 1, acronym: 2, misspelling: 3, unsanctioned: 4, rid: 5, intlLabel: 6, intlSynonym: 7 };
const LIMIT = 50;
const norm = (s) => s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

let data = "";
let manifest = null;       // Promise of Map(shard name -> file number)
let stop = new Set();
const shards = new Map();  // shard name -> Promise of a prepared shard
let full = null;           // { tree, indexes } once the full index has loaded
let fullLoading = null;
let intlOn = false, intlReady = false, intlLoading = null;
let last = null;           // { q, rules, keys: Map(index name -> key ids) }, over the full index
let latest = null;         // the newest query message, answered again when the full index lands

function get(path, priority = "auto") {
  return fetch(data + path, { priority }).then((r) => {
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  });
}

function prepare(bundle, name) {
  const { keys, postings, display } = bundle;
  // Word starts after the first: sorted once, then merged with the keys, which are sorted already.
  const later = [];
  for (let k = 0; k < keys.length; k++) {
    const key = keys[k];
    for (let p = key.indexOf(" "); p >= 0; p = key.indexOf(" ", p + 1)) {
      const end = key.indexOf(" ", p + 1);
      if (!stop.has(key.slice(p + 1, end < 0 ? key.length : end))) later.push([key.slice(p + 1), k]);
    }
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
  // Every key in one string, so a substring is found with indexOf. "\n" joins them, and no
  // normalized query holds it, so a match never spans two keys. starts[k] is key k's offset.
  const starts = new Int32Array(keys.length + 1);
  for (let k = 0, at = 0; k <= keys.length; k++) { starts[k] = at; at += (keys[k]?.length ?? 0) + 1; }
  return { name, keys, postings, display, sfx, key, joined: keys.join("\n"), starts, mark: new Uint32Array(keys.length), stamp: 0 };
}

// A shard carries its own node table, and a label stored as "" is its node's label key.
function prepareShard(bundle, name) {
  const { keys, postings, labels } = bundle;
  for (let k = 0; k < keys.length; k++) {
    const p = postings[k];
    for (const code of typeof p === "number" ? [p] : p) {
      if (code % 8 === KIND.label && labels[Math.floor(code / 8)] === "") labels[Math.floor(code / 8)] = keys[k];
    }
  }
  const ix = prepare(bundle, name);
  ix.table = { ids: bundle.ids, labels, retired: bundle.retired };
  return ix;
}

function lowerBound(arr, q) {
  let lo = 0, hi = arr.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid] < q) lo = mid + 1; else hi = mid; }
  return lo;
}

// The key holding offset p of the joined string.
function keyAt(starts, p) {
  let lo = 0, hi = starts.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (starts[mid] <= p) lo = mid; else hi = mid; }
  return lo;
}

// How a key matches: 0 at its start, 1 at a later word start, 2 inside a word, -1 not at all.
function matchType(key, q, substrings) {
  if (key.startsWith(q)) return 0;
  for (let p = key.indexOf(" "); p >= 0; p = key.indexOf(" ", p + 1)) if (key.startsWith(q, p + 1)) return 1;
  return substrings && key.includes(q) ? 2 : -1;
}

// The keys with a word start that begins with q, and with `substrings` every key holding q.
function candidates(ix, q, substrings) {
  const stamp = ++ix.stamp, mark = ix.mark, found = [];
  for (let r = lowerBound(ix.sfx, q); r < ix.sfx.length && ix.sfx[r].startsWith(q); r++) {
    const k = ix.key[r];
    if (mark[k] !== stamp) { mark[k] = stamp; found.push(k); }
  }
  if (substrings) {
    for (let p = ix.joined.indexOf(q); p >= 0; ) {
      const k = keyAt(ix.starts, p);
      if (mark[k] !== stamp) { mark[k] = stamp; found.push(k); }
      p = ix.joined.indexOf(q, ix.starts[k + 1]);
    }
  }
  return found;
}

function tier(kind, type, exact) {
  if (kind === KIND.label || kind === KIND.rid) return exact ? 0 : type === 0 ? 1 : type === 1 ? 3 : 4;
  return type === 0 ? 2 : type === 1 ? 3 : 4;
}

// Each node's best tier and the name it matched by, kept per node table and reset after each
// search, because a Map over thousands of matching nodes costs more than the search itself.
const UNSET = 5;
function scratch(table) {
  table.scratch ??= { tier: new Int8Array(table.ids.length).fill(UNSET), via: new Array(table.ids.length).fill(null), touched: [] };
  return table.scratch;
}

// Ranks the matches of q in indexes that share one node table. `pools` holds each index's
// matching keys for the previous query when the results narrow, and is null otherwise.
function searchIn(q, indexes, table, substrings, pools) {
  const keysBy = new Map();
  const { tier: tierOf, via: viaOf, touched } = scratch(table);
  touched.length = 0;
  // A RID matches only once the query holds a digit, so "r" doesn't list every term by its RID.
  const rids = /\d/.test(q);
  for (const ix of indexes) {
    const pool = pools ? pools.get(ix.name) : candidates(ix, q, substrings);
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
        if (t < tierOf[node]) {
          if (tierOf[node] === UNSET) touched.push(node);
          tierOf[node] = t;
          viaOf[node] = kind === KIND.label || kind === KIND.rid || kind === KIND.misspelling ? null : ix.display[k] ?? key;
        }
      }
    }
    keysBy.set(ix.name, kept);
  }
  const results = top(touched, tierOf, table).map((node) => ({
    id: table.ids[node], label: table.labels[node], retired: table.retired[node], tier: tierOf[node], via: viaOf[node],
  }));
  for (const node of touched) tierOf[node] = UNSET;
  return { out: { q, results, total: touched.length }, keysBy };
}

// The LIMIT best nodes, ranked retired last, then by tier, label length, and label. A histogram
// over the integer part of that order finds the cut in one pass, so only the kept nodes are sorted.
const MAX_LENGTH = 255;
function top(nodes, tierOf, table) {
  const rank = (node) => (table.retired[node] * 5 + tierOf[node]) * (MAX_LENGTH + 1) + Math.min(table.labels[node].length, MAX_LENGTH);
  const counts = new Uint32Array(2 * 5 * (MAX_LENGTH + 1));
  for (const node of nodes) counts[rank(node)] += 1;
  let cut = 0;
  for (let seen = 0; cut < counts.length && seen < LIMIT; cut++) seen += counts[cut];
  const kept = [];
  for (const node of nodes) if (rank(node) < cut) kept.push(node);
  kept.sort((a, b) => rank(a) - rank(b) || (table.labels[a] < table.labels[b] ? -1 : 1));
  return kept.slice(0, LIMIT);
}

// One-character queries match the most terms and narrow from nothing, so their answers are
// computed once, in the background after the full index loads, and kept until an index loads.
const oneChar = new Map();
function fullSearch(q) {
  const substrings = q.length >= 3;
  const rules = `${substrings}|${full.indexes.map((ix) => ix.name).join(",")}`;
  // Below three characters the word-start range is exact and cheap, so only substring
  // queries narrow the previous query's matches.
  const narrow = substrings && last && last.rules === rules && q.startsWith(last.q);
  let found = q.length === 1 ? oneChar.get(q) : null;
  if (!found) {
    found = searchIn(q, full.indexes, full.tree, substrings, narrow ? last.keys : null);
    if (q.length === 1) oneChar.set(q, found);
  }
  last = { q, rules, keys: found.keysBy };
  return found.out;
}

function warmOneChar() {
  const chars = [...new Set(full.indexes[0].keys.map((key) => Array.from(key)[0]))];
  const next = () => {
    const c = chars.pop();
    if (c === undefined) return;
    if (!oneChar.has(c)) oneChar.set(c, searchIn(c, full.indexes, full.tree, false, null));
    setTimeout(next, 0);
  };
  setTimeout(next, 0);
}

// The shard whose name is a prefix of q, or null when no shard name is: either q is shorter than
// the shards under it, or no word start begins with q.
async function shardFor(q) {
  const names = await manifest;
  const chars = Array.from(q);
  for (let i = 1; i <= chars.length; i++) {
    const name = chars.slice(0, i).join("");
    if (!names.has(name)) continue;
    if (!shards.has(name)) {
      const loading = get(`search/${names.get(name)}.json`, "high").then((b) => prepareShard(b, name));
      loading.catch(() => shards.delete(name));
      shards.set(name, loading);
    }
    return shards.get(name);
  }
  return null;
}

function loadFull() {
  fullLoading ??= Promise.all([manifest, get("tree.json", "low"), get("search-en.json", "low")]).then(([, tree, en]) => {
    full = { tree, indexes: [prepare(en, "en")] };
    last = null;
    self.postMessage({ type: "complete" });
    if (latest?.partial) respond(latest);
    warmOneChar();
  });
  return fullLoading;
}

function loadIntl() {
  intlLoading ??= loadFull().then(() => get("search-intl.json")).then((b) => {
    full.indexes.push(prepare(b, "intl"));
    intlReady = true;
    last = null;
    oneChar.clear();
  });
  return intlLoading;
}

async function answer(raw) {
  const q = norm(raw);
  if (!q) return { q, results: [], total: 0, partial: false };
  if (intlOn) loadIntl();
  else loadFull();
  if (!full) {
    const ix = await shardFor(q).catch(() => null);
    if (!full) {
      const out = ix ? searchIn(q, [ix], ix.table, q.length >= 3, null).out : { q, results: [], total: 0 };
      return { ...out, partial: q.length >= 3 || intlOn || out.total === 0 };
    }
  }
  let out = fullSearch(q);
  if (out.total === 0 && !intlLoading) { await loadIntl(); out = fullSearch(q); }
  return { ...out, partial: intlOn && !intlReady };
}

async function respond(msg) {
  const out = await answer(msg.q);
  if (msg === latest) msg.partial = out.partial;
  self.postMessage({ type: "results", seq: msg.seq, ...out });
}

function showIntl() {
  intlOn = true;
  loadIntl().then(() => {
    self.postMessage({ type: "intl-ready" });
    if (latest?.partial) respond(latest);
  });
}

self.onmessage = ({ data: msg }) => {
  if (msg.type === "init") {
    data = msg.data;
    manifest = get("search/index.json").then((m) => {
      stop = new Set(m.stop);
      return new Map(m.shards.map((name, n) => [name, n]));
    });
    intlOn = Boolean(msg.intl);   // the saved setting: other languages load with the first query
  } else if (msg.type === "intl") {
    showIntl();
  } else if (msg.type === "query") {
    latest = msg;
    respond(msg);
  }
};
