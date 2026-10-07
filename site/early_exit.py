"""Decide whether a scheduled run can stop early, because the deployed site already renders this input.

Usage: python3 site/early_exit.py --record FILE --base-url URL --base-path P

Reads URL/version.json and prints `skip=true` when the deployed tag, commit, generator
commit, and base path all equal this run's, and `skip=false` otherwise, including when
nothing is deployed yet or the file can't be read. The workflow appends the line to
$GITHUB_OUTPUT.
"""
import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

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
    parser.add_argument("--record", required=True, help="the JSON file resolve_input.py printed")
    parser.add_argument("--base-url", required=True, help="the deployed site's URL, from configure-pages")
    parser.add_argument("--base-path", default="", help="this run's base path, from configure-pages")
    args = parser.parse_args(argv)
    record = json.loads(Path(args.record).read_text())
    deployed = fetch(args.base_url.rstrip("/") + "/version.json")
    skip = matches(deployed, record, generator_commit(), args.base_path)
    print(f"skip={'true' if skip else 'false'}")


if __name__ == "__main__":
    main()
