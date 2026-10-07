# RadLex browser

## Overview

A static term browser for RadLex, rebuilt from the newest version tag of the official `RSNA/RadLex` repository and published on GitHub Pages at `hoodcm.github.io/radlex-browser/`. The generator in `site/` resolves the input, extracts it with ROBOT SPARQL queries, builds a model, and writes one prebuilt page per term plus the tree and search bundles. The browser runtime in `site/static/` is plain ES modules with no build step.

The plan set, the shared contracts, and Michael's locked decisions live in `~/GitHub/anatomy-ontology/radlex/docs/plans/2026-10-06-radlex-browser-design.md`. Read its "Shared contracts" section before changing a file name, a JSON field, a page path, or a flag, because the complete-site plan relies on them.

## Gotchas

- Never commit, push, or branch in `~/GitHub/RadLex` or any `RSNA` repository from this project. A change to `RSNA/RadLex` is drafted under `~/GitHub/anatomy-ontology/radlex/upstream-drafts/`, and Michael files it.
- Creating or changing a repository or Pages setting and pushing are outward actions, so confirm with Michael first unless he authorized them for the task.
- `site/static/tokens.css` is compiled output. Edit the `radlex` token instance at `~/.claude/skills/design-tools/references/house-styles/radlex.tokens.json` and recompile with the command at the top of `site/static/site.css`. The file is committed because the public repository can't install the private design-tools package.
- No third-party runtime dependency: the generator uses the Python standard library, ROBOT (pinned jar, checksum verified), and Java 21. Tests use pytest, and the browser checks use Playwright driving Chrome for Testing.
- Gates compare counts against the scoped class count from the same ROBOT run, never against a number written in code.

## Commands

| Command | Description |
|---------|-------------|
| `python3 site/resolve_input.py --out site/_build/input` | Resolve the newest `RSNA/RadLex` tag and fetch its OWL, printing the JSON record |
| `python3 site/build.py --input <owl> --out site/_build/site --base-path /radlex-browser` | Build the site from an OWL file |
| `python3 site/check_site.py site/_build/site` | Run the fail-closed site gates on a build |
| `python3 -m pytest tests -q` | Run the test suite |
| `python3 -m http.server -d site/_build/site 8000` | Serve a build locally, with an empty base path |

Run `python3 -m pytest tests -q` before a commit.

## Architecture decisions

- Static files only, one prebuilt page per term in the reader layout, with the ontology view done in CSS over the same markup, so term URLs return 200 and read without JavaScript.
- Labels and annotations are read with ROBOT SPARQL queries, because ROBOT's OBO Graphs conversion keeps one arbitrary label per class and loses English labels.
- Every `localStorage` key and cache name starts with `radlex:<base path>:`, because all `*.github.io` project sites share one browser origin.

## Project files

| File | Purpose | Update frequency |
|------|---------|------------------|
| `CLAUDE.md` | Project instructions | As needed |
| `CONTEXT.md` | Orientation head: what this is, current state, decisions, where to read next. Small by contract (`~/.claude/references/context-head.md`). Detail lives in the docs it routes to | When a fact changes. Update in place, with no dates, because `CHANGELOG.md` records the timeline |
| `CHANGELOG.md` | Timeline of changes and decision-making | After adding or changing features, fixing bugs, or altering architecture, not after routine edits |
| `TODO.md` | Rendered worklist, compiled from `.claude/todo/open/`. Never hand-edit it | Through the todo store |

## Before starting work

Read `CONTEXT.md`, which is head-form and small. Grep `TODO.md` for `## Start here` and `## Continuation` and read those sections only, because `/next` owns full triage.

## After completing a task

Run `/end-session` at the wrap, which updates `CHANGELOG.md`, `CONTEXT.md`, and the todo store that `TODO.md` renders from.
