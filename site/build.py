"""Build the static RadLex browser.

Usage: python3 site/build.py --input OWL_OR_TSV_DIR --out DIR --base-path P [--record FILE]

--input is an OWL file, extracted with ROBOT, or a directory of query TSVs such as a test
fixture. --base-path is an empty string or /name, and every internal URL is absolute
under it. --record is the JSON that resolve_input.py printed, and version.json carries
it. Without one, the build records the input's own SHA-256 and leaves the tag fields
empty. The build ID is the first 12 hex characters of the SHA-256 of the input sha256,
the generator commit, and the base path, joined by newlines.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import extract
import model
import render

SITE = Path(__file__).resolve().parent
STATIC = SITE / "static"
NOT_SHIPPED = {"boot.js", "VENDORED.md"}
VERSION_FIELDS = ("tag", "commit", "tag_date", "source", "sha256", "generator_commit",
                  "base_path", "build_id", "built_at")


def normalize_base(base):
    base = (base or "").strip().rstrip("/")
    if base and not base.startswith("/"):
        base = "/" + base
    return base


def generator_commit():
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=SITE, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_id(input_sha, gen_commit, base):
    return hashlib.sha256(f"{input_sha}\n{gen_commit}\n{base}".encode()).hexdigest()[:12]


def input_sha256(path):
    path = Path(path)
    if path.is_file():
        return extract.sha256_file(path)
    digest = hashlib.sha256()
    for f in sorted(path.glob("*.tsv")):
        digest.update(f.name.encode() + b"\0" + f.read_bytes())
    return digest.hexdigest()


def prepare_out(out):
    """Empty the output folder, refusing anything that isn't a previous build."""
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        if not (out / "version.json").is_file():
            sys.exit(f"build: {out} is not empty and holds no version.json, so it is not a build to replace")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def copy_static(out, bid):
    dest = out / "static" / bid
    for src in STATIC.rglob("*"):
        if src.is_file() and src.name not in NOT_SHIPPED:
            target = dest / src.relative_to(STATIC)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)


def load_ontology(input_path, workdir):
    input_path = Path(input_path)
    if input_path.is_dir():
        ex = extract.load(input_path)
    else:
        ex = extract.extract(input_path, workdir)
    return model.Ontology(ex)


def build(input_path, out, base, record=None, workdir=None):
    started = time.time()
    base = normalize_base(base)
    record = dict(record or {})
    record.setdefault("sha256", input_sha256(input_path))
    for key in ("tag", "commit", "tag_date", "source"):
        record.setdefault(key, "")
    gen = generator_commit()
    bid = build_id(record["sha256"], gen, base)

    with tempfile.TemporaryDirectory() as tmp:
        onto = load_ontology(input_path, workdir or tmp)
    out = prepare_out(out)
    ctx = render.Context(onto, base, bid, record, (STATIC / "boot.js").read_text().strip())

    for rid in onto.terms:
        write(out / "RID" / f"{rid}.html", render.term_page(ctx, rid))
    write(out / "index.html", render.home_page(ctx))
    write(out / "404.html", render.not_found_page(ctx))
    copy_static(out, bid)

    version = {k: record.get(k, "") for k in ("tag", "commit", "tag_date", "source", "sha256")}
    version.update(generator_commit=gen, base_path=base, build_id=bid,
                   built_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    write(out / "version.json", json.dumps(version, indent=2) + "\n")
    files = [f for f in out.rglob("*") if f.is_file()]
    return {"build_id": bid, "base_path": base, "terms": len(onto.terms), "files": len(files),
            "bytes": sum(f.stat().st_size for f in files), "seconds": round(time.time() - started, 1)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, help="an OWL file or a directory of query TSVs")
    parser.add_argument("--out", required=True, help="the site folder to write")
    parser.add_argument("--base-path", default="", help='"" or /name, with no trailing slash')
    parser.add_argument("--record", help="the JSON file resolve_input.py printed")
    args = parser.parse_args(argv)
    record = json.loads(Path(args.record).read_text()) if args.record else None
    print(json.dumps(build(args.input, args.out, args.base_path, record)))


if __name__ == "__main__":
    main()
