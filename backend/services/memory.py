"""Reading and writing what an employee knows.

The model here takes 400k tokens of context, so this is not a compression scheme
— we could stuff everything in. It is a curation scheme: choosing the ~24k tokens
that make the next turn better, and refusing to store lessons drawn from work
that was never proven to work.
"""

import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models import Employee, Memory, MemoryBlock
from models.memory import BLOCK_LABELS, BLOCK_LIMITS, MEMORY_KINDS, MEMORY_SCOPES

from . import embeddings

log = logging.getLogger(__name__)

# Above this, two memories are the same thing said twice.
MERGE_SIMILARITY = 0.92
# Between this and MERGE_SIMILARITY, they are about the same thing and may disagree.
CONTRADICTION_SIMILARITY = 0.75

# A rejection teaches more than a success, so it survives ranking more easily.
OUTCOME_WEIGHT = {
    "rejected": 1.35,
    "reopened": 1.25,
    "abandoned": 1.1,
    "shipped": 1.0,
    "neutral": 0.95,
}
HALF_LIFE_DAYS = 45.0
DEFAULT_DECAY_DAYS = 90
# Promotion to company-wide memory needs corroboration from more than one agent.
PROMOTION_USES = 3
PROMOTION_DISTINCT_AGENTS = 2

_WORD = re.compile(r"[a-z0-9_]+")
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "when", "then",
    "you", "your", "are", "was", "were", "has", "have", "had", "not", "but",
    "its", "it's", "our", "their", "they", "them", "will", "would", "should",
    "can", "could", "use", "used", "using", "make", "made", "does", "did",
}  # fmt: skip


@dataclass
class Hit:
    memory: Memory
    score: float
    similarity: float


# --------------------------------------------------------------------------
# core blocks
# --------------------------------------------------------------------------


def default_block_content(employee: Employee, label: str) -> str:
    if label == "persona":
        return employee.persona or ""
    if label == "company":
        company = employee.company
        parts = [f"{company.name}"]
        if company.industry:
            parts.append(f"Industry: {company.industry}")
        if company.mission:
            parts.append(f"Mission: {company.mission}")
        return "\n".join(parts)
    if label == "focus":
        return "Nothing in progress."
    return "Nothing recorded about the person I work for yet."


def blocks_for(db: Session, employee: Employee) -> list[MemoryBlock]:
    """The four always-in-context blocks, created on first read."""
    existing = {
        block.label: block
        for block in db.scalars(
            select(MemoryBlock).where(MemoryBlock.employee_id == employee.id)
        )
    }
    created = False
    for label in BLOCK_LABELS:
        if label in existing:
            continue
        block = MemoryBlock(
            employee_id=employee.id,
            label=label,
            content=default_block_content(employee, label),
            char_limit=BLOCK_LIMITS.get(label, 2000),
            updated_by="System",
        )
        db.add(block)
        existing[label] = block
        created = True
    if created:
        db.flush()
    return [existing[label] for label in BLOCK_LABELS]


def set_block(
    db: Session, employee: Employee, label: str, content: str, updated_by: str = "You"
) -> MemoryBlock:
    if label not in BLOCK_LABELS:
        raise ValueError(f"Unknown memory block '{label}'. Use one of: {', '.join(BLOCK_LABELS)}")
    blocks = {block.label: block for block in blocks_for(db, employee)}
    block = blocks[label]
    if block.pinned and updated_by != "You":
        raise PermissionError(f"The {label} block is pinned; only you can change it.")
    limit = block.char_limit or BLOCK_LIMITS.get(label, 2000)
    block.content = content[:limit]
    block.version += 1
    block.updated_by = updated_by[:120]
    db.add(block)
    db.flush()
    return block


def blocks_text(db: Session, employee: Employee) -> str:
    lines = []
    for block in blocks_for(db, employee):
        if block.content.strip():
            lines.append(f"[{block.label}]\n{block.content.strip()}")
    return "\n\n".join(lines)


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


def _text_of(title: str, body: str) -> str:
    return f"{title}\n{body}".strip()


