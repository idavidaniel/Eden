# Eden v2 — implementation plan

What we have is a working software company: a manager plans, engineers write code
in a git repo, a QA agent reviews, and the platform refuses to believe any of them
until it runs the build itself. That verification gate is the best thing in this
codebase and everything below is built around it.

What you asked for:

1. Every employee is an individual agent with its own API and memory.
2. Companies in any industry, not just software.
3. A cleaner, minimal, modern, multi-page interface.
4. Enhancements beyond what anyone has done.
5. Agents that can do all kinds of development and work.

Those are not five features. They are one architectural move and its consequences.

**The move:** today an employee is a database row that `engine.py` reads while
executing a run. In v2 an employee is a persistent, addressable agent — its own
memory, credentials, budget, model policy and HTTP endpoint — and a *run* becomes
just one of several things that can send it work.

Everything else follows. Any-industry needs the work spine generalised
(Ticket → WorkItem, files → Artifact, `verify_command` → Check). All-kinds-of-work
needs the capability plane widened (workspaces beyond git, the internet, real
connectors). The interface has to show an organisation of agents instead of a board
of tickets. And "beyond anyone" is the thing this codebase has already half-earned:
**nobody else refuses to believe their agents.** Push that all the way to a provable,
replayable record for every deliverable.

---

## Measured constraints

Five things I verified against the running stack rather than assumed. Two of them
change the design.

| Question | Answer | Consequence |
| --- | --- | --- |
| Is pgvector actually there? | **Yes — 0.8.6, extension already created** in `agent_db` | No infra work. `CREATE EXTENSION` is already done by the image. |
| HNSW dimension ceiling? | **2000** on `vector` (confirmed by error); `halfvec(2048)` indexes fine | Rules out the 2048-dim Nemotron embedders for a plain `vector` column. |
| Embeddings on the same NVIDIA key? | **Yes.** `nv-embedqa-e5-v5` → 1024 dims, asymmetric query/passage, 3 passages in 0.72s | Pick this one: 1024 is HNSW-safe, and asymmetric retrieval is exactly right for memory. Batch — 7 sequential single calls timed out at 2 min; a batch of 3 took 0.72s. |
| How many models on that endpoint? | **102**, incl. `llama-3.1-nemotron-ultra-253b-v1`, `kimi-k3`, `deepseek-v4-flash`, `gpt-oss-120b`, code and vision models, and three **NeMo Guard** safety models | Per-employee model routing is a different `model` string. Same base URL, same key. The safety layer is off-the-shelf. |
| Context window of the working model? | **≥ 400,000 tokens** (400,017 counted, 17.8s; 200k in 1.5s) | **This overturns the usual memory design.** |

That last row matters most. Letta/MemGPT-style memory exists because the window is
small. Ours isn't. So the purpose of memory here is **not compression — it is
curation and truth.** We could stuff 400k tokens in. We shouldn't, because 400k
tokens costs ~18s of prefill and real money on every turn, and irrelevant context
measurably degrades tool-calling accuracy. We target ~24k tokens per turn and spend
the engineering on choosing *which* 24k, and on proving the memories are true.

The real scarce resources are **output tokens** (currently `MAX_TOKENS=4096`),
**latency**, and **money** — not context.

---

## Where the existing code helps and where it fights

Grounded in the current tree, not guessed:

**Already shaped for this**

- `ToolContext.run` is already `Run | None`, and `run_agent_turn()` only writes a
  `RunStep` `if ctx.run` — so a single employee turn outside a batch run already
  works. ([tools/base.py:15](../backend/agents/tools/base.py), [engine.py:109](../backend/agents/engine.py))
- `structured_call()` with a forced tool call is reliable for structured output.
  Every new machine-readable output in this plan uses it. ([llm.py:113](../backend/agents/llm.py))
- The tool registry already filters by employee and refuses ungranted tools in
  `execute()`. Grants just move from role-derived to per-identity. ([tools/__init__.py](../backend/agents/tools/__init__.py))
- `services/crypto.py` already seals secrets; `services/identity.py` already mints a
  token per employee per tool.
- `Activity.seq` is a monotonic cursor and the SSE stream already honours
  `last-event-id`. Replay is solved.
