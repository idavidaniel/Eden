# AI Employee as a Service (EaaS)

A multi-tenant platform for building "AI employees": agents with a persona, a
private knowledge base, persistent memory and a registry of tools they can call.
This repository is the working prototype of the architecture described in
[project-document.txt](project-document.txt).

```
┌────────────┐   /api/backend/*   ┌──────────────┐   OpenAI-compatible   ┌──────────┐
│  Next.js   │ ─────────────────▶ │   FastAPI    │ ────────────────────▶ │ Nemotron │
│ dashboard  │ ◀───  SSE  ─────── │ + LangGraph  │                       │ (NVIDIA) │
└────────────┘                    └──────┬───────┘                       └──────────┘
                                         │
                          ┌──────────────┴──────────────┐
                          ▼                             ▼
                 Postgres + pgvector               Redis cache
              (checkpoints, knowledge base)     (LLM responses)
```

## What works today

| Capability | Status | Where |
| --- | --- | --- |
| Agent turn over Nemotron with visible reasoning | Working | [backend/agent/llm.py](backend/agent/llm.py) |
| Token-by-token streaming to the dashboard (SSE) | Working | [backend/main.py](backend/main.py), [frontend/src/lib/api.ts](frontend/src/lib/api.ts) |
| Core memory blocks (persona / human) kept out of the transcript | Working | [backend/agent/memory.py](backend/agent/memory.py) |
| Per-thread state persisted in Postgres | Working | [backend/agent/graph.py](backend/agent/graph.py) |
| Contextual-retrieval ingestion + hybrid search with reranking | Working | [backend/rag/](backend/rag) |
| MCP tool registry (JSON-RPC 2.0, stateless) | Working | [backend/mcp_registry/](backend/mcp_registry) |
| LLM response cache | Working, exact-match only (not semantic) | [backend/agent/cache.py](backend/agent/cache.py) |
| MCP authorization | Mock — checks the header and bearer token, does not verify signatures | [backend/mcp_registry/auth.py](backend/mcp_registry/auth.py) |
| Tenant isolation | Enforced in queries, no row-level security or auth on the app API yet | — |
| The agent calling its own MCP tools | Not implemented — tools are exposed, the graph does not invoke them | — |
| Durable execution (Temporal), billing, prompt compression | Not implemented | — |

## Quick start

```bash
cp .env.example .env   # add your NVIDIA_API_KEY (https://build.nvidia.com)
docker compose up --build
```

- Dashboard: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

The first backend build downloads PyTorch and takes several minutes; the first
knowledge-base call downloads the embedding and reranker models into the
`model_cache` volume.

Smoke-test the running stack:

```bash
python3 scripts/smoke_test.py
```

## Running without Docker

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn main:app --reload            # DATABASE_URL unset -> in-memory checkpoints
```

```bash
cd frontend
npm install
npm run dev                          # proxies to http://localhost:8000 by default
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness plus which backing services are configured |
| `POST` | `/run_task` | Run one turn, return reasoning + reply |
| `POST` | `/run_task/stream` | Same, streamed as SSE (`reasoning` / `content` / `done`) |
| `GET` | `/threads/{id}` | Replay a thread's checkpointed transcript |
| `POST` | `/knowledge/ingest` | Chunk, contextualise, embed and store a document |
| `POST` | `/knowledge/search` | Hybrid search + cross-encoder rerank |
| `POST` | `/mcp` | JSON-RPC 2.0: `initialize`, `ping`, `tools/list`, `tools/call` |

`/mcp` requires two headers:

```bash
curl -s localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Mcp-Protocol-Version: 2026-07-28' \
  -H 'Authorization: Bearer dev-token' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Tests

```bash
cd backend && pip install -r requirements-dev.txt && pytest
```

The suite stubs the model provider, so it needs no API key, database or Redis.
Frontend checks: `npm run lint && npm run build`.

## Configuration

All settings come from the environment; see [backend/config.py](backend/config.py).

| Variable | Default | Notes |
| --- | --- | --- |
| `NVIDIA_API_KEY` | — | Required for real model calls |
| `MODEL` | `nvidia/nemotron-3.5-lightning-30b-a3b` | Any OpenAI-compatible NVIDIA model |
| `DATABASE_URL` | unset | Unset = in-memory checkpoints, no knowledge base |
| `REDIS_URL` | unset | Unset = caching disabled |
| `REQUIRE_MCP_AUTH` | `true` | Set `false` to open `/mcp` for local experiments |
| `API_URL` (frontend) | `http://localhost:8000` | Server-side only; the browser uses `/api/backend/*` |

## Repository layout

```
backend/
  config.py            environment-driven settings
  main.py              FastAPI app: agent, knowledge and MCP routes
  agent/               LangGraph runtime, core memory, LLM client, cache
  rag/                 pgvector schema, ingestion, hybrid retrieval
  mcp_registry/        MCP server, tool registry, authorization middleware
  tests/               pytest suite (no external services required)
frontend/
  src/app/             App Router pages and the /api/backend proxy
  src/components/      dashboard UI
  src/lib/api.ts       typed client incl. SSE parsing
scripts/smoke_test.py  end-to-end check against a running stack
```