def remember(
    db: Session,
    *,
    company_id: str,
    kind: str,
    title: str,
    body: str = "",
    employee_id: str | None = None,
    scope: str = "private",
    source_kind: str | None = None,
    source_id: str | None = None,
    outcome: str = "neutral",
    confidence: float = 0.6,
    tags: list[str] | None = None,
    created_by: str = "System",
    embedding: list[float] | None = None,
) -> tuple[Memory, str]:
    """Store one memory, merging it into an existing one when they say the same thing.

    Returns the row and what happened: created | merged | superseded.
    """
    if kind not in MEMORY_KINDS:
        raise ValueError(f"Unknown memory kind '{kind}'. Use one of: {', '.join(MEMORY_KINDS)}")
    if scope not in MEMORY_SCOPES:
        raise ValueError(f"Unknown scope '{scope}'.")

    text = _text_of(title, body)
    if embedding is None:
        vectors = embeddings.embed_passages([text])
        embedding = vectors[0] if vectors else None

    twin, similarity = _closest_existing(
        db, company_id=company_id, employee_id=employee_id, kind=kind, text=text,
        embedding=embedding,
    )

    if twin is not None and similarity >= MERGE_SIMILARITY:
        twin.uses += 1
        twin.confidence = max(twin.confidence, confidence)
        twin.last_used_at = datetime.now(UTC)
        twin.decay_at = datetime.now(UTC) + timedelta(days=DEFAULT_DECAY_DAYS)
        if len(body) > len(twin.body):
            twin.body = body
        twin.tags = sorted(set(twin.tags or []) | set(tags or []))
        db.add(twin)
        db.flush()
        return twin, "merged"

    memory = Memory(
        company_id=company_id,
        employee_id=employee_id,
        kind=kind,
        scope=scope,
        title=title[:240],
        body=body,
        embedding=embedding,
        source_kind=source_kind,
        source_id=source_id,
        outcome=outcome,
        confidence=max(0.0, min(1.0, confidence)),
        tags=tags or [],
        created_by=created_by[:120],
        decay_at=datetime.now(UTC) + timedelta(days=DEFAULT_DECAY_DAYS),
    )
    db.add(memory)
    db.flush()

    if twin is not None and similarity >= CONTRADICTION_SIMILARITY:
        # Close enough to be about the same thing, far enough to disagree. Keep
        # both — the old one is still evidence of what was believed and when.
        twin.superseded_by = memory.id
        db.add(twin)
        db.flush()
        return memory, "superseded"

    return memory, "created"


def _closest_existing(
    db: Session,
    *,
    company_id: str,
    employee_id: str | None,
    kind: str,
    text: str,
    embedding: list[float] | None,
) -> tuple[Memory | None, float]:
    candidates = list(
        db.scalars(
            select(Memory).where(
                Memory.company_id == company_id,
                Memory.kind == kind,
                Memory.archived_at.is_(None),
                Memory.superseded_by.is_(None),
                Memory.employee_id == employee_id
                if employee_id
                else Memory.employee_id.is_(None),
            )
        )
    )
    best, best_similarity = None, 0.0
    for candidate in candidates:
        if embedding and candidate.embedding:
            similarity = embeddings.cosine(embedding, candidate.embedding)
        else:
            similarity = _lexical_similarity(text, _text_of(candidate.title, candidate.body))
        if similarity > best_similarity:
            best, best_similarity = candidate, similarity
    return best, best_similarity


def forget(db: Session, memory: Memory, by: str = "You") -> Memory:
    """Archive rather than delete: what an agent used to believe is evidence."""
    memory.archived_at = datetime.now(UTC)
    memory.created_by = memory.created_by or by
    db.add(memory)
    db.flush()
    return memory


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------


def tokenise(text: str) -> set[str]:
    return {
        word for word in _WORD.findall(text.lower()) if len(word) > 2 and word not in _STOPWORDS
    }


