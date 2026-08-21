#!/usr/bin/env python3
"""End-to-end smoke test against a running stack.

Usage: python3 scripts/smoke_test.py [base_url]
Exits non-zero on the first failure so it can gate a deploy.
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


def request(path, payload=None, headers=None, timeout=180):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers=headers or ({"Content-Type": "application/json"} if data else {}),
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def check(name, fn):
    print(f"→ {name} ... ", end="", flush=True)
    try:
        result = fn()
    except (urllib.error.URLError, urllib.error.HTTPError, AssertionError) as exc:
        print(f"FAIL\n   {exc}")
        sys.exit(1)
    print("ok")
    return result


def main():
    health = check("health", lambda: request("/health"))
    print(f"   model={health['model']} persistence={health['persistence']} cache={health['cache']}")
    if not health["llm_configured"]:
        print("   NVIDIA_API_KEY is not set; agent calls will fail.")
        sys.exit(1)

    tools = check(
        "mcp tools/list",
        lambda: request(
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            MCP_HEADERS,
        )["result"]["tools"],
    )
    print(f"   tools: {', '.join(t['name'] for t in tools)}")

    def run_turn():
        body = request(
            "/run_task",
            {
                "thread_id": "smoke-test",
                "message": "Reply with exactly the word: pong",
                "persona_block": "You are terse.",
                "human_block": "The client is running a smoke test.",
            },
        )
        assert body["reply"], "empty reply from the agent"
        return body

    turn = check("agent turn", run_turn)
    print(f"   reasoning: {len(turn['reasoning'])} chars")
    print(f"   reply: {turn['reply'][:120]}")

    check(
        "thread replay",
        lambda: request("/threads/smoke-test")["messages"] or _fail("no checkpointed messages"),
    )
    print("\nAll checks passed.")


def _fail(message):
    raise AssertionError(message)


if __name__ == "__main__":
    main()
