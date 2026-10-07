"""check_site.py passes a clean build and fails closed on each failure shape."""
import json
import os
import shutil
from pathlib import Path

import pytest

import build
import check_site

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module", params=["v44", "v43"])
def clean(request, tmp_path_factory):
    out = tmp_path_factory.mktemp(f"clean-{request.param}") / "site"
    build.build(FIXTURES / request.param, out, "/radlex-browser")
    return FIXTURES / request.param, out


def run(site, tsv):
    try:
        check_site.main([str(site), "--tsv", str(tsv)])
    except SystemExit as exc:
        return exc.code
    return 0


def tree_path(site):
    bid = json.loads((site / "version.json").read_text())["build_id"]
    return site / "data" / bid / "tree.json"


def edit_tree(site, change):
    path = tree_path(site)
    tree = json.loads(path.read_text())
    change(tree)
    path.write_text(json.dumps(tree))


def delete_page(site):
    (site / "RID" / "RID58.html").unlink()


def mislabel(site):
    page = site / "RID" / "RID58.html"
    page.write_text(page.read_text().replace("<title>liver | RadLex</title>", "<title>Leber | RadLex</title>"))


def second_root(site):
    def change(tree):
        rid1 = tree["ids"].index("RID1")
        for kids in tree["children"]:
            if rid1 in kids:
                kids.remove(rid1)
    edit_tree(site, change)


def corrupt_children(site):
    def change(tree):
        i = tree["ids"].index("RID35904")
        tree["children"][i][0] = tree["ids"].index("RID58")
    edit_tree(site, change)


def broken_link(site):
    page = site / "RID" / "RID665.html"
    page.write_text(page.read_text().replace("/RID/RID35904.html", "/RID/RID99999999.html", 1))


def oversized(site):
    page = site / "RID" / "RID665.html"
    page.write_text(page.read_text() + "<!--" + os.urandom(48 * 1024).hex() + "-->")


def search_dir(site):
    bid = json.loads((site / "version.json").read_text())["build_id"]
    return site / "data" / bid / "search"


def shard_missing_key(site):
    path = search_dir(site) / "0.json"
    shard = json.loads(path.read_text())
    del shard["keys"][0], shard["postings"][0]
    shard["display"] = {}
    path.write_text(json.dumps(shard))


def shard_file_missing(site):
    (search_dir(site) / "0.json").unlink()


def version_field(site):
    path = site / "version.json"
    version = json.loads(path.read_text())
    del version["generator_commit"]
    path.write_text(json.dumps(version))


def test_clean_build_passes(clean):
    tsv, site = clean
    assert run(site, tsv) == 0


@pytest.mark.parametrize("mutate", [delete_page, mislabel, second_root, corrupt_children,
                                    broken_link, oversized, version_field, shard_missing_key,
                                    shard_file_missing])
def test_failure_shape_fails(clean, tmp_path, mutate):
    tsv, site = clean
    copy = tmp_path / "site"
    shutil.copytree(site, copy)
    mutate(copy)
    assert run(copy, tsv) == 1


def test_no_class_in_the_namespaces_fails_by_name(clean, tmp_path, capsys):
    tsv, site = clean
    empty = tmp_path / "tsv"
    shutil.copytree(tsv, empty)
    (empty / "count.tsv").write_text("?n\n0\n")
    (empty / "classes.tsv").write_text("?c\n")
    assert run(site, empty) == 1
    assert "no named classes in the namespaces of namespaces.json" in capsys.readouterr().err


def test_summary_reports_unmapped_properties(clean, capsys):
    tsv, site = clean
    assert run(site, tsv) == 0
    assert "| Unmapped annotation properties |" in capsys.readouterr().out