- `workspace.check_command()` is a clean, shared validator — the natural place to
  hang runner profiles.

**Fights us**

- **Five phase functions take `run: Run` positionally** — `plan_run`, `work_ticket`,
  `verify_project`, `review_ticket`, `wrap_up`. The turn layer is free; the phase
  layer is not. That is the seam to cut on, and it is smaller than 870 lines suggests.
- **No Alembic.** `db.py:ADDED_COLUMNS` is a hand-maintained list of `ALTER TABLE …
  ADD COLUMN`. `create_all` handles new tables fine, so most of v2 lands without it —
  but nothing that *renames*, *backfills*, *changes a type* or *adds a constraint*
  can ship this way. Phase 0.
- **`services/roles.py` is a hardcoded software catalogue** with `writes_code` and
  `manages` booleans. It has to become data.
- **`verify_command: String(255)`** — one shell command per project is the entire
  verification vocabulary.
- **`identity.py` mints credentials nothing authenticates against.** `reveal()` shows
  them in the UI; no code path ever checks one. The MCP bridge checks that a bearer
  token is *present*, not that it is *valid*.
- Tool handlers return `str`. No artifacts, no sources, no structured errors.
- The SQLite test path: `Activity.seq` already needs
  `BigInteger().with_variant(Integer, "sqlite")`. `Vector` columns and `JSONB` need
  the same treatment or the 56 tests stop running.

---

## Layer 1 — Agents that are actually agents

### Tables

Keep `employees` (it is your word, and renaming costs a migration for nothing). Add:
`model_policy JSON`, `autonomy_level`, `budget_daily_cents`, `spend_mtd_cents`,
`api_enabled`, `state`, `heartbeat_at`.

```
memory_blocks   id, employee_id, label, content TEXT, char_limit, pinned, version, updated_by, updated_at
                -- labels: persona | company | focus | human. Always in context.

memories        id, company_id, employee_id NULL, kind, scope, title, body TEXT,
                embedding vector(1024), source_kind, source_id, outcome, confidence FLOAT,
                uses INT, last_used_at, decay_at, superseded_by NULL, created_at
                -- kind:  episode | fact | procedure
                -- scope: private | team | company     (employee_id NULL + company = org memory)
                -- INDEX USING hnsw (embedding vector_cosine_ops)

agent_tokens    id, employee_id, name, prefix, hash, scopes JSON, expires_at, last_used_at, revoked_at
agent_tasks     id, employee_id, source, request JSON, status, result JSON, run_id NULL,
                created_by, lease_until, started_at, finished_at
usage_events    id, company_id, employee_id, task_id, model, prompt_tokens, completion_tokens,
                cost_cents, latency_ms, created_at
```

### The API

```
POST   /agents/{id}/messages                 one turn, synchronous, returns reply + tool calls
POST   /agents/{id}/tasks                    202 + task id
GET    /agents/{id}/tasks/{tid}              poll
GET    /agents/{id}/tasks/{tid}/stream       SSE
GET    /agents/{id}/card                     public agent card: who they are, skills, tools, endpoint
GET    /agents/{id}/memory                   blocks + searchable memories
PUT    /agents/{id}/memory/blocks/{label}
POST   /agents/{id}/memory                   teach a fact
DELETE /agents/{id}/memory/{mid}             forget
POST   /agents/{id}/tokens                   mint (shown once)
DELETE /agents/{id}/tokens/{tid}             revoke
GET    /agents/{id}/usage
```

Auth is `Authorization: Bearer edn_<prefix>_<secret>`: look up by indexed `prefix`,
verify with the existing `crypto.verify_secret`. Scopes: `agent:message`, `agent:task`,
`memory:read`, `memory:write`, `tools:<group>`. One FastAPI dependency, `current_agent()`.

The same token authenticates the MCP bridge, which replaces `MockOAuthMiddleware`
with something real. That closes the loop: the credentials on the employee profile
page stop being set dressing and start being the actual key to that employee.

### Memory

Five kinds, one table, because they share a retrieval path:

- **Core blocks** — always in context, agent-editable via a `memory_edit` tool,
  hard char limits. Persona, company, current focus, and what they know about *you*.
