"""Contracts: build.py flags, page paths, the build-ID meta tag, and version.json fields."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

import build

FIXTURES = Path(__file__).parent / "fixtures"
VERSION_FIELDS = {"tag", "commit", "tag_date", "source", "sha256", "generator_commit",
                  "base_path", "build_id", "built_at"}
LEFTOVERS = ("\\n", "\\t", '\\"', '"@', "^^", "&amp;amp;", "&amp;quot;", "&amp;lt;")


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.urls, self.text, self.meta, self.stack = [], [], {}, []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for key in ("href", "src"):
            if a.get(key):
                self.urls.append(a[key])
        if tag == "meta" and a.get("name"):
            self.meta[a["name"]] = a.get("content")

    def handle_data(self, data):
        self.text.append(data)


def internal(url):
    return not re.match(r"^(https?:|mailto:|#)", url)


@pytest.fixture(scope="module", params=[("v44", "/radlex-browser"), ("v44", ""), ("v43", "/radlex-browser"), ("v43", "")])
def site(request, tmp_path_factory):
    shape, base = request.param
    out = tmp_path_factory.mktemp(f"{shape}-site")
    record = {"tag": "4.4", "commit": "c" * 40, "tag_date": "2026-10-07", "source": "release-asset"}
    summary = build.build(FIXTURES / shape, out, base, record)
    return shape, base, out, summary


def test_page_paths_and_version_json(site):
    shape, base, out, summary = site
    version = json.loads((out / "version.json").read_text())
    assert set(version) == VERSION_FIELDS and all(version[k] is not None for k in VERSION_FIELDS)
    assert version["base_path"] == base and version["build_id"] == summary["build_id"]
    assert re.fullmatch(r"[0-9a-f]{12}", version["build_id"])
    pages = sorted(p.stem for p in (out / "RID").glob("*.html"))
    assert len(pages) == summary["terms"]
    assert (out / "index.html").is_file() and (out / "404.html").is_file()
    assert (out / "static" / version["build_id"] / "site.css").is_file()


def test_every_page_carries_the_build_id_and_base_path_urls(site):
    shape, base, out, summary = site
    for path in [out / "index.html", out / "404.html", *(out / "RID").glob("*.html")]:
        page = Page(path.read_text())
        assert page.meta["radlex-build"] == summary["build_id"]
        for url in filter(internal, page.urls):
            assert url.startswith(base + "/"), f"{path.name}: {url}"
        text = "".join(page.text)
        assert not any(s in text for s in LEFTOVERS), path.name


def test_rid665_relationships_in_five_groups(site):
    out = site[2]
    html = (out / "RID" / "RID665.html").read_text()
    rel = re.search(r'<section class="s-relationships".*?</section>', html).group(0)
    assert "Relationships (25)" in rel
    assert len(re.findall(r'<span class="reader-name">', rel)) == 5
    assert len(re.findall(r"<li>", rel)) == 25


def test_retired_banner_names_the_replacement(site):
    out = site[2]
    html = (out / "RID" / "RID10103.html").read_text()
    banner = re.search(r'<div class="banner".*?</div>', html).group(0)
    assert "RID10191" in banner and "Use " in banner


@pytest.mark.parametrize("shape, rid, word", [("v44", "RID11209", "laprascopic"), ("v43", "RID28438", "allathalamus")])
def test_misspelling_never_displays(tmp_path, shape, rid, word):
    build.build(FIXTURES / shape, tmp_path, "")
    assert word not in (tmp_path / "RID" / f"{rid}.html").read_text()


def test_build_id_follows_its_inputs():
    assert build.build_id("a", "g", "") != build.build_id("a", "g", "/radlex-browser")
    assert build.build_id("a", "g", "") == build.build_id("a", "g", "")
    assert build.normalize_base("radlex-browser/") == "/radlex-browser"
    assert build.normalize_base("/") == ""


def test_refuses_to_replace_a_folder_that_is_not_a_build(tmp_path):
    (tmp_path / "keep.txt").write_text("mine")
    with pytest.raises(SystemExit):
        build.build(FIXTURES / "v44", tmp_path, "")
    assert (tmp_path / "keep.txt").read_text() == "mine"


def test_cli_flags(tmp_path, capsys):
    record = tmp_path / "record.json"
    record.write_text(json.dumps({"tag": "4.4", "commit": "c", "tag_date": "2026-10-07",
                                  "source": "repo-owl", "path": "x", "sha256": "f" * 64}))
    build.main(["--input", str(FIXTURES / "v44"), "--out", str(tmp_path / "s"),
                "--base-path", "/radlex-browser", "--record", str(record)])
    summary = json.loads(capsys.readouterr().out)
    version = json.loads((tmp_path / "s" / "version.json").read_text())
    assert version["tag"] == "4.4" and version["sha256"] == "f" * 64
    assert summary["build_id"] == version["build_id"]
