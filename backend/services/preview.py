"""Builds a Flutter package to web and serves it, so a finished app can be seen.

The container has no display and no Android SDK, but Flutter's web target needs
neither: `flutter build web` produces static files the platform can serve, which
is the shortest honest path from "the agents wrote an app" to "here it is".
"""

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from config import get_settings

from . import workspace

log = logging.getLogger(__name__)

# Previews are slow and rare; one at a time keeps them off the run workers.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview")

BUILD_TIMEOUT = 900


def previews_root() -> Path:
    return Path(get_settings().data_dir) / "previews"


def slug(package: str) -> str:
    return package.strip("./").replace("/", "-") or "root"


def base_href(company_slug: str, project_key: str, package: str) -> str:
    """Served through the dashboard's proxy, so assets resolve for the browser."""
    return f"/api/backend/preview/{company_slug}/{project_key.lower()}/{slug(package)}/"


def output_dir(company_slug: str, project_key: str, package: str) -> Path:
    return previews_root() / company_slug / project_key.lower() / slug(package)


def flutter_packages(space: workspace.Workspace) -> list[str]:
    """Directories holding a pubspec.yaml, relative to the workspace root."""
    found = []
    for pubspec in sorted(space.root.rglob("pubspec.yaml")):
        relative = pubspec.parent.relative_to(space.root)
        parts = relative.parts
        if any(part in workspace.IGNORED_DIRS for part in parts):
            continue
        found.append(relative.as_posix() or ".")
    return found


def build(company_slug: str, project_key: str, project_name: str, package: str) -> dict:
    """Run the web build and publish its output. Returns the new preview state."""
    space = workspace.for_project(company_slug, project_key)
    space.init(project_name)
    href = base_href(company_slug, project_key, package)

    started = datetime.now(UTC).isoformat()
    package_dir = space.root / ("" if package == "." else package)

    # Hand-written packages have no web/ directory, and `flutter build web`
    # refuses without one. Adding it is idempotent and touches nothing else.
    if not (package_dir / "web").is_dir():
        try:
            scaffold = space.run(
                "flutter create . --platforms=web",
                cwd="" if package == "." else package,
                timeout=BUILD_TIMEOUT,
            )
            log.info("web scaffold for %s: exit %s", package, scaffold["exit_code"])
        except Exception as exc:
            return {
                "status": "failed",
                "package": package,
                "error": f"Could not add web support: {exc}",
                "built_at": started,
            }

    try:
        result = space.run(
            f"flutter build web --release --base-href={href}",
            cwd="" if package == "." else package,
            timeout=BUILD_TIMEOUT,
        )
    except Exception as exc:
        return {
            "status": "failed",
            "package": package,
            "error": str(exc),
            "built_at": started,
        }

    if result["exit_code"] != 0:
        return {
            "status": "failed",
            "package": package,
            "error": result["output"][-3000:],
            "built_at": started,
        }

    source = package_dir / "build" / "web"
    if not source.is_dir():
        return {
            "status": "failed",
            "package": package,
            "error": "The build reported success but produced no build/web directory.",
            "built_at": started,
        }

    destination = output_dir(company_slug, project_key, package)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)

    return {
        "status": "ready",
        "package": package,
        "url": href,
        "built_at": datetime.now(UTC).isoformat(),
        "error": None,
    }


def submit(fn, *args) -> None:
    _executor.submit(fn, *args)
