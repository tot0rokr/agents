"""Open a URL in headless Chromium and report what a browser would show.

Runs inside the Playwright container that browse.sh starts. Writes a
screenshot and the page's visible text to --out, and prints a JSON report:
final URL, title, HTTP status, XHR/fetch responses, failed requests,
console errors and uncaught exceptions -- the parts of a JS-rendered page
that curl cannot see. Exits 1 when a wait timed out; the report then shows
the page as it stood.
"""
import argparse
import json
import os
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("url")
parser.add_argument("--out", default="/out")
parser.add_argument("--host-out", default="", help="--out as the host sees it")
parser.add_argument("--name", default="page", help="basename of the outputs")
parser.add_argument("--wait", type=int, default=0,
                    help="extra milliseconds after load, for late SPA data")
parser.add_argument("--wait-for", default="",
                    help="selector to wait for, e.g. 'text=ALL PASS'")
parser.add_argument("--full-page", action="store_true")
parser.add_argument("--width", type=int, default=1440)
parser.add_argument("--height", type=int, default=900)
parser.add_argument("--storage-state", default="",
                    help="cookies/localStorage file the user saved themselves")
parser.add_argument("--text-limit", type=int, default=3000)
parser.add_argument("--timeout", type=int, default=30000, help="milliseconds")
parser.add_argument("--timezone", default="",
                    help="IANA zone the page renders times in, e.g. Asia/Seoul")
args = parser.parse_args()

console, failed, xhr, page_errors, timed_out = [], [], [], [], []

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    context = browser.new_context(
        viewport={"width": args.width, "height": args.height},
        storage_state=args.storage_state or None,
        timezone_id=args.timezone or None,
    )
    page = context.new_page()
    page.on("console", lambda m: console.append(f"{m.type}: {m.text}")
            if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    page.on("requestfailed",
            lambda r: failed.append(f"{r.method} {r.url} ({r.failure})"))
    page.on("response",
            lambda r: xhr.append(f"{r.status} {r.request.method} {r.url}")
            if r.request.resource_type in ("xhr", "fetch") else None)

    # No response at all is a hard failure: there is nothing to show. Past
    # that, a timeout is often the answer itself (the page shows something
    # other than expected), so record it and still report what is on screen.
    response = page.goto(args.url, wait_until="commit", timeout=args.timeout)
    try:
        page.wait_for_load_state("load", timeout=args.timeout)
    except PlaywrightTimeout:
        timed_out.append("load")
    # An SPA that polls never goes idle; settle for "quiet enough".
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeout:
        pass
    if args.wait_for:
        try:
            page.wait_for_selector(args.wait_for, timeout=args.timeout)
        except PlaywrightTimeout:
            timed_out.append(f"wait-for {args.wait_for}")
    if args.wait:
        page.wait_for_timeout(args.wait)

    shot = os.path.join(args.out, f"{args.name}.png")
    page.screenshot(path=shot, full_page=args.full_page)
    text = page.inner_text("body")
    with open(os.path.join(args.out, f"{args.name}.txt"), "w") as f:
        f.write(text)

    def host(path):
        return path.replace(args.out, args.host_out, 1) if args.host_out else path

    print(json.dumps({
        "url": page.url,
        "title": page.title(),
        "status": response.status if response else None,
        "timed_out": timed_out,
        "timezone": page.evaluate(
            "Intl.DateTimeFormat().resolvedOptions().timeZone"),
        "screenshot": host(shot),
        "text_file": host(os.path.join(args.out, f"{args.name}.txt")),
        "text": text[:args.text_limit],
        "xhr": xhr,
        "failed_requests": failed,
        "console": console,
        "page_errors": page_errors,
    }, indent=1, ensure_ascii=False))
    browser.close()

sys.exit(1 if timed_out else 0)
