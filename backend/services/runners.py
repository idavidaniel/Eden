"""Which toolchain runs a command, and where.

The base image carries Python, Node, git and Flutter. Everything else — Go,
Rust, the JVM, .NET, LaTeX — runs in a container started for that one command,
with no network and the workspace bind-mounted. That is how an employee can
build a Rust project without the platform image being forty gigabytes.

Container profiles are off unless ENABLE_RUNNER_PROFILES is set *and* a Docker
socket is reachable, because mounting the host's Docker socket is a genuine
privilege escalation. When they are off, asking for one says so.
"""

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

log = logging.getLogger(__name__)

RUNNERS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runners")
DOCKER_SOCKET = "/var/run/docker.sock"


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    commands: list[str]
    in_image: bool = False
    image: str = ""
    timeout: int = 120
    cache: str = ""
    env: dict = field(default_factory=dict)
    packages: list[str] = field(default_factory=list)
    # Container runners get no network by default. A profile that needs to fetch
    # dependencies has to say so in the YAML, where it is visible.
    network: str = "none"

    @property
    def containerised(self) -> bool:
        return not self.in_image


@lru_cache
def all_profiles() -> dict[str, Profile]:
    path = os.path.join(RUNNERS_DIR, "profiles.yaml")
    if not os.path.exists(path):
        return {}
    with open(path) as handle:
        raw = yaml.safe_load(handle) or {}
    profiles = {}
    for item in raw.get("profiles") or []:
        profile = Profile(
            key=item["key"],
            name=item.get("name", item["key"]),
            commands=list(item.get("commands") or []),
            in_image=bool(item.get("in_image")),
            image=item.get("image", ""),
            timeout=int(item.get("timeout", 120)),
            cache=item.get("cache", ""),
            env=dict(item.get("env") or {}),
            packages=list(item.get("packages") or []),
            network=item.get("network", "none"),
        )
        profiles[profile.key] = profile
    return profiles


@lru_cache
def containers_enabled() -> bool:
    if os.getenv("ENABLE_RUNNER_PROFILES", "false").lower() not in {"1", "true", "yes"}:
        return False
    if not shutil.which("docker"):
        log.info("Runner profiles are enabled but the docker client is not installed.")
        return False
    if not os.path.exists(DOCKER_SOCKET):
        log.info("Runner profiles are enabled but %s is not mounted.", DOCKER_SOCKET)
        return False
    return True


def profile_for(program: str) -> Profile | None:
    for profile in all_profiles().values():
        if program in profile.commands:
            return profile
    return None


@lru_cache
def allowed_programs() -> frozenset[str]:
    """Every program that can actually be started right now.

    In-image commands are filtered by what is on PATH. The old hardcoded list
    advertised `node`, `mypy` and `tree`, none of which are in the image — so an
    employee could spend a tool call discovering that for itself.
    """
    programs: set[str] = set()
    for profile in all_profiles().values():
        if profile.in_image:
            programs.update(name for name in profile.commands if shutil.which(name))
        elif containers_enabled():
            programs.update(profile.commands)
    return frozenset(programs)


def status() -> dict:
    return {
        "containers_enabled": containers_enabled(),
        "profiles": [
            {
                "key": profile.key,
                "name": profile.name,
                "commands": profile.commands,
                "where": "in-image" if profile.in_image else f"container ({profile.image})",
                "available": profile.in_image or containers_enabled(),
            }
            for profile in all_profiles().values()
        ],
    }


def _self_container() -> str:
    """This container's id, so a sibling can borrow its volumes.

    Translating a named volume to a host path is fragile and differs between
    Docker Desktop and a Linux daemon. `--volumes-from` sidesteps it: the runner
    sees /data exactly where this process sees it.
    """
    return os.getenv("HOSTNAME", "").strip()


def docker_argv(profile: Profile, argv: list[str], work_dir: str) -> list[str]:
    """The container invocation for one command."""
    command = [
        "docker",
        "run",
        "--rm",
        f"--network={profile.network}",
        "--memory=2g",
        "--cpus=2",
        "--volumes-from",
        _self_container(),
        "-w",
        work_dir,
    ]
    if profile.cache:
        command += ["-v", profile.cache]
    for key, value in profile.env.items():
        command += ["-e", f"{key}={value}"]
    command.append(profile.image)
    return command + argv


def unavailable_reason(profile: Profile) -> str | None:
    """Why this profile cannot be used right now, in words worth showing."""
    if profile.in_image:
        return None
    if os.getenv("ENABLE_RUNNER_PROFILES", "false").lower() not in {"1", "true", "yes"}:
        return (
            f"The {profile.name} toolchain runs in a container, and container runners are "
            "switched off. Set ENABLE_RUNNER_PROFILES=true to turn them on."
        )
    if not shutil.which("docker") or not os.path.exists(DOCKER_SOCKET):
        return (
            f"The {profile.name} toolchain needs the Docker socket mounted into this "
            f"container ({DOCKER_SOCKET}); it is not there."
        )
    if not _self_container():
        return "Could not work out this container's id, so a runner cannot share its workspace."
    return None


def run_in_container(
    profile: Profile, argv: list[str], work_dir: str, timeout: int
) -> subprocess.CompletedProcess:
    return subprocess.run(
        docker_argv(profile, argv, work_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
