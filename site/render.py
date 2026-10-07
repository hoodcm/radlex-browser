"""Render the term pages, the home page, and 404.html from the Ontology.

Every page shares one shell: a top bar, an empty sidebar the tree script draws, and a
<main> that in-site navigation swaps. The term page is the reader layout, and the
ontology view re-lays the same markup in CSS: the Annotations and Description wrappers
become panels, `.owl-name` replaces `.reader-name`, and each value's data-property shows.
"""
from collections import defaultdict
from html import escape as e

from extract import local_name
from model import RETIRED_ID, rid_sort_key

FONT_PRELOAD = "fonts/dm-sans-latin-wght-normal.woff2"
STYLESHEETS = ("tokens.css", "site.css")
TWO_COLUMN_FROM = 5


class Context:
    """What every page needs besides its own content."""

    def __init__(self, onto, base, build_id, record, boot_js):
        self.onto = onto
        self.base = base
        self.build_id = build_id
        self.record = record
        self.boot_js = boot_js
        self.count = len(onto.terms)

    def static(self, name):
        return f"{self.base}/static/{self.build_id}/{name}"

    def term_href(self, rid):
        return f"{self.base}/RID/{rid}.html"

    @property
    def home(self):
        return f"{self.base}/"


# --- shell --------------------------------------------------------------------

def page(ctx, title, main, *, description=""):
    links = "".join(f'<link rel="stylesheet" href="{ctx.static(s)}">' for s in STYLESHEETS)
    version = ctx.record.get("tag", "")
    desc = f'<meta name="description" content="{e(description)}">' if description else ""
    return (
        '<!doctype html>\n<html lang="en" data-view="reader"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{e(title)}</title>{desc}"
        f'<meta name="radlex-build" content="{ctx.build_id}">'
        f'<meta name="radlex-base" content="{e(ctx.base)}">'
        f'<link rel="icon" href="{ctx.static("icon.svg")}" type="image/svg+xml">'
        f'<link rel="preload" href="{ctx.static(FONT_PRELOAD)}" as="font" type="font/woff2" crossorigin>'
        f"{links}<script>{ctx.boot_js}</script></head>"
        '<body><div class="app" data-dtools-role="page">'
        '<header class="topbar">'
        f'<a class="wordmark" href="{ctx.home}"><b>RadLex</b><span>RSNA</span></a>'
        '<button type="button" class="search" data-search aria-haspopup="dialog">'
        f'<span class="long">Search {ctx.count:,} terms by name, synonym, or RID</span>'
        '<span class="short">Search</span><kbd>⌘K</kbd></button>'
        '<nav class="topnav" aria-label="Site">'
        '<button type="button" class="view-switch" data-view-switch aria-pressed="false">Ontology view</button>'
        + (f'<span class="chip" data-dtools-role="chip">v{e(version)}</span>' if version else "") +
        '<a class="keep" href="https://github.com/RSNA/RadLex">GitHub</a></nav>'
        "</header>"
        '<div class="body"><nav class="sidebar" data-dtools-role="sidebar" aria-label="RadLex hierarchy"></nav>'
        f'<main class="main" id="main" tabindex="-1">{main}</main></div></div></body></html>\n'
    )


# --- values -------------------------------------------------------------------

def term_link(ctx, ref):
    onto = ctx.onto
    if ref in onto.terms:
        t = onto.terms[ref]
        cls = ' class="retired"' if t.retired else ""
        return f'<a href="{ctx.term_href(ref)}"{cls}>{e(t.label)}</a>'
    if ref == RETIRED_ID:
        return f'<span class="group">{e(onto.label(ref))}</span>'
    return f'<a class="ext" href="{e(ref)}" rel="external">{e(onto.label(ref))}</a>'


def sorted_refs(ctx, refs):
    return sorted(refs, key=lambda r: (ctx.onto.label(r).casefold(), rid_sort_key(r)))


def vals(ctx, refs):
    cls = "vals" if len(refs) >= TWO_COLUMN_FROM else "vals one"
    return f'<ul class="{cls}">' + "".join(f"<li>{term_link(ctx, r)}</li>" for r in refs) + "</ul>"


def annotation(value, text=None):
    """One annotation value, tagged with its source property's local name."""
    lang = f' <span class="lang">{e(value.lang)}</span>' if value.lang not in ("", "en") else ""
    body = e(text if text is not None else value.text)
    return f'<span class="v" data-property="{e(local_name(value.prop))}">{body}</span>{lang}'


