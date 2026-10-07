"""Speed check against a deployed site, under a throttled network and CPU.

Usage: python3 tests/speed.py [--url https://hoodcm.github.io/radlex-browser] [--runs 3]

Chrome for Testing through Playwright, with CDP throttling of 150 ms round trip, 1.6 Mbps
down, 750 kbps up, and the CPU slowed four times. Measures the first contentful paint of
RID665 on a cold cache, the term-to-term swap after hover prefetch (desktop) and after
on-screen prefetch (touch), the cold swap with no prefetch, the time per search keystroke
from input to painted results over 20 queries once the full index has loaded, the first
search on a cold page (typing "liver" at 150 ms a key, from the first keystroke to the first
painted results), and the longest task while imaging sign expands. Prints one line per measure and a JSON report,
and exits non-zero when a held target is missed.
"""
import argparse
import glob
import json
import os
import statistics
import sys

from playwright.sync_api import sync_playwright

CHROME_GLOB = "~/.chrome-for-testing/chrome/*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
NETWORK = {"offline": False, "latency": 150, "downloadThroughput": 1.6e6 / 8, "uploadThroughput": 750e3 / 8}
CPU_SLOWDOWN = 4
QUERIES = ["liver", "lung", "carotid", "kidney", "aorta", "femur", "brain", "heart", "spleen", "rid58",
           "pancreas", "ive", "fracture", "stenosis", "thyroid", "mri", "contrast", "lesion", "pleural effusion", "vertebra"]
FIRST_QUERY = "liver"
TARGETS = {"fcp_ms": 1000, "warm_swap_ms": 100, "search_p95_ms": 16, "first_search_ms": 1000, "long_task_ms": 50}
# The page set: RID665 and the terms it links to, imaging sign for the expansion.
START = "/RID/RID665.html"


def chrome():
    found = sorted(glob.glob(os.path.expanduser(CHROME_GLOB)))
    if not found:
        sys.exit("Chrome for Testing is missing: npx @puppeteer/browsers install chrome@stable --path ~/.chrome-for-testing")
    return found[-1]


def throttle(page, cache=True):
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", NETWORK)
    cdp.send("Network.setCacheDisabled", {"cacheDisabled": not cache})
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": CPU_SLOWDOWN})
    return cdp


INSTRUMENT = """() => {
  window.__swap = [];
  document.addEventListener('click', () => { window.__t0 = performance.now(); }, true);
  document.addEventListener('radlex:navigated', () => requestAnimationFrame(() =>
    window.__swap.push(performance.now() - window.__t0)));
}"""


def wait_ready(page):
    page.wait_for_function("!!(window.RADLEX && RADLEX.navigate)", timeout=60000)


def fcp(browser, url, runs):
    times = []
    for _ in range(runs):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        throttle(page, cache=False)
        page.goto(url + START, wait_until="load", timeout=120000)
        times.append(page.evaluate("performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? null"))
        ctx.close()
    return statistics.median(times), times


def swaps(browser, url, mode, runs):
    """Swap times for `runs` relationship links: hover, touch, or cold (no prefetch)."""
    touch = mode == "touch"
    ctx = browser.new_context(viewport={"width": 390, "height": 844} if touch else {"width": 1440, "height": 900},
                              is_mobile=touch, has_touch=touch)
    page = ctx.new_page()
    throttle(page)
    page.goto(url + START, wait_until="load", timeout=120000)
    wait_ready(page)
    page.evaluate(INSTRUMENT)
    out = []
    for i in range(runs):
        page.wait_for_timeout(3000 if touch else 500)   # on-screen prefetch, or settle
        link = page.locator("main .s-relationships a, main .s-hierarchy a").nth(i % 3)
        if mode == "hover":
            link.hover()
            page.wait_for_timeout(2500)                  # 100 ms delay plus the fetch at 1.6 Mbps
            link.click()
        elif mode == "touch":
            link.scroll_into_view_if_needed()
            page.wait_for_timeout(2500)
            link.tap()
        else:
            page.evaluate("(el) => el.click()", link.element_handle())
        page.wait_for_function("n => window.__swap.length > n", arg=len(out), timeout=60000)
        out.append(page.evaluate("window.__swap[window.__swap.length - 1]"))
        page.go_back()
        page.wait_for_function("n => window.__swap.length > n", arg=len(out), timeout=60000)
        page.evaluate("window.__swap.pop()")
    ctx.close()
    return statistics.median(out), out


def type_query(page, query):
    box = page.locator(".search-dialog input[type=search]")
    box.fill("")
    for ch in query:
        page.keyboard.type(ch)
        page.wait_for_timeout(150)
    page.wait_for_function("q => document.querySelector('.search-dialog .results').dataset.query === q",
                           arg=query, timeout=60000)


