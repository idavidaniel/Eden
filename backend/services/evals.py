"""Does any of this actually work better than the simple version?

The memory system, the reflection gate, the retrieval tiers — all of it is
complexity, and complexity has to earn its place. This runs a fixed set of
briefs through a real company twice, once with memory and once without, and
reports the three numbers that would move if memory were helping:

  * first-try check pass rate — did the work pass without being sent back?
  * tool calls per work item — did it flail less?
  * tokens per accepted deliverable — did it cost less to get something good?

The suites are deliberately repetitive: several briefs in each one depend on a
convention established by an earlier brief. An agent that remembered should do
better on the third than on the first. If the numbers do not move, this says
so rather than quietly not being run.

Nothing here is a benchmark against anyone else. It is a regression test on our
own claims.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Check, CheckResult, Company, RunStep, UsageEvent, WorkItem
from models.work import Project

from . import packs

log = logging.getLogger(__name__)

SUITES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals", "suites"
)


class EvalError(RuntimeError):
    pass


@dataclass
class Brief:
    key: str
    title: str
    brief: str
    checks: list[dict] = field(default_factory=list)


@dataclass
class Suite:
    key: str
    name: str
    pack: str
    team: list[str]
    briefs: list[Brief]


@dataclass
class ArmResult:
    """What one side of the A/B actually produced."""

    memory: bool
    company_id: str
    projects: list[str] = field(default_factory=list)
    first_try_pass_rate: float | None = None
    checks_run: int = 0
    checks_passed: int = 0
    items: int = 0
    items_done: int = 0
    tool_calls_per_item: float | None = None
    tokens_per_artifact: float | None = None
    cost_micros: float = 0.0
    wall_seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "memory": self.memory,
            "company_id": self.company_id,
            "projects": self.projects,
            "first_try_pass_rate": self.first_try_pass_rate,
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "items": self.items,
            "items_done": self.items_done,
            "tool_calls_per_item": self.tool_calls_per_item,
            "tokens_per_artifact": self.tokens_per_artifact,
            "cost_micros": self.cost_micros,
            "wall_seconds": round(self.wall_seconds, 1),
        }


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def all_suites() -> dict[str, Suite]:
    suites: dict[str, Suite] = {}
    if not os.path.isdir(SUITES_DIR):
        return suites
    for name in sorted(os.listdir(SUITES_DIR)):
        if not name.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(SUITES_DIR, name)
        with open(path) as handle:
            raw = yaml.safe_load(handle) or {}
        try:
            suite = Suite(
                key=raw["key"],
                name=raw.get("name", raw["key"]),
                pack=raw.get("pack", "software_studio"),
                team=list(raw.get("team") or []),
                briefs=[
                    Brief(
                        key=item["key"],
                        title=item.get("title", item["key"]),
                        brief=item["brief"].strip(),
                        checks=list(item.get("checks") or []),
                    )
                    for item in raw.get("briefs") or []
                ],
            )
        except KeyError as exc:
            raise EvalError(f"{name} is missing {exc}") from exc
        if not suite.briefs:
            raise EvalError(f"{name} has no briefs, so it measures nothing.")
        packs.get_pack(suite.pack)  # fails loudly if the pack is not installed
        suites[suite.key] = suite
    return suites


def get_suite(key: str) -> Suite:
    suites = all_suites()
    if key not in suites:
        raise EvalError(
            f"No eval suite called '{key}'. Have: {', '.join(sorted(suites)) or 'none'}."
        )
    return suites[key]


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------


def run_suite(
    db: Session,
    suite: Suite,
    *,
    tenant_id: str,
    arms: tuple[bool, ...] = (True, False),
    label: str = "",
) -> dict:
    """Run every brief once per arm, in a throwaway company per arm."""
    started = time.perf_counter()
    stamp = label or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    results = [
        _run_arm(db, suite, memory=memory, stamp=stamp, tenant_id=tenant_id)
        for memory in arms
    ]

    return {
        "suite": suite.key,
        "name": suite.name,
        "label": stamp,
        "ran_at": datetime.now(UTC).isoformat(),
        "wall_seconds": round(time.perf_counter() - started, 1),
        "arms": [arm.as_dict() for arm in results],
        "comparison": _compare(results),
        "note": _verdict(results),
    }


def _run_arm(
    db: Session, suite: Suite, *, memory: bool, stamp: str, tenant_id: str
) -> ArmResult:
    from agents import engine
    from api.companies import found_company

    started = time.perf_counter()
    company = found_company(
        db,
        tenant_id=tenant_id,
        name=f"Eval {suite.name} {'with' if memory else 'without'} memory {stamp}",
        pack=suite.pack,
        starting_team=suite.team or None,
        description=f"Throwaway company for eval suite {suite.key}.",
    )
    company.settings = {**(company.settings or {}), "memory_enabled": memory, "eval": True}
    db.add(company)
    db.commit()

    result = ArmResult(memory=memory, company_id=company.id)

    for brief in suite.briefs:
        project = Project(
            company_id=company.id,
            name=brief.title,
            key=brief.key.upper()[:10],
            brief=brief.brief,
            status="planning",
        )
        db.add(project)
        db.flush()

        for position, spec in enumerate(brief.checks):
            db.add(
                Check(
                    company_id=company.id,
                    project_id=project.id,
                    key=spec["key"],
                    name=spec.get("name", spec["key"]),
                    kind=spec["kind"],
                    spec=dict(spec.get("spec") or {}),
                    required=True,
                    position=position,
                    created_by="Eval",
                )
            )
        db.commit()
        result.projects.append(project.id)

        # Runs synchronously: an eval that returned before the work finished
        # would be measuring nothing.
        try:
            engine.execute_run(_queue_run(db, project))
        except Exception:
            log.exception("eval brief %s blew up", brief.key)

    _measure(db, company, result)
    result.wall_seconds = time.perf_counter() - started
    return result


def _queue_run(db: Session, project: Project) -> str:
    from models import Run

    run = Run(
        company_id=project.company_id,
        project_id=project.id,
        status="queued",
        brief=project.brief,
    )
    db.add(run)
    db.commit()
    return run.id


def _measure(db: Session, company: Company, result: ArmResult) -> None:
    items = list(
        db.scalars(
            select(WorkItem)
            .join(Project, WorkItem.project_id == Project.id)
            .where(Project.company_id == company.id)
        )
    )
    result.items = len(items)
    result.items_done = len([item for item in items if item.status == "done"])

    # First try means the check ran before the item was ever sent back. An item
    # that passed on its fourth attempt did not pass first try.
    first_try = [item for item in items if item.rework_count == 0]
    verdicts = list(
        db.scalars(
            select(CheckResult).where(
                CheckResult.company_id == company.id,
                CheckResult.work_item_id.in_([item.id for item in items]) if items else False,
            )
        )
    )
    result.checks_run = len(verdicts)
    result.checks_passed = len([row for row in verdicts if row.status == "pass"])
    if first_try and verdicts:
        passed_first = {
            row.work_item_id
            for row in verdicts
            if row.status == "pass" and row.work_item_id in {item.id for item in first_try}
        }
        result.first_try_pass_rate = round(len(passed_first) / len(items), 4) if items else None

    steps = list(
        db.scalars(select(RunStep).where(RunStep.company_id == company.id))
    )
    calls = sum(len(step.tool_calls or []) for step in steps)
    if result.items:
        result.tool_calls_per_item = round(calls / result.items, 2)

    totals = db.execute(
        select(
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_micros), 0.0),
        ).where(UsageEvent.company_id == company.id)
    ).one()
    tokens = int(totals[0] or 0) + int(totals[1] or 0)
    result.cost_micros = float(totals[2] or 0.0)

    from models import Artifact

    accepted = db.scalar(
        select(func.count())
        .select_from(Artifact)
        .where(Artifact.company_id == company.id, Artifact.superseded_by.is_(None))
    )
    if accepted:
        result.tokens_per_artifact = round(tokens / accepted, 1)


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

METRICS = [
    ("first_try_pass_rate", "higher", "passed its checks first time"),
    ("tool_calls_per_item", "lower", "tool calls per work item"),
    ("tokens_per_artifact", "lower", "tokens per accepted deliverable"),
]


def _compare(arms: list[ArmResult]) -> list[dict]:
    with_memory = next((arm for arm in arms if arm.memory), None)
    without = next((arm for arm in arms if not arm.memory), None)
    if not with_memory or not without:
        return []

    rows = []
    for field_name, direction, label in METRICS:
        on = getattr(with_memory, field_name)
        off = getattr(without, field_name)
        if on is None or off is None:
            rows.append(
                {
                    "metric": field_name,
                    "label": label,
                    "with_memory": on,
                    "without_memory": off,
                    "verdict": "not measured",
                }
            )
            continue
        better = on > off if direction == "higher" else on < off
        same = abs(on - off) < 1e-9
        rows.append(
            {
                "metric": field_name,
                "label": label,
                "with_memory": on,
                "without_memory": off,
                "change": round(on - off, 4),
                "verdict": "no difference" if same else ("better" if better else "worse"),
            }
        )
    return rows


def _verdict(arms: list[ArmResult]) -> str:
    rows = _compare(arms)
    measured = [row for row in rows if row["verdict"] not in {"not measured"}]
    if not measured:
        return (
            "Nothing was measurable: no checks ran, or no deliverable was produced. "
            "This says nothing about memory either way."
        )
    better = [row for row in measured if row["verdict"] == "better"]
    worse = [row for row in measured if row["verdict"] == "worse"]

    if len(better) > len(worse):
        return (
            f"Memory helped on {len(better)} of {len(measured)} measures. "
            "One run is not evidence — repeat it before believing it."
        )
    if worse and not better:
        return (
            f"Memory made every measured number worse ({len(worse)} of {len(measured)}). "
            "On this suite it is not earning its complexity."
        )
    return (
        f"No clear difference: {len(better)} better, {len(worse)} worse, "
        f"{len(measured) - len(better) - len(worse)} unchanged. "
        "Memory is not paying for itself on this suite yet."
    )
