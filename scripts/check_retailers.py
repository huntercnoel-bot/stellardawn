#!/usr/bin/env python3
"""Check Micro Center and Best Buy in-store stock for the Mac Studio models.

Writes site/retailers.json (and site/retailers-debug.json with raw responses), which the
dashboard shows next to the Apple Store results.

    python3 scripts/check_retailers.py [--out site/retailers.json] [--previous prev.json]

Micro Center sits behind a Cloudflare challenge that blocks plain HTTP clients from cloud
servers, so its pages load in a real Chromium via Playwright (run under xvfb in CI).
Micro Center (the approach other Micro Center trackers use): each store's stock shows on
the product page when it's loaded with ?storeid=<store id>, in the ".inventoryCnt"
element ("5 NEW IN STOCK", "SOLD OUT"). Product IDs are found by searching Micro Center
for the Apple part number (and for "256GB" M5 Ultra listings).

Best Buy: uses the official Products/Stores API when BESTBUY_API_KEY is set (free key from
developer.bestbuy.com). Its old no-key endpoint is gone, so without a key the script only
records what the product page shows in a real browser (retailers-debug.json).
"""
import argparse
import html as htmllib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_inventory as ci  # noqa: E402  (shared HTTP client, config, pacing)

print = ci.print
MC_BASE = "https://www.microcenter.com"
MC_STORES = [  # store id, name (from Micro Center's store picker)
    ("205", "Phoenix, AZ"), ("101", "Tustin, CA"), ("195", "Santa Clara, CA"), ("181", "Denver, CO"),
    ("185", "Miami, FL"), ("065", "Duluth, GA"), ("041", "Marietta, GA"), ("151", "Chicago, IL"),
    ("025", "Westmont, IL"), ("165", "Indianapolis, IN"), ("191", "Overland Park, KS"),
    ("121", "Cambridge, MA"), ("085", "Rockville, MD"), ("125", "Parkville, MD"),
    ("055", "Madison Heights, MI"), ("045", "St. Louis Park, MN"), ("095", "Brentwood, MO"),
    ("175", "Charlotte, NC"), ("075", "North Jersey, NJ"), ("171", "Westbury, NY"),
    ("115", "Brooklyn, NY"), ("145", "Flushing, NY"), ("105", "Yonkers, NY"), ("141", "Columbus, OH"),
    ("051", "Mayfield Heights, OH"), ("071", "Sharonville, OH"), ("061", "St. Davids, PA"),
    ("215", "Austin, TX"), ("131", "Dallas, TX"), ("155", "Houston, TX"), ("081", "Fairfax, VA"),
]
MC_SEARCHES = {  # model key -> searches whose results are filtered by title
    "96gb": ["MHL74LL/A"],
    "256gb": ["mac studio m5 ultra 256GB"],
    "m5max36": ["MHL64LL/A"],
}
MC_TITLE_MATCH = {  # a listing belongs to a model when its title matches
    "96gb": re.compile(r"MHL74LL|M5 Ultra.*96GB", re.I),
    "256gb": re.compile(r"M5 Ultra.*256GB", re.I),
    "m5max36": re.compile(r"MHL64LL|M5 Max.*36GB", re.I),
}
BB_SKUS = {"96gb": ["6566930"], "m5max36": ["6566932"], "256gb": []}
BB_ZIPS = ["10001", "90012", "60611", "77056", "85016", "19103", "75225", "95128", "94108", "98101",
           "80206", "20001", "02116", "30326", "33131", "55425", "48084", "43219", "28211", "37215"]
PAGE_HEADERS = ci.PAGE_HEADERS
MC_MAX_LISTINGS = 2
debug = {}


def pause():
    time.sleep(0.6 + 0.6 * ci.random.random())


def get(url, params=None, headers=None):
    ci._failures = 0  # retailer requests don't share Apple's refusal counter
    return ci.http_get(url, params, headers or PAGE_HEADERS)