def prose(value):
    paras = [p for p in value.text.split("\n\n") if p.strip()]
    inner = "".join("<p>" + "<br>".join(e(line) for line in p.split("\n")) + "</p>" for p in paras)
    return f'<div class="prose" data-property="{e(local_name(value.prop))}">{inner}</div>'


def pairs(rows):
    """A definition list from (dt html, dd html, class for both[, class for the dd]) rows, or ""."""
    out = []
    for dt, dd, c, *dd_extra in rows:
        dd_cls = " ".join(filter(None, [c, *dd_extra]))
        out.append(f'<dt{f" class=\"{c}\"" if c else ""}>{dt}</dt><dd{f" class=\"{dd_cls}\"" if dd_cls else ""}>{dd}</dd>')
    return f'<dl class="pairs">{"".join(out)}</dl>' if out else ""


def section(key, heading, body):
    if not body:
        return ""
    return f'<section class="s-{key}" data-dtools-role="section"><h2>{e(heading)}</h2>{body}</section>'


def rel_name(ctx, prop, some=True):
    reader = ctx.onto.relations.get(prop) or prop
    return (f'<span class="reader-name">{e(reader)}</span>'
            f'<span class="owl-name">{e(prop)}{" some" if some else ""}</span>')


# --- term page ----------------------------------------------------------------

def crumbs(ctx, rid):
    path = ctx.onto.path(rid)[:-1]
    if not path:
        return ""
    links = [term_link(ctx, r) for r in path]
    sep = '<span class="sep" aria-hidden="true">›</span>'
    if len(links) <= 4:
        inner = sep.join(links)
    else:
        hidden = links[2:-2]
        inner = (sep.join(links[:2]) + sep
                 + f'<button type="button" class="more" aria-label="Show {len(hidden)} hidden levels">…</button>'
                 + f'<span class="hidden-levels" hidden>{sep.join(hidden)}</span>'
                 + sep + sep.join(links[-2:]))
    return f'<nav class="crumbs" aria-label="Breadcrumb" data-dtools-group="crumbs">{inner}</nav>'


def head(ctx, t):
    chip = '<span class="chip" data-dtools-role="chip">Retired</span>' if t.retired else ""
    actions = ""
    if t.copyable:
        actions = ('<div class="actions" data-dtools-group="actions">'
                   '<button type="button" data-copy="rid">Copy RID</button>'
                   '<button type="button" data-copy="as">Copy as…</button></div>')
    return (f'<div class="head" data-dtools-group="head">{crumbs(ctx, t.rid)}'
            f'<h1{" class=\"retired\"" if t.retired else ""}>{e(t.label)}</h1>'
            f'<div class="idline" data-dtools-group="id"><span class="chip" data-dtools-role="chip">{e(t.rid)}</span>'
            f'{chip}<span class="mono iri">{e(t.iri)}</span></div>{actions}</div>')


def banner(ctx, t):
    if not t.retired:
        return ""
    if t.replacements:
        reps = " or ".join(f'{term_link(ctx, r)} <span class="code">{e(r)}</span>' for r in t.replacements)
        text = f"Use {reps} instead."
    else:
        text = "No replacement recorded."
    return (f'<div class="banner" role="note" data-dtools-role="panel"><b>Retired term.</b> '
            f"<span>{text}</span></div>")


def names_section(t):
    names = ([annotation(t.german_value)] if t.german_value else []) + [annotation(v) for v in t.synonyms]
    rows = []
    if names:
        rows.append(("Synonyms", ", ".join(names), ""))
    if t.acronyms:
        rows.append(("Acronyms", ", ".join(annotation(v) for v in t.acronyms), ""))
    former = [v for v in t.obsolete_names if v.text.casefold() != t.label.casefold()]
    if former:
        rows.append(("Former name", ", ".join(annotation(v) for v in former), ""))
    if t.unsanctioned:
        rows.append(("Unsanctioned terms", ", ".join(annotation(v) for v in t.unsanctioned), "owl-only"))
    return section("names", "Names", pairs(rows))


def hierarchy_section(ctx, t):
    onto = ctx.onto
    parents = onto.parents.get(t.rid, [])
    rows = []
    if parents or t.external_parents:
        rows.append(("Is a", vals(ctx, list(parents) + [p for p in t.external_parents if p not in parents]), ""))
    kids = onto.children.get(t.rid, [])
    if kids:
        rows.append((f"Children ({len(kids):,})", vals(ctx, kids), ""))
    return section("hierarchy", "Hierarchy", pairs(rows))


