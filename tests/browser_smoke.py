"""Browser smoke test: the tree, search, in-site navigation, the views, and the no-JavaScript pages.

Usage: python3 tests/browser_smoke.py --input OWL_OR_TSV_DIR | --site DIR

Builds the input with base path /radlex-browser into a temporary folder, or takes a site
already built with that base path, serves it with `python3 -m http.server`, and drives
Chrome for Testing through Playwright. Prints one line per check and exits non-zero when
any check fails.
"""
import argparse
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = "/radlex-browser"
CHROME_GLOB = "~/.chrome-for-testing/chrome/*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"


def chrome():
    if os.environ.get("CI"):
        return None
    found = sorted(glob.glob(os.path.expanduser(CHROME_GLOB)))
    if not found:
        sys.exit("Chrome for Testing is missing: npx @puppeteer/browsers install chrome@stable --path ~/.chrome-for-testing")
    return found[-1]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(folder):
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                            cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    origin = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(origin + BASE + "/version.json", timeout=1)
            return proc, origin
        except OSError:
            time.sleep(0.1)
    proc.kill()
    sys.exit("http.server did not start")


class Checks:
    def __init__(self):
        self.failed = 0

    def run(self, name, fn):
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:  # each check reports, and the run goes on
            self.failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}")


def rid_of(page):
    return page.evaluate("document.querySelector('main .detail')?.dataset.rid ?? null")


def wait_rid(page, rid):
    page.wait_for_function("rid => document.querySelector('main .detail')?.dataset.rid === rid", arg=rid, timeout=15000)


