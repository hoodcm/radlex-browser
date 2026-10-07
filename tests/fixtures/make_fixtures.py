"""Freeze the v43 and v44 fixtures: the real query output, sliced to a closed set of classes.

Usage: python3 tests/fixtures/make_fixtures.py --shape v43|v44 --tsv DIR

DIR holds the TSVs `site/extract.py` wrote for the full ontology. The slice starts from the
core RIDs below and closes over named parents, relationship fillers, and replacement
targets, so every pointer in the slice resolves inside it. Each TSV keeps only the rows
whose class is in the slice, with the original ROBOT bytes, and count.tsv holds the
slice's size.
"""
import argparse
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "site"))
import extract  # noqa: E402

CORE = [
    "RID665",                        # path, subtree, 25 relationships in five groups
    "RID10103", "RID10191",          # retired term and its replacement
    "RID58",                         # liver, the search target
    "RID15849",                      # the retired bucket of 4.3
    "RID16386",                      # a synonym that repeats only the German label
    "RID5799",                       # a definition with a line break
    "RID31917", "RID38142", "RID38138",  # 4.3 replacement chain through a retired target
    "RID28438",                      # a 4.3 misspelling
]
EXTRA = {
    "v43": [],
    "v44": ["RID12936",              # deprecated, parentless, no replacement
            "RID11209"],             # a 4.4 misspelling marked by its synonym type
}
EXTERNAL = {"v43": [], "v44": ["http://purl.obolibrary.org/obo/BFO_0000002"]}


def rows(path):
    with open(path, encoding="utf-8") as fh:
        header = fh.readline()
        return header, [line for line in fh]


def cells(line):
    return [extract.decode_cell(c) for c in line.rstrip("\n").split("\t")]


def closure(tsv, core_iris):
    parents, targets, replaced = {}, {}, {}
    for line in rows(tsv / "parents.tsv")[1]:
        c, p = cells(line)
        parents.setdefault(c.value, []).append(p.value)
    for line in rows(tsv / "relationships.tsv")[1]:
        c, _, t = cells(line)
        targets.setdefault(c.value, []).append(t.value)
    ns = extract.load_namespaces()
    _, by_prop = extract.load_properties()
    for line in rows(tsv / "annotations.tsv")[1]:
        c, p, v = cells(line)
        if by_prop.get(p.value) == "replaced_by":
            if isinstance(v, extract.IRI):
                replaced.setdefault(c.value, []).append(v.value)
            else:
                base = c.value[:c.value.rfind("/") + 1]
                replaced.setdefault(c.value, []).append(base + v.lex.strip())
    keep, stack = set(), list(core_iris)
    while stack:
        iri = stack.pop()
        if iri in keep or not any(iri.startswith(n) for n in ns):
            continue
        keep.add(iri)
        stack += parents.get(iri, [])
        stack += replaced.get(iri, [])
        if iri in core_iris:
            stack += targets.get(iri, [])
    return keep


def subtree(tsv, roots):
    children = {}
    for line in rows(tsv / "parents.tsv")[1]:
        c, p = cells(line)
        children.setdefault(p.value, []).append(c.value)
    out, stack = set(), list(roots)
    while stack:
        iri = stack.pop()
        if iri not in out:
            out.add(iri)
            stack += children.get(iri, [])
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shape", choices=["v43", "v44"], required=True)
    parser.add_argument("--tsv", required=True, type=Path)
    args = parser.parse_args()
    tsv, out = args.tsv, HERE / args.shape
    classes = {cells(line)[0].value for line in rows(tsv / "classes.tsv")[1]}
    by_rid = {iri.rsplit("/", 1)[-1]: iri for iri in classes}
    core = [by_rid[r] for r in CORE + EXTRA[args.shape] if r in by_rid]
    # The subtrees of RID665 and of the retired bucket come whole.
    core += subtree(tsv, [by_rid["RID665"], by_rid["RID15849"]])
    keep = closure(tsv, set(core))
    external = set(EXTERNAL[args.shape])

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    filters = {
        "classes.tsv": lambda c: c[0].value in keep,
        "annotations.tsv": lambda c: c[0].value in keep,
        "axiom_annotations.tsv": lambda c: c[0].value in keep,
        "parents.tsv": lambda c: c[0].value in keep and c[1].value in keep,
        "relationships.tsv": lambda c: c[0].value in keep and c[2].value in keep,
        "external.tsv": lambda c: c[0].value in external,
    }
    for name, keep_row in filters.items():
        header, lines = rows(tsv / name) if (tsv / name).stat().st_size else ("", [])
        kept = [line for line in lines if keep_row(cells(line))]
        (out / name).write_text(header + "".join(kept) if kept or header else "", encoding="utf-8")
    (out / "count.tsv").write_text(f"?n\n{len(keep)}\n")
    print(f"{args.shape}: {len(keep)} classes -> {out}")


if __name__ == "__main__":
    main()
