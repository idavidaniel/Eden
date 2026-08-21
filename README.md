# Eden — AI employees that work as a company

Create a company, describe what it does, hire AI employees into real roles, and
give them a project. A manager breaks the brief into tickets, assigns them by
role, and the team works the board: writing code in a git workspace, running
tests, reviewing each other's work, documenting it in the wiki and coordinating
in chat — while you watch it happen live and interrupt when you want to.

```
                     ┌──────────────────────────────────────────┐
   You ─── brief ───▶│  Manager agent: plan → tickets → assign   │
                     └───────────────┬──────────────────────────┘
                                     │
        ┌───────────────┬────────────┼─────────────┬────────────────┐
        ▼               ▼            ▼             ▼                ▼
    Backend eng    Frontend eng    QA eng     Tech writer      Product mgr
        │               │            │             │                │
        └──── each acts through their own accounts on ──────────────┘
                 tracker · wiki · workspace(git) · chat
                                     │
                        every action ▼ appended to the activity feed → live UI
```

## What it does

| Surface | What is there |
| --- | --- |
| **Companies** | Found a company with a description, mission and handbook — every employee reads it before working. |
| **People** | Hire from a role catalogue (manager, PM, architect, backend, frontend, QA, writer, analyst, devops). Roster, org chart by reporting line, per-employee profile. |
| **Credentials** | Each employee gets a username, password and API token *per tool*, sealed at rest and revealable or rotatable from their profile. |
| **Projects & board** | Jira-shaped: epics/stories/tasks/bugs, six statuses, drag between columns, acceptance criteria, comments, and the agent's own work log per ticket. |
| **Code workspace** | A real git repo per project. Agents read, write, **run** (sandboxed) and commit under their own name. Browse the tree, edit in the editor, read diffs. |
| **Wiki** | Confluence-shaped spaces and pages with version history, written by the team as they work. |
| **Chat** | Channels shared with the agents. Mention someone (`@Ada`) and they pick it up, use their tools, and reply. |
| **Live feed** | Every tool call, commit, status change and message, streamed to the dashboard over SSE. |
| **Runs** | Start, pause, resume or stop an autonomous run. QA-rejected work comes back for a rework pass. |
| **MCP** | The same tool registry exposed over JSON-RPC 2.0, so external clients can act as an employee. |

## Quick start

```bash
cp .env.example .env     # add NVIDIA_API_KEY from https://build.nvidia.com
docker compose up --build
```

- Dashboard: http://localhost:3000
- API docs: http://localhost:8000/docs

Then either click "New company" in the dashboard, or run the scripted demo:

```bash
python3 scripts/demo.py
```

It founds a company, hires six employees, files a project brief and prints the
team's activity as they work through it.

## How a run works

1. **Plan** — the manager reads the brief and the roster, then writes 4–8 tickets
   with acceptance criteria and assigns each to the role that fits.
2. **Work** — for each ticket, that employee gets their persona, the company
   profile, the ticket, the workspace file list, the wiki index and recent chat.
   They then act through their tools until they stop.
3. **Review** — QA reads the acceptance criteria, inspects the files, runs the
   tests, and either closes the ticket or sends it back with a comment.
4. **Rework** — a second pass picks up anything QA rejected.
5. **Wrap up** — the manager posts the outcome to `#general`.

You can pause or stop between any two steps; the run checks before each one.

## Guardrails that matter

- **Toolbelts are enforced.** A manager calling `write_file` is refused by the
  registry, and their prompt tells them what they cannot reach and who to ask.
- **Commands are sandboxed.** `run_command` has no shell — no pipes, redirection
  or chaining — and only allows interpreters and inspection tools
  (`python3`, `pytest`, `node`, `ruff`, `ls`, `cat`, `grep`, `find`, `git`, …).
- **Workspaces are contained.** Every path is resolved and rejected if it escapes
  the project root.
- **Restarts are survivable.** Runs interrupted by a restart are marked as such
  instead of hanging in `running` forever.

## Repository layout

```
backend/
  config.py         environment-driven settings
  db.py             engine, session, schema creation
  models/           companies, employees, identities, projects, tickets, wiki, chat, runs
  api/              HTTP surface, one module per area
  agents/
    engine.py       plan → work → review → rework → wrap up
    llm.py          model client (tool calling, streaming, lenient JSON)
    prompts.py      system prompts, including the toolbelt briefing
    tools/          tracker, wiki, chat, workspace + registry with access checks
  services/         crypto (sealing), identity issuing, git workspaces, activity feed
  tests/            36 tests, no external services required
frontend/src/
  app/              App Router pages (company shell + 8 surfaces) and the API proxy
  components/       dashboard, board, workspace editor, wiki, chat, org chart, live feed
  lib/              typed API client, hooks, formatting
scripts/            demo.py (scripted company) and smoke_test.py (stack check)
```

## Tests

```bash
docker compose run --rm backend pytest      # or: cd backend && pytest
cd frontend && npm run lint && npm run build
python3 scripts/smoke_test.py               # against a running stack
```

The backend suite runs on SQLite with a stubbed model provider — no API key,
database or Redis needed.

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `NVIDIA_API_KEY` | — | Required for the employees to think |
| `MODEL` | `nvidia/nemotron-3.5-lightning-30b-a3b` | Any OpenAI-compatible NVIDIA model with tool calling |
| `SECRET_KEY` | `dev-insecure-key` | Seals employee credentials — change it for anything real |
| `DATABASE_URL` | set by compose | Postgres |
| `DATA_DIR` | `/data` | Where project git workspaces live |
| `MAX_AGENT_STEPS` | `24` | Tool calls one employee gets per ticket; they are warned 3 short of it |
| `MAX_RUN_PASSES` | `4` | Ceiling on passes; a run also stops once a pass finishes nothing |
| `RUN_CONCURRENCY` | `2` | Projects that can run at once |
| `API_URL` (frontend) | `http://localhost:8000` | Server-side only; the browser uses `/api/backend/*` |

## Not built yet

- External connectors. Tools sit behind an adapter and the built-in modules
  implement it; Jira Cloud, Confluence and GitHub adapters are not written.
- Authentication. There are no platform users — anyone who can reach the API is
  an admin of every company.
- MCP authorization verifies that a bearer token is present, not that it is valid.
- Runs execute tickets one at a time; employees do not work in parallel.