def _lexical_similarity(a: str, b: str) -> float:
    """Jaccard over content words. The honest fallback when there is no embedder."""
    left, right = tokenise(a), tokenise(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _recency_weight(memory: Memory) -> float:
    when = memory.last_used_at or memory.created_at
    if not when:
        return 0.6
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    age_days = max(0.0, (datetime.now(UTC) - when).total_seconds() / 86400)
    return 0.5 + 0.5 * math.exp(-age_days / HALF_LIFE_DAYS)


def search(
    db: Session,
    company_id: str,
    query: str,
    *,
    employee_id: str | None = None,
    kinds: list[str] | None = None,
    limit: int = 8,
    include_company: bool = True,
    min_score: float = 0.0,
) -> tuple[list[Hit], str]:
    """Rank memories for one prompt. Returns the hits and which mode was used.

    Score is `similarity × confidence × recency × outcome_weight`. Similarity is
    cosine when the embedder is available and the rows have vectors, and a word
    overlap otherwise — the caller is told which, and so is the reader.
    """
    visible = [Memory.company_id == company_id, Memory.archived_at.is_(None)]
    if employee_id and include_company:
        visible.append(
            or_(Memory.employee_id == employee_id, Memory.employee_id.is_(None))
        )
    elif employee_id:
        visible.append(Memory.employee_id == employee_id)
    if kinds:
        visible.append(Memory.kind.in_(kinds))

    rows = list(db.scalars(select(Memory).where(*visible)))
    if not rows:
        return [], "empty"

    query_vector = embeddings.embed_query(query) if query.strip() else None
    mode = "vector" if query_vector and any(row.embedding for row in rows) else "lexical"

    hits: list[Hit] = []
    for row in rows:
        if mode == "vector" and row.embedding:
            similarity = embeddings.cosine(query_vector, row.embedding)
        else:
            similarity = _lexical_similarity(query, _text_of(row.title, row.body))
        if similarity <= 0:
            continue
        score = (
            similarity
            * max(0.05, row.confidence)
            * _recency_weight(row)
            * OUTCOME_WEIGHT.get(row.outcome, 1.0)
        )
        # A superseded memory is still findable, but it should lose to its replacement.
        if row.superseded_by:
            score *= 0.35
        if score >= min_score:
            hits.append(Hit(memory=row, score=score, similarity=similarity))

    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:limit], mode


def note_use(db: Session, memories: list[Memory], employee_id: str | None) -> None:
    """Record that these memories were actually retrieved into a turn."""
    now = datetime.now(UTC)
    for memory in memories:
        memory.uses += 1
        memory.last_used_at = now
        memory.decay_at = now + timedelta(days=DEFAULT_DECAY_DAYS)
        if employee_id:
            memory.used_by = sorted(set(memory.used_by or []) | {employee_id})
        db.add(memory)
    if memories:
        db.flush()


# --------------------------------------------------------------------------
# promotion and forgetting
# --------------------------------------------------------------------------


def promotable(db: Session, company_id: str) -> list[Memory]:
    """Private memories that more than one agent has leaned on and been right."""
    rows = db.scalars(
        select(Memory).where(
            Memory.company_id == company_id,
            Memory.scope == "private",
            Memory.archived_at.is_(None),
            Memory.superseded_by.is_(None),
        )
    )
    return [
        row
        for row in rows
        if row.uses >= PROMOTION_USES and len(row.used_by or []) >= PROMOTION_DISTINCT_AGENTS
    ]


def promote(db: Session, memory: Memory, to: str = "company", by: str = "You") -> Memory:
    if to not in MEMORY_SCOPES:
        raise ValueError(f"Unknown scope '{to}'.")
    memory.scope = to
    if to == "company":
        # Company memory belongs to the company, not to whoever learned it first.
        memory.employee_id = None
    memory.confidence = min(1.0, memory.confidence + 0.1)
    memory.created_by = f"{memory.created_by} → promoted by {by}"[:120]
    db.add(memory)
    db.flush()
    return memory


def archive_stale(db: Session, company_id: str, now: datetime | None = None) -> int:
    """Retire memories nothing has retrieved and nothing is confident about."""
    now = now or datetime.now(UTC)
    rows = db.scalars(
        select(Memory).where(
            Memory.company_id == company_id,
            Memory.archived_at.is_(None),
            Memory.uses == 0,
            Memory.confidence < 0.7,
            Memory.decay_at.is_not(None),
            Memory.decay_at < now,
        )
    )
    count = 0
    for row in rows:
        row.archived_at = now
        db.add(row)
        count += 1
    if count:
        db.flush()
    return count


def backfill_embeddings(db: Session, company_id: str, limit: int = 200) -> int:
    """Vectorise memories written while the embedder was unavailable."""
    if not embeddings.available():
        return 0
    rows = list(
        db.scalars(
            select(Memory)
            .where(Memory.company_id == company_id, Memory.embedding.is_(None))
            .limit(limit)
        )
    )
    if not rows:
        return 0
    vectors = embeddings.embed_passages([_text_of(row.title, row.body) for row in rows])
    if not vectors:
        return 0
    for row, vector in zip(rows, vectors, strict=True):
        row.embedding = vector
        db.add(row)
    db.flush()
    return len(rows)