class Browser:
    """A real Chromium session (Playwright) for sites behind a Cloudflare challenge."""

    CHALLENGE = ("Just a moment", "Attention Required", "Access denied")

    def __init__(self, headless=False):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=headless, args=["--disable-blink-features=AutomationControlled"],
            executable_path=os.environ.get("CHROMIUM_PATH") or None)
        self._ctx = self._browser.new_context(
            user_agent=ci.HEADERS["User-Agent"], locale="en-US", viewport={"width": 1280, "height": 900})
        self._ctx.route("**/*", lambda route: route.abort()
                        if route.request.resource_type in ("image", "font", "media") else route.continue_())
        # Best Buy shows a "Select your Country" page unless this cookie says the shopper is in the US.
        self._ctx.add_cookies([{"name": "intl_splash", "value": "false", "domain": ".bestbuy.com", "path": "/"}])
        self.page = self._ctx.new_page()

    def get(self, url, params=None, wait_s=25):
        if params:
            url += ("&" if "?" in url else "?") + ci.urllib.parse.urlencode(params)
        self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        deadline = time.monotonic() + wait_s
        while any(c in (self.page.title() or "") for c in self.CHALLENGE):
            if time.monotonic() > deadline:
                raise RuntimeError(f"challenge not passed: {self.page.title()}")
            self.page.wait_for_timeout(1000)
        return self.page.content()

    def close(self):
        try:
            self._browser.close()
        finally:
            self._pw.stop()


def open_browser():
    try:
        return Browser(headless=os.environ.get("HEADLESS") == "1")
    except Exception as exc:  # playwright not installed or no display
        debug["browser_error"] = str(exc)
        print("No browser, falling back to plain HTTP:", exc)
        return None


# ---------------------------------------------------------------- Micro Center

def mc_find_products(fetch):
    """Return {model key: [{id, title, url}]} by searching Micro Center."""
    found = {}
    for key, queries in MC_SEARCHES.items():
        items = {}
        for q in queries:
            try:
                page = fetch(f"{MC_BASE}/search/search_results.aspx", {"Ntt": q, "myStore": "false"})
            except Exception as exc:
                debug.setdefault("mc_search_errors", {})[q] = str(exc)
                continue
            links = re.findall(r'href="(/product/(\d{6,7})/[^"]+)"[^>]*>\s*([^<]{10,300}?)\s*<', page)
            if not links:  # titles may sit in data attributes instead of link text
                links = [(path, pid, htmllib.unescape(t)) for path, pid, t in re.findall(
                    r'href="(/product/(\d{6,7})/[^"]+)"[^>]*?(?:data-name|title)="([^"]{10,300})"', page)]
            debug.setdefault("mc_search", {})[q] = {"length": len(page), "links": links[:10]}
            if not links:
                debug.setdefault("mc_search_snippet", {})[q] = page[:3000]
            for path, pid, title in links:
                title = htmllib.unescape(title).strip()
                if MC_TITLE_MATCH[key].search(title + " " + path):
                    items[pid] = {"id": pid, "title": title, "url": MC_BASE + path.split("?")[0]}
            ci.pause()
        found[key] = list(items.values())[:MC_MAX_LISTINGS]
    return found


def mc_stock(page):
    """Parse a Micro Center product page's store stock: (count, text)."""
    m = re.search(r'class="[^"]*inventoryCnt[^"]*"[^>]*>(.*?)</(?:span|div|p|dd|td)>', page, re.S)
    text = " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split()) if m else ""
    if not text:
        m = re.search(r"(\d+\+?)\s*(?:NEW\s+)?IN STOCK|SOLD OUT", page, re.I)
        text = m.group(0) if m else ""
    num = re.search(r"\d+", text)
    count = int(num.group()) if num and "IN STOCK" in text.upper() else 0
    return count, text


