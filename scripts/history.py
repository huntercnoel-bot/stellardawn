"""Stock history: when each store last had each model, and a feed of restock / sell-out events.

Runs during the publish step (merge_inventory.py), comparing this run's results with the
last published ones:

- Each store's availability per model gets
    "in_since":     when the current in-stock streak started (only while in stock)
    "last_seen":    the last time it was seen in stock
    "last_restock": when it last went from out of stock to in stock
- history.json keeps recent events: {"t", "store", "name", "city", "state", "model",
  "event": "restock" | "sold_out", "lasted" (minutes in stock, for sold_out)}.

Only real observations count: "unknown" / "error" (not checked this run) never create events.
"""
from datetime import datetime

KEEP_EVENTS = 1500
KEEP_DAYS = 14
OBSERVED = {"available", "unavailable", "ineligible"}


def _time(iso):
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def _checked(avail, fallback):
    """When this availability was observed: its newest per-setup check, else the run time."""
    times = [v.get("checked") for v in avail.get("variants", {}).values() if v.get("checked")]
    return max(times) if times else fallback


def stores_by_id(snapshot):
    """{id: store} from a packed or unpacked snapshot."""
    if isinstance(snapshot.get("stores"), dict):
        return snapshot["stores"]
    out = {}
    for c in snapshot.get("cities", []):
        for s in c.get("stores", []):
            if isinstance(s, dict):
                out.setdefault(s["id"], s)
    return out


def track(stores, prev_stores, events, now_iso):
    """Annotate each store's availability (stores: {id: store}, one entry per store) and
    append events for changes since the previous run. Returns the pruned event list."""
    for sid, store in stores.items():
        old_store = prev_stores.get(sid, {})
        for key, avail in store.get("availability", {}).items():
            old = old_store.get("availability", {}).get(key, {})
            for field in ("last_seen", "last_restock", "in_since"):
                if old.get(field) and not avail.get(field):
                    avail[field] = old[field]
            status, before = avail.get("status"), old.get("status")
            when = _checked(avail, now_iso)
            if status == "available":
                avail["last_seen"] = max(avail.get("last_seen") or "", when)
                if before != "available":
                    avail["in_since"] = when
                    if before in OBSERVED:  # a store seen for the first time isn't a "restock"
                        avail["last_restock"] = when
                        events.append(_event(store, key, "restock", when))
            elif status in OBSERVED:
                if before == "available":
                    lasted = None
                    start, end = _time(old.get("in_since")), _time(when)
                    if start and end:
                        lasted = max(0, round((end - start).total_seconds() / 60))
                    events.append({**_event(store, key, "sold_out", when), "lasted": lasted})
                avail.pop("in_since", None)
            # unknown / error: not observed this run, so keep what we knew
    return prune(events, now_iso)


def _event(store, key, kind, when):
    return {"t": when, "store": store["id"], "name": store.get("name", ""),
            "city": store.get("city", ""), "state": store.get("state", ""), "model": key, "event": kind}


def prune(events, now_iso):
    now = _time(now_iso)
    keep = []
    for e in events:
        t = _time(e.get("t"))
        if t and now and (now - t).days < KEEP_DAYS:
            keep.append(e)
    keep.sort(key=lambda e: e["t"])
    return keep[-KEEP_EVENTS:]
