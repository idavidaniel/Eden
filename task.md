# Roadmap

Status of the platform against the blueprint in `project-document.txt`.
See the table in [README.md](README.md) for what each item means in practice.

## Done

- [x] Workspace skills (`.agents/skills/nemotron_api`, `.agents/skills/langgraph_memory`)
- [x] Dockerised stack: Postgres + pgvector, Redis, FastAPI backend, Next.js frontend,
      with healthchecks and ordered startup
- [x] Agent runtime: LangGraph `StateGraph` over Nemotron, reasoning kept separate
      from the answer
- [x] Core memory blocks (persona / human) rendered into the system prompt each turn
- [x] Per-thread checkpointing in Postgres, in-memory fallback when no database
- [x] Token streaming end to end (LangGraph custom stream → SSE → dashboard)
- [x] Contextual-retrieval ingestion and hybrid search (pgvector + BM25 + cross-encoder)
- [x] MCP server: JSON-RPC 2.0 `initialize` / `ping` / `tools/list` / `tools/call`
- [x] Test suite that runs without external services, plus CI

## Next

- [ ] Let the agent actually call its MCP tools (tool-calling loop in the graph)
- [ ] Real authorization: verify OAuth 2.1 JWTs against the IdP's JWKS, and put
      auth on the app API, not just `/mcp`
- [ ] Tenant isolation at the database level (Postgres row-level security)
- [ ] Semantic cache (embed the prompt, vector-search cached entries) — today the
      cache only hits on an exact prompt match
- [ ] Async task execution: queue long-running jobs instead of holding the request
      open, with retries and step-level observability (Temporal in the blueprint)
- [ ] Knowledge-base management UI: upload documents, browse chunks, inspect retrieval
- [ ] Prompt compression for long-context turns (LLMLingua)
- [ ] Usage metering and billing hooks
