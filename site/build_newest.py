"""Build the newest RSNA/RadLex version tag whose build passes the site gates.

Usage: python3 site/build_newest.py --out DIR --base-path P --work DIR [--summary FILE] [--attempts N] [--repo OWNER/NAME]

Tries the version tags newest first, at most N of them (default 3). Each attempt resolves
the tag's input into WORK/<tag>/input, builds it into WORK/<tag>/site with the ROBOT output
in WORK/<tag>/tsv, and runs check_site.py on it. WORK must be empty or absent. The first build that passes moves to --out,
which must not exist yet. A tag that fails to resolve, build, or pass the gates is skipped,
and the build that ships names the newest tag in version.json's `fallback_from`. Appends any
fallback, with each failure's reason, and the gate table to --summary, prints a GitHub
warning on a fallback, and exits non-zero when every attempt fails, so the deployed site
stays as it was.
"""
import argparse
import contextlib
import io
import shutil
import sys
import traceback
from pathlib import Path

import build
import check_site
import resolve_input


class GateFailure(Exception):
    pass


def attempt(repo, pick, work, base, fallback_from):
    """Resolve, build, and gate one tag. Returns the site folder and the gate table."""
    folder = work / pick[0]
    record = resolve_input.resolve(repo, folder / "input", pick)
    if fallback_from:
        record["fallback_from"] = fallback_from
    site = folder / "site"
    build.build(record["path"], site, base, record, folder)
    tsv = Path(record["path"]) if Path(record["path"]).is_dir() else folder / "tsv"
    table, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(table), contextlib.redirect_stderr(errors):
        try:
            check_site.main([str(site), "--tsv", str(tsv)])
        except SystemExit as exc:
            if exc.code:
                raise GateFailure(errors.getvalue().strip()) from None
    return site, table.getvalue()


def reason(exc):
    if isinstance(exc, GateFailure):
        return str(exc)
    return "".join(traceback.format_exception_only(exc)).strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="the site folder to write, which must not exist")
    parser.add_argument("--base-path", default="", help='"" or /name, with no trailing slash')
    parser.add_argument("--work", required=True, help="a folder for each attempt's input, build, and ROBOT output")
    parser.add_argument("--summary", help="a Markdown file to append the outcome to, such as $GITHUB_STEP_SUMMARY")
    parser.add_argument("--attempts", type=int, default=3, help="how many tags to try, newest first")
    parser.add_argument("--repo", default=resolve_input.DEFAULT_REPO, help="GitHub OWNER/NAME to read tags from")
    args = parser.parse_args(argv)
    out, work = Path(args.out), Path(args.work)
    if out.exists():
        sys.exit(f"build_newest: {out} already exists")
    if work.exists() and any(work.iterdir()):
        sys.exit(f"build_newest: {work} is not empty")
    tags = resolve_input.version_tags(resolve_input.ls_remote(args.repo))[:args.attempts]
    if not tags:
        sys.exit(f"build_newest: no tag matches {resolve_input.TAG_PATTERN.pattern}")

    failures, shipped, table = [], None, ""
    for pick in tags:
        fallback_from = {"tag": tags[0][0], "commit": tags[0][1]} if failures else None
        try:
            site, table = attempt(args.repo, pick, work, args.base_path, fallback_from)
        except (Exception, SystemExit) as exc:  # any failure on a tag moves on to the next one down
            failures.append((pick[0], reason(exc)))
            print(f"build_newest: {pick[0]} failed: {failures[-1][1]}", file=sys.stderr)
            continue
        shutil.move(str(site), str(out))
        shipped = pick[0]
        break

    lines = []
    if failures:
        lead = f"Fell back to `{shipped}`" if shipped else "Every tag tried failed, so nothing deploys"
        lines.append(f"**{lead}.** These tags failed, newest first:\n")
        for tag, why in failures:
            detail = " ".join(why.split())
            lines.append(f"- `{tag}`: {detail[:500]}")
        lines.append("")
        if shipped:
            print(f"::warning title=Fell back to {shipped}::{failures[0][0]} failed: {' '.join(failures[0][1].split())[:300]}")
    report = "\n".join(lines) + table
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(report + "\n")
    else:
        print(report)
    if not shipped:
        sys.exit(1)


if __name__ == "__main__":
    main()