def keystroke_latencies(log):
    pending, out = {}, []
    for entry in log:
        if "input" in entry:
            pending[entry["input"]] = entry["t"]
        elif "painted" in entry and entry["painted"] in pending:
            out.append(entry["t"] - pending.pop(entry["painted"]))
    return out


def search(browser, url):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    throttle(page)
    page.goto(url + START, wait_until="load", timeout=120000)
    wait_ready(page)
    page.wait_for_function("!!window.RADLEX.openSearch", timeout=60000)
    page.keyboard.press("Meta+k")
    page.keyboard.type(FIRST_QUERY, delay=150)
    page.wait_for_function("() => RADLEX.searchLog.some((e) => e.n > 0)", timeout=120000)
    log = page.evaluate("RADLEX.searchLog")
    start = next(e["t"] for e in log if "input" in e)
    shown = next(e for e in log if e.get("n"))
    first = shown["t"] - start
    print(f"      first results painted for {shown['painted']!r}, partial={shown['partial']}")
    page.wait_for_function("RADLEX.searchComplete === true", timeout=120000)
    page.evaluate("RADLEX.searchLog.length = 0")
    for q in QUERIES:
        type_query(page, q)
    times = sorted(keystroke_latencies(page.evaluate("RADLEX.searchLog")))
    ctx.close()
    p95 = times[min(len(times) - 1, int(round(0.95 * (len(times) - 1))))]
    return first, statistics.median(times), p95, len(times)


def expansion(browser, url):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    throttle(page)
    page.goto(url + START, wait_until="load", timeout=120000)
    tree = page.evaluate("fetch(RADLEX.data + 'tree.json').then(r => r.json())")
    rid = tree["ids"][tree["labels"].index("imaging sign")]
    page.goto(f"{url}/RID/{rid}.html", wait_until="load", timeout=120000)
    page.wait_for_selector(".sidebar .row[aria-current]", timeout=120000)
    page.wait_for_timeout(1000)
    page.evaluate("""() => { window.__long = [];
      new PerformanceObserver((l) => window.__long.push(...l.getEntries().map((e) => e.duration))).observe({ type: 'longtask' }); }""")
    page.click(".sidebar .row[aria-current] .tw")
    page.wait_for_function("document.querySelector('.sidebar .row[aria-current]')?.getAttribute('aria-expanded') === 'true'")
    page.wait_for_timeout(1000)
    long = page.evaluate("window.__long")
    ctx.close()
    return max(long, default=0.0), rid


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="https://hoodcm.github.io/radlex-browser")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    url = args.url.rstrip("/")
    report, missed = {}, []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=chrome())
        report["fcp_ms"], report["fcp_runs"] = fcp(browser, url, args.runs)
        report["warm_swap_ms"], report["hover_swaps"] = swaps(browser, url, "hover", args.runs)
        report["touch_swap_ms"], report["touch_swaps"] = swaps(browser, url, "touch", args.runs)
        report["cold_swap_ms"], report["cold_swaps"] = swaps(browser, url, "cold", args.runs)
        (report["first_search_ms"], report["search_median_ms"], report["search_p95_ms"],
         report["keystrokes"]) = search(browser, url)
        report["long_task_ms"], report["imaging_sign"] = expansion(browser, url)
        browser.close()
    checks = [
        ("first contentful paint, RID665, cold", "fcp_ms", report["fcp_ms"], True),
        ("term-to-term swap, desktop, hover prefetch", "warm_swap_ms", report["warm_swap_ms"], True),
        ("term-to-term swap, touch, on-screen prefetch", "warm_swap_ms", report["touch_swap_ms"], True),
        ("cold swap, no prefetch (reported only)", None, report["cold_swap_ms"], False),
        ("search keystroke, median (reported only)", None, report["search_median_ms"], False),
        ("search keystroke, 95th percentile", "search_p95_ms", report["search_p95_ms"], True),
        ("first search on a cold page (card above 1 s)", "first_search_ms", report["first_search_ms"], False),
        (f"imaging sign expansion, longest task ({report['imaging_sign']})", "long_task_ms", report["long_task_ms"], True),
    ]
    for name, key, value, held in checks:
        target = TARGETS.get(key)
        verdict = "    " if target is None else ("PASS" if value < target else ("FAIL" if held else "OVER"))
        if held and target is not None and value >= target:
            missed.append(name)
        print(f"{verdict}  {name}: {value:.0f} ms" + (f" (target {target} ms)" if target else ""))
    print(json.dumps(report))
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
