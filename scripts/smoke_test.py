#!/usr/bin/env python3
"""End-to-end smoke test against a running stack.

Creates a throwaway company, checks every surface responds, then deletes it.
Usage: python3 scripts/smoke_test.py [base_url]
"""

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Mcp-Protocol-Version": "2026-07-28",
    "Authorization": "Bearer dev-token",
}


def call(path, payload=None, method=None, headers=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers=headers or ({"Content-Type": "application/json"} if data else {}),
        method=method or ("POST" if data else "GET"),
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        return json.loads(body) if body else None


def check(name, fn):
    print(f"→ {name} ... ", end="", flush=True)
    try:
        result = fn()
    except (urllib.error.URLError, urllib.error.HTTPError, AssertionError, ValueError) as exc:
        print(f"FAIL\n   {exc}")
        sys.exit(1)
    print("ok")
    return result


def main():
    health = check("health", lambda: call("/health"))
    print(f"   model={health['model']} persistence={health['persistence']}")
    if not health["llm_configured"]:
        print("   NVIDIA_API_KEY is not set; the employees cannot think.")
        sys.exit(1)

    roles = check("role catalogue", lambda: call("/roles"))
    print(f"   {len(roles)} roles available")

    company = check(
        "found a company",
        lambda: call(
            "/companies",
            {
                "name": "Smoke Test Co",
                "description": "Temporary company created by the smoke test.",
                "starting_team": ["engineering_manager", "backend_engineer", "qa_engineer"],
            },
        ),
    )
    company_id = company["id"]

    try:
        team = check("team was hired", lambda: call(f"/companies/{company_id}/employees"))
        assert len(team) == 3, f"expected 3 hires, got {len(team)}"
        print(f"   {', '.join(f'{p['name']} ({p['title']})' for p in team)}")

        creds = check(
            "credentials are issued",
            lambda: call(f"/employees/{team[0]['id']}/credentials")["accounts"],
        )
        assert creds and creds[0]["password"], "no password issued"
        print(f"   {len(creds)} service accounts for {team[0]['name']}")

        project = check(
            "create a project",
            lambda: call(
                f"/companies/{company_id}/projects",
                {"name": "Smoke Project", "brief": "Prove the workspace works."},
            ),
        )

        check(
            "workspace is a git repo",
            lambda: call(f"/projects/{project['id']}/files")["entries"] or _fail("empty workspace"),
        )
        check(
            "write a file",
            lambda: call(
                f"/projects/{project['id']}/file",
                {"path": "smoke.txt", "content": "hello", "commit_message": "smoke"},
                method="PUT",
            ),
        )
        commits = check("commit history", lambda: call(f"/projects/{project['id']}/commits"))
        assert commits[0]["subject"] == "smoke", "commit missing"

        check(
            "ticket board",
            lambda: call(f"/projects/{project['id']}/tickets", {"title": "Smoke ticket"}),
        )
        check(
            "wiki",
            lambda: call(
                f"/companies/{company_id}/documents", {"title": "Smoke page", "body": "hello"}
            ),
        )
        channels = check("chat channels", lambda: call(f"/companies/{company_id}/channels"))
        check(
            "post a message",
            lambda: call(f"/channels/{channels[0]['id']}/messages", {"body": "smoke test"}),
        )

        tools = check(
            "mcp tools/list",
            lambda: call(
                "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=MCP_HEADERS
            )["result"]["tools"],
        )
        print(f"   {len(tools)} tools exposed over MCP")

        feed = check("activity feed", lambda: call(f"/companies/{company_id}/activity")["events"])
        print(f"   {len(feed)} events recorded")
    finally:
        call(f"/companies/{company_id}", method="DELETE")
        print("→ cleaned up the test company")

    print("\nAll checks passed.")


def _fail(message):
    raise AssertionError(message)


if __name__ == "__main__":
    main()
