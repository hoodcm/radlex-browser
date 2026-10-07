# TODO

<!-- todo:worklist:start -->

## Start here
_as of 2026-10-07 · 1 streams startable · 0 now/next items untyped_

- radlex-browser — next: Implement the RadLex browser complete-site plan (build)

## Next

- **Implement the RadLex browser complete-site plan**
  Add the per-term data files, copy functions, downloads and info pages, service worker, CI speed check, and legacy URL inventory, then draft the move into `RSNA/RadLex`.
  ↳ links: ~/GitHub/anatomy-ontology/radlex/docs/plans/2026-10-06-radlex-browser-complete-plan.md

<!-- todo:worklist:end -->

<!-- todo:continuation:start -->

## Continuation

The proof-of-concept plan is implemented. Its outcome line and deviations section record what was built, and the live site at `https://hoodcm.github.io/radlex-browser/` renders the `4.3` tag. Start the complete-site plan, `~/GitHub/anatomy-ontology/radlex/docs/plans/2026-10-06-radlex-browser-complete-plan.md`, with `/implement-plan` on that path.

- **First, per the series map's session protocol:** apply every carry-forward entry addressed to the complete-site plan in `~/GitHub/anatomy-ontology/radlex/docs/plans/2026-10-06-radlex-browser-design.md`, and refine the plan with the `plan-refiner` agent, because the run-order table marks it unrefined.
- **Contracts that changed in the proof of concept:** the "Bundles" contract (search shards under `data/<build-id>/search/`), the "Tag fallback" contract (`site/build_newest.py`), and the "Build record" contract (`fallback_from`). The series map holds each.

The gates are `python3 -m pytest tests -q` (145 passing) and `python3 tests/browser_smoke.py --site <build>` (10 of 10 on 4.4 and 4.3). `python3 tests/speed.py` measures the live site, and its throttled numbers move with the Mac's load, so run it on a quiet machine.

<!-- todo:continuation:end -->
