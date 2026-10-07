"""Write the browser bundles under data/<build-id>/.

tree.json holds parallel arrays over every tree node, the generated `retired` group
included: `ids`, `labels` (English, by the label fallback order), `children` (lists of
node indexes), and `retired` (0 or 1), plus `top`, the indexes of the top-level nodes.
Nodes are in breadth-first order from the top, children sorted by label.

search-en.json and search-intl.json each hold `keys`, sorted normalized names stored
once, and parallel `postings`: per key, node index * 8 + kind, as one number or a list.
`display` maps a key index to a name's written form when that differs from the key, for
every name but an English label or a RID, which display from tree.json. search-en.json
covers English labels, synonyms, acronyms, misspellings, unsanctioned names, and RIDs,
and search-intl.json the names in other languages. The search worker adds the word-start
entries when it loads a bundle: the start of each key, and each later word that isn't one
of the stop words.

search/index.json lists the shards of the English index, `shards`, sorted, and the stop
words, `stop`. The shard named at position n is search/<n>.json, and it holds every key
with a word start that begins with its name. Shard names are prefix-free: a shard over
SHARD_CAP gzipped bytes is replaced by one shard per next character, and a word start
equal to the split name itself is left to the full index. A shard holds its own node
table, `ids`, `labels`, and `retired`, with `keys`, `postings` (local node index * 8 +
kind), and `display` as in search-en.json. A label equal to its node's label key in the
shard is stored as "", and the worker fills it from the key.
"""
import gzip
import json
import re
import unicodedata
from collections import defaultdict, deque

from model import RETIRED_ID

KIND = {"label": 0, "synonym": 1, "acronym": 2, "misspelling": 3, "unsanctioned": 4, "rid": 5,
        "intl-label": 6, "intl-synonym": 7}
ENGLISH = {"", "en"}
# An English label displays from tree.json, so every other name keeps its written form.
LABEL_KINDS = {KIND["label"], KIND["rid"]}
# Function words that start no word-start entry after a key's first word, so "of" doesn't
# put a third of the index in one shard. A query reaches them as a substring.
STOP = ("a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to")
SHARD_CAP = 32 * 1024


