"""Contracts: the TSV decoding rules and the namespaces, properties, and relations schemas."""
import json
import re

import pytest

import extract as ex

SITE = ex.SITE
DECODED = ex.decode_cell


@pytest.mark.parametrize("cell, expected", [
    (r'"line one\nline two"', ex.Literal("line one\nline two")),
    (r'"a\tb"', ex.Literal("a\tb")),
    (r'"say \"capsule\""', ex.Literal('say "capsule"')),
    (r'"back\\slash"', ex.Literal("back\\slash")),
    ('"liver"@en', ex.Literal("liver", lang="en")),
    ('"Leber"@de', ex.Literal("Leber", lang="de")),
    ('"2014-08-19T00:00:00"^^<http://www.w3.org/2001/XMLSchema#dateTime>',
     ex.Literal("2014-08-19T00:00:00", datatype="http://www.w3.org/2001/XMLSchema#dateTime")),
    ("<http://www.radlex.org/RID/RID58>", ex.IRI("http://www.radlex.org/RID/RID58")),
    ("_:b0", ex.Blank("b0")),
    ("46900", ex.Literal("46900")),
    ("", None),
])
def test_decode_cell(cell, expected):
    assert DECODED(cell) == expected


def test_no_break_space_and_runs_are_normalized():
    assert ex.normalize(" middle  cerebral   artery ") == "middle cerebral artery"


def test_names_fold_line_breaks_and_prose_keeps_them():
    assert ex.normalize("left\nrib") == "left rib"
    assert ex.normalize("first  line \n\n\n\n second", prose=True) == "first line\n\nsecond"


def test_blank_node_values_are_skipped(tmp_path):
    rows = {
        "count.tsv": "?n\n1\n",
        "classes.tsv": "?c\n<http://radlex.org/RID/RID1>\n",
        "annotations.tsv": "?c\t?p\t?v\n"
                           "<http://radlex.org/RID/RID1>\t<http://www.w3.org/2000/01/rdf-schema#label>\t_:b1\n"
                           "<http://radlex.org/RID/RID1>\t<http://www.w3.org/2000/01/rdf-schema#label>\t\"one\"@en\n",
        "axiom_annotations.tsv": "?c\t?p\t?t\t?q\t?v\n",
        "parents.tsv": "?c\t?parent\n",
        "relationships.tsv": "?c\t?prop\t?target\n",
        "external.tsv": "?e\t?label\t?parent\n",
    }
    for name, text in rows.items():
        (tmp_path / name).write_text(text)
    out = ex.load(tmp_path, relations_path=tmp_path / "relations.json")
    labels = [v.text for v in out.values["http://radlex.org/RID/RID1"]]
    assert labels == ["one"]


def test_namespaces_schema():
    doc = json.loads((SITE / "namespaces.json").read_text())
    assert set(doc) == {"namespaces"}
    assert doc["namespaces"] and all(re.match(r"^https?://.+/$", ns) for ns in doc["namespaces"])


FIELDS = {"label", "definition", "synonym", "acronym", "misspelling", "unsanctioned", "comment",
          "xref", "source", "replaced_by", "obsolete_name", "version_changed", "deprecated"}


def test_properties_schema():
    doc = json.loads((SITE / "properties.json").read_text())
    assert set(doc) == {"fields", "synonym_type_property", "synonym_types"}
    assert set(doc["fields"]) == FIELDS
    all_iris = [iri for iris in doc["fields"].values() for iri in iris]
    assert all(re.match(r"^https?://\S+$", iri) for iri in all_iris)
    assert len(all_iris) == len(set(all_iris)), "an IRI feeds two fields"
    assert set(doc["synonym_types"]) <= FIELDS


def test_radlex_properties_expand_across_every_namespace():
    namespaces = json.loads((SITE / "namespaces.json").read_text())["namespaces"]
    doc = json.loads((SITE / "properties.json").read_text())
    groups = [*doc["fields"].values(), *doc["synonym_types"].values()]
    for iris in groups:
        locals_by_ns = {ns: {i[len(ns):] for i in iris if i.startswith(ns)} for ns in namespaces}
        names = set().union(*locals_by_ns.values())
        for ns in namespaces:
            assert locals_by_ns[ns] == names, f"{names - locals_by_ns[ns]} missing under {ns}"


def test_relations_schema():
    doc = json.loads((SITE / "relations.json").read_text())
    assert doc and all(re.match(r"^\w[\w-]*$", k) and isinstance(v, str) and v for k, v in doc.items())


def test_reader_name():
    assert ex.reader_name("Has_Regional_Part") == "Has regional part"
    assert ex.reader_name("Distal_to") == "Distal to"
    assert ex.reader_name("Has_MR_Sequence") == "Has MR sequence"


def test_scope_placeholder_covers_every_namespace():
    text = ex.instantiate("SELECT ?c WHERE { ?c ?p ?o . %SCOPE(?c)% }", ["http://a/", "http://b/"])
    assert 'STRSTARTS(STR(?c), "http://a/")' in text and 'STRSTARTS(STR(?c), "http://b/")' in text
    assert "%SCOPE" not in text
