"""Structural assertions over a document: sections, patterns, arithmetic.

The point of this kind is that it decides without a model. "Does the contract
have a Limitation of Liability section?" and "do the line items sum to the
total?" are facts about the text, and a fact about the text is checkable.
"""

import re

from models import Check

from .base import CheckContext, Verdict, error, needs_artifact
from .expressions import ExpressionError, evaluate

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
# "1. TERM" / "ARTICLE 4 — TERMINATION" / "Term." as a line of its own.
LEGAL_HEADING = re.compile(
    r"^\s*(?:(?:article|section|clause)\s+)?(?:[0-9]+(?:\.[0-9]+)*[.)]?\s+)?"
    r"([A-Z][A-Za-z ,'/&-]{2,60})\s*[.:]?\s*$",
    re.MULTILINE | re.IGNORECASE,
)
DEFINED_TERM = re.compile(r'"([A-Z][A-Za-z0-9 ]{2,40})"')
CAPITALISED_USE = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){0,3})\b")
NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")


def _headings(text: str) -> list[str]:
    found = [match.group(2).strip() for match in HEADING.finditer(text)]
    found += [match.group(1).strip() for match in LEGAL_HEADING.finditer(text)]
    return found


def _has_section(text: str, wanted: str) -> bool:
    target = wanted.strip().lower()
    return any(target in heading.lower() for heading in _headings(text))


def run(check: Check, ctx: CheckContext) -> Verdict:
    missing_artifact = needs_artifact(check, ctx)
    if missing_artifact:
        return missing_artifact

    spec = check.spec or {}
    text = ctx.content
    problems: list[str] = []
    evidence: dict = {"content_hash": ctx.artifact.content_hash}

    wanted_sections = spec.get("must_contain_sections") or []
    if wanted_sections:
        missing = [name for name in wanted_sections if not _has_section(text, name)]
        evidence["sections_found"] = _headings(text)[:40]
        evidence["sections_missing"] = missing
        if missing:
            problems.append(f"missing section(s): {', '.join(missing)}")

    for pattern in spec.get("must_match") or []:
        if not re.search(pattern, text, re.IGNORECASE):
            problems.append(f"nothing matches /{pattern}/")

    banned_hits: list[str] = []
    for pattern in spec.get("must_not_match") or []:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            banned_hits.append(match.group(0)[:60])
    if banned_hits:
        evidence["found"] = banned_hits[:20]
        problems.append(f"{len(banned_hits)} placeholder(s) or banned pattern(s) left in")

    minimum = spec.get("min_chars")
    if minimum and len(text) < int(minimum):
        problems.append(f"only {len(text)} characters; at least {minimum} expected")

    rule = spec.get("rule")
    if rule:
        outcome = _apply_rule(rule, text, evidence)
        if outcome:
            problems.append(outcome)

    expression = spec.get("expression")
    if expression:
        values = {**(spec.get("values") or {}), **_extract_values(text, spec.get("extract") or {})}
        evidence["values"] = values
        try:
            if not evaluate(expression, values):
                problems.append(f"`{expression}` is not true for {values}")
        except ExpressionError as exc:
            return error(f"{check.name}: {exc}")

    if problems:
        return Verdict(
            status="fail",
            detail=f"{check.name}: " + "; ".join(problems),
            evidence=evidence,
        )
    return Verdict(status="pass", detail=f"{check.name}: passed.", evidence=evidence)


def _apply_rule(rule: str, text: str, evidence: dict) -> str | None:
    if rule == "every_defined_term_has_a_definition":
        return _defined_terms(text, evidence)
    if rule == "percentages_and_totals_are_consistent":
        return _percentages(text, evidence)
    return f"unknown assertion rule '{rule}'"


def _defined_terms(text: str, evidence: dict) -> str | None:
    """A term in quotes is a definition; the same phrase capitalised is a use.

    Undefined capitalised phrases are the classic contract bug: `the Services`
    used in clause 8 when nothing ever said what the Services are.
    """
    defined = {term.strip().lower() for term in DEFINED_TERM.findall(text)}
    evidence["defined_terms"] = sorted(defined)[:40]
    if not defined:
        return None

    # Only phrases that also appear quoted somewhere are candidates for a
    # definition, so ordinary proper nouns are not flagged.
    body_without_definitions = DEFINED_TERM.sub(" ", text)
    used = {phrase.strip().lower() for phrase in CAPITALISED_USE.findall(body_without_definitions)}
    undefined = sorted(
        phrase
        for phrase in used
        if phrase not in defined
        and any(phrase in term or term in phrase for term in defined)
        and phrase not in {"the", "this", "that"}
    )
    if undefined:
        evidence["undefined_terms"] = undefined[:20]
        return f"used without definition: {', '.join(undefined[:6])}"
    return None


def _percentages(text: str, evidence: dict) -> str | None:
    percentages = [float(value) for value in re.findall(r"(\d{1,3}(?:\.\d+)?)\s?%", text)]
    evidence["percentages"] = percentages[:30]
    over = [value for value in percentages if value > 100]
    if over:
        return f"percentage over 100: {', '.join(str(value) for value in over[:5])}"
    return None


def _extract_values(text: str, extract: dict) -> dict:
    """Pull named numbers out of the document for the expression to use."""
    values: dict = {}
    for name, pattern in extract.items():
        found = re.findall(pattern, text)
        numbers = []
        for item in found:
            raw = item if isinstance(item, str) else next((part for part in item if part), "")
            match = NUMBER.search(raw)
            if match:
                numbers.append(float(match.group(0).replace(",", "")))
        values[name] = numbers if len(numbers) != 1 else numbers[0]
    return values
