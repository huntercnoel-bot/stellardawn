#!/usr/bin/env python3
"""Check Apple Store pickup availability for Mac Studio models near major US cities.

Reads scripts/config.json and writes a JSON snapshot (default: site/inventory.json)
that the dashboard in site/index.html renders.

    pip install curl_cffi   # strongly recommended, see below
    python3 scripts/check_inventory.py [--out site/inventory.json] [--limit N]

How it talks to Apple (the same approach other open-source Apple stock trackers use):
- Apple's pickup endpoints sit behind Akamai bot protection, which fingerprints the TLS
  handshake. Python's own HTTP client gets blocked (HTTP 541), so requests go through
  curl_cffi impersonating Chrome when it's installed.
- Headers mimic the XHR the Apple Store page makes, with the product's own page as Referer.
- It tries /shop/retail/pickup-message first and falls back to /shop/fulfillment-messages,
  then sticks with whichever answered.

Each model has one or more variants (e.g. 256GB with different chips/storage). A variant
names a standard `part` number (MHL74LL/A), or a build-to-order product code plus
`options` (Apple's 065-xxxx option codes), or just its Apple Store `page`, in which case
the checker tries to read the part / options from that page at run time.
"""
import argparse
import functools
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from curl_cffi import requests as cffi_requests
except ImportError:  # still works for local testing, but Apple will likely block it
    cffi_requests = None

print = functools.partial(print, flush=True)  # stream progress into CI logs
ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "scripts" / "config.json"
ENDPOINTS = {
    "pickup-message": ("https://www.apple.com/shop/retail/pickup-message",
                       {"pl": "true", "mts.0": "regular", "searchNearby": "true"}),
    "fulfillment-messages": ("https://www.apple.com/shop/fulfillment-messages",
                             {"fae": "true", "pl": "true", "mts.0": "regular", "searchNearby": "true"}),
}
IMPERSONATE = "chrome"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Origin": "https://www.apple.com",
}
PAGE_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
DEFAULT_REFERER = "https://www.apple.com/shop/buy-mac/mac-studio"
DELAY_SECONDS = (0.8, 1.6)
RETRIES = 2
TIMEOUT_SECONDS = 15
# Stop early when Apple refuses this many requests in a row, so a blocked run ends fast.
MAX_CONSECUTIVE_FAILURES = 4
# Standard part numbers look like MHL74LL/A; build-to-order product codes like Z1U5 or RO_...
PART_RE = re.compile(r'"(?:partNumber|part|sku)"\s*:\s*"((?:M[A-Z0-9]{4}LL/A)|(?:Z[A-Z0-9]{3,9}))"')
RO_RE = re.compile(r'"(RO_[A-Z0-9_]{6,})"')
OPTIONS_RE = re.compile(r'option\.0=((?:065-[A-Z0-9]{4}(?:,|%2C)?)+)', re.I)
RANK = {"available": 4, "unavailable": 3, "ineligible": 2, "unknown": 1}
STORE_URL_KEYS = ("hoursUrl", "storeUrl", "reservationUrl", "makeReservationUrl")


class AppleUnavailable(RuntimeError):
    """Apple refused too many requests in a row; skip the rest of this run."""


_failures = 0
_endpoint = None  # the endpoint that last answered


def pause():
    time.sleep(random.uniform(*DELAY_SECONDS))


def _get_once(url, params, headers):
    """One GET; returns (status, text). Uses curl_cffi (Chrome fingerprint) when available."""
    if cffi_requests is not None:
        resp = cffi_requests.get(url, params=params, headers=headers,
                                 impersonate=IMPERSONATE, timeout=TIMEOUT_SECONDS)
        return resp.status_code, resp.text
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(urllib.request.Request(full, headers=headers),
                                    timeout=TIMEOUT_SECONDS) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(400).decode("utf-8", "replace")


def http_get(url, params=None, headers=None):
    """GET with a short retry; counts consecutive failures across the whole run."""
    global _failures
    if _failures >= MAX_CONSECUTIVE_FAILURES:
        raise AppleUnavailable("skipped: Apple refused the previous requests")
    last_error = None
    for attempt in range(RETRIES):
        try:
            status, text = _get_once(url, params or {}, headers or HEADERS)
            if status == 200:
                _failures = 0
                return text
            last_error = f"HTTP {status}: {' '.join(text[:160].split())}"
        except Exception as exc:  # network errors from either client
            last_error = str(exc)
        if attempt < RETRIES - 1:
            time.sleep(2 + random.random() * 2)
    _failures += 1
    raise RuntimeError(last_error)


