"""Contextual-retrieval ingestion pipeline.

Each chunk is embedded together with a short, LLM-written description of where
it sits in the parent document, which stops isolated chunks from losing the
subject they refer to ("the company" -> "Acme's 2025 filing").
"""

import logging
from functools import lru_cache

from agent.llm import call_nemotron
from config import get_settings

from .db import DocumentChunk, KnowledgeBase, new_id, session

log = logging.getLogger(__name__)

CONTEXT_PROMPT = """<document>
{document}
</document>
Here is the chunk we want to situate within the whole document:
<chunk>
{chunk}
</chunk>
Give a short succinct context to situate this chunk within the overall document \
for the purposes of improving search retrieval. Answer only with the context and nothing else."""


@lru_cache
def get_embedder():
    """Load the sentence-transformer lazily: it costs ~90MB and several seconds."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embedding_model)


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Split on paragraph boundaries, packing up to `max_chars` per chunk."""
    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), max_chars - overlap):
                chunks.append(paragraph[start : start + max_chars])
            continue
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def generate_context(document: str, chunk: str) -> str:
    """Ask the model to situate a chunk. Falls back to no context on failure."""
    try:
        _, context = call_nemotron(CONTEXT_PROMPT.format(document=document[:12000], chunk=chunk))
        return context.strip()
    except Exception as exc:
        log.warning("Contextualisation failed, storing chunk without context: %s", exc)
        return ""


def ingest_document(
    tenant_id: str,
    text: str,
    kb_name: str = "default",
    kb_id: str | None = None,
    contextualise: bool = True,
) -> dict:
    """Chunk, contextualise, embed and store a document. Returns a summary dict."""
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Document is empty.")

    db = session()
    try:
        if kb_id:
            kb = db.query(KnowledgeBase).filter_by(id=kb_id, tenant_id=tenant_id).one_or_none()
            if kb is None:
                raise ValueError(f"Knowledge base {kb_id} not found for this tenant.")
        else:
            kb = KnowledgeBase(id=new_id(), tenant_id=tenant_id, name=kb_name)
            db.add(kb)
            db.flush()

        start = db.query(DocumentChunk).filter_by(kb_id=kb.id).count()
        embedder = get_embedder()

        for offset, chunk in enumerate(chunks):
            context = generate_context(text, chunk) if contextualise else ""
            enriched = f"{context}\n\n{chunk}" if context else chunk
            db.add(
                DocumentChunk(
                    id=new_id(),
                    kb_id=kb.id,
                    position=start + offset,
                    content=chunk,
                    context=context or None,
                    embedding=embedder.encode(enriched).tolist(),
                )
            )

        db.commit()
        return {"kb_id": kb.id, "kb_name": kb.name, "chunks_ingested": len(chunks)}
    finally:
        db.close()
