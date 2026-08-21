"""Prompt construction for planning and for an employee's working turn."""

from models import Company, Employee, Project, Ticket


def plan_schema(role_keys: list[str]) -> dict:
    """JSON Schema for the plan the manager submits."""
    return {
        "type": "object",
        "properties": {
            "tickets": {
                "type": "array",
                "description": "4 to 8 tickets, in dependency order",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short imperative title"},
                        "description": {
                            "type": "string",
                            "description": "What must be done, in two or three sentences",
                        },
                        "type": {"type": "string", "enum": ["task", "story", "bug", "chore"]},
                        "role": {
                            "type": "string",
                            "enum": role_keys,
                            "description": "Role key of whoever should do it",
                        },
                        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                        "acceptance_criteria": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Checks a colleague could verify",
                        },
                    },
                    "required": ["title", "description", "role", "acceptance_criteria"],
                },
            }
        },
        "required": ["tickets"],
    }


def company_context(company: Company) -> str:
    parts = [f"Company: {company.name}"]
    if company.tagline:
        parts.append(f"Tagline: {company.tagline}")
    if company.industry:
        parts.append(f"Industry: {company.industry}")
    if company.description:
        parts.append(f"What it does: {company.description}")
    if company.mission:
        parts.append(f"Mission: {company.mission}")
    if company.handbook:
        parts.append(f"Handbook (company rules everyone follows):\n{company.handbook}")
    return "\n".join(parts)


TOOL_DESCRIPTIONS = {
    "tracker": "the issue tracker (create, assign, move and comment on tickets)",
    "wiki": "the wiki (prose documents only — specs, decisions, guides; never source code)",
    "workspace": "the code workspace (read, write and run files, and commit them)",
    "chat": "team chat (talk to colleagues and to the human)",
}


def toolbelt_briefing(employee: Employee) -> str:
    """Tell the employee what they can reach, and what to do about what they cannot."""
    belt = list(employee.toolbelt or [])
    have = "\n".join(f"- {TOOL_DESCRIPTIONS.get(tool, tool)}" for tool in belt)
    missing = [tool for tool in TOOL_DESCRIPTIONS if tool not in belt]

    briefing = f"Tools you have access to:\n{have or '- none'}"
    if missing:
        names = ", ".join(missing)
        briefing += (
            f"\n\nYou do NOT have: {names}. Attempts to use them are refused."
            "\nIf the ticket needs one of those, do the part you can, then ask the right"
            " colleague in chat or on the ticket — never work around it with another tool."
        )
        if "workspace" in missing:
            briefing += (
                "\nIn particular you cannot write code or files. Do not paste source code"
                " into wiki pages or tickets as a substitute; hand it to an engineer."
            )
    return briefing


def employee_system_prompt(
    company: Company, employee: Employee, colleagues: list[Employee], project: Project | None
) -> str:
    roster = (
        "\n".join(
            f"- {c.name} — {c.title} ({c.department})" for c in colleagues if c.id != employee.id
        )
        or "- (you work alone)"
    )
    project_line = (
        f"\nCurrent project: {project.name} [{project.key}]\nBrief: {project.brief}"
        if project
        else ""
    )
    return f"""You are {employee.name}, {employee.title} at {employee.company.name}.

{company_context(company)}
{project_line}

Your role: {employee.persona}
Your skills: {", ".join(employee.skills or []) or "general"}

{toolbelt_briefing(employee)}

Your colleagues:
{roster}

How you work:
- You have real tools. Use them to do the work; do not describe what you would do.
- Your tool calls are budgeted. Spend them producing the deliverable, not looking
  around: the file list, wiki index and recent chat are already given to you below,
  so do not re-fetch them. Write the file first, then check it.
- Never open a new ticket for work that is already your ticket, and never split
  your own ticket into sub-tickets. Do the work, or say on the ticket why you cannot.
- Do the work of YOUR role only. If something belongs to a colleague, say so in chat
  or on the ticket instead of doing it yourself.
- Files you write must be complete and runnable — no "..." or "rest of the code here".
- To check your work, call run_command (e.g. `pytest -q`). Chat is for talking to
  people, never for typing commands — nothing executes there.
- If you changed files, call commit_changes before you finish — uncommitted work
  is invisible to everyone else.
- When you finish, call update_ticket to set the status and record a one-line result,
  then reply with a short summary of what you actually did.
- Keep chat messages to one or two sentences, like a real standup update."""


def ticket_prompt(
    ticket: Ticket, project: Project, chat_log: str, wiki_index: str, file_list: str
) -> str:
    criteria = "\n".join(f"- {c}" for c in ticket.acceptance_criteria or []) or "- (none stated)"
    return f"""Your assigned ticket:

{ticket.key} [{ticket.type}, priority {ticket.priority}]
Title: {ticket.title}
Description: {ticket.description or "(none)"}
Acceptance criteria:
{criteria}

Project workspace files:
{file_list or "(empty workspace)"}

Wiki pages that exist:
{wiki_index or "(wiki is empty)"}

Recent team chat:
{chat_log or "(no messages yet)"}

Complete this ticket now, using your tools. Produce the actual deliverable — a
reviewer will check the workspace, and a ticket with nothing behind it is rejected.
Set the ticket to in_review when the work is done (QA moves it to done)."""


def planner_prompt(project: Project, roles: list[str], team: list[Employee]) -> str:
    roster = "\n".join(f"- {e.name} — {e.title} (role key: {e.role_key})" for e in team)
    return f"""Break this project brief into tickets for your team.

Project: {project.name} [{project.key}]
Brief:
{project.brief}

Your team:
{roster}

Available role keys: {", ".join(roles)}

Rules:
- 4 to 8 tickets. Each is one focused piece of work one person can finish alone.
- Order them so that dependencies come first (design before implementation,
  implementation before QA, documentation last).
- Every ticket needs concrete acceptance criteria that someone else could check.
- Set "role" to the role key of whoever should do it. Only use roles on the team.
- Do not create tickets for work no one on the team can do."""


REVIEW_PROMPT = """You are reviewing a colleague's finished work.

{ticket_block}

What they reported:
{result}

Files in the workspace:
{file_list}

Check the work against the acceptance criteria using your tools: read the files
they claim to have written, and run the tests with run_command. Then either:
- update_ticket with status=done if it genuinely meets the criteria, or
- update_ticket with status=todo and comment_ticket explaining precisely what is
  missing, so they can fix it.
Be strict but fair: reject work that does not exist in the workspace."""
