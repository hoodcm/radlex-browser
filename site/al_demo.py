"""Build a demo of the browser over the Anatomic Locations staging data.

Reads `data/anatomic_locations.json` at a git ref of the staging clone (default `origin/main`,
what was pushed), writes it as the query TSVs build.py takes, with `containedById` as the tree
parent, builds the site, and relabels the RadLex brand strings for the demo.

Usage: python3 site/al_demo.py [--staging DIR] [--ref REF] [--out DIR]
"""
import argparse
import json
import subprocess
from pathlib import Path

import build

SITE = Path(__file__).resolve().parent
NS = "http://radlex.org/RID/"
RADLEX_PAGE = "https://hoodcm.github.io/radlex-browser/RID/{}.html"
RADLEX_ENTITIES = Path.home() / "GitHub/anatomy-ontology/data/radlex/radlex_entities.json"
RDFS_LABEL = "<http://www.w3.org/2000/01/rdf-schema#label>"
EXACT = "<http://www.geneontology.org/formats/oboInOwl#hasExactSynonym>"
RELATED = "<http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym>"
XREF = "<http://www.geneontology.org/formats/oboInOwl#hasDbXref>"
COMMENT = "<http://www.w3.org/2000/01/rdf-schema#comment>"
SOURCE = "<http://purl.org/dc/terms/source>"


def lit(text, lang=""):
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", " ").replace("\n", " ")
    return f'"{text}"' + (f"@{lang}" if lang else "")


def iri(rid):
    return f"<{NS}{rid}>"


def write_tsvs(entries, sources, out):
    out.mkdir(parents=True, exist_ok=True)
    ids = {e["radlexId"] for e in entries}
    radlex = json.loads(RADLEX_ENTITIES.read_text())
    radlex = radlex.get("entities", radlex)
    if isinstance(radlex, dict):
        radlex = list(radlex.values())
    rl_label = {r["rid"]: r["preferred_label"] for r in radlex if isinstance(r, dict) and "rid" in r}

    ann, parents, rels, external = [], [], [], {}
    for e in entries:
        c = iri(e["radlexId"])
        ann.append((c, RDFS_LABEL, lit(e["description"], "en")))
        for s in e.get("synonyms", []):
            text = s["text"] if isinstance(s, dict) else s
            lang = (s.get("lang") or s.get("language") or "en") if isinstance(s, dict) else "en"
            scope = (s.get("scope") or "exact").lower() if isinstance(s, dict) else "exact"
            ann.append((c, EXACT if "exact" in scope else RELATED, lit(text, lang)))
        for code in e.get("codes", []):
            pred = code.get("predicate", "").replace("skos:", "").replace("Match", "")
            ann.append((c, XREF, lit(f"{code['system']}:{code['code']} ({pred})")))
        facts = [f"Node type: {e['nodeType'].replace('_', ' ')}"]
        if e.get("sexSpecific"):
            facts.append(f"Sex: {e['sexSpecific']}")
        if e.get("peritonealRelation"):
            facts.append(f"Peritoneal relation: {e['peritonealRelation']}")
        if e.get("locationClassificationIds"):
            facts.append("Location classifications: " + ", ".join(e["locationClassificationIds"]))
        ann.append((c, COMMENT, lit(". ".join(facts) + ".")))
        for key in e.get("sources", []):
            cite = sources.get(key, {}).get("citation")
            ann.append((c, SOURCE, lit(f"{cite} ({key})" if cite else key)))
        if e.get("containedById"):
            parents.append((c, iri(e["containedById"])))
        if e.get("partOfId"):
            rels.append((c, f"<{NS}Part_Of>", iri(e["partOfId"])))
        isa = e.get("isA")
        if isa:
            if isa in ids:
                rels.append((c, f"<{NS}Is_A>", iri(isa)))
            else:
                ext = RADLEX_PAGE.format(isa)
                external[ext] = rl_label.get(isa, isa)
                rels.append((c, f"<{NS}Is_A>", f"<{ext}>"))
        for field, prop in (("leftId", "Left_Variant"), ("rightId", "Right_Variant"),
                            ("unsidedId", "Unsided_Variant")):
            if e.get(field):
                rels.append((c, f"<{NS}{prop}>", iri(e[field])))

    def dump(name, header, rows):
        (out / name).write_text(header + "\n" + "".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")

    dump("count.tsv", "?n", [(str(len(entries)),)])
    dump("classes.tsv", "?c", [(iri(e["radlexId"]),) for e in entries])
    dump("annotations.tsv", "?c\t?p\t?v", ann)
    dump("axiom_annotations.tsv", "?c\t?p\t?t\t?q\t?v", [])
    dump("parents.tsv", "?c\t?parent", parents)
    dump("relationships.tsv", "?c\t?prop\t?target", rels)
    dump("external.tsv", "?e\t?label\t?parent", [(f"<{k}>", lit(v, "en"), "") for k, v in external.items()])


BRAND = [
    ("<b>RadLex</b><span>RSNA</span>", "<b>Anatomic Locations</b><span>staging</span>"),
    ("<dt>Is a</dt>", "<dt>Contained by</dt>"),
    ("<dt>Children (", "<dt>Contains ("),
    ('aria-label="RadLex hierarchy"', 'aria-label="Containment hierarchy"'),
    ("https://github.com/RSNA/RadLex", "https://github.com/openimagingdata/anatomic-locations-staging"),
    (" | RadLex</title>", " | Anatomic Locations</title>"),
    ("<title>RadLex</title>", "<title>Anatomic Locations</title>"),
    ("<h1>RadLex</h1>", "<h1>Anatomic Locations</h1>"),
    ("terms by name, synonym, or RID", "locations by name, synonym, or ID"),
]


def rebrand(site, ref_line):
    for page in site.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        for old, new in BRAND:
            text = text.replace(old, new)
        if page.name == "index.html" and page.parent == site:
            start = text.find('<p class="release">')
            end = text.find("</p>", start)
            if start >= 0:
                text = text[:start] + f'<p class="release">{ref_line}' + text[end:]
        page.write_text(text, encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--staging", default=str(Path.home() / "GitHub/anatomic-locations-staging"))
    p.add_argument("--ref", default="origin/main")
    p.add_argument("--out", default=str(SITE / "_build/al"))
    a = p.parse_args()

    def show(path):
        return subprocess.run(["git", "-C", a.staging, "show", f"{a.ref}:{path}"],
                              check=True, capture_output=True, text=True).stdout

    doc = json.loads(show("data/anatomic_locations.json"))
    src = json.loads(show("data/sources.json"))
    sources = {s["id"]: s for s in src}
    commit = subprocess.run(["git", "-C", a.staging, "rev-parse", "--short", a.ref],
                            check=True, capture_output=True, text=True).stdout.strip()
    entries = doc["bodyParts"]
    tsv = Path(a.out + "-input")
    write_tsvs(entries, sources, tsv)
    summary = build.build(tsv, a.out, "", {"tag": commit, "source": "anatomic-locations-staging"})
    rebrand(Path(a.out), f"Staging snapshot {doc.get('$version', '')}, commit {commit}. "
                         f"{len(entries):,} entries. The tree follows containment (contained by).")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
