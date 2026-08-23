"""Does the artifact parse, and does it have the shape it is supposed to have?

Useful the moment a deliverable is structured rather than prose: a financial
model that must have named sheets, a config file, an export that downstream
tooling will read.
"""

import csv
import io
import json

import jsonschema
import yaml

from models import Check

from .base import CheckContext, Verdict, error, needs_artifact


def run(check: Check, ctx: CheckContext) -> Verdict:
    missing_artifact = needs_artifact(check, ctx)
    if missing_artifact:
        return missing_artifact

    spec = check.spec or {}
    fmt = spec.get("format", "json")
    evidence = {"content_hash": ctx.artifact.content_hash, "format": fmt}

    try:
        parsed = _parse(ctx.content, fmt)
    except Exception as exc:
        return Verdict(
            status="fail",
            detail=f"{check.name}: the file does not parse as {fmt} — {exc}",
            evidence=evidence,
        )

    schema = spec.get("schema")
    if schema:
        try:
            jsonschema.validate(parsed, schema)
        except jsonschema.ValidationError as exc:
            where = "/".join(str(part) for part in exc.absolute_path) or "(root)"
            return Verdict(
                status="fail",
                detail=f"{check.name}: at {where}, {exc.message}",
                evidence={**evidence, "path": where},
            )
        except jsonschema.SchemaError as exc:
            return error(f"{check.name}: the check's own schema is invalid — {exc.message}")

    required_keys = spec.get("required_keys") or []
    if required_keys:
        if not isinstance(parsed, dict):
            return Verdict(
                status="fail",
                detail=f"{check.name}: expected an object with keys, got {type(parsed).__name__}.",
                evidence=evidence,
            )
        missing = [key for key in required_keys if key not in parsed]
        if missing:
            return Verdict(
                status="fail",
                detail=f"{check.name}: missing key(s) {', '.join(missing)}.",
                evidence={**evidence, "keys": sorted(parsed)[:40]},
            )

    required_columns = spec.get("required_columns") or []
    if required_columns:
        columns = _columns(parsed)
        missing = [name for name in required_columns if name not in columns]
        evidence["columns"] = columns
        if missing:
            return Verdict(
                status="fail",
                detail=f"{check.name}: missing column(s) {', '.join(missing)}.",
                evidence=evidence,
            )

    minimum_rows = spec.get("min_rows")
    if minimum_rows is not None and isinstance(parsed, list):
        evidence["rows"] = len(parsed)
        if len(parsed) < int(minimum_rows):
            return Verdict(
                status="fail",
                detail=f"{check.name}: {len(parsed)} row(s), at least {minimum_rows} expected.",
                evidence=evidence,
            )

    return Verdict(status="pass", detail=f"{check.name}: parses and matches.", evidence=evidence)


def _parse(text: str, fmt: str):
    if fmt == "json":
        return json.loads(text)
    if fmt in {"yaml", "yml"}:
        return yaml.safe_load(text)
    if fmt == "csv":
        return list(csv.DictReader(io.StringIO(text)))
    if fmt == "jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    raise ValueError(f"unsupported format '{fmt}'")


def _columns(parsed) -> list[str]:
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        return list(parsed[0].keys())
    if isinstance(parsed, dict):
        return list(parsed.keys())
    return []
