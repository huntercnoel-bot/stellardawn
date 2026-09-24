#!/usr/bin/env python3
"""Start the next "Check inventory" run ~5 minutes after this one began (used in CI).

GitHub's */5 cron often runs late or not at all, so the workflow keeps itself going: the
last job waits until INTERVAL seconds after the run started, then dispatches the workflow
again, but only if no other run is queued, waiting or in progress (so there's never more
than one chain). Set the repo variable PAUSE_CHECKS=1 to stop the chain.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

INTERVAL = 300
WORKFLOW = "check-inventory.yml"


def call(path, method="GET", body=None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}",
        method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['TOKEN']}",
                 "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode()
    return json.loads(text) if text else {}


def others_active(run_id):
    count = 0
    for status in ("queued", "waiting", "pending", "requested", "in_progress"):
        runs = call(f"/actions/workflows/{WORKFLOW}/runs?status={status}&per_page=20").get("workflow_runs", [])
        count += sum(1 for r in runs if r["id"] != run_id)
    return count


def main():
    if os.environ.get("PAUSE_CHECKS") == "1":
        print("PAUSE_CHECKS=1, not starting another run")
        return
    run_id = int(os.environ["GITHUB_RUN_ID"])
    started = datetime.fromisoformat(call(f"/actions/runs/{run_id}")["run_started_at"].replace("Z", "+00:00"))
    wait = INTERVAL - (datetime.now(timezone.utc) - started).total_seconds()
    if wait > 0:
        print(f"waiting {wait:.0f}s so runs start about every {INTERVAL // 60} minutes")
        time.sleep(wait)
    active = others_active(run_id)
    if active:
        print(f"{active} other run(s) already queued or running, not starting another")
        return
    call(f"/actions/workflows/{WORKFLOW}/dispatches", "POST", {"ref": os.environ.get("GITHUB_REF_NAME", "main")})
    print("started the next run")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never fail the publish job over this
        print(f"could not start the next run: {exc}", file=sys.stderr)