- **Episodic** — what this employee did and how it turned out, labelled
  `shipped | rejected | reopened | abandoned`.
- **Semantic** — facts learned about the company, the codebase, the client, the domain.
- **Procedural** — "how I do X here", distilled from work that passed.
- **Organisational** — promoted from personal, gated (below).

**Context assembly** — a relevance budget, not a size budget. Target ~24k tokens:

| Tier | Contents | Budget |
| --- | --- | --- |
| 0 | system prompt + 4 core blocks | ~2.5k |
| 1 | the work item, its checks, and the **last check result verbatim** | ~2k |
| 2 | k=8 semantic memories, ranked `similarity × confidence × recency × outcome_weight` | ~4k |
| 3 | k=3 procedures matching the work-item kind | ~3k |
| 4 | k=5 episodes with matching tags, **weighted toward failures** | ~3k |
| 5 | artifact excerpts, file list, chat tail (as today) | ~9k |

Tier 4 is a deliberate opinion: an agent should remember what got rejected more
strongly than what sailed through. Rejections are where the information is.

**Reflection** runs when a work item closes, not on a timer. One forced tool call —
`record_learning(facts[], procedure|null, episode_summary, outcome)` — then dedupe by
embedding: cosine > 0.92 merges (bump `uses`, keep higher confidence); 0.75–0.92 with a
detected contradiction sets `superseded_by` on the older row.

**The learning gate.** An agent may only distil a `procedure` from a work item whose
checks *passed*. The verification gate becomes the learning gate. An agent cannot
learn a lesson from work that was never proven to work — which is precisely the
failure mode that burned this project before.

**Promotion** private → team → company requires ≥3 uses across ≥2 distinct agents'
passed work items, or explicit human approval. One agent's wrong belief does not get
to poison the company.

**Forgetting**: `decay_at` set on write, reset on retrieval; never-retrieved,
low-confidence memories archive after 90 days — soft-deleted, still visible in the UI.

**Proving it works.** Not a vibe: the eval harness (Layer 6) runs a fixed brief set
with memory on and off and reports first-try check pass rate, tool calls per work
item, and tokens per accepted artifact. If those numbers do not move, the memory
system is not earning its complexity and we say so.

### Model routing

`model_policy` per employee, e.g.
`{"default": "nvidia/nemotron-3.5-lightning-30b-a3b", "plan": "nvidia/llama-3.1-nemotron-ultra-253b-v1", "review": "moonshotai/kimi-k3", "embed": "nvidia/nv-embedqa-e5-v5"}`.
All 102 models sit behind one base URL and one key, so this is a lookup, not an
integration. Every call writes a `usage_events` row.

---

## Layer 2 — The work spine, for any industry

**WorkItem → Artifact → Check.**

```
work_items      (evolves tickets) + kind, depends_on JSON, deliverable_spec JSON,
                capability_hint, budget_tokens, due_at, approval_required
artifacts       id, project_id, work_item_id, kind, name, storage, locator, version,
                content_hash, produced_by, superseded_by, meta JSON
                -- storage: git | blob | rows | external
checks          id, project_id NULL, work_item_id NULL, artifact_kind NULL,
                name, kind, spec JSON, required, order
check_results   id, check_id, work_item_id, artifact_id, run_id, status, score NULL,
                detail TEXT, evidence JSON, ran_at, duration_ms
```

`Ticket` becomes `WorkItem` in place (rename + `kind` backfill — Alembic, Phase 0).
`project.verify_command` becomes one `checks` row of kind `command`, so nothing regresses.

### Verification without a compiler

This is the hard part, and the part that decides whether v2 is real. Six check kinds,
every one run **by the platform**, never self-reported:

| kind | how the platform runs it | example |
| --- | --- | --- |
| `command` | today's `workspace.run()` | `pytest -q`, `dart analyze .` |
| `schema` | jsonschema / a parser | "the model file parses and has the required sheets" |
| `assertion` | a small safe expression evaluator over extracted values | "line items sum to the total, ±0.01" |
| `citation` | every claim-tagged sentence resolves to a `sources` row **whose stored text literally contains the quote** | research memos |
| `rubric` | an independent evaluator agent against a fixed rubric | "does this contract include a limitation-of-liability clause?" |
| `human` | a blocking approval gate | partner sign-off before filing |