def find_part(html):
    """Return the first standard or build-to-order part number embedded in a page, or None."""
    match = PART_RE.search(html)
    return match.group(1) if match else None


def discover(html):
    """Read {part, options} for a variant from its Apple Store page, best effort."""
    options = OPTIONS_RE.search(html)
    ro = RO_RE.search(html)
    if options and ro:
        return {"part": ro.group(1), "options": urllib.parse.unquote(options.group(1))}
    part = find_part(html)
    return {"part": part} if part else {}


def resolve_parts(models):
    """Fill in each variant's part number (and options), reading its Apple page when needed."""
    global _failures
    for model in models:
        for variant in model["variants"]:
            if variant.get("part") or not variant.get("page"):
                continue
            try:
                found = discover(http_get(variant["page"], headers=PAGE_HEADERS))
                variant.update(found)
                if not found:
                    variant["error"] = "no part number found on Apple page"
            except Exception as exc:
                variant["error"] = str(exc)
            print(f"{model['short']} {variant['label']}: "
                  f"{variant.get('part') or variant.get('error')} {variant.get('options', '')}".rstrip())
            pause()
    # Product pages and the pickup API are guarded separately; start the stock checks fresh.
    _failures = 0


def fetch_pickup(variants, zip_code, referer=None):
    """Return Apple's pickup JSON for these variants near a ZIP, trying both endpoints."""
    global _endpoint
    params = {"location": zip_code}
    for i, v in enumerate(variants):
        params[f"parts.{i}"] = v["part"]
        if v.get("options"):
            params[f"option.{i}"] = v["options"]
    headers = {**HEADERS, "Referer": referer or DEFAULT_REFERER}
    order = [_endpoint] + [e for e in ENDPOINTS if e != _endpoint] if _endpoint else list(ENDPOINTS)
    errors = []
    for name in order:
        url, base = ENDPOINTS[name]
        try:
            data = json.loads(http_get(url, {**base, **params}, headers))
        except AppleUnavailable:
            raise
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            continue
        if store_list(data) is not None:
            _endpoint = name
            return data
        errors.append(f"{name}: unexpected response {' '.join(json.dumps(data)[:160].split())}")
    raise RuntimeError("; ".join(errors))


def store_list(payload):
    """Stores from either endpoint's response shape, or None if neither matches."""
    body = payload.get("body") if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        return None
    if isinstance(body.get("stores"), list):  # /shop/retail/pickup-message
        return body["stores"]
    stores = body.get("content", {}).get("pickupMessage", {}).get("stores")  # fulfillment-messages
    return stores if isinstance(stores, list) else None


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
    stores = store_list(payload) or []
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
        variants = [v for v in model["variants"] if v.get("part")]
        if not variants:
            errors[model["key"]] = "no part numbers to check"
            continue
        try:
            referer = variants[0].get("page") or model.get("apple_url")
            for sid, row in parse_stores(fetch_pickup(variants, city["zip"], referer), model).items():
                stores.setdefault(sid, {**row, "availability": {}})
                stores[sid]["availability"].update(row["availability"])
        except Exception as exc:  # the dashboard shows per-city, per-model errors
            errors[model["key"]] = str(exc)
        pause()
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
    print("HTTP client:", "curl_cffi (Chrome fingerprint)" if cffi_requests else "urllib (likely blocked by Apple)")
    resolve_parts(models)

    results = []
    for city in cities:
        stores, errors = check_city(city, models)
        results.append({**city, "stores": stores, "errors": errors})
        in_stock = sum(1 for s in stores if any(a["status"] == "available" for a in s["availability"].values()))
        print(f"{city['name']}, {city['state']}: {len(stores)} stores, {in_stock} in stock"
              + (f"; errors {errors}" if errors else ""))

    print("Apple endpoint used:", _endpoint or "none answered")
    snapshot = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": _endpoint,
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
