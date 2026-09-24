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
from concurrent.futures import ThreadPoolExecutor
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
DELAY_SECONDS = (1.2, 2.0)
RETRIES = 2
WORKERS = 1
# Build-to-order setups are checked in 1/BTO_SLICES of cities per run (rotating).
BTO_SLICES = 3
# Results for setups not checked this run stay on the page this long.
CARRY_MINUTES = 60
# Stop starting new cities after this long so the run always finishes and publishes.
RUN_BUDGET_SECONDS = 300
TIMEOUT_SECONDS = 15
# Stop early when Apple refuses this many requests in a row, so a blocked run ends fast.
MAX_CONSECUTIVE_FAILURES = 5
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
            status = None
        if attempt < RETRIES - 1:
            # 541 is Apple's rate limit / bot refusal; it eases off after a longer pause.
            time.sleep(30 + random.random() * 15 if status == 541 else 3 + random.random() * 3)
    _failures += 1
    raise RuntimeError(last_error)


def find_part(html):
    """Return the first standard or build-to-order part number embedded in a page, or None."""
    match = PART_RE.search(html)
    return match.group(1) if match else None


DEFAULT_KIT_RE = re.compile(r'"defaultKit"\s*:\s*\{\s*"part"\s*:\s*"(RO_[A-Z0-9_]+)"\s*,\s*"options"\s*:\s*\{(.*?)\}')


def discover(html):
    """Read {part, options} for a variant from its Apple Store page, best effort.

    Configurator pages embed the configured kit, e.g.
    "defaultKit":{"part":"RO_MACSTUDIO_...","options":{"memory":"065-CLQ7",...}}.
    """
    kit = DEFAULT_KIT_RE.search(html)
    if kit:
        codes = re.findall(r'"(065-[A-Z0-9]{4})"', kit.group(2))
        if codes:
            return {"part": kit.group(1), "options": ",".join(codes)}
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
            if isinstance(url, str) and url.startswith("/"):
                url = "https://www.apple.com" + url
            if isinstance(url, str) and url.startswith("http://www.apple.com/"):
                url = "https://" + url[len("http://"):]
            if isinstance(url, str) and url.startswith("https://www.apple.com/"):
                return url
    return ""


def parse_stores(payload, model, checked=""):
    """Return {storeNumber: store row} with this model's availability from one response.

    Each model's availability keeps per-setup results under "variants", so setups checked
    in different runs can be combined (see summarize)."""
    stores = store_list(payload) or []
    rows = {}
    for store in stores:
        parts = store.get("partsAvailability", {})
        variants = {}
        for variant in model["variants"]:
            if not variant.get("part"):
                continue
            info = parts.get(variant["part"])
            if info is None and variant.get("options") and len(parts) == 1:
                info = next(iter(parts.values()))  # build-to-order answers may be keyed differently
            info = info or {}
            variants[variant["label"]] = {
                "status": status_of(info),
                "quote": info.get("pickupSearchQuote") or info.get("storePickupQuote") or "",
                "checked": checked,
            }
        rows[store.get("storeNumber", "")] = {
            "id": store.get("storeNumber", ""),
            "name": store.get("storeName", ""),
            "city": store.get("city", ""),
            "state": store.get("state", ""),
            "distance": store.get("storeDistanceWithUnit", ""),
            "url": store_url(store),
            "availability": {model["key"]: summarize({"variants": variants})},
        }
    return rows


def summarize(avail):
    """Set status / quote / in_stock from the per-setup results in avail["variants"]."""
    variants = avail.get("variants", {})
    best = max(variants.values(), key=lambda v: RANK.get(v["status"], 0), default=None)
    avail["status"] = best["status"] if best else avail.get("status", "unknown")
    avail["quote"] = best["quote"] if best else avail.get("quote", "")
    avail["in_stock"] = [label for label, v in variants.items() if v["status"] == "available"]
    return avail