The `rubric` check is the soft spot, so it gets four hard mechanisms:

1. The evaluator never sees the author's self-report or the author's name — both stripped.
2. The rubric is fixed **before** the work starts (declared at planning time), so it
   cannot be written to fit the output.
3. Each criterion is answered by forced tool call as
   `{criterion_id, verdict, evidence_quote}` — and **`evidence_quote` must appear
   verbatim in the artifact.** The platform string-matches it; a quote that isn't
   there marks the criterion `error`, not `pass`. That is a mechanical hallucination
   check on the verifier itself.
4. N=3 evaluators, optionally on different models. Record agreement. Below threshold
   → escalate to a human. Never average a disagreement into a pass.

### Industry packs

A pack is a YAML file loaded into DB tables at company creation, editable afterwards.

```yaml
key: law_firm
name: Law firm
departments: [Practice, Research, Compliance, Client]
roles:
  - key: managing_partner
    title: Managing Partner
    manages: true
    capabilities: [plan, delegate, approve, client_comms]
  - key: associate
    title: Associate
    capabilities: [draft_document, legal_research, cite_check]
artifact_kinds:
  - key: contract_draft
    storage: blob
    renderer: document
    default_checks: [required_clauses, defined_terms_used, citation_check]
work_item_kinds: [matter, drafting_task, research_question, review, filing]
checks:
  - key: required_clauses
    kind: assertion
    spec: {must_contain_sections: [Term, Termination, Limitation of Liability, Governing Law]}
  - key: defined_terms_used
    kind: assertion
    spec: {rule: every_capitalised_defined_term_has_a_definition}
handbook: |
  ...
```

Ship five: **software_studio** (today's behaviour, byte for byte, so the 56 tests stay
green), **law_firm**, **marketing_agency**, **research_lab**, and **blank** — where you
define the roles, artifacts and checks yourself in the UI.

`services/roles.py` becomes a loader plus the software pack. Roles move to a table.
The planner assigns by **capability**, not by hardcoded role key.

### All kinds of development, without a 40GB image

Runner profiles. `backend/runners/*.yaml` declares image, allowed commands, timeouts
and cache volume. `workspace.run()` gains a `profile` argument:

- profile is in-image (`python`, `node`, `flutter`, `dart`, `git`) → today's subprocess path;
- otherwise → `docker run --rm --network=none -v workspace:/w -w /w <image> <argv>`
  through the mounted socket, with the *same* allow-list, path guard and timeout logic.

Images pull on first use rather than being baked in. Base image stays ~3.5GB. Profiles
worth shipping: `go`, `rust`, `jvm`, `dotnet`, `data` (duckdb + pandas), `latex`.

---

## Layer 3 — The capability plane

- **Tool contract v2.** `Tool` gains `scopes`, `cost_hint`, `requires_connection`,
  `destructive`. Handlers return `ToolResult{text, artifacts[], sources[], error_hint}`
  instead of a bare `str`. `error_hint` is the sentence that teaches the model how to
  recover — the same trick that made `edit_file` work.
- **Grants move from role to identity**: `tool_grants(employee_id, tool_or_group,
  scopes, granted_by, expires_at)`. `employee.toolbelt` becomes the seed, not the rule.
- **`tool_calls` audit table** — every call, args redacted, duration, cost, work item.
  Raw material for the ledger and for spotting repeated manual work.
- **Non-code workspaces**, each with the platform-can-verify-it property: documents
  (sections + citations, checked by `citation`/`rubric`), spreadsheet models
  (formulas evaluated server-side, checked by `assertion`), data (a per-project DuckDB,
  SQL + charts, checked by `command`), research (fetch/search with a source ledger).
  Design/media is honestly limited: SVG and HTML mockups yes, real image generation no.
