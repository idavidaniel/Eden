"""Per-project git workspaces that agents read from and write to.

Every project gets a real repository on disk. Agents commit as themselves, so
`git log` in a workspace reads like a team's history rather than one bot's.
"""

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from config import get_settings

from . import runners

MAX_FILE_BYTES = 400_000
MAX_OUTPUT_CHARS = 6000
DEFAULT_TIMEOUT = 60
# Toolchains that legitimately take minutes (pub get, analysis, widget tests).
SLOW_TIMEOUT = 420
SLOW_COMMANDS = {"flutter", "dart"}


def allowed_commands() -> set[str]:
    """Programs an employee may start right now.

    Comes from the runner profiles, so the set grows when container runners are
    switched on and shrinks back when they are not — rather than advertising a
    toolchain that would fail the moment somebody used it.
    """
    return runners.allowed_programs()


# Kept as a name because prompts and tool descriptions read it. It reflects what
# is actually runnable in this deployment, not a hardcoded wish list.
ALLOWED_COMMANDS = allowed_commands()
IGNORED_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "dist",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".dart_tool",
    "build",
    ".gradle",
    "Pods",
}
DEFAULT_GITIGNORE = """__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/
.venv/
node_modules/
dist/
.next/
.dart_tool/
build/
.gradle/
*.iml
"""


class WorkspaceError(RuntimeError):
    pass