def search_ids(page, query, typed=False):
    box = page.locator(".search-dialog input[type=search]")
    box.fill("")
    if typed:
        box.press_sequentially(query, delay=60)
    else:
        box.fill(query)
    page.wait_for_function("q => document.querySelector('.search-dialog .results')?.dataset.query === q",
                           arg=query, timeout=30000)
    return page.eval_on_selector_all(".search-dialog .results li", "els => els.map(e => e.dataset.id)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", help="an OWL file or a folder of query TSVs to build")
    group.add_argument("--site", help=f"a site already built with base path {BASE}")
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="radlex-smoke-")
    if args.input:
        sys.path.insert(0, str(ROOT / "site"))
        import build  # noqa: E402
        build.build(args.input, Path(tmp) / BASE.strip("/"), BASE)
        root = tmp
    else:
        site = Path(args.site).resolve()
        if json.loads((site / "version.json").read_text())["base_path"] != BASE:
            sys.exit(f"{site} was not built with base path {BASE}")
        os.symlink(site, Path(tmp) / BASE.strip("/"))
        root = tmp
    site = Path(root) / BASE.strip("/")
    tree = json.loads(next((site / "data").glob("*/tree.json")).read_text())
    imaging_sign = tree["ids"][tree["labels"].index("imaging sign")]

    server, origin = serve(root)
    url = lambda path: f"{origin}{BASE}{path}"  # noqa: E731
    checks, errors = Checks(), []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=chrome())
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("response", lambda r: r.status >= 400 and errors.append(f"{r.status} {r.url}"))
            page.goto(url("/RID/RID665.html"))

            def tree_opens():
                page.wait_for_selector(".sidebar .row[aria-current]", timeout=15000)
                state = page.evaluate("RADLEX.tree.state()")
                assert state["current"] == "RID665", state["current"]
                path = page.evaluate("RADLEX.state().path")
                missing = [rid for rid in path[:-1] if rid not in state["expanded"]]
                assert not missing, f"path not expanded: {missing}"
                assert page.locator(".sidebar .pins .row").count() > 0, "no pinned rows"
                assert page.inner_text(".sidebar .row[aria-current] .lb") == "middle cerebral artery"
            checks.run("tree opens to RID665 with its path expanded and pinned rows", tree_opens)

            def filter_carotid():
                page.fill(".sidebar .filter input", "carotid")
                page.wait_for_function("RADLEX.tree.state().filtering", timeout=5000)
                page.wait_for_selector(".sidebar .row.match", timeout=5000)
                matches = page.eval_on_selector_all(".sidebar .rows .row.match .lb", "els => els.map(e => e.textContent)")
                assert matches and all("carotid" in m.lower() for m in matches), matches[:5]
                first = page.inner_text(".sidebar .rows .row >> nth=0")
                assert "carotid" not in first.lower(), f"first row {first!r} is not an ancestor"
                page.fill(".sidebar .filter input", "")
                page.wait_for_function("!RADLEX.tree.state().filtering", timeout=5000)
            checks.run('filtering "carotid" shows matches with their ancestors', filter_carotid)

            def search_liver():
                page.keyboard.press("Meta+k")
                page.wait_for_selector(".search-dialog[open]")
                assert search_ids(page, "liver")[0] == "RID58"
                search_ids(page, "RID58")
                page.keyboard.press("Enter")
                wait_rid(page, "RID58")
                assert page.url.endswith("/RID/RID58.html")
            checks.run('⌘K "liver" lists RID58 first, and "RID58" goes straight to it', search_liver)

            def search_typed():
                page.keyboard.press("Meta+k")
                typed = search_ids(page, "ive", typed=True)
                pasted = search_ids(page, "ive")
                assert "RID58" in typed, typed[:10]
                assert typed == pasted, (typed[:5], pasted[:5])
                page.keyboard.press("Escape")
            checks.run('"ive" typed key by key lists RID58, the same as pasted', search_typed)

            def swap_and_back():
                page.goto(url("/RID/RID665.html"))
                wait_rid(page, "RID665")
                page.evaluate("window.__marker = 'kept'")
                page.click(".s-relationships a >> nth=0")
                page.wait_for_function("document.querySelector('main .detail').dataset.rid !== 'RID665'")
                assert page.evaluate("window.__marker") == "kept", "the page reloaded"
                page.go_back()
                wait_rid(page, "RID665")
                assert page.evaluate("window.__marker") == "kept", "Back reloaded the page"
            checks.run("a relationship link swaps the page, and Back restores it", swap_and_back)

            def ontology_persists():
                page.click("[data-view-switch]")
                assert page.evaluate("document.documentElement.dataset.view") == "ontology"
                page.reload()
                wait_rid(page, "RID665")
                assert page.evaluate("document.documentElement.dataset.view") == "ontology"
                assert page.is_visible(".s-relationships .owl-name")
                page.click("[data-view-switch]")
            checks.run("the ontology view persists across a reload", ontology_persists)

            def imaging_sign_expands():
                page.goto(url(f"/RID/{imaging_sign}.html"))
                page.wait_for_selector(".sidebar .row[aria-current]", timeout=15000)
                page.wait_for_timeout(500)
                page.evaluate("""() => { window.__long = [];
                    new PerformanceObserver((l) => window.__long.push(...l.getEntries().map((e) => e.duration)))
                      .observe({ type: 'longtask' }); }""")
                page.click(".sidebar .row[aria-current] .tw")
                page.wait_for_function("document.querySelector('.sidebar .row[aria-current]')?.getAttribute('aria-expanded') === 'true'")
                page.wait_for_timeout(500)
                long = page.evaluate("window.__long")
                assert not [d for d in long if d > 50], f"long tasks {long}"
            checks.run(f"expanding imaging sign ({imaging_sign}) has no long task over 50 ms", imaging_sign_expands)

            def console_clean():
                assert not errors, errors[:3]
            checks.run("the console logs no errors", console_clean)

            def no_js():
                plain = browser.new_context(java_script_enabled=False).new_page()
                plain.goto(url("/RID/RID665.html"))
                crumbs = plain.eval_on_selector_all(".crumbs a:visible", "els => els.map(e => e.textContent)")
                assert len(crumbs) >= 2, crumbs
                hier = plain.eval_on_selector_all(".s-hierarchy a", "els => els.map(e => e.getAttribute('href'))")
                for rid in ("RID35904", "RID36443", "RID36444"):
                    assert f"{BASE}/RID/{rid}.html" in hier, (rid, hier)
            checks.run("with JavaScript off, RID665 shows its breadcrumb, parents, and children as links", no_js)
            browser.close()
    finally:
        server.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(1 if checks.failed else 0)


if __name__ == "__main__":
    main()
