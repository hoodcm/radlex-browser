"""Decide whether a scheduled run can stop early, because the deployed site already renders this input.

Usage: python3 site/early_exit.py --base-url URL --base-path P [--repo OWNER/NAME]

Reads the newest version tag with `git ls-remote` and URL/version.json, and prints
`skip=true` when the deployed tag, commit, generator commit, and base path all equal this
run's, and `skip=false` otherwise, including when nothing is deployed yet, a file can't be
read, or the deployed build fell back from the newest tag, so a scheduled run retries it.
The workflow appends the line to $GITHUB_OUTPUT.
"""
import argparse
import json
import subprocess
import urllib.error
import urllib.request

import resolve_input
from build import generator_commit, normalize_base


def matches(deployed, record, gen_commit, base_path):
    if not deployed:
        return False
    return (deployed.get("tag") == record.get("tag") and deployed.get("commit") == record.get("commit")
            and deployed.get("generator_commit") == gen_commit
            and deployed.get("base_path") == normalize_base(base_path))


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)
    except (urllib.error.URLError, ValueError, OSError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="the deployed site's URL, from configure-pages")
    parser.add_argument("--base-path", default="", help="this run's base path, from configure-pages")
    parser.add_argument("--repo", default=resolve_input.DEFAULT_REPO, help="GitHub OWNER/NAME to read tags from")
    args = parser.parse_args(argv)
    try:
        tag, commit = resolve_input.select_tag(resolve_input.ls_remote(args.repo))
    except (resolve_input.ResolveError, OSError, subprocess.CalledProcessError):
        tag, commit = None, None
    deployed = fetch(args.base_url.rstrip("/") + "/version.json")
    skip = tag is not None and matches(deployed, {"tag": tag, "commit": commit}, generator_commit(), args.base_path)
    print(f"skip={'true' if skip else 'false'}")


if __name__ == "__main__":
    main()