@dataclass
class Workspace:
    root: Path

    # --- paths ----------------------------------------------------------
    def resolve(self, relative: str) -> Path:
        candidate = (self.root / relative.lstrip("/")).resolve()
        if not str(candidate).startswith(str(self.root.resolve())):
            raise WorkspaceError(f"Path escapes the workspace: {relative}")
        return candidate

    # --- reads ----------------------------------------------------------
    def tree(self) -> list[dict]:
        entries: list[dict] = []
        for path in sorted(self.root.rglob("*")):
            if any(part in IGNORED_DIRS for part in path.relative_to(self.root).parts):
                continue
            relative = path.relative_to(self.root).as_posix()
            entries.append(
                {
                    "path": relative,
                    "name": path.name,
                    "type": "dir" if path.is_dir() else "file",
                    "size": path.stat().st_size if path.is_file() else 0,
                }
            )
        return entries

    def read(self, relative: str) -> str:
        path = self.resolve(relative)
        if not path.is_file():
            raise WorkspaceError(f"No such file: {relative}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError(f"File too large to read: {relative}")
        return path.read_text(errors="replace")

    # --- writes ---------------------------------------------------------
    def write(self, relative: str, content: str) -> dict:
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        path.write_text(content)
        return {"path": relative, "bytes": len(content), "created": not existed}

    def delete(self, relative: str) -> dict:
        path = self.resolve(relative)
        if path.is_file():
            path.unlink()
            return {"path": relative, "deleted": True}
        raise WorkspaceError(f"No such file: {relative}")

    # --- git ------------------------------------------------------------
    def git(self, *args: str, author: tuple[str, str] | None = None) -> str:
        env = dict(os.environ)
        if author:
            name, email = author
            env.update(
                {
                    "GIT_AUTHOR_NAME": name,
                    "GIT_AUTHOR_EMAIL": email,
                    "GIT_COMMITTER_NAME": name,
                    "GIT_COMMITTER_EMAIL": email,
                }
            )
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            raise WorkspaceError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()

    def init(self, project_name: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if (self.root / ".git").exists():
            return
        self.git("init", "-q", "-b", "main")
        readme = self.root / "README.md"
        if not readme.exists():
            readme.write_text(f"# {project_name}\n\nWorkspace created by the platform.\n")
        # Keep test and build caches out of the history the team reads.
        ignore = self.root / ".gitignore"
        if not ignore.exists():
            ignore.write_text(DEFAULT_GITIGNORE)
        self.git("add", "-A")
        self.git(
            "commit", "-q", "-m", "Initialise workspace", author=("Platform", "platform@eden.local")
        )

    def commit(self, message: str, author: tuple[str, str]) -> dict:
        self.git("add", "-A")
        status = self.git("status", "--porcelain")
        if not status:
            return {"committed": False, "reason": "nothing to commit"}
        self.git("commit", "-q", "-m", message, author=author)
        return {
            "committed": True,
            "sha": self.git("rev-parse", "--short", "HEAD"),
            "message": message,
        }

    def log(self, limit: int = 30) -> list[dict]:
        if not (self.root / ".git").exists():
            return []
        raw = self.git("log", f"-{limit}", "--pretty=format:%h\x1f%an\x1f%ar\x1f%s")
        entries = []
        for line in raw.splitlines():
            sha, author, when, subject = line.split("\x1f")
            entries.append({"sha": sha, "author": author, "when": when, "subject": subject})
        return entries

    def diff(self, sha: str) -> str:
        return self.git("show", "--stat", "--patch", sha)

    # --- running -------------------------------------------------------
    def run(
        self,
        command: str,
        timeout: int | None = None,
        cwd: str = "",
        profile: str | None = None,
    ) -> dict:
        """Run an allow-listed command inside the workspace.

        No shell: the command is tokenised and executed directly, so there is no
        redirection, piping or chaining, and only the allow-listed programs can be
        started at all. `cwd` picks a subdirectory - monorepos put each package in
        one, and without it `flutter pub get` has nothing to resolve.

        A program the base image does not carry runs in its own container through
        a runner profile, under the same allow-list, path guard and timeout.
        """
        argv, program = check_command(command)
        working_dir = self.resolve(cwd) if cwd else self.root
        if not working_dir.is_dir():
            raise WorkspaceError(f"No such directory: {cwd}")

        chosen = runners.all_profiles().get(profile) if profile else runners.profile_for(program)
        if chosen is None:
            chosen = runners.all_profiles().get("host")
        if chosen and chosen.containerised:
            blocked = runners.unavailable_reason(chosen)
            if blocked:
                raise WorkspaceError(blocked)

        if timeout is None:
            if chosen and chosen.timeout:
                timeout = chosen.timeout
            else:
                timeout = SLOW_TIMEOUT if program in SLOW_COMMANDS else DEFAULT_TIMEOUT

        try:
            if chosen and chosen.containerised:
                result = runners.run_in_container(chosen, argv, str(working_dir), timeout)
            else:
                result = subprocess.run(
                    argv,
                    cwd=working_dir,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "CI": "true"},
                )
        except subprocess.TimeoutExpired:
            raise WorkspaceError(
                f"'{program}' did not finish within {timeout}s and was stopped."
            ) from None

        output = (result.stdout + result.stderr).strip()
        return {
            "command": f"{command} (in {cwd})" if cwd else command,
            "exit_code": result.returncode,
            "output": output[-MAX_OUTPUT_CHARS:] or "(no output)",
            "truncated": len(output) > MAX_OUTPUT_CHARS,
            "profile": chosen.key if chosen else "host",
        }


def check_command(command: str) -> tuple[list[str], str]:
    """Validate a command against the sandbox rules. Returns (argv, program)."""
    for character in ("|", ">", "<", "&", ";", "`", "$("):
        if character in command:
            raise WorkspaceError(f"'{character}' is not available - commands run without a shell.")

    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise WorkspaceError(f"Could not parse the command: {exc}") from exc
    if not argv:
        raise WorkspaceError("Empty command.")

    program = Path(argv[0]).name
    available = allowed_commands()
    if program not in available:
        known = runners.profile_for(program)
        if known:
            raise WorkspaceError(
                runners.unavailable_reason(known) or f"'{program}' is unavailable."
            )
        raise WorkspaceError(
            f"'{program}' is not allowed here. Allowed: {', '.join(sorted(available))}"
        )
    return argv, program


def for_project(company_slug: str, project_key: str) -> Workspace:
    root = Path(get_settings().workspaces_dir) / company_slug / project_key.lower()
    return Workspace(root=root)
