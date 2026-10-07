"""Contracts: the Pages workflow's triggers and its early-exit rule."""
from pathlib import Path

import pytest

import early_exit

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "pages.yml"


def test_triggers_permissions_and_concurrency():
    text = WORKFLOW.read_text()
    on = text[text.index("\non:\n"):text.index("\npermissions:")]
    assert "push:\n    branches: [main]" in on
    assert "workflow_dispatch:" in on
    assert "schedule:" in on and "cron:" in on
    assert "permissions:\n  contents: read\n  pages: write\n  id-token: write" in text
    assert "concurrency:\n  group: pages" in text
    for action in ("actions/configure-pages@v6", "actions/upload-pages-artifact@v5", "actions/deploy-pages@v5"):
        assert action in text


def test_only_a_scheduled_run_can_skip():
    text = WORKFLOW.read_text()
    assert 'if [ "${{ github.event_name }}" = "schedule" ]; then' in text
    assert "site/early_exit.py" in text


def test_the_build_falls_back_through_build_newest():
    text = WORKFLOW.read_text()
    assert "python3 site/build_newest.py --out _site" in text
    assert '--summary "$GITHUB_STEP_SUMMARY"' in text


RECORD = {"tag": "4.3", "commit": "d53bd9c", "tag_date": "2026-08-10", "source": "release-asset"}
DEPLOYED = {"tag": "4.3", "commit": "d53bd9c", "generator_commit": "g1", "base_path": "/radlex-browser",
            "build_id": "x", "sha256": "s", "tag_date": "2026-08-10", "source": "release-asset", "built_at": "t"}


def test_skips_when_tag_commit_generator_and_base_path_match():
    assert early_exit.matches(DEPLOYED, RECORD, "g1", "/radlex-browser")
    assert early_exit.matches(DEPLOYED, RECORD, "g1", "/radlex-browser/")


@pytest.mark.parametrize("change", [
    {"tag": "4.4"}, {"commit": "e000000"}, {"generator_commit": "g2"}, {"base_path": ""},
])
def test_rebuilds_when_any_of_the_four_differs(change):
    deployed = {**DEPLOYED, **change}
    assert not early_exit.matches(deployed, RECORD, "g1", "/radlex-browser")


def test_rebuilds_when_nothing_is_deployed():
    assert not early_exit.matches(None, RECORD, "g1", "/radlex-browser")
