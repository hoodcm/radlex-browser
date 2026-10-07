"""Fail-closed gates on a built site.

Usage: python3 site/check_site.py SITE --tsv DIR [--sample N]

DIR is the query output of the ROBOT run that built SITE, so every count is checked
against that run's scoped class count, never a number written here. Exits non-zero when:
the page count differs from the scoped count; a class with an @en label renders another
title; the tree has other than one live root plus the retired group; tree.json's parent
edges differ from the pages' "Is a" lists, or a search posting names a node with no
page; an internal link in the sample is broken; a page exceeds 40 KB gzipped or the site
900 MB; or version.json lacks a field. Prints the file count, the site size, and the
gzipped bundle sizes as a Markdown table.
"""
import argparse
import gzip
import html
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import extract

PAGE_GZIP_LIMIT = 40 * 1024
SITE_LIMIT = 900 * 1024 * 1024
VERSION_FIELDS = ("tag", "commit", "tag_date", "source", "sha256", "generator_commit",
                  "base_path", "build_id", "built_at")
RETIRED_ID = "retired"
# The pages the browser smoke test, the linter pass, and the speed check open.
NAMED_SAMPLE = ("RID665", "RID10103", "RID58", "RID10191", "RID35904", "RID36443")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
ISA_RE = re.compile(r"<dt>Is a</dt><dd>(.*?)</dd>", re.S)
HREF_RE = re.compile(r'\b(?:href|src)="([^"]*)"')
TERM_HREF_RE = re.compile(r'<a href="[^"]*/RID/([^"/]+)\.html"')


class Gate:
    def __init__(self):
        self.failures = []

    def fail(self, message):
        self.failures.append(message)


def english_labels(tsv):
    """The first @en label per class IRI, normalized as the extraction does."""
    labels = {}
    for _, (c, p, v) in extract.read_tsv(tsv / "annotations.tsv"):
        if (isinstance(c, extract.IRI) and p.value == "http://www.w3.org/2000/01/rdf-schema#label"
                and isinstance(v, extract.Literal) and v.lang == "en"):
            labels.setdefault(c.value, extract.normalize(v.lex))
    return labels


def check_pages(site, tsv, gate):
    count = next(int(cells[0].lex) for _, cells in extract.read_tsv(tsv / "count.tsv"))
    classes = [cells[0].value for _, cells in extract.read_tsv(tsv / "classes.tsv")]
    pages = {p.stem: p for p in (site / "RID").glob("*.html")}
    if len(pages) != count:
        gate.fail(f"{len(pages)} term pages against a scoped class count of {count}")
    missing = {extract.local_name(c) for c in classes} - set(pages)
    if missing:
        gate.fail(f"{len(missing)} classes have no page, such as {sorted(missing)[:3]}")
    labels = {extract.local_name(iri): label for iri, label in english_labels(tsv).items()}
    isa, oversized = {}, []
    for rid, path in pages.items():
        text = path.read_text(encoding="utf-8")
        if len(gzip.compress(text.encode(), 6)) > PAGE_GZIP_LIMIT:
            oversized.append(rid)
        m = ISA_RE.search(text)
        isa[rid] = set()
        if m:
            isa[rid] = set(TERM_HREF_RE.findall(m.group(1)))
            if 'class="group"' in m.group(1):
                isa[rid].add(RETIRED_ID)
        if rid in labels:
            title = html.unescape(TITLE_RE.search(text).group(1))
            h1 = html.unescape(H1_RE.search(text).group(1))
            if title != f"{labels[rid]} | RadLex" or h1 != labels[rid]:
                gate.fail(f"{rid} renders {h1!r} for its @en label {labels[rid]!r}")
    if oversized:
        gate.fail(f"{len(oversized)} pages exceed 40 KB gzipped, such as {oversized[:3]}")
    return pages, isa


