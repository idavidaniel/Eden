#!/usr/bin/env python3
"""Run an eval suite and print what it found.

    docker compose exec backend python /app/../scripts/run_evals.py software_studio

This spends real money on real model calls — it runs every brief twice, in two
throwaway companies. That is the point: the comparison is worthless if either
side is simulated.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for candidate in ("/app", os.path.join(os.path.dirname(HERE), "backend")):
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)

from db import session  # noqa: E402
from services import evals  # noqa: E402


def _first_tenant(db) -> str:
    from sqlalchemy import select

    from models import Tenant

    row = db.scalar(select(Tenant).order_by(Tenant.created_at))
    return row.id if row else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", nargs="?", help="Which suite. Omit to list them.")
    parser.add_argument(
        "--memory-only",
        action="store_true",
        help="Run only the with-memory arm. Faster, and proves nothing about memory.",
    )
    parser.add_argument("--json", action="store_true", help="Print the raw report.")
    parser.add_argument("--label", default="", help="Name this run in the report.")
    parser.add_argument(
        "--tenant",
        default="",
        help="Which organisation owns the throwaway companies. Defaults to the first.",
    )
    args = parser.parse_args()

    if not args.suite:
        for suite in evals.all_suites().values():
            print(
                f"{suite.key:20} {suite.name} — {len(suite.briefs)} brief(s), pack {suite.pack}"
            )
        return 0

    db = session()
    try:
        suite = evals.get_suite(args.suite)
        tenant_id = args.tenant or _first_tenant(db)
        if not tenant_id:
            print(
                "error: no organisation exists yet. Sign up first, so the throwaway "
                "companies belong to somebody.",
                file=sys.stderr,
            )
            return 2
        report = evals.run_suite(
            db,
            suite,
            tenant_id=tenant_id,
            arms=(True,) if args.memory_only else (True, False),
            label=args.label,
        )
    except evals.EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"\n{report['name']} — {report['wall_seconds']}s\n")
    for arm in report["arms"]:
        label = "with memory" if arm["memory"] else "without memory"
        print(
            f"  {label:16} {arm['items_done']}/{arm['items']} done, "
            f"{arm['checks_passed']}/{arm['checks_run']} checks passed, "
            f"${arm['cost_micros'] / 1_000_000:.4f}"
        )

    if report["comparison"]:
        print()
        for row in report["comparison"]:
            print(
                f"  {row['label']:38} "
                f"on {row['with_memory']!s:>8}  off {row['without_memory']!s:>8}  "
                f"{row['verdict']}"
            )

    print(f"\n{report['note']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
