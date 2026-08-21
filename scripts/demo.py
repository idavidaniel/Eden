#!/usr/bin/env python3
"""Spin up a demo company, give it a project, and watch the team work.

Usage: python3 scripts/demo.py [base_url]
Leaves the company in place so you can explore it in the dashboard.
"""

import json
import sys
import time
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")

BRIEF = """Build a small Python command-line tool that reads a CSV of solar panel
readings (timestamp, panel_id, watts) and reports which panels are underperforming.
Print an aligned table and support a --threshold flag. Include a README and tests."""


def call(path, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method or ("POST" if data else "GET"),
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
        return json.loads(body) if body else None


def main():
    company = call(
        "/companies",
        {
            "name": "Lumen Analytics",
            "tagline": "Dashboards for solar installers",
            "industry": "Clean energy software",
            "description": "We build small web tools that help solar installers track panel performance.",
            "mission": "Make panel data legible to non-engineers.",
            "handbook": "Ship small. Python for backends. Every feature needs a test.",
        },
    )
    print(f"Founded {company['name']}  →  {BASE.replace(':8000', ':3000')}/companies/{company['id']}")
    for person in call(f"/companies/{company['id']}/employees"):
        print(f"  {person['avatar']} {person['name']:<16} {person['title']}")

    project = call(
        f"/companies/{company['id']}/projects", {"name": "Panel Health CLI", "brief": BRIEF}
    )
    print(f"\nCreated project {project['name']} [{project['key']}]")

    run = call(f"/projects/{project['id']}/runs", {})
    print(f"Started run {run['id']}\n")

    seen = 0
    while True:
        state = call(f"/projects/{project['id']}")
        events = call(f"/companies/{company['id']}/activity?limit=200")["events"]
        for event in events[seen:]:
            print(f"  {event['actor'][:26]:<26} {event['summary'][:80]}")
        seen = len(events)

        status = state["runs"][0]["status"] if state["runs"] else "unknown"
        if status in {"completed", "failed", "cancelled", "interrupted"}:
            print(f"\nRun {status}. Tickets: {state['counts']}")
            break
        time.sleep(10)


if __name__ == "__main__":
    main()
