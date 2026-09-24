#!/usr/bin/env python3
"""Check Apple Store pickup availability for Mac Studio models near major US cities.

Reads scripts/config.json and writes a JSON snapshot (default: site/inventory.json)
that the dashboard in site/index.html renders. Standard library only.

    python3 scripts/check_inventory.py [--out site/inventory.json] [--limit N]

Each model has one or more variants (e.g. 256GB with different chips/storage). A
variant either names its Apple `part` number, or points at its Apple Store `page`
and the part number is read from that page at run time.
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "scripts" / "config.json"
ENDPOINT = "https://www.apple.com/shop/fulfillment-messages"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.apple.com/shop/buy-mac/mac-studio",
}
DELAY_SECONDS = 1.5
RETRIES = 3
# Apple part numbers: standard models look like MHL74LL/A, build-to-order like Z1U500038.
PART_RE = re.compile(r'"(?:partNumber|part|sku)"\s*:\s*"((?:M[A-Z0-9]{4}LL/A)|(?:Z[A-Z0-9]{3,9}))"')
RANK = {"available": 4, "unavailable": 3, "ineligible": 2, "unknown": 1}
STORE_URL_KEYS = ("hoursUrl", "storeUrl", "reservationUrl", "makeReservationUrl")


def http_get(url):
    last_error = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"request failed after {RETRIES} attempts: {last_error}")


def find_part(html):
    """Return the first Apple part number embedded in a product page, or None."""
    match = PART_RE.search(html)
    return match.group(1) if match else None


def resolve_parts(models):
    """Fill in each variant's part number, reading it from its Apple page when needed."""
    for model in models:
        for variant in model["variants"]:
            if variant.get("part") or not variant.get("page"):
                continue
            try:
                variant["part"] = find_part(http_get(variant["page"]))
                if not variant["part"]:
                    variant["error"] = "no part number found on Apple page"
            except Exception as exc:
                variant["error"] = str(exc)
            print(f"{model['short']} {variant['label']}: {variant.get('part') or variant.get('error')}")
            time.sleep(DELAY_SECONDS)


def fetch_pickup(parts, zip_code):
    """Return Apple's fulfillment-messages JSON for the given part numbers near a ZIP."""
    params = [("fae", "true"), ("pl", "true"), ("mts.0", "regular"), ("location", zip_code)]
    params += [(f"parts.{i}", part) for i, part in enumerate(parts)]
    return json.loads(http_get(f"{ENDPOINT}?{urllib.parse.urlencode(params)}"))


def status_of(info):
    """Map Apple's pickupDisplay value to available / unavailable / ineligible / unknown."""
    display = (info or {}).get("pickupDisplay")
    return display if display in RANK else "unknown"


def store_url(store):
    """Return the store's own apple.com page from a pickup response, if Apple sent one."""
    for source in (store, store.get("retailStore") or {}):
        for key in STORE_URL_KEYS:
            url = source.get(key)
            if isinstance(url, str) and url.startswith("https://www.apple.com/"):
                return url
    return ""


def parse_stores(payload, model):
    """Return {storeNumber: store row} with this model's availability from one response."""
    stores = payload.get("body", {}).get("content", {}).get("pickupMessage", {}).get("stores", [])
    rows = {}
    for store in stores:
        parts = store.get("partsAvailability", {})
        best, quote, in_stock = "unknown", "", []
        for variant in model["variants"]:
            if not variant.get("part"):
                continue
            info = parts.get(variant["part"], {})
            status = status_of(info)
            if status == "available":
                in_stock.append(variant["label"])
            if RANK[status] > RANK[best]:
                best = status
                quote = info.get("pickupSearchQuote") or info.get("storePickupQuote") or ""
        rows[store.get("storeNumber", "")] = {
            "id": store.get("storeNumber", ""),
            "name": store.get("storeName", ""),
            "city": store.get("city", ""),
            "state": store.get("state", ""),
            "distance": store.get("storeDistanceWithUnit", ""),
            "url": store_url(store),
            "availability": {model["key"]: {"status": best, "quote": quote, "in_stock": in_stock}},
        }
    return rows


def check_city(city, models):
    """Query each model separately so one bad part number can't break the others."""
    stores, errors = {}, {}
    for model in models:
        parts = [v["part"] for v in model["variants"] if v.get("part")]
        if not parts:
            errors[model["key"]] = "no part numbers to check"
            continue
        try:
            for sid, row in parse_stores(fetch_pickup(parts, city["zip"]), model).items():
                stores.setdefault(sid, {**row, "availability": {}})
                stores[sid]["availability"].update(row["availability"])
        except Exception as exc:  # the dashboard shows per-city, per-model errors
            errors[model["key"]] = str(exc)
        time.sleep(DELAY_SECONDS)
    for store in stores.values():  # a model whose request failed for this city
        for key, msg in errors.items():
            store["availability"].setdefault(key, {"status": "error", "quote": msg, "in_stock": []})
    return list(stores.values()), errors


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "site" / "inventory.json"))
    ap.add_argument("--limit", type=int, default=0, help="only check the first N cities")
    args = ap.parse_args()

    config = json.loads(CONFIG.read_text())
    models = config["models"]
    cities = config["cities"][: args.limit or None]
    resolve_parts(models)

    results = []
    for city in cities:
        stores, errors = check_city(city, models)
        results.append({**city, "stores": stores, "errors": errors})
        in_stock = sum(1 for s in stores if any(a["status"] == "available" for a in s["availability"].values()))
        print(f"{city['name']}, {city['state']}: {len(stores)} stores, {in_stock} in stock"
              + (f"; errors {errors}" if errors else ""))

    snapshot = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "models": models,
        "cities": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=1))
    print(f"wrote {out}")

    # Fail the run only when nothing came back at all, so partial data still publishes.
    if results and not any(c["stores"] for c in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
