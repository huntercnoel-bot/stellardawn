#!/usr/bin/env python3
"""Combine inventory parts from parallel check_inventory.py shards into one inventory.json.

    python3 scripts/merge_inventory.py out/inventory.json parts/*.json [--previous prev.json]

Areas missing from every part (a shard crashed or timed out) keep their last published
results, so they never vanish from the page.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_inventory as ci  # noqa: E402


def merge(parts, previous=None):
    """Cities in config order; models (with discovered part numbers) from the first part
    that has them; the newest timestamp."""
    order = {(c["name"], c["state"]): i for i, c in enumerate(json.loads(ci.CONFIG.read_text())["cities"])}
    cities = {}
    for part in parts:
        for c in part.get("cities", []):
            cities[(c["name"], c["state"])] = c
    for c in (previous or {}).get("cities", []):  # areas no shard reported this run
        key = (c["name"], c["state"])
        if key in order and key not in cities:
            cities[key] = {**c, "errors": {}}
    models = next((p["models"] for p in parts if p.get("models")), [])
    for p in parts:  # prefer a part whose build-to-order codes were resolved
        if any(v.get("options") for m in p.get("models", []) for v in m["variants"]):
            models = p["models"]
            break
    return {
        "updated": max((p.get("updated", "") for p in parts), default=""),
        "source": next((p["source"] for p in parts if p.get("source")), None),
        "models": models,
        "cities": sorted(cities.values(), key=lambda c: order.get((c["name"], c["state"]), 1e9)),
    }


def main():
    args = sys.argv[1:]
    previous = None
    if "--previous" in args:
        i = args.index("--previous")
        prev_path = args[i + 1]
        del args[i:i + 2]
        try:
            previous = ci.unpack(json.loads(Path(prev_path).read_text()))
        except (OSError, ValueError) as exc:
            print(f"no previous results: {exc}")
    out, *paths = args
    parts = []
    for path in paths:
        try:
            parts.append(ci.unpack(json.loads(Path(path).read_text())))
        except (OSError, ValueError) as exc:
            print(f"skipping {path}: {exc}")
    if not parts and not previous:
        sys.exit("no inventory parts to merge")
    if not parts:
        parts = [{**previous, "cities": []}]
    merged = merge(parts, previous)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(ci.pack(merged), separators=(",", ":")))
    print(f"merged {len(parts)} parts, {len(merged['cities'])} areas -> {out}")


if __name__ == "__main__":
    main()
