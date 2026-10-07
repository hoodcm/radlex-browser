"""Contract: build_newest.py ships the newest tag that passes, falling back one tag at a time."""
import json
import shutil
from pathlib import Path

import pytest

import build_newest
import resolve_input

FIXTURES = Path(__file__).parent / "fixtures"
A, B, C = "a" * 40, "b" * 40, "c" * 40


def broken_count(tmp_path):
    """A 4.4-shape input whose scoped class count disagrees with its pages."""
    folder = tmp_path / "broken"
    shutil.copytree(FIXTURES / "v44", folder)
    (folder / "count.tsv").write_text("?n\n99999\n")
    return folder


@pytest.fixture
def tags(monkeypatch):
    """Tags 4.4, 4.3, and 4.2, with the input each resolves to set by the test."""
    inputs = {}

    def resolve(repo, out_dir, pick):
        source = inputs[pick[0]]
        if isinstance(source, Exception):
            raise source
        return {"tag": pick[0], "commit": pick[1], "tag_date": "2026-08-10", "source": "repo-owl",
                "path": str(source), "sha256": pick[1]}

    text = "".join(f"{sha}\trefs/tags/{tag}\n" for sha, tag in ((B, "4.3"), (A, "4.4"), (C, "4.2")))
    monkeypatch.setattr(resolve_input, "ls_remote", lambda repo: text)
    monkeypatch.setattr(resolve_input, "resolve", resolve)
    return inputs


def run(tmp_path, *extra):
    summary = tmp_path / "summary.md"
    args = ["--out", str(tmp_path / "_site"), "--base-path", "/radlex-browser",
            "--work", str(tmp_path / "work"), "--summary", str(summary), *extra]
    try:
        build_newest.main(args)
        code = 0
    except SystemExit as exc:
        code = exc.code
    return code, summary.read_text() if summary.exists() else ""


def version(tmp_path):
    return json.loads((tmp_path / "_site" / "version.json").read_text())


def test_newest_tag_that_passes_ships_without_fallback(tmp_path, tags):
    tags.update({"4.4": FIXTURES / "v44", "4.3": FIXTURES / "v43"})
    code, summary = run(tmp_path)
    assert code == 0
    assert version(tmp_path)["tag"] == "4.4" and "fallback_from" not in version(tmp_path)
    assert "Fell back" not in summary and "| Tag |" in summary


@pytest.mark.parametrize("failure", ["gate", "resolve"])
def test_a_failing_newest_tag_falls_back_to_the_next(tmp_path, tags, capsys, failure):
    tags["4.4"] = broken_count(tmp_path) if failure == "gate" else resolve_input.ResolveError("no OWL")
    tags["4.3"] = FIXTURES / "v43"
    code, summary = run(tmp_path)
    assert code == 0
    assert version(tmp_path)["tag"] == "4.3"
    assert version(tmp_path)["fallback_from"] == {"tag": "4.4", "commit": A}
    assert "Fell back to `4.3`" in summary and "`4.4`:" in summary and "| Fell back from | `4.4` |" in summary
    assert "::warning title=Fell back to 4.3::4.4 failed" in capsys.readouterr().out


def test_every_tag_failing_exits_non_zero_and_ships_nothing(tmp_path, tags):
    tags.update({"4.4": broken_count(tmp_path), "4.3": resolve_input.ResolveError("no OWL")})
    code, summary = run(tmp_path, "--attempts", "2")
    assert code not in (0, None)
    assert not (tmp_path / "_site").exists()
    assert "Every tag tried failed" in summary and "`4.4`:" in summary and "`4.3`:" in summary
    assert "`4.2`" not in summary


def test_version_tags_are_newest_first():
    text = f"{A}\trefs/tags/4.9\n{B}\trefs/tags/4.10\n{C}\trefs/tags/RadLex4.3\n"
    assert resolve_input.version_tags(text) == [("4.10", B), ("4.9", A)]