- **The internet** — today's biggest gap; agents cannot reach it at all. `services/web.py`
  with `fetch`, `search`, `browse`. Default-deny egress allow-list per company. Every
  fetch writes a `sources` row (`url, fetched_at, content_hash, title, text_path`) so
  citation checks have something to resolve against.

  Injection defence, concretely, not as a slogan: fetched text enters context inside
  `<untrusted-source id="src_7">…</untrusted-source>`; the system prompt says content
  in those envelopes is data; **and state-changing tools are blocked in the same turn
  as a fresh fetch** — the agent must summarise the source in one turn before acting in
  the next. Plus `nvidia/llama-3.1-nemoguard-8b-topic-control` on fetched text, which
  we already have access to.
- **Real connectors.** `services/connectors/{github,jira,slack,notion,gdrive}.py`, each
  a small interface (`list_items`, `create_item`, `update_item`, `comment`). The tracker
  tool dispatches on the company's `connections` row — `create_ticket` writes to Jira when
  connected, to the built-in tracker when not. Same tool surface either way. Secrets use
  the existing `crypto.seal`.
- **MCP both ways.** We are already an MCP server. Add the client: `mcp_clients` +
  `mcp_tools` tables, per-employee grants, and failure isolation so a dead server
  degrades to "tool unavailable" rather than breaking a turn.
- **Safety**: egress policy, spend cap, `destructive` tools requiring approval, secret
  redaction in logs *and* in model context, and a per-company kill switch.

---

## Layer 4 — The organisation runs

- **Org clock.** `services/clock.py`: one daemon thread ticking every few seconds.
  Lease due `agent_tasks` and ready `work_items` with `SELECT … FOR UPDATE SKIP LOCKED`
  (Postgres-native, safe under concurrency), dispatch to the existing thread pool, renew
  leases by `heartbeat_at`, requeue on expiry. A Run becomes a *label grouping tasks*,
  not the execution driver. `execute_run()` survives as a thin wrapper so nothing regresses.
  The existing orphan-release at startup generalises to lease expiry.
- **Work graph, not work list.** `depends_on` + a ready-set. Cycle detection at plan
  time rejects the plan and re-asks the planner (forced tool call, so it can be retried
  mechanically). A failed dependency blocks its dependents *with a reason* rather than
  silently skipping them.
- **A real agent protocol.** `agent_messages(kind, from_id, to_id, work_item_id, body,
  payload, thread_id, replies_to)` with `kind ∈ request | accept | decline | deliver |
  question | escalate`. Delivered to an inbox that wakes the recipient on the next tick.
  Ping-pong is bounded: `thread_id` + hop counter, max 6 hops, then auto-escalate to the
  manager, then to you.
- **Handoff packets.** When A hands to B, A must emit `{what_i_did, where_it_is,
  what_you_need_to_know, what_i_could_not_do}` by forced tool call. B reads the packet
  instead of re-reading the world. Cheap, and it is what real teams do.
- **Meetings that produce artifacts.** Standup, planning, design review, retro — each
  ends in `{decisions[], action_items[{owner, what, due}], risks[]}`. Action items become
  work items automatically. A retro additionally writes procedural memories, subject to
  the learning gate.
- **Human in the loop.** `approvals(subject_kind, subject_id, requested_by, reason,
  status, decided_by)`. Destructive tools and `human` checks create one and **block the
  lease**. One "Needs you" queue. A budget ceiling breach raises an approval rather than
  dying quietly. Interrupts land mid-turn by checking a cancellation flag between tool
  calls — the loop in `run_agent_turn` already has the natural place for it.
- **Performance from real data.** `check_results` gives first-try pass rate, rework rate,
  tokens per accepted artifact, time to done — per employee. A coaching loop proposes a
  persona or procedure edit for an underperformer; you approve; it applies with version
  history and a rollback.

---

## Layer 5 — The interface

One direction, committed to: **a quiet instrument panel.** Light-first, near-white
surfaces, one accent, hairline borders, typography-led, dense but unhurried. No glass,
no emoji. The product's job is to make you trust a machine's report about work you did
not watch — that calls for the visual language of an instrument, not a toy dashboard.

