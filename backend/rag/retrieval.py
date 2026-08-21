"""Hybrid retrieval: dense (pgvector) + sparse (BM25), reranked by a cross-encoder."""

from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

from config import get_settings

from .db import DocumentChunk, KnowledgeBase, session
from .ingestion import get_embedder


@lru_cache
def get_reranker():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(get_settings().reranker_model)


def search(
    tenant_id: str, kb_id: str, query: str, top_k: int = 5, candidates: int = 20
) -> list[dict]:
    """Return the `top_k` most relevant chunks for a query, highest score first."""
    db = session()
    try:
        kb = db.query(KnowledgeBase).filter_by(id=kb_id, tenant_id=tenant_id).one_or_none()
        if kb is None:
            raise ValueError(f"Knowledge base {kb_id} not found for this tenant.")

        query_embedding = get_embedder().encode(query).tolist()
        dense = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.kb_id == kb_id)
            .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
            .limit(candidates)
            .all()
        )

        # BM25 over the whole KB. Fine for a prototype-sized corpus; move to a
        # Postgres tsvector index once a KB outgrows memory.
        all_chunks = db.query(DocumentChunk).filter(DocumentChunk.kb_id == kb_id).all()
        if not all_chunks:
            return []

        bm25 = BM25Okapi([c.content.lower().split() for c in all_chunks])
        scores = bm25.get_scores(query.lower().split())
        sparse = [all_chunks[i] for i in np.argsort(scores)[::-1][:candidates]]

        merged = {c.id: c for c in dense}
        merged.update({c.id: c for c in sparse})
        merged_chunks = list(merged.values())

        pairs = [
            [query, f"{c.context}\n\n{c.content}" if c.context else c.content]
            for c in merged_chunks
        ]
        rerank_scores = get_reranker().predict(pairs)

        ranked = sorted(
            zip(rerank_scores, merged_chunks, strict=True),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [
            {
                "id": chunk.id,
                "score": float(score),
                "content": chunk.content,
                "context": chunk.context,
                "position": chunk.position,
            }
            for score, chunk in ranked[:top_k]
        ]
    finally:
        db.close()