def relationships_section(ctx, t):
    groups = defaultdict(list)
    for prop, ref in t.relationships:
        groups[prop].append(ref)
    if not groups:
        return ""
    order = sorted(groups, key=lambda p: (ctx.onto.relations.get(p) or p).casefold())
    rows = [(rel_name(ctx, p), vals(ctx, sorted_refs(ctx, groups[p])), "") for p in order]
    return section("relationships", f"Relationships ({len(t.relationships):,})", pairs(rows))


def referenced_section(ctx, t):
    groups = ctx.onto.referenced_by.get(t.rid)
    if not groups:
        return ""
    order = sorted(groups, key=lambda p: (ctx.onto.relations.get(p) or p).casefold())
    rows = [(rel_name(ctx, p, some=False), vals(ctx, sorted_refs(ctx, groups[p])), "") for p in order]
    total = sum(len(v) for v in groups.values())
    return section("referenced", f"Referenced by ({total:,})", pairs(rows))


def xrefs_section(t):
    rows = []
    if t.xrefs:
        rows.append(("Cross-references", ", ".join(annotation(v) for v in t.xrefs), "", "code"))
    if t.sources:
        rows.append(("Source", ", ".join(annotation(v) for v in t.sources), ""))
    if t.version_changed:
        rows.append(("Change history", ", ".join(annotation(v) for v in t.version_changed), "owl-only"))
    return section("xrefs", "Cross-references and source", pairs(rows))


def term_main(ctx, t):
    definition = section("definition", "Definition", "".join(prose(v) for v in t.definitions))
    comments = section("comments", "Comments", "".join(prose(v) for v in t.comments))
    ann = definition + comments + names_section(t) + xrefs_section(t)
    desc = hierarchy_section(ctx, t) + relationships_section(ctx, t) + referenced_section(ctx, t)
    panels = ""
    if ann:
        panels += f'<div class="ann" data-dtools-role="panel"><h2 class="panel-title">Annotations</h2>{ann}</div>'
    if desc:
        panels += f'<div class="desc" data-dtools-role="panel"><h2 class="panel-title">Description</h2>{desc}</div>'
    return f'<article class="detail" data-rid="{e(t.rid)}">{head(ctx, t)}{banner(ctx, t)}{panels}</article>'


def term_page(ctx, rid):
    t = ctx.onto.terms[rid]
    first_def = t.definitions[0].text.split("\n")[0] if t.definitions else ""
    return page(ctx, f"{t.label} | RadLex", term_main(ctx, t), description=first_def)


# --- home and 404 -------------------------------------------------------------

def search_box(ctx):
    return (f'<button type="button" class="search hero-search" data-search aria-haspopup="dialog">'
            f'<span>Search {ctx.count:,} terms by name, synonym, or RID</span><kbd>⌘K</kbd></button>')


def home_page(ctx):
    onto = ctx.onto
    rows = []
    for root in onto.roots:
        rows.append(f"<h2>{term_link(ctx, root)}</h2>")
        kids = onto.children.get(root, [])
        items = "".join(f'<li>{term_link(ctx, k)} <span class="ct">{len(onto.children.get(k, [])):,}</span></li>'
                        for k in kids)
        rows.append(f'<ul class="branches">{items}</ul>')
    if onto.retired_group:
        rows.append(f'<p class="retired-note">{len(onto.retired_group):,} retired terms sit under '
                    f'<span class="group">{e(onto.label(RETIRED_ID))}</span> in the tree.</p>')
    rec = ctx.record
    meta = (f'<p class="release">RadLex {e(rec.get("tag", ""))}, tagged {e(rec.get("tag_date", ""))}. '
            f"{ctx.count:,} terms.</p>")
    main = (f'<article class="detail home" data-dtools-group="home"><div class="head"><h1>RadLex</h1>{meta}</div>'
            f'{search_box(ctx)}<section data-dtools-role="section">{"".join(rows)}</section></article>')
    return page(ctx, "RadLex", main, description="Browse the RadLex radiology lexicon.")


def not_found_page(ctx):
    main = (f'<article class="detail notfound" data-dtools-group="notfound"><h1>Page not found</h1>'
            f'<p>No RadLex page lives at this address. Search for the term, or start from the '
            f'<a href="{ctx.home}">RadLex home page</a>.</p>{search_box(ctx)}</article>')
    return page(ctx, "Page not found | RadLex", main)
