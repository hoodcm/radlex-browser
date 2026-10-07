"""Contracts: the Term fields and the Ontology indexes, on the 4.4 and 4.3 fixtures."""
from pathlib import Path

import pytest

import extract
import model

FIXTURES = Path(__file__).parent / "fixtures"
RELATIONS = Path(__file__).parent.parent / "site" / "relations.json"
SHAPES = ["v44", "v43"]


def load(shape):
    return extract.load(FIXTURES / shape, relations_path=RELATIONS)


@pytest.fixture(scope="module", params=SHAPES)
def onto(request):
    return model.Ontology(load(request.param))


def test_every_namespace_class_is_one_term(onto):
    ex = onto.extraction
    assert len(onto.terms) == len(ex.classes) == ex.count
    assert {t.iri for t in onto.terms.values()} == set(ex.classes)
    assert all(t.rid == extract.local_name(t.iri) for t in onto.terms.values())
    assert not any(t.iri.startswith("_:") for t in onto.terms.values())


def test_merged_external_class_is_a_reference_not_a_term():
    onto = model.Ontology(load("v44"))
    bfo = "http://purl.obolibrary.org/obo/BFO_0000002"
    assert bfo in onto.external and onto.external[bfo].label == "continuant"
    assert "BFO_0000002" not in onto.terms


def test_one_live_root(onto):
    assert onto.roots == ["RID0"]


def test_term_fields(onto):
    t = onto.terms["RID665"]
    assert t.label == "middle cerebral artery" and not t.retired and t.copyable
    assert len(t.relationships) == 25 and len({p for p, _ in t.relationships}) == 5
    assert onto.path("RID665")[0] == "RID0" and onto.path("RID665")[-1] == "RID665"
    assert set(onto.children["RID665"]) == {"RID36443", "RID36444"}


def ex_with(values):
    """A one-class extraction carrying the given (field, text, lang) values."""
    iri = "http://radlex.org/RID/RID1"
    ex = extract.Extraction(namespaces=["http://radlex.org/RID/"], count=1, classes=[iri])
    ex.values[iri] = [extract.Value(f, text, "p", lang) for f, text, lang in values]
    return ex


@pytest.mark.parametrize("values, label", [
    ([("label", "Leber", "de"), ("obsolete_name", "old liver", ""), ("label", "liver", "en")], "liver"),
    ([("label", "Leber", "de"), ("obsolete_name", "old liver", "")], "old liver"),
    ([("label", "Leber", "de")], "Leber"),
    ([], "RID1"),
])
def test_label_fallback_order(values, label):
    assert model.Ontology(ex_with(values)).terms["RID1"].label == label


def test_synonyms_dedup_case_insensitively_against_both_labels():
    onto = model.Ontology(ex_with([("label", "liver", "en"), ("label", "Leber", "de"),
                                   ("synonym", "LIVER", "en"), ("synonym", "leber", "la"),
                                   ("synonym", "hepar", "la"), ("synonym", "Hepar", "la")]))
    assert [v.text for v in onto.terms["RID1"].synonyms] == ["hepar"]


def test_german_duplicate_synonym_is_dropped():
    t = model.Ontology(load("v43")).terms["RID16386"]
    assert t.german and t.german.casefold() not in {v.text.casefold() for v in t.synonyms}


def test_deprecated_parentless_class_sits_under_retired():
    onto = model.Ontology(load("v44"))
    t = onto.terms["RID12936"]
    assert t.retired and not t.parents
    assert "RID12936" in onto.children[model.RETIRED_ID]
    assert onto.path("RID12936") == [model.RETIRED_ID, "RID12936"]


def retire(ex, rid, *targets):
    iri = next(c for c in ex.classes if c.endswith("/" + rid))
    base = iri[:iri.rfind("/") + 1]
    ex.values[iri].append(extract.Value("deprecated", "true", "owl:deprecated"))
    for t in targets:
        ex.values[iri].append(extract.Value("replaced_by", base + t, "IAO_0100001", is_iri=True))


@pytest.mark.parametrize("shape", SHAPES)
def test_replacement_chain_through_retired_target_resolves_to_live_term(shape):
    ex = load(shape)
    # RID10103 -> RID10191, made retired here and pointed on to RID58.
    retire(ex, "RID10191", "RID58")
    onto = model.Ontology(ex)
    assert onto.terms["RID10103"].replacements == ["RID58"]


def test_real_chain_in_43_resolves():
    assert model.Ontology(load("v43")).terms["RID31917"].replacements == ["RID38138"]


@pytest.mark.parametrize("shape", SHAPES)
def test_replacement_cycle_stops(shape):
    ex = load(shape)
    retire(ex, "RID10191", "RID10103")
    onto = model.Ontology(ex)
    assert onto.terms["RID10103"].replacements == []
    assert onto.terms["RID10191"].replacements == []


def test_referenced_by_never_repeats_own_relationships(onto):
    for rid, groups in onto.referenced_by.items():
        points_to = {ref for _, ref in onto.terms[rid].relationships}
        for refs in groups.values():
            assert not points_to & set(refs)


def test_referenced_by_inverts_relationships():
    ex = ex_with([("label", "a", "en")])
    b = "http://radlex.org/RID/RID2"
    ex.classes.append(b)
    ex.count = 2
    ex.relationships[b] = [("http://radlex.org/RID/Part_Of", "http://radlex.org/RID/RID1")]
    onto = model.Ontology(ex)
    assert dict(onto.referenced_by["RID1"]) == {"Part_Of": ["RID2"]}
    ex.relationships["http://radlex.org/RID/RID1"] = [("http://radlex.org/RID/Has_Part", b)]
    assert not model.Ontology(ex).referenced_by["RID1"]


@pytest.mark.parametrize("shape, rid, word", [("v44", "RID11209", "laprascopic"),
                                              ("v43", "RID28438", "allathalamus")])
def test_misspelling_is_search_only(shape, rid, word):
    t = model.Ontology(load(shape)).terms[rid]
    assert [v.text for v in t.misspellings] == [word]
    assert word not in {v.text for v in t.synonyms + t.acronyms + t.unsanctioned}