def check_tree(site, data, pages, isa, gate):
    tree = json.loads((data / "tree.json").read_text())
    ids = tree["ids"]
    parents = defaultdict(set)
    for i, kids in enumerate(tree["children"]):
        for c in kids:
            if not 0 <= c < len(ids):
                gate.fail(f"tree.json: {ids[i]} has an out-of-range child index {c}")
                continue
            parents[ids[c]].add(ids[i])
    roots = [n for n in ids if not parents[n]]
    live = [n for i, n in enumerate(ids) if n in roots and n != RETIRED_ID and not tree["retired"][i]]
    others = [n for n in roots if n not in live and n != RETIRED_ID]
    if len(live) != 1 or others:
        gate.fail(f"the tree has {len(live)} live roots {live[:3]} and parentless nodes {others[:3]}, "
                  "against one live root plus the retired group")
    if sorted(ids[i] for i in tree["top"]) != sorted(roots):
        gate.fail("tree.json top differs from its parentless nodes")
    if set(ids) - {RETIRED_ID} != set(pages):
        gate.fail("tree.json ids differ from the term pages")
    wrong = [rid for rid in pages if parents[rid] != isa.get(rid, set())]
    if wrong:
        gate.fail(f"{len(wrong)} pages' Is a lists differ from tree.json's parent edges, such as {wrong[:3]}")
    for name in ("search-en.json", "search-intl.json"):
        index = json.loads((data / name).read_text())
        bad = 0
        for p in index["postings"]:
            for code in ([p] if isinstance(p, int) else p):
                node = code // 8
                if not 0 <= node < len(ids) or ids[node] not in pages:
                    bad += 1
        if bad:
            gate.fail(f"{name}: {bad} postings name a node with no page")
        if len(index["postings"]) != len(index["keys"]):
            gate.fail(f"{name}: postings and keys differ in length")
    return tree


def resolve(site, base, url):
    """The file an internal URL serves on Pages, or None when it points outside the base."""
    path = url.split("#")[0].split("?")[0]
    if not path.startswith(base + "/"):
        return None
    rel = path[len(base) + 1:]
    target = site / rel
    if rel == "" or rel.endswith("/"):
        return target / "index.html"
    if not target.suffix and not target.exists():
        return target.with_suffix(".html")
    return target


def check_links(site, base, pages, build_id, gate):
    rng = random.Random(build_id)
    sample = [site / "index.html", site / "404.html"]
    sample += [pages[r] for r in NAMED_SAMPLE if r in pages]
    sample += [pages[r] for r in rng.sample(sorted(pages), min(500, len(pages)))]
    broken = []
    for page in dict.fromkeys(sample):
        for url in HREF_RE.findall(page.read_text(encoding="utf-8")):
            url = html.unescape(url)
            if re.match(r"^(https?:|mailto:|#)", url):
                continue
            target = resolve(site, base, url)
            if target is None or not target.is_file():
                broken.append(f"{page.name} -> {url}")
    if broken:
        gate.fail(f"{len(broken)} broken internal links, such as {broken[:3]}")
    return len(sample)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", type=Path)
    parser.add_argument("--tsv", required=True, type=Path, help="the query TSVs of the run that built SITE")
    args = parser.parse_args(argv)
    site, gate = args.site, Gate()

    version_path = site / "version.json"
    version = json.loads(version_path.read_text()) if version_path.is_file() else {}
    lacking = [f for f in VERSION_FIELDS if f not in version]
    if lacking:
        gate.fail(f"version.json lacks {lacking}")
    build_id, base = version.get("build_id", ""), version.get("base_path", "")
    data = site / "data" / build_id

    pages, isa = check_pages(site, args.tsv, gate)
    check_tree(site, data, pages, isa, gate)
    sampled = check_links(site, base, pages, build_id, gate)

    files = [f for f in site.rglob("*") if f.is_file()]
    size = sum(f.stat().st_size for f in files)
    if size > SITE_LIMIT:
        gate.fail(f"the site is {size / 2**20:.0f} MB, over 900 MB")
    rows = [("Files", f"{len(files):,}"), ("Site size", f"{size / 2**20:.1f} MB"),
            ("Pages linked-checked", f"{sampled:,}")]
    for name in ("tree.json", "search-en.json", "search-intl.json"):
        path = data / name
        if path.is_file():
            rows.append((f"{name} gzipped", f"{len(gzip.compress(path.read_bytes(), 9)) / 1024:.0f} KB"))
    print("| Check | Value |\n|---|---|")
    print("\n".join(f"| {k} | {v} |" for k, v in rows))
    if gate.failures:
        for f in gate.failures:
            print(f"check_site: {f}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
