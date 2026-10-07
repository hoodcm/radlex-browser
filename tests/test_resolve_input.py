"""Contract: resolve_input.py --out DIR prints tag, commit, tag_date, source, path, sha256."""
import hashlib
import json

import pytest

import resolve_input as ri

A = "a" * 40
B = "b" * 40
C = "c" * 40


def ls(*pairs):
    return "".join(f"{sha}\trefs/tags/{name}\n" for sha, name in pairs)


def test_numeric_comparison_beats_string_order():
    assert ri.select_tag(ls((A, "4.9"), (B, "4.10"))) == ("4.10", B)


def test_v_prefix_is_a_version():
    assert ri.select_tag(ls((A, "4.3"), (B, "v4.4"))) == ("v4.4", B)


def test_non_matching_tag_is_ignored():
    assert ri.select_tag(ls((A, "4.3"), (B, "RadLex4.3"), (C, "4.4-rc1"))) == ("4.3", A)


def test_peeled_commit_wins_for_an_annotated_tag():
    text = f"{A}\trefs/tags/4.4\n{B}\trefs/tags/4.4^{{}}\n"
    assert ri.select_tag(text) == ("4.4", B)


def test_no_matching_tag_exits_non_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(ri, "ls_remote", lambda repo: ls((A, "RadLex4.3"), (B, "latest")))
    with pytest.raises(SystemExit) as exc:
        ri.main(["--out", str(tmp_path)])
    assert exc.value.code not in (0, None)


class FakeCheckout:
    files = {"RadLex.owl": b"<owl/>", "README.md": b"x"}

    def __init__(self, repo, tag, workdir):
        pass

    def commit_date(self):
        return "2026-08-10"

    def paths(self):
        return list(self.files)

    def export(self, path, dest):
        open(dest, "wb").write(self.files[path])


def test_release_without_owl_asset_falls_through_to_repo_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ri, "ls_remote", lambda repo: ls((A, "4.3")))
    monkeypatch.setattr(ri, "TagCheckout", FakeCheckout)
    monkeypatch.setattr(ri, "release_assets", lambda repo, tag: [("notes.docx", "https://x/notes.docx")])
    ri.main(["--out", str(tmp_path)])
    record = json.loads(capsys.readouterr().out)
    assert set(record) == {"tag", "commit", "tag_date", "source", "path", "sha256"}
    assert record["source"] == "repo-owl"
    assert record["tag"] == "4.3" and record["commit"] == A and record["tag_date"] == "2026-08-10"
    assert record["sha256"] == hashlib.sha256(b"<owl/>").hexdigest()
    assert open(record["path"], "rb").read() == b"<owl/>"


def test_ofn_is_the_last_resort():
    assert ri.pick_repo_file(["README.md", "src/ontology/radlex-edit.ofn", "a.ofn"]) == (
        "repo-ofn", "src/ontology/radlex-edit.ofn")
    assert ri.pick_repo_file(["README.md"]) is None


def test_owl_asset_preferred_over_zip():
    assets = [("r.owl.zip", "z"), ("RadLex.owl", "o"), ("notes.docx", "d")]
    assert ri.pick_asset(assets) == ("RadLex.owl", "o")
    assert ri.pick_asset([("r.owl.zip", "z")]) == ("r.owl.zip", "z")
