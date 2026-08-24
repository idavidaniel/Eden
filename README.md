# Eden — companies of AI employees whose work is checked before it counts as done

Found a company in any industry. It is staffed with the roles that industry
actually has. Give it a brief; it plans the work, does it, and produces
deliverables — and nothing is marked done because an agent said so. Something
checkable has to agree.

Every employee is an addressable agent with its own memory, its own toolbelt,
its own budget and its own API token. The dashboard is one client of that API,
not a privileged path through the middle of it.

```
  You ── brief ──▶ plan ──▶ work ──▶ ARTIFACT ──▶ CHECK ──▶ done
                                         │           │
                                         │           ├── command   run it, read the exit status
                                         │           ├── schema    parse it against a schema
                                         │           ├── assertion match it against rules
                                         │           ├── citation  look every quote up in its source
                                         │           ├── rubric    a panel votes; a vote whose
                                         │           │             quote is not in the document
                                         │           │             is discarded
                                         │           └── human     you decide
                                         │
                                         └── hash ──▶ ledger ──▶ re-provable later
```

The last arrow is the point. `POST /projects/{id}/ledger/verify` re-reads the
hash chain, re-hashes every deliverable, and runs every deterministic check
again. If the file changed after it passed, or somebody quietly tightened the
standard, the report says so. If nothing was ever checked, it says that too —
an intact chain over an empty record is not evidence that any work was done.

## Any industry

An industry pack is a YAML file that decides the roles, the vocabulary for
work, the kinds of deliverable, and how each kind gets checked. Five ship:

| Pack | Roles | Work is called | Deliverables checked by |
| --- | --- | --- | --- |
| `software_studio` | manager, PM, architect, backend, frontend, QA, devops, writer, analyst, designer | task, bug, chore | a command that runs, plus rubrics |
| `law_firm` | managing partner, associate, paralegal, compliance, clerk | matter, drafting task | clause rules, defined-term checks, citations |
| `marketing_agency` | strategist, copywriter, designer, analyst, manager | campaign, brief, asset | tone rubrics, claim citations |
| `research_lab` | principal investigator, researcher, analyst, writer | study, experiment, paper | citation resolution, schema validation |
| `blank` | two generalists | task | nothing until you add some |

A law firm gets partners and contract drafts, not backend engineers and pull
requests. Roles live in the database, so a pack can be edited and re-applied.

## Every employee is an agent

```bash
# Mint a token for one employee, then talk to them.
curl -X POST localhost:8000/agents/$ID/messages \
  -H "Authorization: Bearer edn_..." \
  -d '{"message": "What is blocking SENSOR-3?"}'
```

A token is the key to **one** agent. It cannot drive a colleague — that is what
stops one compromised agent from becoming all of them. Scopes narrow it further.

| Surface | What is there |
| --- | --- |
| `GET /agents/{id}/card` | Who they are, every tool they can reach, which model answers which purpose |
| `GET /agents/{id}/prompt` | The exact system prompt they run with. Nothing hidden from you that is not hidden from them |
| `POST /agents/{id}/messages` | One turn, synchronously, with every tool call and a per-tier context report |
| `POST /agents/{id}/tasks` | Queue work; the org clock picks it up. SSE stream per task |
| `GET /agents/{id}/memory` | Their four always-loaded blocks and their searchable store, with a retrieval preview |
| `GET /agents/{id}/usage` | Tokens and cost, today/month/all-time, against their daily cap |

### Memory, and whether it earns its place

Four short blocks always in context, plus a searchable store of facts, episodes
and procedures retrieved per turn. Retrieval is by meaning when an embedding
model is configured and by words when it is not, and the interface says which.

Two rules do the work:

- **The learning gate.** An agent may only distil a *procedure* from a work item
  whose checks passed. You can teach it facts; know-how has to be earned. The
  HTTP endpoint refuses `kind: "procedure"` for the same reason.
- **Failure outranks success.** A rejection teaches more than a success, so the
  ranking weights it higher. A contradiction supersedes rather than overwrites —
  what an agent used to believe is evidence, so it is kept and marked.

Whether any of that helps is a claim, so it is measurable:

```bash
docker compose exec backend python /app/../scripts/run_evals.py software_studio
```

The suite runs a fixed set of briefs twice — memory on, memory off — in two
throwaway companies, and reports first-try check pass rate, tool calls per work
item, and tokens per accepted deliverable. It can conclude that the idea failed.

## The org runs without you

A clock leases queued work with `SELECT … FOR UPDATE SKIP LOCKED`, so two
processes never take the same task and a worker that dies mid-turn has its lease
reclaimed. It is **off per company by default**, because it spends money.

- One turn per employee at a time — they have one workspace and one identity.
- Agents message each other; a thread that goes round in circles is escalated to
  a manager, and if there is no manager, to you.
