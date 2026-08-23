"""Grading by an independent evaluator — with the evaluator itself checked.

A model grading a model is the soft spot in every "AI verifies AI" scheme, so
this kind is built with four hard mechanisms rather than a promise:

1. The evaluator never sees who wrote the work or what they said about it.
2. The rubric is declared before the work starts, so it cannot be written to fit
   the output.
3. Each verdict must carry an `evidence_quote`, and the platform checks that the
   quote appears *verbatim* in the artifact. A criterion whose quote is not
   there is recorded as an error, never a pass. That catches a hallucinating
   evaluator mechanically, without a second model.
4. Several evaluators vote. Agreement is recorded; a split escalates to a human
   instead of being averaged into a pass.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from models import Check

from .base import CheckContext, Verdict, error, needs_artifact

log = logging.getLogger(__name__)

DEFAULT_EVALUATORS = 3
MAX_EVALUATORS = 5
# Below this share of evaluators agreeing, nobody gets to call it a pass.
AGREEMENT_THRESHOLD = 0.67
WHITESPACE = re.compile(r"\s+")

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion_id": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["pass", "fail"]},
                    "evidence_quote": {
                        "type": "string",
                        "description": (
                            "A span copied EXACTLY from the document that justifies the "
                            "verdict. It is checked character by character against the "
                            "document, so paraphrasing fails."
                        ),
                    },
                    "reason": {"type": "string", "description": "One sentence."},
                },
                "required": ["criterion_id", "verdict", "evidence_quote", "reason"],
            },
        }
    },
    "required": ["criteria"],
}


def normalise(text: str) -> str:
    return WHITESPACE.sub(" ", text.lower().replace("’", "'")).strip()


def run(check: Check, ctx: CheckContext) -> Verdict:
    missing_artifact = needs_artifact(check, ctx)
    if missing_artifact:
        return missing_artifact

    spec = check.spec or {}
    criteria = spec.get("criteria") or []
    if not criteria:
        return error(f"{check.name}: the rubric has no criteria, so there is nothing to grade.")

    count = max(1, min(int(spec.get("evaluators", DEFAULT_EVALUATORS)), MAX_EVALUATORS))
    models = spec.get("models") or [None] * count
    models = (models * count)[:count]

    document = ctx.content
    prompt = _prompt(criteria, document, spec.get("context", ""))

    ballots = _collect_ballots(prompt, models, criteria, document)
    usable = [ballot for ballot in ballots if ballot["ok"]]
    if not usable:
        detail = ballots[0]["error"] if ballots else "no evaluator answered"
        return error(f"{check.name}: could not grade it — {detail}")

    per_criterion = _tally(criteria, usable)
    failing = [row for row in per_criterion if row["verdict"] == "fail"]
    unresolved = [row for row in per_criterion if row["verdict"] == "unresolved"]
    score = sum(1 for row in per_criterion if row["verdict"] == "pass") / len(per_criterion)
    agreement = sum(row["agreement"] for row in per_criterion) / len(per_criterion)

    evidence = {
        "content_hash": ctx.artifact.content_hash,
        "evaluators": len(usable),
        "requested_evaluators": count,
        "agreement": round(agreement, 3),
        "criteria": per_criterion,
        "quote_failures": sum(row["quote_failures"] for row in per_criterion),
    }

    if unresolved:
        names = ", ".join(row["criterion_id"] for row in unresolved)
        return Verdict(
            status="pending",
            score=round(score, 3),
            detail=(
                f"{check.name}: evaluators disagree on {names}. "
                "A split verdict is not a pass — this needs a person."
            ),
            evidence={**evidence, "needs_human": True},
        )
    if failing:
        reasons = "; ".join(f"{row['criterion_id']}: {row['reason']}" for row in failing[:4])
        return Verdict(
            status="fail",
            score=round(score, 3),
            detail=f"{check.name}: {reasons}",
            evidence=evidence,
        )
    return Verdict(
        status="pass",
        score=round(score, 3),
        detail=(
            f"{check.name}: {len(per_criterion)} criteria met, "
            f"{len(usable)} evaluators agreeing {agreement:.0%}."
        ),
        evidence=evidence,
    )


def _prompt(criteria: list[dict], document: str, context: str) -> list[dict]:
    lines = "\n".join(
        f"- {item.get('id', index)}: {item.get('question', '')}"
        for index, item in enumerate(criteria)
    )
    system = (
        "You grade a document against a fixed rubric. You do not know who wrote it "
        "and you will not be told. Judge only what is in the document.\n\n"
        "For every criterion, quote a span copied EXACTLY from the document — "
        "character for character — that justifies your verdict. The quote is "
        "checked against the document automatically. If you cannot find a real "
        "span that supports a pass, the verdict is fail; quote the part that is "
        "closest and say what is missing. Never invent a quote."
    )
    user = f"""Rubric:
{lines}