```css
:root {
  --bg:#fbfbfa; --surface:#ffffff; --raised:#f6f6f5;
  --line:#e6e6e3; --line-strong:#d4d4d0;
  --text:#17171a; --muted:#6b6b70; --faint:#9a9aa0;
  --accent:#2f5fe0; --accent-soft:#eef2fe;
  --pass:#1a7f4b; --fail:#c0392b; --warn:#a86a00;
  --radius:8px; --radius-lg:12px;
  --font:"Inter",ui-sans-serif,system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,monospace;
  --dur:140ms; --ease:cubic-bezier(.2,.6,.3,1);
}
:root[data-theme="dark"] {
  --bg:#0d0d0f; --surface:#141417; --raised:#1a1a1e;
  --line:#26262b; --line-strong:#33333a;
  --text:#f2f2f3; --muted:#9a9aa2; --faint:#6a6a72;
  --accent:#7d9dff; --accent-soft:#161c33;
  --pass:#3ecf8e; --fail:#ff6b5e; --warn:#e0a33a;
}
```

Type scale 12/13/14/16/20/28/36. Icons: **Lucide** as a real dependency — hand-rolling
eighty icons is weeks of work for a worse result, and it tree-shakes.

### Routes

```
/                              companies
/c/[company]                   home — what happened, what needs you
/c/[company]/agents            roster + org chart
/c/[company]/agents/[id]       the agent page
/c/[company]/work              board | list | graph | timeline
/c/[company]/work/[item]       work item, its checks, its artifacts
/c/[company]/artifacts         every deliverable, by kind
/c/[company]/artifacts/[id]    per-kind renderer, versions, provenance
/c/[company]/studio/[ws]       code | docs | data | research
/c/[company]/knowledge         wiki
/c/[company]/rooms             chat + meetings
/c/[company]/ops               live operations: tasks, checks, cost
/c/[company]/inbox             approvals, questions, escalations
/c/[company]/connections       MCP servers, connectors, egress policy
/c/[company]/settings
```

Today's `/companies/[id]/*` routes 301 to `/c/[slug]/*`.

### The screen that defines the product

`/c/[company]/agents/[id]`. Header: name, title, live state, today's spend against
budget, first-try pass rate. Five tabs:

1. **Overview** — current work, recent artifacts, pass rate over time, reporting line.
2. **Memory** — the four core blocks as editable cards with char counters; below them
   the memory table (kind, scope, confidence, uses, last used) with a search box that
   runs **the actual vector query**, so you can see what this agent would retrieve for a
   given prompt before it runs. Teach. Forget. Contradiction badges.
3. **Work log** — every turn, tool call and check verdict. The audit trail.
4. **API** — endpoint, tokens (mint / rotate / revoke, shown once), scopes, a
   copy-pasteable `curl`, usage graph.
5. **Config** — persona, capabilities, tool grants, model policy per task kind,
   autonomy level, budgets.

### Honesty as a design element

Every claim carries a provenance chip: `✓ verified · pytest -q · 3m ago` in `--pass`,
or `claimed · unverified` in `--muted`. An artifact no check has touched says so
plainly. A rubric-scored artifact shows the score *and* the evaluator agreement. Cost
is always on screen. **The UI never renders an agent's self-report as a fact.**

### Data layer

TanStack Query for cache and invalidation, plus one multiplexed SSE connection per
company that pushes **invalidation keys, not payloads**. 200 events/second becomes 200
cheap invalidations coalesced into a handful of refetches, instead of 200 re-renders.
Reconnection reuses the `last-event-id` support that already exists.

---

## Layer 6 — Proof, and what is actually new

### The work ledger

Every consequential event appends a hash-chained row:

```
ledger  seq, company_id, prev_hash, hash, kind, actor_id, subject, payload JSON, at
        hash = sha256(prev_hash || canonical_json(payload))
```

Covering: brief accepted, plan produced, item assigned, every tool call, every artifact
version by content hash, every check result, every approval.

- `GET /projects/{id}/ledger/verify` recomputes the chain **and re-runs every
  deterministic check against the recorded artifact hashes.** "Was this really tested?"
  becomes a command, not a conversation.
- Tamper-evident: you cannot retroactively claim a check passed.
- Exportable as a signed `work-record.json` you can hand a client or an auditor.

### Honest novelty

