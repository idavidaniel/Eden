# Roadmap

## Done

### The spine

- [x] Alembic migrations, with a baseline that adopts a pre-migration database
      and a test that runs the whole chain — and its downgrades — on Postgres
- [x] Work items → artifacts → checks, replacing tickets-and-vibes
- [x] Six check kinds: command, schema, assertion, citation, rubric, human
- [x] Content-addressed deliverables; a file edited after it passed no longer
      hashes to what the ledger recorded
- [x] Hash-chained ledger, one per company, with `POST /ledger/verify`
- [x] Re-verification that replays deterministic checks and reports which ones
      no longer agree — and refuses to call an empty record proved

### Agents

- [x] Every employee addressable at `/agents/{id}/*` with its own token; a token
      is the key to one agent and cannot drive a colleague
- [x] Scoped tokens, revocable, hashed at rest, shown once
- [x] Memory: four always-loaded blocks plus a searchable store, vector when an
      embedding model is configured and lexical when not, saying which
- [x] The learning gate — a procedure may only be distilled from work whose
      checks passed, over HTTP as well as in the reflection pass
- [x] Failure-weighted ranking; contradictions supersede rather than overwrite
- [x] Six-tier context assembler that reports what each tier contributed
- [x] Per-employee model policy, daily spend cap, and measured token accounting

### Any industry

- [x] Industry packs as YAML → database rows; roles, work vocabulary,
      deliverable kinds and their checks
- [x] Five packs: software studio, law firm, marketing agency, research lab, blank
- [x] Roles read from the database, so a pack can be edited and re-applied

### Capabilities

- [x] Tool contract v2 with grants, audit and refusal reasons
- [x] Internet access with a default-deny allow-list, a source ledger, and an
      untrusted-source envelope
- [x] Read-only-after-fetch: a turn that read the web may not act until the next one
- [x] Container runner profiles (Go, Rust, JVM, .NET, LaTeX, Node, data, Flutter)
- [x] GitHub and Jira connectors behind the existing tool interface
- [x] MCP client — another server's tools appear alongside the built-in ones
- [x] Agent-authored tools behind a review gate, with their own examples re-run
      before approval

### The org

- [x] Org clock with `FOR UPDATE SKIP LOCKED` leasing and lease reclamation
- [x] Autonomy opt-in per company, and a halt switch that refuses every turn
- [x] Agent-to-agent protocol with hop limits and escalation
- [x] Meetings that must end in a structured outcome, which becomes work
- [x] Approvals that block work until a person answers
- [x] Performance read from finished work; coaching that proposes, never applies

### The interface

- [x] Design tokens with all three theme states; a serif for deliverables so a
      document reads as a document
- [x] One SSE connection per company, shared, driving query invalidation
- [x] Twelve routes under `/c/[companyId]`, with 308s from the old ones
- [x] The provenance chip: verdict, then method, then evidence

### Accounts

- [x] Tenants, users and sessions; every company scoped to the organisation
      that owns it, with existing data adopted rather than orphaned
- [x] bcrypt passwords, refused rather than truncated past bcrypt's 72-byte read
- [x] Short-lived access tokens, revocable rotating refresh tokens, and replay
      detection that ends every session of that user
- [x] TOTP with sealed secrets, hashed backup codes, and a setup step that does
      not switch anything on until a real code works
- [x] Rate limits on signup and login, plus a per-account lockout
- [x] Scoping enforced structurally — a contextvar and `api/lookups.py`, so a
      new route cannot forget it
- [x] Sign in, sign up, second factor and profile in the browser, with the
      session in HTTP-only cookies

### Proof

- [x] Exportable work record with a record hash
- [x] A/B eval harness (memory on vs off) that can report that the idea failed
- [x] 200 backend tests, lint and CI

## Next

- [ ] Invitations, so an organisation can have more than one person in it —
      and roles, so they need not all be owners
- [ ] Email verification, and the address change it would make safe
- [ ] Password reset. There is no way back in from a forgotten password
- [ ] Verify MCP bearer tokens against an IdP's JWKS rather than our own store,
      for clients that are not Eden agents
- [ ] Parallel work per employee — currently one turn each at a time
- [ ] Android SDK in the image so `flutter build apk` produces an installable app
- [ ] Run the eval suites repeatedly and publish the distribution; one run is
      not evidence and the harness says so
- [ ] Confluence connector, and an artifact kind that writes to it
- [ ] A UI for authored tools (proposing is agent-side; reviewing is API-only)
- [ ] Cost forecasting before a run, not just accounting after it
