#!/usr/bin/env python3
"""Check Apple Store pickup availability for Mac Studio models near major US cities.

Reads scripts/config.json and writes a JSON snapshot (default: site/inventory.json)
that the dashboard in site/index.html renders. Standard library only.

    python3 scripts/check_inventory.py [--out site/inventory.json] [--limit N]
"""
import argparse
import json
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
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.apple.com/shop/buy-mac/mac-studio",
}
DELAY_SECONDS = 1.5
RETRIES = 3


def fetch_pickup(parts, zip_code):
    """Return Apple's fulfillment-messages JSON for the given part numbers near a ZIP."""
    params = [("fae", "true"), ("pl", "true"), ("mts.0", "regular"), ("location", zip_code)]
    params += [(f"parts.{i}", part) for i, part in enumerate(parts)]
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    last_error = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"request failed after {RETRIES} attempts: {last_error}")


def status_of(availability):
    """Map Apple's pickupDisplay value to available / unavailable / ineligible / unknown."""
    display = (availability or {}).get("pickupDisplay")
    if display in ("available", "unavailable", "ineligible"):
        return display
    return "unknown"


def parse_stores(payload, models):
    """Pull store rows out of a fulfillment-messages response."""
    stores = payload.get("body", {}).get("content", {}).get("pickupMessage", {}).get("stores", [])
    rows = []
    for store in stores:
        parts = store.get("partsAvailability", {})
        availability = {}
        for model in models:
            if not model.get("part"):
                availability[model["key"]] = {"status": "not_stocked"}
                continue
            info = parts.get(model["part"], {})
            availability[model["key"]] = {
                "status": status_of(info),
                "quote": info.get("pickupSearchQuote") or info.get("storePickupQuote") or "",
            }
        rows.append({
            "id": store.get("storeNumber", ""),
            "name": store.get("storeName", ""),
            "city": store.get("city", ""),
            "state": store.get("state", ""),
            "distance": store.get("storeDistanceWithUnit", ""),
            "availability": availability,
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "site" / "inventory.json"))
    ap.add_argument("--limit", type=int, default=0, help="only check the first N cities")
    args = ap.parse_args()

    config = json.loads(CONFIG.read_text())
    models = config["models"]
    cities = config["cities"][: args.limit or None]
    parts = [m["part"] for m in models if m.get("part")]

    results = []
    for i, city in enumerate(cities):
        entry = {**city, "stores": [], "error": None}
        try:
            entry["stores"] = parse_stores(fetch_pickup(parts, city["zip"]), models)
        except Exception as exc:  # keep going; the dashboard shows per-city errors
            entry["error"] = str(exc)
        results.append(entry)
        ok = entry["error"] is None
        in_stock = sum(
            1 for s in entry["stores"]
            if any(a["status"] == "available" for a in s["availability"].values())
        )
        print(f"{city['name']}, {city['state']}: "
              + (f"{len(entry['stores'])} stores, {in_stock} in stock" if ok else f"ERROR {entry['error']}"))
        if i < len(cities) - 1:
            time.sleep(DELAY_SECONDS)

    snapshot = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "models": models,
        "cities": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=1))
    print(f"wrote {out}")

    # Fail the run only when every city errored, so partial data still publishes.
    if results and all(c["error"] for c in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
