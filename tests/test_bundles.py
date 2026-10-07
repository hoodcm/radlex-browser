"""Contracts: the tree.json, search-en.json, and search-intl.json schemas."""
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
    return onto, out, read("tree.json"), read("search-en.json"), read("search-intl.json")


def test_tree_schema(built):
    onto, _, tree, _, _ = built
    assert set(tree) == {"ids", "labels", "children", "retired", "top"}
    n = len(tree["ids"])
    assert n == len(tree["labels"]) == len(tree["children"]) == len(tree["retired"])
    assert len(set(tree["ids"])) == n == len(onto.terms) + (1 if onto.retired_group else 0)
    assert all(0 <= c < n for kids in tree["children"] for c in kids)
    assert set(tree["retired"]) <= {0, 1}
    assert [tree["ids"][i] for i in tree["top"]] == onto.roots + ([RETIRED_ID] if onto.retired_group else [])


def test_retired_group_node(built):
    onto, _, tree, _, _ = built
    if not onto.retired_group:
        pytest.skip("no retired class without a live parent")
    i = tree["ids"].index(RETIRED_ID)
    assert tree["labels"][i] == RETIRED_LABEL
    assert {tree["ids"][c] for c in tree["children"][i]} == set(onto.retired_group)


def test_parent_edges_rebuild_the_models_parents(built):
    onto, _, tree, _, _ = built
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
    onto, _, tree, en, _ = built
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
