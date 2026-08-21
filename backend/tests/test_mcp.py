import pytest

HEADERS = {"Mcp-Protocol-Version": "2026-07-28", "Authorization": "Bearer test-token"}


def rpc(client, method, params=None, headers=HEADERS, req_id=1):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}},
        headers=headers,
    )


def test_missing_protocol_version_is_rejected(client):
    response = rpc(client, "tools/list", headers={"Authorization": "Bearer t"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600


def test_missing_token_returns_401_with_challenge(client):
    response = rpc(client, "tools/list", headers={"Mcp-Protocol-Version": "2026-07-28"})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer realm=\"mcp\"")


def test_initialize_advertises_protocol_and_capabilities(client):
    result = rpc(client, "initialize").json()["result"]
    assert result["protocolVersion"] == "2026-07-28"
    assert "tools" in result["capabilities"]


def test_tools_list_exposes_schemas(client):
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {"send_email", "search_knowledge_base"} <= names
    for tool in tools:
        assert tool["inputSchema"]["type"] == "object"


def test_tools_call_executes_handler(client):
    result = rpc(
        client,
        "tools/call",
        {"name": "send_email", "arguments": {"to": "a@b.com", "body": "hi"}},
    ).json()["result"]
    assert result["isError"] is False
    assert "a@b.com" in result["content"][0]["text"]


def test_tool_error_is_reported_in_band(client):
    result = rpc(client, "tools/call", {"name": "send_email", "arguments": {}}).json()["result"]
    assert result["isError"] is True


def test_unknown_tool_and_method(client):
    assert rpc(client, "tools/call", {"name": "nope"}).json()["error"]["code"] == -32601
    assert rpc(client, "does/not/exist").json()["error"]["code"] == -32601


@pytest.mark.parametrize("req_id", [1, "abc"])
def test_request_id_is_echoed(client, req_id):
    assert rpc(client, "ping", req_id=req_id).json()["id"] == req_id
