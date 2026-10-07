"""Extract the RadLex classes from an OWL file with one ROBOT query run.

Usage: python3 site/extract.py --input OWL --out DIR [--robot-jar JAR]

ROBOT loads the ontology once and runs every query in site/queries/, writing one TSV
per query. Each query is scoped to named classes in the namespaces of namespaces.json
through its %SCOPE(?var)% placeholder. ROBOT writes TSV cells in N-Triples style, so
decoding unescapes them, splits language tags and datatypes, strips <> from IRIs, and
skips blank nodes. Values are then normalized: no-break and other spaces become plain
spaces, runs of spaces collapse, and every value is trimmed. Names fold line breaks
into spaces, and prose fields (definition, comment) keep single line breaks and at
most one blank line. Every value keeps the IRI of the property it came from.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
QUERIES = SITE / "queries"

ROBOT_VERSION = "1.9.10"
ROBOT_JAR_SHA256 = "16a73c074f3df359a7338a84b4e0788785fe06117f931bb9796e9619ea776105"
ROBOT_URL = f"https://github.com/ontodev/robot/releases/download/v{ROBOT_VERSION}/robot.jar"
DEFAULT_JAR = ROOT / ".robot" / "robot.jar"

PROSE_FIELDS = {"definition", "comment"}


# --- ROBOT --------------------------------------------------------------------

def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_robot(jar=DEFAULT_JAR):
    """Return the pinned ROBOT jar, downloading it when missing, and verify its checksum."""
    jar = Path(jar)
    if not jar.exists():
        jar.parent.mkdir(parents=True, exist_ok=True)
        tmp = jar.with_suffix(".part")
        with urllib.request.urlopen(ROBOT_URL, timeout=300) as resp, open(tmp, "wb") as fh:
            while chunk := resp.read(1 << 20):
                fh.write(chunk)
        tmp.replace(jar)
    actual = sha256_file(jar)
    if actual != ROBOT_JAR_SHA256:
        raise SystemExit(f"ROBOT jar checksum mismatch for {jar}: expected {ROBOT_JAR_SHA256}, got {actual}")
    return jar


def load_namespaces(path=SITE / "namespaces.json"):
    return json.loads(Path(path).read_text())["namespaces"]


def scope_filter(var, namespaces, inside=True):
    test = " || ".join(f'STRSTARTS(STR({var}), "{ns}")' for ns in namespaces)
    return f"FILTER(isIRI({var}) && {'' if inside else '!'}({test}))"


def instantiate(query_text, namespaces):
    text = re.sub(r"%SCOPE\((\?\w+)\)%", lambda m: scope_filter(m.group(1), namespaces), query_text)
    return re.sub(r"%OUTSIDE\((\?\w+)\)%", lambda m: scope_filter(m.group(1), namespaces, inside=False), text)


def run_robot(owl, tsv_dir, jar, namespaces):
    """Run every query in site/queries/ in one ROBOT invocation, writing <name>.tsv each."""
    tsv_dir = Path(tsv_dir)
    tsv_dir.mkdir(parents=True, exist_ok=True)
    java_args = shlex.split(os.environ.get("ROBOT_JAVA_ARGS", "-Xmx4g"))
    with tempfile.TemporaryDirectory() as work:
        cmd = ["java", *java_args, "-jar", str(jar), "query", "--input", str(owl)]
        for rq in sorted(QUERIES.glob("*.rq")):
            concrete = Path(work) / rq.name
            concrete.write_text(instantiate(rq.read_text(), namespaces))
            cmd += ["--query", str(concrete), str(tsv_dir / f"{rq.stem}.tsv")]
        subprocess.run(cmd, check=True)
    return tsv_dir


# --- TSV decoding -------------------------------------------------------------

@dataclass(frozen=True)
class IRI:
    value: str


@dataclass(frozen=True)
class Literal:
    lex: str
    lang: str = ""
    datatype: str = ""


@dataclass(frozen=True)
class Blank:
    label: str


ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", '"': '"', "'": "'", "\\": "\\"}
ESCAPE_RE = re.compile(r'\\(u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|[ntrbf"\'\\])')


def unescape(text):
    def sub(m):
        code = m.group(1)
        if code[0] in "uU":
            return chr(int(code[1:], 16))
        return ESCAPES[code]
    return ESCAPE_RE.sub(sub, text)


def decode_cell(cell):
    """Decode one N-Triples-style TSV cell to an IRI, Literal, or Blank, or None when unbound."""
    if cell == "":
        return None
    if cell.startswith("<") and cell.endswith(">"):
        return IRI(cell[1:-1])
    if cell.startswith("_:"):
        return Blank(cell[2:])
    if cell.startswith('"'):
        end = cell.rfind('"')
        lex = unescape(cell[1:end])
        rest = cell[end + 1:]
        if rest.startswith("@"):
            return Literal(lex, lang=rest[1:])
        if rest.startswith("^^<") and rest.endswith(">"):
            return Literal(lex, datatype=rest[3:-1])
        return Literal(lex)
    return Literal(cell)  # bare numbers and booleans


def read_tsv(path):
    """Yield (raw cells, decoded cells) per row of a ROBOT TSV, skipping the header.

    ROBOT writes a query with no results as an empty file, header included.
    """
    with open(path, encoding="utf-8") as fh:
        if not fh.readline():
            return
        for line in fh:
            raw = line.rstrip("\n").split("\t")
            yield raw, [decode_cell(c) for c in raw]


SPACES = re.compile(r"[ \t\u00a0\u2000-\u200a\u202f\u205f\u3000]+")


def normalize(text, prose=False):
    """Plain spaces, collapsed runs, trimmed. Names fold line breaks; prose keeps them."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not prose:
        return SPACES.sub(" ", text.replace("\n", " ")).strip()
    lines = [SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# --- Extraction ---------------------------------------------------------------

@dataclass(frozen=True)
class Value:
    field: str
    text: str
    prop: str
    lang: str = ""
    datatype: str = ""
    is_iri: bool = False


@dataclass
class Extraction:
    namespaces: list
    count: int
    classes: list
    values: dict = field(default_factory=lambda: defaultdict(list))
    unmapped: Counter = field(default_factory=Counter)
    parents: dict = field(default_factory=lambda: defaultdict(list))
    relationships: dict = field(default_factory=lambda: defaultdict(list))
    external: dict = field(default_factory=dict)
    relations: dict = field(default_factory=dict)


def load_properties(path=SITE / "properties.json"):
    doc = json.loads(Path(path).read_text())
    by_prop = {}
    for name, props in doc["fields"].items():
        for prop in props:
            by_prop[prop] = name
    return doc, by_prop


def local_name(iri):
    return re.split(r"[/#]", iri)[-1]


def reader_name(local):
    """Has_Regional_Part -> Has regional part. Words in capitals, such as MR, keep them."""
    words = [w for w in local.split("_") if w]
    out = [words[0][:1].upper() + words[0][1:]]
    out += [w if len(w) > 1 and w.isupper() else w.lower() for w in words[1:]]
    return " ".join(out)


def load(tsv_dir, namespaces=None, properties_path=SITE / "properties.json",
         relations_path=SITE / "relations.json"):
    """Decode a directory of ROBOT TSVs into an Extraction."""
    tsv_dir = Path(tsv_dir)
    namespaces = namespaces or load_namespaces()
    doc, by_prop = load_properties(properties_path)
    type_prop = doc["synonym_type_property"]
    type_field = {iri: name for name, iris in doc["synonym_types"].items() for iri in iris}

    count = next(int(cells[0].lex) for _, cells in read_tsv(tsv_dir / "count.tsv"))
    classes = [cells[0].value for _, cells in read_tsv(tsv_dir / "classes.tsv")
               if isinstance(cells[0], IRI)]
    ex = Extraction(namespaces=namespaces, count=count, classes=classes)

    # A synonym axiom typed by a synonym_types IRI moves its value to that field.
    retyped = {}
    for raw, (c, p, t, q, v) in read_tsv(tsv_dir / "axiom_annotations.tsv"):
        if isinstance(q, IRI) and q.value == type_prop and isinstance(v, IRI) and v.value in type_field:
            retyped[(raw[0], raw[1], raw[2])] = type_field[v.value]

    for raw, (c, p, v) in read_tsv(tsv_dir / "annotations.tsv"):
        if not isinstance(c, IRI) or isinstance(v, Blank) or v is None:
            continue
        name = retyped.get((raw[0], raw[1], raw[2])) or by_prop.get(p.value)
        if name is None:
            ex.unmapped[p.value] += 1
            continue
        if isinstance(v, IRI):
            value = Value(name, v.value, p.value, is_iri=True)
        else:
            value = Value(name, normalize(v.lex, prose=name in PROSE_FIELDS), p.value, v.lang, v.datatype)
        ex.values[c.value].append(value)

    for _, (c, parent) in read_tsv(tsv_dir / "parents.tsv"):
        if isinstance(parent, IRI) and parent.value not in ex.parents[c.value]:
            ex.parents[c.value].append(parent.value)

    for _, (c, prop, target) in read_tsv(tsv_dir / "relationships.tsv"):
        pair = (prop.value, target.value)
        if pair not in ex.relationships[c.value]:
            ex.relationships[c.value].append(pair)

    for _, (e, label, parent) in read_tsv(tsv_dir / "external.tsv"):
        entry = ex.external.setdefault(e.value, {"labels": {}, "parents": []})
        if isinstance(label, Literal):
            entry["labels"].setdefault(label.lang, normalize(label.lex))
        if isinstance(parent, IRI) and parent.value not in entry["parents"]:
            entry["parents"].append(parent.value)

    known = json.loads(Path(relations_path).read_text()) if Path(relations_path).exists() else {}
    present = sorted({local_name(p) for rels in ex.relationships.values() for p, _ in rels})
    ex.relations = {name: known.get(name) or reader_name(name) for name in present}
    return ex


def write_relations(ex, path=SITE / "relations.json"):
    """Merge the reader names for the relationships present into relations.json, keeping edits."""
    path = Path(path)
    known = json.loads(path.read_text()) if path.exists() else {}
    merged = {**ex.relations, **known}
    path.write_text(json.dumps(dict(sorted(merged.items())), indent=2) + "\n")


def extract(owl, out_dir, jar=None):
    namespaces = load_namespaces()
    tsv_dir = run_robot(owl, Path(out_dir) / "tsv", ensure_robot(jar or DEFAULT_JAR), namespaces)
    return load(tsv_dir, namespaces)


DECODE_LEFTOVERS = ("\\n", "\\t", '"@', "^^")


def summary(ex):
    fed = Counter(v.field for vals in ex.values.values() for v in vals)
    leftovers = sum(1 for vals in ex.values.values() for v in vals
                    if any(s in v.text for s in DECODE_LEFTOVERS))
    return {"count": ex.count, "classes": len(ex.classes), "fields": dict(sorted(fed.items())),
            "unmapped": dict(ex.unmapped.most_common()), "relations": len(ex.relations),
            "external_classes": len(ex.external), "decode_leftovers": leftovers}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, help="the OWL file to extract")
    parser.add_argument("--out", required=True, help="directory for the query TSVs")
    parser.add_argument("--robot-jar", help=f"ROBOT jar (default {DEFAULT_JAR}, fetched when missing)")
    args = parser.parse_args(argv)
    ex = extract(args.input, args.out, args.robot_jar)
    write_relations(ex)
    report = summary(ex)
    print(json.dumps(report, indent=2))
    if report["classes"] != report["count"]:
        sys.exit(f"extract: {report['classes']} classes extracted against a scoped count of {report['count']}")


if __name__ == "__main__":
    main()
