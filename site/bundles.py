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
entries when it loads a bundle.
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


def dump(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def write_bundles(onto, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    tree, index = tree_bundle(onto)
    en, intl = search_entries(onto, index)
    sizes = {}
    for name, obj in (("tree.json", tree), ("search-en.json", search_bundle(en)),
                      ("search-intl.json", search_bundle(intl))):
        data = dump(obj).encode()
        (out_dir / name).write_bytes(data)
        sizes[name] = {"bytes": len(data), "gzip": len(gzip.compress(data, 9))}
    return sizes
