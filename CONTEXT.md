# CONTEXT.md

## What this is

The code for a fast static replacement of the radlex.org term browser. This repository owns the generator and the browser runtime only. The ontology comes from the newest version tag of `RSNA/RadLex`, the plans and shared contracts live in `~/GitHub/anatomy-ontology/radlex/docs/plans/`, and the `radlex` design token instance lives in the design-tools skill under `~/.claude`.

## Current state

Built by two plans in order, a proof of concept and then the complete site. Which plan is implemented, and its checkpoint range, is in the run-order table of the series map named in `## Read next`. The deployed build's tag and generator commit are in `https://hoodcm.github.io/radlex-browser/version.json`.

## Decisions & dead ends

- Its own small repository, not a fork of `RSNA/RadLex`, because a fork needs hand syncing of tags. The code moves into `RSNA/RadLex` by pull request once it looks good.
- A single-page app was rejected, because term URLs would return a 404 status and non-JavaScript clients would see nothing.
- ROBOT's OBO Graphs conversion was rejected as the extractor, because it lost the English label on several top-level terms.

## Read next

| Doc | What you get | Read when |
|-----|--------------|-----------|
| `~/GitHub/anatomy-ontology/radlex/docs/plans/2026-10-06-radlex-browser-design.md` | The series map: locked decisions, shared contracts, run-order table, carry-forward log | Before any change to a contract, and at the start of a plan session |
| `~/GitHub/anatomy-ontology/radlex/docs/plans/2026-10-06-radlex-browser-complete-plan.md` | The complete-site plan | Before starting the complete-site work |

---

*Last updated: 2026-10-07*
