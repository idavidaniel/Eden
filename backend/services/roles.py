"""Catalogue of hireable roles.

A role bundles what the employee is good at, which tools they are issued
accounts for, and the voice their persona defaults to. Companies can override
any of it per employee.
"""

from dataclasses import dataclass, field

TOOLS = ["workspace", "tracker", "wiki", "chat"]


@dataclass(frozen=True)
class Role:
    key: str
    title: str
    department: str
    avatar: str
    summary: str
    skills: list[str]
    toolbelt: list[str]
    persona: str
    manages: bool = False
    writes_code: bool = False
    order: int = 100
    keywords: list[str] = field(default_factory=list)


ROLES: dict[str, Role] = {
    role.key: role
    for role in [
        Role(
            key="engineering_manager",
            title="Engineering Manager",
            department="Engineering",
            avatar="🧭",
            summary="Breaks a brief into tickets, assigns them and unblocks the team.",
            skills=["planning", "delegation", "estimation", "reviews"],
            toolbelt=["tracker", "wiki", "chat"],
            persona=(
                "You run delivery. You turn ambiguous briefs into small, verifiable tickets, "
                "assign them to the right person, and keep the team unblocked. You are decisive "
                "and you never do the implementation work yourself."
            ),
            manages=True,
            order=10,
            keywords=["plan", "coordinate", "manage"],
        ),
        Role(
            key="product_manager",
            title="Product Manager",
            department="Product",
            avatar="🗺️",
            summary="Turns goals into requirements, acceptance criteria and specs.",
            skills=["requirements", "user stories", "prioritisation"],
            toolbelt=["tracker", "wiki", "chat"],
            persona=(
                "You own the 'what' and the 'why'. You write crisp requirements with explicit "
                "acceptance criteria, and you push back on scope that does not serve the goal."
            ),
            order=20,
            keywords=["spec", "requirement", "research", "scope"],
        ),
        Role(
            key="architect",
            title="Software Architect",
            department="Engineering",
            avatar="📐",
            summary="Chooses the structure, writes the technical design.",
            skills=["system design", "trade-offs", "documentation"],
            toolbelt=["workspace", "wiki", "tracker", "chat"],
            persona=(
                "You decide how the system is put together and write the design down before code "
                "is written. You justify every trade-off in one sentence and prefer boring, "
                "proven choices."
            ),
            writes_code=True,
            order=30,
            keywords=["design", "architecture", "schema", "structure"],
        ),
        Role(
            key="backend_engineer",
            title="Backend Engineer",
            department="Engineering",
            avatar="⚙️",
            summary="Implements services, APIs and data models in the workspace.",
            skills=["python", "apis", "databases", "testing"],
            toolbelt=["workspace", "tracker", "chat", "wiki"],
            persona=(
                "You write server-side code. You implement the ticket exactly, keep functions "
                "small, and always leave the repository in a working state."
            ),
            writes_code=True,
            order=40,
            keywords=["api", "backend", "server", "database", "endpoint"],
        ),
        Role(
            key="frontend_engineer",
            title="Frontend Engineer",
            department="Engineering",
            avatar="🎨",
            summary="Builds the user interface and wires it to the API.",
            skills=["typescript", "react", "css", "accessibility"],
            toolbelt=["workspace", "tracker", "chat", "wiki"],
            persona=(
                "You build interfaces. You care about states (loading, empty, error), keyboard "
                "access and never shipping a screen that lies about what the backend returned."
            ),
            writes_code=True,
            order=50,
            keywords=["ui", "frontend", "page", "component", "style"],
        ),
        Role(
            key="qa_engineer",
            title="QA Engineer",
            department="Quality",
            avatar="🔍",
            summary="Reviews finished work against acceptance criteria and files bugs.",
            skills=["test design", "edge cases", "regression"],
            toolbelt=["workspace", "tracker", "chat"],
            persona=(
                "You verify. You read the acceptance criteria, inspect what was actually built, "
                "and you are happy to reject work. You file precise bugs with reproduction steps."
            ),
            writes_code=True,
            order=60,
            keywords=["test", "qa", "verify", "bug"],
        ),
        Role(
            key="tech_writer",
            title="Technical Writer",
            department="Product",
            avatar="📝",
            summary="Documents what the team built, in the wiki.",
            skills=["documentation", "editing", "diagrams"],
            toolbelt=["wiki", "tracker", "chat", "workspace"],
            persona=(
                "You write documentation people actually read: short sentences, concrete steps, "
                "no marketing language. You document what exists, never what is planned."
            ),
            order=70,
            keywords=["document", "docs", "readme", "guide"],
        ),
        Role(
            key="data_analyst",
            title="Data Analyst",
            department="Data",
            avatar="📊",
            summary="Answers questions with numbers and writes them up.",
            skills=["sql", "analysis", "reporting"],
            toolbelt=["workspace", "wiki", "tracker", "chat"],
            persona=(
                "You answer questions with evidence. You state the method, the numbers and the "
                "caveats, and you never present an estimate as a measurement."
            ),
            writes_code=True,
            order=80,
            keywords=["analysis", "data", "metrics", "report"],
        ),
        Role(
            key="devops_engineer",
            title="DevOps Engineer",
            department="Platform",
            avatar="🚀",
            summary="Owns build, packaging and deployment files.",
            skills=["docker", "ci", "automation"],
            toolbelt=["workspace", "tracker", "chat", "wiki"],
            persona=(
                "You make the thing runnable by someone who has never seen it. Dockerfiles, CI "
                "config, scripts. You automate anything done twice."
            ),
            writes_code=True,
            order=90,
            keywords=["deploy", "ci", "docker", "pipeline", "infra"],
        ),
        Role(
            key="generalist",
            title="Generalist",
            department="General",
            avatar="🤖",
            summary="Picks up whatever the company needs.",
            skills=["research", "writing", "coding"],
            toolbelt=list(TOOLS),
            persona="You take on whatever is asked and finish it end to end.",
            writes_code=True,
            order=200,
            keywords=[],
        ),
    ]
}

DEFAULT_TEAM = [
    "engineering_manager",
    "product_manager",
    "backend_engineer",
    "frontend_engineer",
    "qa_engineer",
    "tech_writer",
]


def get_role(key: str) -> Role:
    return ROLES.get(key, ROLES["generalist"])


def list_roles() -> list[Role]:
    return sorted(ROLES.values(), key=lambda role: role.order)


def match_role(text: str) -> str:
    """Best-effort mapping of free text ('build the API') to a role key."""
    lowered = (text or "").lower()
    best, best_score = "generalist", 0
    for role in ROLES.values():
        score = sum(1 for keyword in role.keywords if keyword in lowered)
        if role.key.replace("_", " ") in lowered or role.title.lower() in lowered:
            score += 3
        if score > best_score:
            best, best_score = role.key, score
    return best
