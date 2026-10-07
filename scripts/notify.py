#!/usr/bin/env python3
"""Send phone alerts (ntfy.sh) for new restocks found in this run.

    python3 scripts/notify.py new_events.json site/inventory.json

Alerts go to the ntfy topic in config.json "alerts": restocks of the "models" list anywhere,
plus "priority_area_models" at stores in priority areas (Miami). Subscribe to the topic in
the free ntfy app to get them.
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_inventory as ci  # noqa: E402

SITE = "https://huntercnoel-bot.github.io/stellardawn/"


def pick(events, inventory, config):
    alerts = config.get("alerts", {})
    everywhere, priority_models = set(alerts.get("models", [])), set(alerts.get("priority_area_models", []))
    stores = inventory.get("stores", {})
    priority_ids = {i for c in inventory.get("cities", []) if c.get("priority") for i in c.get("stores", [])}
    models = {m["key"]: m for m in config["models"]}
    out = []
    for e in events:
        if e.get("event") != "restock":
            continue
        if e["model"] in everywhere or (e["model"] in priority_models and e["store"] in priority_ids):
            m = models.get(e["model"], {})
            avail = stores.get(e["store"], {}).get("availability", {}).get(e["model"], {})
            setup = ", ".join(avail.get("in_stock", []))
            url = next((v.get("page") for v in m.get("variants", []) if v["label"] in avail.get("in_stock", [])),
                       m.get("apple_url", SITE))
            out.append({
                "title": f"{m.get('short', e['model'])} in stock: Apple {e['name']}",
                "body": f"{m.get('label', '')}{' (' + setup + ')' if setup else ''} at Apple {e['name']}, "
                        f"{e['city']}, {e['state']}. Pick up at apple.com.",
                "url": url,
                "miami": e["store"] in priority_ids,
            })
    return out


def send(topic, alert):
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}", data=alert["body"].encode(), method="POST",
        headers={"Title": alert["title"].encode("ascii", "ignore").decode(), "Click": alert["url"],
                 "Priority": "urgent" if alert["miami"] else "high", "Tags": "computer",
                 "Actions": f"view, Open apple.com, {alert['url']}; view, Tracker, {SITE}"})
    urllib.request.urlopen(req, timeout=15).read()


def main():
    events = json.loads(Path(sys.argv[1]).read_text() or "[]")
    inventory = json.loads(Path(sys.argv[2]).read_text())
    config = json.loads(ci.CONFIG.read_text())
    topic = config.get("alerts", {}).get("topic")
    alerts = pick(events, inventory, config)
    for a in alerts[:10]:  # a burst cap, in case a run sees many stores at once
        try:
            send(topic, a)
            print("sent:", a["title"])
        except Exception as exc:
            print("alert failed:", exc)
    print(f"{len(alerts)} alert(s)")


if __name__ == "__main__":
    main()
