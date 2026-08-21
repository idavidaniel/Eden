def test_health_reports_configuration(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["persistence"] == "memory"
    assert body["cache"] == "disabled"


def test_run_task_returns_reasoning_and_reply(client):
    body = client.post(
        "/run_task",
        json={"thread_id": "t1", "message": "ping", "persona_block": "You are terse."},
    ).json()

    assert body["reply"] == "answer: PING"
    assert body["reasoning"] == "thinking about ping"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]


def test_thread_state_persists_across_turns(client):
    for message in ("first", "second"):
        client.post("/run_task", json={"thread_id": "t2", "message": message})

    messages = client.get("/threads/t2").json()["messages"]
    assert [m["content"] for m in messages] == [
        "first",
        "answer: FIRST",
        "second",
        "answer: SECOND",
    ]


def test_threads_are_isolated(client):
    client.post("/run_task", json={"thread_id": "a", "message": "hello"})
    assert client.get("/threads/b").json()["messages"] == []


def test_stream_emits_reasoning_then_content_then_done(client):
    response = client.post("/run_task/stream", json={"thread_id": "t3", "message": "ping"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    import json

    events = [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "reasoning"
    assert "content" in kinds
    assert kinds[-1] == "done"
    assert "".join(e["delta"] for e in events if e["type"] == "content") == "answer: PING"
