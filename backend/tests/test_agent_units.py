from agent.graph import build_prompt
from agent.memory import compile_system_prompt
from rag.ingestion import chunk_text


def test_system_prompt_contains_core_memory_blocks():
    prompt = compile_system_prompt(
        {"persona_block": "You are Ada.", "human_block": "Likes brevity."}
    )
    assert "You are Ada." in prompt
    assert "Likes brevity." in prompt


def test_system_prompt_has_defaults():
    assert "helpful AI employee" in compile_system_prompt({})


def test_build_prompt_puts_system_first_and_keeps_order():
    state = {
        "persona_block": "P",
        "human_block": "H",
        "messages": [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
        ],
    }
    prompt = build_prompt(state)
    assert prompt[0]["role"] == "system"
    assert [m["content"] for m in prompt[1:]] == ["one", "two"]


def test_chunk_text_splits_on_paragraphs_within_budget():
    text = "\n\n".join(f"paragraph {i} " + "x" * 100 for i in range(20))
    chunks = chunk_text(text, max_chars=300)
    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)
    assert "".join(chunks).count("paragraph") == 20


def test_chunk_text_splits_oversized_paragraph():
    chunks = chunk_text("y" * 1000, max_chars=200, overlap=0)
    assert len(chunks) == 5


def test_chunk_text_empty():
    assert chunk_text("   \n\n ") == []


def test_sqlalchemy_url_pins_psycopg3():
    from rag.db import _sqlalchemy_url

    assert _sqlalchemy_url("postgresql://u:p@db:5432/x") == "postgresql+psycopg://u:p@db:5432/x"
    assert _sqlalchemy_url("postgres://u:p@db/x").startswith("postgresql+psycopg://")
    assert _sqlalchemy_url("postgresql+psycopg://u@db/x") == "postgresql+psycopg://u@db/x"
