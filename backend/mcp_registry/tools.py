"""Tool registry exposed over MCP.

Each entry pairs a JSON Schema (what the model sees) with a handler (what runs).
Handlers are deliberately side-effect-free stubs; swap them for real
integrations as they are built.
"""

from collections.abc import Callable
from typing import Any

ToolHandler = Callable[[dict[str, Any]], str]


def _send_email(args: dict[str, Any]) -> str:
    to = args.get("to")
    if not to:
        raise ValueError("'to' is required")
    return f"[stub] Email queued to {to} (subject: {args.get('subject', 'n/a')})."


def _search_knowledge_base(args: dict[str, Any]) -> str:
    from rag.retrieval import search

    results = search(
        tenant_id=args["tenant_id"],
        kb_id=args["kb_id"],
        query=args["query"],
        top_k=int(args.get("top_k", 3)),
    )
    if not results:
        return "No matching passages."
    return "\n\n---\n\n".join(f"({r['score']:.2f}) {r['content']}" for r in results)


TOOLS: dict[str, dict[str, Any]] = {
    "send_email": {
        "definition": {
            "name": "send_email",
            "description": "Send an email on behalf of the AI employee.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient address"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "body"],
            },
        },
        "handler": _send_email,
    },
    "search_knowledge_base": {
        "definition": {
            "name": "search_knowledge_base",
            "description": "Hybrid search over a tenant's ingested documents.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "kb_id": {"type": "string"},
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 3},
                },
                "required": ["tenant_id", "kb_id", "query"],
            },
        },
        "handler": _search_knowledge_base,
    },
}


def list_definitions() -> list[dict]:
    return [tool["definition"] for tool in TOOLS.values()]


def call(name: str, arguments: dict[str, Any]) -> str:
    if name not in TOOLS:
        raise KeyError(name)
    return TOOLS[name]["handler"](arguments or {})