def normalize_key(text):
    """Lowercase, diacritics stripped, punctuation folded to single spaces."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


def tree_order(onto):
    """Node ids in breadth-first order from the top-level nodes."""
    top = list(onto.roots) + ([RETIRED_ID] if onto.retired_group else [])
    order, seen, queue = [], set(), deque(top)
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        order.append(node)
        queue.extend(onto.children.get(node, []))
    order += sorted(set(onto.terms) - seen)
    return order, top


def tree_bundle(onto):
    order, top = tree_order(onto)
    index = {node: i for i, node in enumerate(order)}
    return {
        "ids": order,
        "labels": [onto.label(n) for n in order],
        "children": [[index[c] for c in onto.children.get(n, [])] for n in order],
        "retired": [int(n in onto.terms and onto.terms[n].retired) for n in order],
        "top": [index[n] for n in top],
    }, index


def search_bundle(entries):
    """entries: (name as written, node index, kind). Keys sorted, each stored once."""
    postings, display = defaultdict(list), {}
    for text, node, kind in entries:
        key = normalize_key(text)
        if not key:
            continue
        code = node * 8 + kind
        if code not in postings[key]:
            postings[key].append(code)
        if kind not in LABEL_KINDS:
            display.setdefault(key, text)
    keys = sorted(postings)
    return {
        "keys": keys,
        "postings": [p[0] if len(p) == 1 else sorted(p) for p in (postings[k] for k in keys)],
        "display": {str(i): display[k] for i, k in enumerate(keys) if k in display and display[k] != k},
    }


def search_entries(onto, index):
    en, intl = [], []
    for rid, t in onto.terms.items():
        i = index[rid]
        en.append((rid, i, KIND["rid"]))
        if t.label_value is None or t.label_lang in ENGLISH:
            en.append((t.label, i, KIND["label"]))
        else:
            intl.append((t.label, i, KIND["intl-label"]))
        if t.german_value:
            intl.append((t.german_value.text, i, KIND["intl-label"]))
        names = {"synonym": t.synonyms, "acronym": t.acronyms, "misspelling": t.misspellings,
                 "unsanctioned": t.unsanctioned}
        for field, values in names.items():
            for v in values:
                if v.lang in ENGLISH:
                    en.append((v.text, i, KIND[field]))
                else:
                    intl.append((v.text, i, KIND["intl-synonym"]))
    return en, intl


def word_starts(key, stop=STOP):
    """The suffixes of a key that begin at its start or at a later word not in `stop`."""
    starts, pos = [], 0
    for j, word in enumerate(key.split(" ")):
        if j == 0 or word not in stop:
            starts.append(key[pos:])
        pos += len(word) + 1
    return starts


def shard(key_ids, index, tree):
    """The keys of `index` numbered in key_ids, with a node table of the nodes they post to."""
    local, nodes, label_key = {}, [], {}
    keys, postings, display = [], [], {}
    for k in key_ids:
        p = index["postings"][k]
        codes = []
        for code in ([p] if isinstance(p, int) else p):
            node, kind = divmod(code, 8)
            if node not in local:
                local[node] = len(nodes)
                nodes.append(node)
            codes.append(local[node] * 8 + kind)
            if kind == KIND["label"]:
                label_key[node] = index["keys"][k]
        if str(k) in index["display"]:
            display[str(len(keys))] = index["display"][str(k)]
        keys.append(index["keys"][k])
        postings.append(codes[0] if len(codes) == 1 else sorted(codes))
    return {
        "ids": [tree["ids"][n] for n in nodes],
        "labels": ["" if label_key.get(n) == tree["labels"][n] else tree["labels"][n] for n in nodes],
        "retired": [tree["retired"][n] for n in nodes],
        "keys": keys, "postings": postings, "display": display,
    }


def search_shards(index, tree, cap=SHARD_CAP):
    """Split a search index by the leading characters of its word starts.

    Returns the manifest and the shards in its order. A group of word starts sharing a
    prefix becomes one shard when it gzips to `cap` bytes or less, and otherwise one group
    per next character, dropping the word starts equal to the prefix.
    """
    leaves = {}

    def fits(obj):
        # These shards gzip at most 12 to 1, so a group 16 times the cap skips the measurement.
        raw = len(dump(obj).encode())
        return raw <= cap or (raw <= 16 * cap and gzip_size(obj) <= cap)

    def split(prefix, group):
        obj = shard(sorted({k for _, k in group}), index, tree)
        if fits(obj) or all(len(s) == len(prefix) for s, _ in group):
            leaves[prefix] = obj
            return
        children = defaultdict(list)
        for s, k in group:
            if len(s) > len(prefix):
                children[s[len(prefix)]].append((s, k))
        for c in sorted(children):
            split(prefix + c, children[c])

    first = defaultdict(list)
    for k, key in enumerate(index["keys"]):
        for s in word_starts(key):
            first[s[0]].append((s, k))
    for c in sorted(first):
        split(c, first[c])
    names = sorted(leaves)
    return {"stop": list(STOP), "shards": names}, [leaves[n] for n in names]


def dump(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def gzip_size(obj):
    return len(gzip.compress(dump(obj).encode(), 9))


def write_bundles(onto, out_dir):
    (out_dir / "search").mkdir(parents=True, exist_ok=True)
    tree, index = tree_bundle(onto)
    en, intl = search_entries(onto, index)
    en_index = search_bundle(en)
    manifest, shards = search_shards(en_index, tree)
    sizes = {}
    for name, obj in (("tree.json", tree), ("search-en.json", en_index),
                      ("search-intl.json", search_bundle(intl)), ("search/index.json", manifest)):
        data = dump(obj).encode()
        (out_dir / name).write_bytes(data)
        sizes[name] = {"bytes": len(data), "gzip": len(gzip.compress(data, 9))}
    shard_gzip = []
    for n, obj in enumerate(shards):
        data = dump(obj).encode()
        (out_dir / "search" / f"{n}.json").write_bytes(data)
        shard_gzip.append(len(gzip.compress(data, 9)))
    sizes["search shards"] = {"count": len(shards), "gzip": sum(shard_gzip), "max_gzip": max(shard_gzip, default=0)}
    return sizes