def check_microcenter(stamp, fetch):
    products = mc_find_products(fetch)
    debug["mc_products"] = products
    stores = []
    for sid, name in MC_STORES:
        row = {"id": "MC" + sid, "name": f"Micro Center {name}", "retailer": "Micro Center",
               "state": name.rsplit(", ", 1)[-1], "checked": stamp, "availability": {}}
        for key, items in products.items():
            best = {"status": "unknown", "quote": "", "in_stock": [], "url": ""}
            for item in items:
                url = f"{item['url']}?storeid={sid}"
                try:
                    count, text = mc_stock(fetch(url))
                except Exception as exc:
                    debug.setdefault("mc_errors", []).append(f"{sid} {item['id']}: {exc}")
                    pause()
                    continue
                debug.setdefault("mc_samples", {}).setdefault(key, {}).setdefault(sid, text)
                if count > 0:
                    best["status"] = "available"
                    best["quote"] = text
                    best["in_stock"].append(item["title"])
                    best["url"] = url
                elif best["status"] != "available" and text:
                    best["status"], best["quote"], best["url"] = "unavailable", text, url
                pause()
            if items:
                row["availability"][key] = best
        stores.append(row)
        print(f"Micro Center {name}: " + ", ".join(f"{k}={v['status']}" for k, v in row["availability"].items()))
    return stores, products


# ---------------------------------------------------------------- Best Buy

def bb_official(key, stamp):
    """Official API: store pickup availability per SKU near each ZIP."""
    stores = {}
    for model, skus in BB_SKUS.items():
        for sku in skus:
            for zip_code in BB_ZIPS:
                try:
                    data = json.loads(get(f"https://api.bestbuy.com/v1/products/{sku}/stores.json",
                                          {"postalCode": zip_code, "apiKey": key}))
                except Exception as exc:
                    debug.setdefault("bb_errors", []).append(f"{sku} {zip_code}: {exc}")
                    continue
                for s in data.get("stores", []):
                    row = stores.setdefault(s["storeID"], {
                        "id": f"BB{s['storeID']}", "name": f"Best Buy {s.get('name', '')}",
                        "retailer": "Best Buy", "state": s.get("region", ""), "checked": stamp,
                        "availability": {}})
                    row["availability"][model] = {
                        "status": "available", "quote": "Pickup today", "in_stock": [sku],
                        "url": f"https://www.bestbuy.com/site/{sku}.p?skuId={sku}"}
                time.sleep(0.4)  # the free API allows about 5 requests a second
    return list(stores.values())


def bb_page_probe(browser):
    """Diagnostics: what bestbuy.com's product page says (pickup/sold out) in a real browser."""
    for model, skus in BB_SKUS.items():
        for sku in skus[:1]:
            url = f"https://www.bestbuy.com/site/{sku}.p?skuId={sku}"
            try:
                page = browser.get(url)
                text = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", page, flags=re.S)).split())
                snips = [text[max(0, m.start() - 120): m.end() + 160] for m in
                         re.finditer(r"Pickup|Sold Out|Add to Cart|Unavailable|Coming Soon", text)][:6]
                debug.setdefault("bb_page", {})[sku] = {"title": browser.page.title(), "length": len(page), "snippets": snips}
            except Exception as exc:
                debug.setdefault("bb_page", {})[sku] = {"error": str(exc)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ci.ROOT / "site" / "retailers.json"))
    ap.add_argument("--previous")
    ap.add_argument("--microcenter", action="store_true", default=os.environ.get("MICROCENTER") == "1",
                    help="also check Micro Center (off by default: its Cloudflare challenge blocks "
                         "cloud servers, so from CI it only burns time)")
    args = ap.parse_args()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print("HTTP client:", "curl_cffi (Chrome fingerprint)" if ci.cffi_requests else "urllib")

    snapshot = {"updated": stamp, "retailers": {}}
    browser = open_browser()  # Micro Center (if enabled) and the Best Buy page probe
    fetch = browser.get if browser else get
    try:
        if args.microcenter:
            mc_stores, mc_products = check_microcenter(stamp, fetch)
            snapshot["retailers"]["Micro Center"] = {"stores": mc_stores, "products": mc_products}
        if browser:
            bb_page_probe(browser)
    finally:
        if browser:
            browser.close()

    bb_key = os.environ.get("BESTBUY_API_KEY", "").strip()
    if bb_key:
        snapshot["retailers"]["Best Buy"] = {"stores": bb_official(bb_key, stamp), "source": "api"}
        print(f"Best Buy: {len(snapshot['retailers']['Best Buy']['stores'])} stores with stock")
    else:
        print("Best Buy: no BESTBUY_API_KEY secret, so only the product-page probe ran (see retailers-debug.json)")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, separators=(",", ":")))
    (out.parent / "retailers-debug.json").write_text(json.dumps(debug, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