| Idea | Who has it | What is actually new here |
| --- | --- | --- |
| Hash-chained deliverable provenance + automated re-verification | audit logs are everywhere; **this is not** | The chain covers artifact hashes and check results, so a finished deliverable can be independently re-proved later |
| **Learning gate** — only passed work becomes procedural memory | nobody | Institutional learning that cannot learn from failure dressed as success |
| Evaluator verified by literal-quote matching | rubric grading is common; the mechanical quote check is not | Catches a hallucinating verifier without another model |
| Eval harness over a whole simulated company | standard for single agents | Not standard for an org: staffing, process and memory become measurable variables |
| Per-employee API + memory | Letta/MemGPT do this for agents | New in an *org* context: an employee you can curl, with a manager and a performance record |
| Agent-authored tools behind a review gate | Voyager-ish, research-stage | Gated on the same check framework as everything else |
| Cost/quality routing per role | emerging | We have 102 models on one key — routing is a lookup, and quality-per-dollar is measurable per employee |
| Counterfactual staffing simulation | nobody | Genuinely novel, genuinely expensive — deferred past v2 |

The first two are the ones I would build the product's identity around.

---

## Phases

Every phase leaves `main` working and ends in something you can see.

| # | Phase | Days | Ends with |
| --- | --- | --- | --- |
| **0** | **Foundations** — Alembic baselined against the current schema, agent tokens + auth dependency, `usage_events`, ledger table + writer | 4 | An employee's token actually authenticates. A cost figure appears. Nothing else changes. |
| **1** | **Agents are real** — memory tables, embeddings service, retrieval, context assembler, reflection with the learning gate, `/agents/*`, the Agent page Memory tab | 7 | `curl` a specific employee and get work done. Watch memory fill up. The A/B eval reports whether it helped. |
| **2** | **Work spine** — WorkItem / Artifact / Check / CheckResult, the six check kinds, artifact viewer | 8 | Non-code deliverables get verified. The 56 existing tests stay green. |
| **3** | **Any industry** — pack loader, 5 packs, DB-backed roles, new company flow | 6 | Found a law firm. It has partners, matters, contract drafts and clause checks. |
| **4** | **Capabilities** — tool contract v2, grants, audit, internet + source ledger + injection envelope, runner profiles, GitHub + Jira connectors, MCP client | 8 | Agents research on the web with citations, build Go and Rust, and write to your real Jira. |
| **5** | **The org runs** — clock + leases, work graph, inbox + protocol, handoffs, meetings→artifacts, approvals, performance | 8 | The company keeps working without a "run". "Needs you" is a real queue. |
| **6** | **The interface** — tokens, Lucide, primitives, TanStack Query + multiplexed SSE, all routes, provenance chips | 10 | The redesign. Can run in parallel with 4–5. |
| **7** | **Proof & frontier** — ledger verify + export, eval harness + suites, agent-authored tools, model routing | 7 | `POST /ledger/verify` re-proves a finished project from scratch. |

**≈ 58 engineer-days**, about twelve weeks solo, ten if 6 overlaps 4–5.

**Cut from v2, deliberately:** cross-company agent marketplace, time-travel forking,
counterfactual staffing simulation, image generation, full multi-tenancy (a single-user
password gate instead), a mobile app.

---

## Decisions I need from you

1. **Scope of the first cut.** Phases 0–3 (~25 days) gets you agents-with-memory and
   any-industry on today's UI. Phases 0–6 is the whole thing. Which are we building?
2. **Interface direction.** I picked light-first "quiet instrument". The current app is
   dark. If you want to stay dark-first, say so now — it changes the token layer, not
   the plan.
3. **Internet access.** It is the biggest capability unlock and the biggest new risk
   surface. Default-deny allow-list is the safe default; is that acceptable, or do you
   want fully open egress?
4. **Docker socket for runner profiles.** It is how we get Go/Rust/JVM without a 40GB
   image, and it is a real privilege escalation on the host. Fine on your laptop, not
   fine on a shared box. Your call.
5. **`MAX_TOKENS=4096`.** Given the 400k context, output is the real limit. Raising it
   costs money per turn but reduces step-limit failures. Worth an experiment in Phase 1.
