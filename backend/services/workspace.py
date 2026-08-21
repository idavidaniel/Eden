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

TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".html",
    ".css",
    ".scss",
    ".sql",
    ".sh",
    ".env",
    ".gitignore",
    ".dockerfile",
    "",
}
MAX_FILE_BYTES = 400_000
MAX_OUTPUT_CHARS = 6000
# Interpreters and inspection tools an employee may start. Anything that installs
# packages, reaches the network or touches the host is deliberately absent.
ALLOWED_COMMANDS = {
    "python",
    "python3",
    "pytest",
    "node",
    "ruff",
    "mypy",
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "find",
    "git",
    "tree",
    "diff",
}
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
    def run(self, command: str, timeout: int = 60) -> dict:
        """Run an allow-listed command inside the workspace.

        No shell: the command is tokenised and executed directly, so there is no
        redirection, piping or chaining, and only the interpreters and inspection
        tools below can be started at all.
        """
        for character in ("|", ">", "<", "&", ";", "`", "$("):
            if character in command:
                raise WorkspaceError(
                    f"'{character}' is not available - commands run without a shell."
                )

        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise WorkspaceError(f"Could not parse the command: {exc}") from exc
        if not argv:
            raise WorkspaceError("Empty command.")

        program = Path(argv[0]).name
        if program not in ALLOWED_COMMANDS:
            raise WorkspaceError(
                f"'{program}' is not allowed here. Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}"
            )

        result = subprocess.run(
            argv,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        output = (result.stdout + result.stderr).strip()
        return {
            "command": command,
            "exit_code": result.returncode,
            "output": output[-MAX_OUTPUT_CHARS:] or "(no output)",
            "truncated": len(output) > MAX_OUTPUT_CHARS,
        }


def for_project(company_slug: str, project_key: str) -> Workspace:
    root = Path(get_settings().workspaces_dir) / company_slug / project_key.lower()
    return Workspace(root=root)