{f"Context for the rubric: {context}" if context else ""}

Document:
---
{document[:60000]}
---

Return one entry per criterion."""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _collect_ballots(
    prompt: list[dict], models: list[str | None], criteria: list[dict], document: str
) -> list[dict]:
    """Ask each evaluator in parallel; a slow panel is a panel nobody runs."""
    from agents.llm import structured_call

    def ask(model: str | None) -> dict:
        try:
            answer = structured_call(
                prompt,
                name="submit_rubric_verdicts",
                description="Grade the document against every rubric criterion.",
                parameters=VERDICT_SCHEMA,
                model=model,
                max_tokens=2000,
            )
            return {"ok": True, "model": model, "criteria": answer.get("criteria", [])}
        except Exception as exc:  # one evaluator failing must not sink the panel
            log.warning("rubric evaluator failed: %s", exc)
            return {"ok": False, "model": model, "error": str(exc)[:200], "criteria": []}

    with ThreadPoolExecutor(max_workers=min(len(models), 5)) as pool:
        ballots = list(pool.map(ask, models))

    known = {str(item.get("id", index)) for index, item in enumerate(criteria)}
    haystack = normalise(document)
    for ballot in ballots:
        for entry in ballot["criteria"]:
            entry["criterion_id"] = str(entry.get("criterion_id", ""))
            quote = (entry.get("evidence_quote") or "").strip()
            entry["quote_found"] = bool(quote) and normalise(quote) in haystack
            entry["known_criterion"] = entry["criterion_id"] in known
    return ballots


def _tally(criteria: list[dict], ballots: list[dict]) -> list[dict]:
    """Majority per criterion, with unverifiable quotes discarded first."""
    rows = []
    for index, item in enumerate(criteria):
        criterion_id = str(item.get("id", index))
        entries = [
            entry
            for ballot in ballots
            for entry in ballot["criteria"]
            if entry["criterion_id"] == criterion_id
        ]
        quote_failures = sum(1 for entry in entries if not entry["quote_found"])
        # An evaluator that could not point at real text does not get a vote.
        votes = [entry for entry in entries if entry["quote_found"]]

        passes = sum(1 for entry in votes if entry.get("verdict") == "pass")
        fails = sum(1 for entry in votes if entry.get("verdict") == "fail")
        total = passes + fails

        if total == 0:
            verdict = "unresolved"
            agreement = 0.0
            reason = (
                "every evaluator's supporting quote was missing from the document"
                if quote_failures
                else "no evaluator returned a verdict"
            )
        else:
            agreement = max(passes, fails) / total
            if agreement < AGREEMENT_THRESHOLD:
                verdict = "unresolved"
            else:
                verdict = "pass" if passes > fails else "fail"
            reason = next(
                (
                    entry.get("reason", "")
                    for entry in votes
                    if entry.get("verdict") == ("pass" if verdict == "pass" else "fail")
                ),
                "",
            )

        rows.append(
            {
                "criterion_id": criterion_id,
                "question": item.get("question", ""),
                "verdict": verdict,
                "agreement": round(agreement, 3),
                "passes": passes,
                "fails": fails,
                "quote_failures": quote_failures,
                "reason": reason[:300],
                "quotes": [
                    entry.get("evidence_quote", "")[:200] for entry in votes if entry.get("reason")
                ][:3],
            }
        )
    return rows