def city_models(models, city_index, run_index, slices):
    """This city's share of build-to-order work for this run.

    Standard parts are checked everywhere every run. Build-to-order setups cost one
    request each, so each run only a 1/`slices` share of cities checks them, one setup
    per city, rotating so every city cycles through every setup."""
    out = []
    for model in models:
        bto = [v for v in model["variants"] if v.get("part") and v.get("options")]
        if bto:
            keep = None
            if city_index % slices == run_index % slices:
                keep = bto[(city_index + run_index // slices) % len(bto)]
            model = {**model, "variants": [v for v in model["variants"] if not v.get("options") or v is keep],
                     "rotated_out": keep is None}
        out.append(model)
    return out


def request_plan(models):
    """Requests for one city: every standard part (across all models) shares a single
    request, and each build-to-order variant gets its own, since Apple keys the answer
    by product code. Returns [(variants, [(model, its variants in this request)])]."""
    standard, plan = [], []
    for model in models:
        std = [v for v in model["variants"] if v.get("part") and not v.get("options")]
        if std:
            standard.append((model, std))
        for v in model["variants"]:
            if v.get("part") and v.get("options"):
                plan.append(([v], [(model, [v])]))
    if standard:
        plan.insert(0, ([v for _, vs in standard for v in vs], standard))
    return plan


def merge_rows(into, rows, key):
    """Merge one request's store rows into `into`, combining per-setup results."""
    for sid, row in rows.items():
        cur = into.setdefault(sid, {**row, "availability": {}})
        new = row["availability"][key]
        old = cur["availability"].setdefault(key, {"variants": {}})
        old.setdefault("variants", {}).update(new.get("variants", {}))
        summarize(old)


def check_city(city, models, checked=""):
    """Check every model near one city. A failed request only affects the models in it."""
    stores, failed, tried = {}, {}, {}
    for variants, members in request_plan(models):
        try:
            referer = next((v["page"] for v in variants if v.get("page")), None) or members[0][0].get("apple_url")
            data = fetch_pickup(variants, city["zip"], referer)
            for model, vs in members:
                merge_rows(stores, parse_stores(data, {**model, "variants": vs}, checked), model["key"])
        except Exception as exc:  # the dashboard shows per-city, per-model errors
            for model, _ in members:
                failed.setdefault(model["key"], str(exc))
        for model, _ in members:
            tried[model["key"]] = tried.get(model["key"], 0) + 1
        pause()
    # A model is in error only when every request for it failed.
    succeeded = {k for s in stores.values() for k in s["availability"]}
    errors = {k: msg for k, msg in failed.items() if k not in succeeded}
    for m in models:
        if m["key"] not in tried and not m.get("rotated_out"):
            errors[m["key"]] = "no part numbers to check"
    for store in stores.values():
        for key, msg in errors.items():
            store["availability"].setdefault(key, {"status": "error", "quote": msg, "in_stock": [], "variants": {}})
        for model in models:  # a model not checked for this store this run
            store["availability"].setdefault(model["key"], {"status": "unknown", "quote": "", "in_stock": [], "variants": {}})
    return list(stores.values()), errors


def pack(snapshot):
    """Store each Apple Store once (areas overlap, so the same store shows up near several
    ZIPs): top-level "stores" by id, areas list store ids. Duplicate sightings of a store in
    one run are combined, so a setup checked from either area counts for both."""
    stores = {}
    for city in snapshot["cities"]:
        ids = []
        for st in city["stores"]:
            if isinstance(st, str):
                ids.append(st)
                continue
            cur = stores.get(st["id"])
            if cur is None:
                stores[st["id"]] = st
            else:
                for key, avail in st.get("availability", {}).items():
                    mine = cur["availability"].setdefault(key, {"variants": {}})
                    for label, v in avail.get("variants", {}).items():
                        old = mine.setdefault("variants", {}).get(label)
                        if old is None or (v.get("checked") or "") > (old.get("checked") or ""):
                            mine["variants"][label] = v
                    if mine.get("variants"):
                        summarize(mine)
                    elif mine.get("status") in (None, "unknown", "error") and avail.get("status"):
                        mine.update({k: avail[k] for k in ("status", "quote", "in_stock") if k in avail})
            ids.append(st["id"])
        city["stores"] = ids
    snapshot["stores"] = {**snapshot.get("stores", {}), **stores}
    return snapshot


def unpack(snapshot):
    """Inverse of pack(): areas get their store objects back. Safe on unpacked data."""
    stores = snapshot.pop("stores", None) or {}
    for city in snapshot.get("cities", []):
        city["stores"] = [stores[i] if isinstance(i, str) else i for i in city.get("stores", [])
                          if not isinstance(i, str) or i in stores]
    return snapshot


def parse_time(iso):
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def carry_forward(results, previous, models, now):
    """Fill gaps from the previous snapshot: setups not checked this run (if recent enough),
    and whole cities Apple didn't answer for."""
    prev_cities = {(c["name"], c["state"]): c for c in previous.get("cities", [])}
    prev_stores = {s["id"]: s for c in previous.get("cities", []) for s in c.get("stores", [])}
    fresh = lambda iso: (t := parse_time(iso)) is not None and (now - t).total_seconds() <= CARRY_MINUTES * 60
    for city in results:
        prev_city = prev_cities.get((city["name"], city["state"]))
        if not city["stores"] and prev_city and prev_city.get("stores") and fresh(prev_city.get("checked")):
            city["stores"] = prev_city["stores"]
            city["checked"] = prev_city["checked"]
            city["errors"] = {}
            continue
        for store in city["stores"]:
            old = prev_stores.get(store["id"])
            if not old:
                continue
            for m in models:
                cur = store["availability"].setdefault(m["key"], {"variants": {}})
                cur.setdefault("variants", {})
                for label, v in old.get("availability", {}).get(m["key"], {}).get("variants", {}).items():
                    if label not in cur["variants"] and fresh(v.get("checked")):
                        cur["variants"][label] = v
                if cur["variants"]:
                    if cur.get("status") == "error":
                        cur["status"] = "unknown"
                    summarize(cur)


def reuse_parts(models, previous):
    """Reuse part numbers / option codes read from Apple's pages in a recent run."""
    prev = {(m["key"], v["label"]): v for m in previous.get("models", []) for v in m.get("variants", [])}
    for m in models:
        for v in m["variants"]:
            old = prev.get((m["key"], v["label"]))
            if not v.get("part") and old and old.get("part"):
                v["part"] = old["part"]
                if old.get("options"):
                    v["options"] = old["options"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "site" / "inventory.json"))
    ap.add_argument("--limit", type=int, default=0, help="only check the first N cities")
    ap.add_argument("--previous", help="last published inventory.json, to carry results forward")
    ap.add_argument("--shard", default="0/1",
                    help="i/n: check only every n-th area starting at i (parallel runners each get "
                         "their own Apple rate limit); combine the parts with merge_inventory.py")
    args = ap.parse_args()

    config = json.loads(CONFIG.read_text())
    models = config["models"]
    shard, shards = (int(x) for x in args.shard.split("/"))
    all_cities = config["cities"][: args.limit or None]
    cities = [c for i, c in enumerate(all_cities) if i % shards == shard]
    city_index = {(c["name"], c["state"]): i for i, c in enumerate(all_cities)}
    previous = {}
    if args.previous and Path(args.previous).exists():
        try:
            previous = unpack(json.loads(Path(args.previous).read_text()))
        except ValueError:
            previous = {}
    print("HTTP client:", "curl_cffi (Chrome fingerprint)" if cffi_requests else "urllib (likely blocked by Apple)")
    reuse_parts(models, previous)
    resolve_parts(models)

    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    run_index = int(now.timestamp() // 300)

    started = time.monotonic()

    def run(indexed):
        _, city = indexed
        i = city_index[(city["name"], city["state"])]  # global index keeps the 256GB rotation even
        if time.monotonic() - started > RUN_BUDGET_SECONDS:
            return {**city, "stores": [], "errors": {m["key"]: "not reached this run" for m in models}, "checked": None}
        stores, errors = check_city(city, city_models(models, i, run_index, BTO_SLICES), stamp)
        counts = {m["short"]: sum(1 for s in stores if s["availability"].get(m["key"], {}).get("status") == "available")
                  for m in models}
        print(f"{city['name']}, {city['state']}: {len(stores)} stores, in stock {counts}"
              + (f"; errors {errors}" if errors else ""))
        return {**city, "stores": stores, "errors": errors, "checked": stamp if stores else None}

    # Least recently checked cities first, so a run that runs out of time is fair over time.
    last = {(c["name"], c["state"]): c.get("checked") or "" for c in previous.get("cities", [])}
    order = sorted(enumerate(cities), key=lambda ic: last.get((ic[1]["name"], ic[1]["state"]), ""))
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        done = {ic[0]: r for ic, r in zip(order, pool.map(run, order))}
    results = [done[i] for i in range(len(cities))]
    carry_forward(results, previous, models, now)

    print("Apple endpoint used:", _endpoint or "none answered")
    snapshot = {
        "updated": stamp,
        "source": _endpoint,
        "models": models,
        "cities": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pack(snapshot), separators=(",", ":")))
    print(f"wrote {out}")

    # Fail the run only when nothing came back at all, so partial data still publishes.
    if results and not any(c["stores"] for c in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