- A meeting that produces nothing did not happen: each one ends in a structured
  outcome that becomes work items.
- **Halt** refuses every turn immediately, including queued ones.

## What agents can reach

38 built-in tools across ten groups, plus any MCP server you register and any
tool an agent wrote that you approved.

- **Egress is default-deny.** Localhost, private ranges and link-local are never
  fetchable, even with the allow-list wide open.
- **A turn that read the web may no longer act.** Prompt injection works by
  getting the context that read the attacker's text to immediately do something;
  a turn boundary in the middle is the cheapest defence that holds. It costs one
  extra turn, only on turns that touched the internet.
- **Fetched text is enveloped** as `<untrusted-source>`, and kept, so a citation
  check can look a quote up in the page it claims to come from.
- **Commands have no shell** — no pipes, redirection or chaining — and container
  profiles (`go`, `rust`, `jvm`, `dotnet`, `latex`, `node`, `data`, `flutter`)
  run `--network=none` when enabled.
- **Every tool call is audited**, including the refused ones and why.

### Tools an agent wrote

An agent that keeps redoing the same calculation can propose a tool. The body is
a single expression run by the same AST-restricted evaluator assertion checks
use — no imports, no attribute access, no I/O. It must supply worked examples,
which run before you ever see the proposal, and again before approval. Nothing
is callable until a person approves it, and the approval goes in the chain with
the expression it approved.

## Quick start

```bash
cp .env.example .env     # add NVIDIA_API_KEY from https://build.nvidia.com
docker compose up --build
```

- Dashboard: http://localhost:3000
- API docs: http://localhost:8000/docs

## Repository layout

```
backend/
  models/           companies, employees, work items, artifacts, checks, memory,
                    ledger, tokens, tasks, grants, authored tools
  migrations/       Alembic, 0001 baseline adopts a pre-migration database
  api/              HTTP surface: companies, agents, ops, connections
  agents/
    engine.py       plan → work → verify → review → close out
    runtime.py      one turn: context, tools, budget, cancellation
    context.py      six-tier assembler; every tier reports what it contributed
    reflect.py      the learning gate
    tools/          ten groups + registry with grant and audit checks
  services/
    checks/         six check kinds; the AST-restricted expression evaluator
    ledger.py       hash chain, one per company
    proof.py        re-verification and the exportable work record
    memory.py       blocks, retrieval, merge, supersede, promote, decay
    clock.py        leasing, reclaiming, scheduling
    evals.py        the A/B harness
  packs/            five industry packs
  evals/suites/     the fixed briefs the harness runs
  tests/            200 tests, no external services required
frontend/src/
  app/c/[companyId]/  overview, agents, work, artifacts, studio, knowledge,
                      rooms, inbox, ops, connections, settings
  components/ui/      primitives, and the provenance chip
  lib/                API client, one shared SSE connection per company
```

## Tests

```bash
make test-backend        # 200 tests, SQLite, stubbed model provider
make test-migrations     # the real migrations, on a scratch Postgres database
make lint
```

The migration tests create a throwaway database, migrate it from empty to head,
and ask Alembic whether the result matches the models. One of them downgrades
every migration back to the baseline and up again, because a downgrade nobody
has run is a downgrade that does not work.

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `NVIDIA_API_KEY` | — | Required for the employees to think |
| `MODEL` | `nvidia/nemotron-3.5-lightning-30b-a3b` | Any OpenAI-compatible NVIDIA model with tool calling |
| `EMBEDDING_MODEL` | `nvidia/nv-embedqa-e5-v5` | 1024 dims. Without it, retrieval is lexical and says so |
| `SECRET_KEY` | `dev-insecure-key` | Seals credentials — change it for anything real |
| `DATABASE_URL` | set by compose | Postgres with pgvector |
| `DATA_DIR` | `/data` | Workspaces and the content-addressed blob store |
| `ORG_CLOCK` | `1` | The clock itself. Companies still opt in individually |
| `ENABLE_RUNNER_PROFILES` | `0` | Container-isolated toolchains. Needs a Docker socket |
| `MAX_AGENT_STEPS` | `32` | Tool calls per turn; they are warned 3 short |
| `RUN_CONCURRENCY` | `2` | Projects that can run at once |

## Known limits

- **No authentication.** There are no platform users: anyone who can reach the
  API is an admin of every company. Agent tokens authenticate *agents*, not you.
- **Cost is an estimate** from a configurable rate table. Tokens are measured.
- **Rubric checks need a model**, so re-verification reports them as recorded
  rather than replaying them. The report distinguishes the two.
- **No native app builds.** Flutter and Dart are in the image, so web builds
  work; there is no Android SDK, no Xcode and no display.
- **One turn per employee at a time.** Different employees run in parallel; one
  employee does not.
- **The eval harness is not a benchmark** against anyone else. It is a
  regression test on our own claims, and one run is not evidence.
