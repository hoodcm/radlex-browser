"""Build a demo of the browser over the Anatomic Locations staging data.

Reads `data/anatomic_locations.json` at a git ref of the staging clone (default `origin/main`,
what was pushed), writes it as the query TSVs build.py takes, with each entry's placing edge as
its parent in the containment tree: its container (`containedInId`, else `embeddedInId`), else
its first whole (`partOfId`) that has a place of its own. An entry that stores neither, such as
a whole that crosses regions, a set, or a class head, is located through its pieces or members,
so it sits in one top-level list and never under a computed place, and each piece in the tree is
tagged with its whole. It builds the site and relabels the RadLex brand strings for the demo.
Each source ships as its own identifier string, so the demo prints it as given.

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
NARROW = "<http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym>"
BROAD = "<http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym>"
SCOPES = {"exact": EXACT, "related": RELATED, "narrow": NARROW, "broad": BROAD}
XREF = "<http://www.geneontology.org/formats/oboInOwl#hasDbXref>"
COMMENT = "<http://www.w3.org/2000/01/rdf-schema#comment>"
SOURCE = "<http://purl.org/dc/terms/source>"


def lit(text, lang=""):
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", " ").replace("\n", " ")
    return f'"{text}"' + (f"@{lang}" if lang else "")


def iri(rid):
    return f"<{NS}{rid}>"


# The top-level list of entries located through their pieces or members. Its id names a node of
# the demo's tree, never a library entry.
THROUGH = "located-through-pieces-or-members"
THROUGH_LABEL = "Located through their pieces or members"


def tree_parents(entries):
    """Each entry's parent in the containment tree, and each piece's listed wholes. An entry that
    stores no container and no whole is located through its pieces or members, by
    a-wholes-location-is-its-pieces-containers-and-its-smallest-encloser-serves-roll-up-only and
    the collection and class-head rules, so it goes in the THROUGH list when a piece, member, side,
    or subclass names it. A body region that stores neither, whole body, is the tree's root, and an
    entry that nothing names is unplaced, so it stays a top-level root that shows the gap. A piece
    goes under its container, else its first whole outside the list, so it sits where it lies, and
    it is tagged with each listed whole it is part of."""
    named = {
        w for e in entries
        for w in [*(e.get("partOfId") or []), *(e.get("memberOfId") or []), e.get("isA"), e.get("unsidedId")]
        if w
    }
    listed = {
        e["radlexId"] for e in entries
        if not (e.get("containedInId") or e.get("embeddedInId") or e.get("partOfId"))
        and e.get("nodeType") != "body_region" and e["radlexId"] in named
    }
    tree, piece_of = {}, {}
    for e in entries:
        rid = e["radlexId"]
        if rid in listed:
            tree[rid] = THROUGH
            continue
        host = e.get("containedInId") or e.get("embeddedInId")
        wholes = e.get("partOfId") or []
        own = [w for w in wholes if w not in listed]
        if host or wholes:
            tree[rid] = host or (own or wholes)[0]
        if tagged := [w for w in wholes if w in listed and w != tree.get(rid)]:
            piece_of[rid] = tagged
    return tree, piece_of


def write_tsvs(entries, out):
    out.mkdir(parents=True, exist_ok=True)
    ids = {e["radlexId"] for e in entries}
    radlex = json.loads(RADLEX_ENTITIES.read_text())
    radlex = radlex.get("entities", radlex)
    if isinstance(radlex, dict):
        radlex = list(radlex.values())
    rl_label = {r["rid"]: r["preferred_label"] for r in radlex if isinstance(r, dict) and "rid" in r}

    tree, piece_of = tree_parents(entries)
    label = {e["radlexId"]: e["description"] for e in entries}
    ann, parents, rels, external = [(iri(THROUGH), RDFS_LABEL, lit(THROUGH_LABEL, "en"))], [], [], {}
    for e in entries:
        c = iri(e["radlexId"])
        ann.append((c, RDFS_LABEL, lit(e["description"], "en")))
        for s in e.get("synonyms", []):
            text = s["text"] if isinstance(s, dict) else s
            lang = (s.get("lang") or s.get("language") or "en") if isinstance(s, dict) else "en"
            scope = (s.get("scope") or "exact").lower() if isinstance(s, dict) else "exact"
            ann.append((c, SCOPES.get(scope, RELATED), lit(text, lang)))
        for code in e.get("codes", []):
            pred = code.get("predicate", "").replace("skos:", "").replace("Match", " match")
            ann.append((c, XREF, lit(f"{code['system']}:{code['code']} ({pred})")))
        facts = [f"Node type: {e['nodeType'].replace('_', ' ')}"] if e.get("nodeType") else []
        if e.get("sexSpecific"):
            facts.append(f"Sex: {e['sexSpecific']}")
        if e.get("peritonealRelation"):
            facts.append(f"Peritoneal relation: {e['peritonealRelation']}")
        if e.get("locationClassificationIds"):
            facts.append("Location classifications: " + ", ".join(e["locationClassificationIds"]))
        if facts:
            ann.append((c, COMMENT, lit(". ".join(facts) + ".")))
        for source in e.get("sources", []):
            ann.append((c, SOURCE, lit(source)))
        wholes = e.get("partOfId") or []
        if e["radlexId"] in tree:
            parents.append((c, iri(tree[e["radlexId"]])))
        if tree.get(e["radlexId"]) == THROUGH:
            ann.append((c, COMMENT, lit("Located through its pieces or members, so the containment tree lists it apart.")))
        for whole in piece_of.get(e["radlexId"], []):
            ann.append((c, COMMENT, lit(f"Piece of {label[whole]}, which is located through its pieces.")))
        if e.get("containedInId"):
            rels.append((c, f"<{NS}Contained_In>", iri(e["containedInId"])))
        if e.get("embeddedInId"):
            rels.append((c, f"<{NS}Embedded_In>", iri(e["embeddedInId"])))
        for whole in wholes:
            rels.append((c, f"<{NS}Part_Of>", iri(whole)))
        for group in e.get("memberOfId") or []:
            rels.append((c, f"<{NS}Member_Of>", iri(group)))
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

    dump("count.tsv", "?n", [(str(len(entries) + 1),)])
    dump("classes.tsv", "?c", [(iri(THROUGH),)] + [(iri(e["radlexId"]),) for e in entries])
    dump("annotations.tsv", "?c\t?p\t?v", ann)
    dump("axiom_annotations.tsv", "?c\t?p\t?t\t?q\t?v", [])
    dump("parents.tsv", "?c\t?parent", parents)
    dump("relationships.tsv", "?c\t?prop\t?target", rels)
    dump("external.tsv", "?e\t?label\t?parent", [(f"<{k}>", lit(v, "en"), "") for k, v in external.items()])
    return {rid: f"{label[rid]} (piece of {', '.join(label[w] for w in ws)})" for rid, ws in piece_of.items()}


def tag_pieces(site, tags):
    """Tag each piece's label in the built tree bundle with its listed wholes, so the tree shows
    where a whole located through its pieces lies."""
    for path in (site / "data").glob("*/tree.json"):
        tree = json.loads(path.read_text())
        tree["labels"] = [tags.get(rid, lab) for rid, lab in zip(tree["ids"], tree["labels"])]
        path.write_text(json.dumps(tree, ensure_ascii=False, separators=(",", ":")))


BRAND = [
    ("<b>RadLex</b><span>RSNA</span>", "<b>Anatomic Locations</b><span>staging</span>"),
    ("<dt>Is a</dt>", "<dt>Placed in</dt>"),
    ("<dt>Children (", "<dt>Places ("),
    ('aria-label="RadLex hierarchy"', 'aria-label="Placement hierarchy"'),
    ('href="https://github.com/RSNA/RadLex">GitHub',
     'href="https://github.com/openimagingdata/anatomic-locations-staging">GitHub'),
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
    commit = subprocess.run(["git", "-C", a.staging, "rev-parse", "--short", a.ref],
                            check=True, capture_output=True, text=True).stdout.strip()
    entries = doc["bodyParts"]
    tsv = Path(a.out + "-input")
    tags = write_tsvs(entries, tsv)
    summary = build.build(tsv, a.out, "", {"tag": commit, "source": "anatomic-locations-staging"})
    tag_pieces(Path(a.out), tags)
    rebrand(Path(a.out), f"Staging snapshot {doc.get('$version', '')}, commit {commit}. "
                         f"{len(entries):,} entries. The tree follows each entry's placing edge: "
                         f"its container, else its first whole. A whole that crosses regions, a "
                         f"set, or a class head is listed apart, located through its pieces or "
                         f"members, and each piece is tagged with its whole.")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
