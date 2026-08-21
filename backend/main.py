"""FastAPI application: control-plane API for the AI employee platform."""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

from agent.graph import compile_agent, create_checkpointer, run_turn, stream_events
from agent.llm import LLMNotConfigured
from agent.memory import user_message
from config import get_settings
from mcp_registry.auth import MockOAuthMiddleware
from mcp_registry.server import router as mcp_router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpointer, closable = create_checkpointer()
    state["agent"] = compile_agent(checkpointer)
    state["closable"] = closable

    if get_settings().database_url:
        try:
            from rag.db import init_db

            init_db()
        except Exception:  # the agent still works without the knowledge base
            log.exception("Knowledge-base schema setup failed; RAG endpoints will error")
    try:
        yield
    finally:
        if closable is not None:
            closable.close()


app = FastAPI(title="AI Employee as a Service", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(MockOAuthMiddleware)
app.include_router(mcp_router)


class AgentRequest(BaseModel):
    thread_id: str = Field(..., description="Conversation key; state is checkpointed per thread.")
    message: str
    persona_block: str = "You are a helpful AI employee."
    human_block: str = "No specific details known about the user."


class IngestRequest(BaseModel):
    tenant_id: str
    text: str
    kb_name: str = "default"
    kb_id: str | None = None
    contextualise: bool = True


class SearchRequest(BaseModel):
    tenant_id: str
    kb_id: str
    query: str
    top_k: int = 5


def _agent():
    agent = state.get("agent")
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent runtime is not initialised.")
    return agent


def _turn_input(req: AgentRequest) -> tuple[dict, dict]:
    payload = {
        "messages": [user_message(req.message)],
        "persona_block": req.persona_block,
        "human_block": req.human_block,
    }
    return payload, {"configurable": {"thread_id": req.thread_id}}


@app.get("/health")
def health():
    settings = get_settings()
    return {
        "status": "ok",
        "model": settings.model,
        "llm_configured": bool(settings.nvidia_api_key),
        "persistence": "postgres" if settings.database_url else "memory",
        "cache": "redis" if settings.redis_url else "disabled",
    }


@app.post("/run_task")
def run_task(req: AgentRequest):
    """Run one turn and return the complete result."""
    payload, config = _turn_input(req)
    try:
        result = run_turn(_agent(), payload, config)
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("run_task failed")
        raise HTTPException(status_code=502, detail=f"Agent run failed: {exc}") from exc

    messages = result.get("messages", [])
    return {
        "status": "success",
        "thread_id": req.thread_id,
        "messages": messages,
        "reply": messages[-1]["content"] if messages else "",
        "reasoning": result.get("current_reasoning", ""),
    }


@app.post("/run_task/stream")
async def run_task_stream(req: AgentRequest):
    """Run one turn, streaming reasoning and answer tokens as SSE."""
    payload, config = _turn_input(req)

    def events():
        try:
            for chunk in stream_events(_agent(), payload, config):
                yield f"data: {json.dumps(chunk)}\n\n"
        except LLMNotConfigured as exc:
            yield f"data: {json.dumps({'type': 'error', 'delta': str(exc)})}\n\n"
        except Exception as exc:  # surfaced in-band: the response already started
            log.exception("run_task/stream failed")
            yield f"data: {json.dumps({'type': 'error', 'delta': str(exc)})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        iterate_in_threadpool(events()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/threads/{thread_id}")
def get_thread(thread_id: str):
    """Replay a thread's checkpointed state."""
    snapshot = _agent().get_state({"configurable": {"thread_id": thread_id}})
    values = snapshot.values or {}
    return {
        "thread_id": thread_id,
        "messages": values.get("messages", []),
        "persona_block": values.get("persona_block"),
        "human_block": values.get("human_block"),
    }


@app.post("/knowledge/ingest")
def ingest(req: IngestRequest):
    from rag.ingestion import ingest_document

    try:
        return ingest_document(
            tenant_id=req.tenant_id,
            text=req.text,
            kb_name=req.kb_name,
            kb_id=req.kb_id,
            contextualise=req.contextualise,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/knowledge/search")
def knowledge_search(req: SearchRequest):
    from rag.retrieval import search

    try:
        return {"results": search(req.tenant_id, req.kb_id, req.query, req.top_k)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
