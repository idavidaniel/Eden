"""Does every claim resolve to a source that actually says it?

The convention agents are taught: end a factual sentence with a marker.

    Revenue grew 14% in 2024. [src:a1b2c3 "revenue increased 14 per cent"]

The platform then does the one thing a model cannot fake: it opens the stored
text of that source and looks for the quote. A marker pointing at a source that
does not contain the quote fails, and so does a numeric claim with no marker at
all when the check is strict.
"""

import re

from sqlalchemy import select

from models import Check, Source

from .base import CheckContext, Verdict, needs_artifact

MARKER = re.compile(
    r"\[src:(?P<id>[A-Za-z0-9_-]{4,40})(?:\s+\"(?P<quote>[^\"]{5,400})\")?\]",
)
SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
# A sentence with a number, a percentage or a year in it is making a claim.
NUMERIC_CLAIM = re.compile(r"\b\d[\d,.]*\s?%|\b(?:19|20)\d{2}\b|\b\d[\d,.]{2,}\b")
WHITESPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Compare on words, not on curly quotes and line wrapping."""
    lowered = text.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    lowered = lowered.replace("—", " ").replace("–", " ").replace("-", " ")
    return WHITESPACE.sub(" ", re.sub(r"[^a-z0-9%'\s]", " ", lowered)).strip()


def run(check: Check, ctx: CheckContext) -> Verdict:
    missing_artifact = needs_artifact(check, ctx)
    if missing_artifact:
        return missing_artifact

    spec = check.spec or {}
    strict = bool(spec.get("require_all_numeric_claims", True))
    text = ctx.content

    sources = {
        row.id: row
        for row in ctx.db.scalars(select(Source).where(Source.company_id == ctx.company.id))
    }
    # Agents cite by a short prefix as often as by the full id.
    by_prefix = {row_id[:8]: row for row_id, row in sources.items()}

    resolved: list[dict] = []
    broken: list[dict] = []

    for match in MARKER.finditer(text):
        source_id = match.group("id")
        quote = (match.group("quote") or "").strip()
        source = sources.get(source_id) or by_prefix.get(source_id[:8])
        if not source:
            broken.append({"source_id": source_id, "problem": "no such source was ever fetched"})
            continue
        if not quote:
            broken.append(
                {
                    "source_id": source_id,
                    "url": source.url,
                    "problem": "cited without a quote, so nothing can be verified",
                }
            )
            continue
        body = _source_text(source)
        if not body:
            broken.append(
                {
                    "source_id": source_id,
                    "url": source.url,
                    "problem": "the stored copy of this source is missing",
                }
            )
            continue
        if normalise(quote) in normalise(body):
            resolved.append({"source_id": source.id, "url": source.url, "quote": quote[:200]})
        else:
            broken.append(
                {
                    "source_id": source.id,
                    "url": source.url,
                    "quote": quote[:200],
                    "problem": "that quote does not appear in the source",
                }
            )

    uncited = _uncited_claims(text) if strict else []

    evidence = {
        "content_hash": ctx.artifact.content_hash,
        "resolved": resolved[:40],
        "broken": broken[:40],
        "uncited_claims": uncited[:20],
        "counts": {
            "resolved": len(resolved),
            "broken": len(broken),
            "uncited": len(uncited),
        },
    }

    if broken or uncited:
        parts = []
        if broken:
            parts.append(f"{len(broken)} citation(s) do not check out")
        if uncited:
            parts.append(f"{len(uncited)} numeric claim(s) carry no source")
        return Verdict(
            status="fail", detail=f"{check.name}: " + "; ".join(parts), evidence=evidence
        )

    if not resolved:
        return Verdict(
            status="pass",
            detail=f"{check.name}: nothing in this document claims a source.",
            evidence=evidence,
        )
    return Verdict(
        status="pass",
        detail=f"{check.name}: {len(resolved)} citation(s) resolve to the text they quote.",
        evidence=evidence,
    )


def _source_text(source: Source) -> str:
    from services import blobs

    if not source.text_key:
        return ""
    try:
        return blobs.get_text(source.text_key)
    except FileNotFoundError:
        return ""


def _uncited_claims(text: str) -> list[str]:
    """Sentences that assert a number without pointing at anything."""
    body = _strip_code_and_tables(text)
    claims = []
    for match in SENTENCE.finditer(body):
        sentence = match.group(0).strip()
        if len(sentence) < 25 or sentence.startswith("#"):
            continue
        if MARKER.search(sentence):
            continue
        if NUMERIC_CLAIM.search(sentence):
            claims.append(sentence[:200])
    return claims


def _strip_code_and_tables(text: str) -> str:
    without_fences = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    return "\n".join(
        line for line in without_fences.splitlines() if not line.lstrip().startswith("|")
    )
