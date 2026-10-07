"""Contracts: the tree.json, search-en.json, and search-intl.json schemas, and the search shards."""
import json
from collections import defaultdict
from pathlib import Path

import pytest

import build
import bundles
from model import RETIRED_ID, RETIRED_LABEL

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module", params=["v44", "v43"])
def built(request, tmp_path_factory):
    out = tmp_path_factory.mktemp(request.param)
    summary = build.build(FIXTURES / request.param, out, "/radlex-browser")
    data = out / "data" / summary["build_id"]
    onto = build.load_ontology(FIXTURES / request.param, None)
    read = lambda name: json.loads((data / name).read_text())  # noqa: E731
    manifest = read("search/index.json")
    shards = [read(f"search/{n}.json") for n in range(len(manifest["shards"]))]
    return onto, out, read("tree.json"), read("search-en.json"), read("search-intl.json"), manifest, shards


def test_tree_schema(built):
    onto, _, tree, *_ = built
    assert set(tree) == {"ids", "labels", "children", "retired", "top"}
    n = len(tree["ids"])
    assert n == len(tree["labels"]) == len(tree["children"]) == len(tree["retired"])
    assert len(set(tree["ids"])) == n == len(onto.terms) + (1 if onto.retired_group else 0)
    assert all(0 <= c < n for kids in tree["children"] for c in kids)
    assert set(tree["retired"]) <= {0, 1}
    assert [tree["ids"][i] for i in tree["top"]] == onto.roots + ([RETIRED_ID] if onto.retired_group else [])


def test_retired_group_node(built):
    onto, _, tree, *_ = built
    if not onto.retired_group:
        pytest.skip("no retired class without a live parent")
    i = tree["ids"].index(RETIRED_ID)
    assert tree["labels"][i] == RETIRED_LABEL
    assert {tree["ids"][c] for c in tree["children"][i]} == set(onto.retired_group)


def test_parent_edges_rebuild_the_models_parents(built):
    onto, _, tree, *_ = built
    parents = defaultdict(set)
    for i, kids in enumerate(tree["children"]):
        for c in kids:
            parents[tree["ids"][c]].add(tree["ids"][i])
    for rid in onto.terms:
        assert parents[rid] == set(onto.parents[rid]), rid
    for i, rid in enumerate(tree["ids"]):
        if rid in onto.terms:
            assert tree["labels"][i] == onto.terms[rid].label
            assert tree["retired"][i] == int(onto.terms[rid].retired)


@pytest.mark.parametrize("bundle", [3, 4])
def test_search_schema_and_ids(built, bundle):
    onto, out, tree, *_ = built
    index = built[bundle]
    assert set(index) == {"keys", "postings", "display"}
    keys = index["keys"]
    assert keys == sorted(set(keys)) and all(k == bundles.normalize_key(k) for k in keys)
    assert len(index["postings"]) == len(keys)
    for p in index["postings"]:
        for code in ([p] if isinstance(p, int) else p):
            rid = tree["ids"][code // 8]
            assert rid in onto.terms and (out / "RID" / f"{rid}.html").is_file()
            assert code % 8 in bundles.KIND.values()
    assert all(0 <= int(i) < len(keys) for i in index["display"])


def test_english_index_covers_labels_and_rids(built):
    onto, _, tree, en, *_ = built
    keys = set(en["keys"])
    for rid, t in onto.terms.items():
        assert bundles.normalize_key(rid) in keys
        if t.label_lang in ("", "en"):
            assert bundles.normalize_key(t.label) in keys


@pytest.mark.parametrize("text, key", [
    ("Liver", "liver"), ("Arteria cerebri média", "arteria cerebri media"),
    ("T1-weighted (MR)", "t1 weighted mr"), ("  RID58 ", "rid58"), ("Größe", "große"),
])
def test_normalize_key(text, key):
    assert bundles.normalize_key(text) == key


def held_by_shards(manifest, shards, index, tree):
    """Assert the shards hold the index: every word start of every key reaches the one shard
    whose name prefixes it, with the key's postings and node labels, or equals a split name."""
    names = manifest["shards"]
    assert names == sorted(set(names))
    assert not [n for n in names if any(n[:i] in names for i in range(1, len(n)))], "names not prefix-free"
    found = {}
    for name, obj in zip(names, shards):
        assert set(obj) == {"ids", "labels", "retired", "keys", "postings", "display"}
        ids, labels = obj["ids"], list(obj["labels"])
        assert len(ids) == len(labels) == len(obj["retired"]) and len(obj["keys"]) == len(obj["postings"])
        assert obj["keys"] == sorted(obj["keys"]) and all(0 <= int(i) < len(obj["keys"]) for i in obj["display"])
        for key, p in zip(obj["keys"], obj["postings"]):
            codes = [p] if isinstance(p, int) else p
            assert any(s.startswith(name) for s in bundles.word_starts(key, set(manifest["stop"]))), (name, key)
            found[name, key] = {(ids[c // 8], c % 8) for c in codes}
            for c in codes:
                if c % 8 == bundles.KIND["label"] and labels[c // 8] == "":
                    labels[c // 8] = key
        assert labels == [tree["labels"][tree["ids"].index(i)] for i in ids], name
    for k, key in enumerate(index["keys"]):
        p = index["postings"][k]
        codes = {(tree["ids"][c // 8], c % 8) for c in ([p] if isinstance(p, int) else p)}
        for s in bundles.word_starts(key, set(manifest["stop"])):
            name = next((n for n in names if s.startswith(n)), None)
            if name is None:
                assert any(n.startswith(s) for n in names), f"word start {s!r} reaches no shard"
            else:
                assert found.get((name, key)) == codes, (name, key)


def test_written_shards_hold_the_english_index(built):
    _, _, tree, en, _, manifest, shards = built
    assert manifest["stop"] == list(bundles.STOP)
    held_by_shards(manifest, shards, en, tree)


@pytest.mark.parametrize("cap", [2048, 256])
def test_split_shards_hold_the_english_index(built, cap):
    _, _, tree, en, *_ = built
    manifest, shards = bundles.search_shards(en, tree, cap=cap)
    assert max(map(len, manifest["shards"])) > 1, "the cap forced no split"
    held_by_shards(manifest, shards, en, tree)
    # A shard exceeds the cap only when it can't split: each of its word starts is its name.
    for name, obj in zip(manifest["shards"], shards):
        if bundles.gzip_size(obj) > cap:
            starts = {s for k in obj["keys"] for s in bundles.word_starts(k) if s.startswith(name)}
            assert starts == {name}, (name, sorted(starts)[:3])


@pytest.mark.parametrize("key, starts", [
    ("liver", ["liver"]),
    ("left lobe of liver", ["left lobe of liver", "lobe of liver", "liver"]),
    ("of the lung", ["of the lung", "lung"]),
    ("t1 weighted", ["t1 weighted", "weighted"]),
])
def test_word_starts_skip_later_stop_words(key, starts):
    assert bundles.word_starts(key) == starts
