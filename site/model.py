"""Build the RadLex term model from an Extraction.

One Term per named class in the RadLex namespaces, keyed by its RID, the IRI local name.
The Ontology carries the indexes the pages and bundles read: children, parents,
referenced_by, path, and the generated retired group.
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field

from extract import Extraction, Value, local_name

RETIRED_ID = "retired"
RETIRED_LABEL = "Retired terms"
RID_PATTERN = re.compile(r"^RID\d+$")
NAME_FIELDS = ("synonym", "acronym", "misspelling", "unsanctioned")


@dataclass
class Term:
    rid: str
    iri: str
    label: str
    label_lang: str
    german: str
    synonyms: list
    acronyms: list
    misspellings: list
    unsanctioned: list
    definitions: list
    comments: list
    xrefs: list
    sources: list
    version_changed: list
    obsolete_names: list
    retired: bool
    replaced_by: list
    replacements: list = field(default_factory=list)
    parents: list = field(default_factory=list)
    external_parents: list = field(default_factory=list)
    relationships: list = field(default_factory=list)
    label_value: Value = None
    german_value: Value = None

    @property
    def copyable(self):
        return bool(RID_PATTERN.match(self.rid))


@dataclass
class External:
    """A named class outside the RadLex namespaces, rendered as an external link."""
    iri: str
    label: str


def rid_sort_key(rid):
    m = re.match(r"^RID(\d+)$", rid)
    return (0, int(m.group(1)), "") if m else (1, 0, rid)


def first(values, lang=None):
    for v in values:
        if lang is None or v.lang == lang:
            return v
    return None


def dedup_names(values, seen):
    """Keep the first of each case-insensitive name not already in `seen`, updating it."""
    kept = []
    for v in values:
        key = v.text.casefold()
        if key and key not in seen:
            seen.add(key)
            kept.append(v)
    return kept


class Ontology:
    def __init__(self, extraction: Extraction):
        self.extraction = extraction
        self.namespaces = extraction.namespaces
        self.relations = extraction.relations
        self.terms = {}
        self.external = {}
        self._rid_of_iri = {}
        for iri in extraction.classes:
            term = self._build_term(iri, extraction.values.get(iri, []))
            self.terms[term.rid] = term
            self._rid_of_iri[iri] = term.rid
        for iri, entry in extraction.external.items():
            labels = entry["labels"]
            label = labels.get("en") or labels.get("") or next(iter(labels.values()), None) or local_name(iri)
            self.external[iri] = External(iri, label)
        self._link_parents()
        self._link_relationships()
        self._resolve_replacements()
        self._index()

    # --- terms ----------------------------------------------------------------

    def in_namespace(self, iri):
        return any(iri.startswith(ns) for ns in self.namespaces)

    def _build_term(self, iri, values):
        by = defaultdict(list)
        for v in values:
            by[v.field].append(v)
        rid = local_name(iri)
        labels = by["label"]
        en, de = first(labels, "en"), first(labels, "de")
        obsolete = by["obsolete_name"]
        label_value = en or first(obsolete) or de
        label = label_value.text if label_value else rid
        seen = {label.casefold()} | ({de.text.casefold()} if de else set())
        names = {name: dedup_names(by[name], seen) for name in NAME_FIELDS}
        deprecated = any(v.text.lower() == "true" for v in by["deprecated"])
        replaced_by = [self._target_rid(v) for v in by["replaced_by"]]
        return Term(
            rid=rid, iri=iri, label=label, label_lang=label_value.lang if label_value else "",
            german=de.text if de else "", synonyms=names["synonym"], acronyms=names["acronym"],
            misspellings=names["misspelling"], unsanctioned=names["unsanctioned"],
            definitions=by["definition"], comments=by["comment"], xrefs=by["xref"],
            sources=by["source"], version_changed=by["version_changed"], obsolete_names=obsolete,
            retired=deprecated or bool(by["replaced_by"]) or bool(obsolete),
            replaced_by=[r for r in replaced_by if r], label_value=label_value, german_value=de)

    def _target_rid(self, value):
        """A replacement pointer as a RID: an IRI's local name, or a bare RID literal."""
        text = value.text.strip()
        if value.is_iri:
            return local_name(text)
        return text if RID_PATTERN.match(text) else None

    def _parent_order(self, rid):
        term = self.terms[rid]
        return (term.retired, rid_sort_key(rid))

    def _link_parents(self):
        for iri, parents in self.extraction.parents.items():
            term = self.terms.get(self._rid_of_iri.get(iri))
            if term is None:
                continue
            for parent in parents:
                prid = self._rid_of_iri.get(parent)
                if prid and prid != term.rid:
                    term.parents.append(prid)
                elif not self.in_namespace(parent):
                    term.external_parents.append(parent)
            # A parent outside the namespaces passes the hierarchy through to its own
            # nearest RadLex ancestors, so the class stays in the tree.
            if not term.parents:
                term.parents = self._through_external(term.external_parents, {term.rid})
            term.parents.sort(key=self._parent_order)

    def _through_external(self, iris, avoid):
        found, seen, stack = [], set(), list(iris)
        while stack:
            iri = stack.pop(0)
            if iri in seen:
                continue
            seen.add(iri)
            entry = self.extraction.external.get(iri)
            for parent in entry["parents"] if entry else []:
                prid = self._rid_of_iri.get(parent)
                if prid and prid not in avoid and prid not in found:
                    found.append(prid)
                elif not prid:
                    stack.append(parent)
        return found

    def _link_relationships(self):
        for iri, rels in self.extraction.relationships.items():
            term = self.terms.get(self._rid_of_iri.get(iri))
            if term is None:
                continue
            for prop, target in rels:
                tid = self._rid_of_iri.get(target)
                ref = tid if tid else target
                if (local_name(prop), ref) not in term.relationships:
                    term.relationships.append((local_name(prop), ref))

    def _resolve_replacements(self):
        for term in self.terms.values():
            if term.retired:
                term.replacements = self.resolve(term.rid)

    def resolve(self, rid):
        """The live terms a retired term's replacement chains end at, stopping on a cycle."""
        live, seen = [], {rid}
        stack = list(self.terms[rid].replaced_by)
        while stack:
            target = stack.pop(0)
            if target in seen or target not in self.terms:
                continue
            seen.add(target)
            t = self.terms[target]
            if not t.retired:
                if target not in live:
                    live.append(target)
            else:
                stack.extend(t.replaced_by)
        return live

    # --- indexes --------------------------------------------------------------

    def _index(self):
        self.parents = {rid: list(t.parents) for rid, t in self.terms.items()}
        self.children = defaultdict(list)
        for rid, parents in self.parents.items():
            for p in parents:
                self.children[p].append(rid)
        self.retired_group = sorted(
            (rid for rid, t in self.terms.items()
             if t.retired and not any(not self.terms[p].retired for p in t.parents)),
            key=rid_sort_key)
        for rid in self.retired_group:
            self.parents[rid] = self.parents[rid] or [RETIRED_ID]
        self.children[RETIRED_ID] = list(self.retired_group)
        for kids in self.children.values():
            kids.sort(key=lambda r: (self.terms[r].label.casefold(), rid_sort_key(r)))
        self.roots = sorted((rid for rid, t in self.terms.items() if not t.parents and not t.retired),
                            key=rid_sort_key)
        self.referenced_by = defaultdict(lambda: defaultdict(list))
        for rid, t in self.terms.items():
            for prop, target in t.relationships:
                if target in self.terms:
                    self.referenced_by[target][prop].append(rid)
        for target, groups in self.referenced_by.items():
            points_to = {ref for _, ref in self.terms[target].relationships}
            for prop in list(groups):
                kept = sorted({r for r in groups[prop] if r not in points_to and r != target},
                              key=rid_sort_key)
                if kept:
                    groups[prop] = kept
                else:
                    del groups[prop]
        self._paths = {}

    def path(self, rid):
        """The ancestors from the top of the tree to `rid`, through each first parent."""
        if rid in self._paths:
            return self._paths[rid]
        chain, seen, cur = [], set(), rid
        while cur is not None and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            parents = self.parents.get(cur, [])
            cur = parents[0] if parents else None
        chain.reverse()
        self._paths[rid] = chain
        return chain

    def label(self, ref):
        if ref == RETIRED_ID:
            return RETIRED_LABEL
        if ref in self.terms:
            return self.terms[ref].label
        if ref in self.external:
            return self.external[ref].label
        return local_name(ref)
