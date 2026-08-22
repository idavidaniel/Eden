# Roadmap

## Done

- [x] Companies with a profile (description, mission, handbook) that every
      employee reads before working
- [x] Role catalogue and hiring, org chart from reporting lines
- [x] Per-employee service accounts (username, password, API token per tool),
      sealed at rest, revealable and rotatable
- [x] Enforced toolbelts — the registry refuses tools an employee was not issued,
      and their prompt says who to ask instead
- [x] Ticket tracker: types, six statuses, acceptance criteria, comments,
      per-ticket agent work log
- [x] Git workspace per project: read, write, sandboxed run, commit as the employee
- [x] Wiki with spaces and version history
- [x] Chat channels where @mentioning an employee gets a real reply
- [x] Autonomous runs: plan → work → QA review → rework → wrap up, with
      pause/resume/stop and recovery from restarts
- [x] Live activity stream (SSE) behind every surface
- [x] MCP bridge exposing the same tools over JSON-RPC 2.0
- [x] 36 backend tests (SQLite + stubbed model), lint and CI

- [x] Flutter and Dart in the workspace image, so employees can scaffold,
      analyse and test real Flutter apps
- [x] Verification gate: a project command the platform runs itself; a failing
      build reopens the ticket regardless of what the employee reported
- [x] Web preview: build a Flutter package for the web and serve it from the board

## Next

- [ ] Android SDK in the image so `flutter build apk` produces an installable app

- [ ] Connectors: Jira Cloud, Confluence and GitHub adapters behind the existing
      tool interface, configured per company in Settings
- [ ] Platform authentication and per-user ownership of companies
- [ ] Verify MCP bearer tokens against an IdP's JWKS instead of checking presence
- [ ] Parallel employees inside one run (dependency-aware scheduling)
- [ ] Long-term memory per employee: what they learned on past projects
- [ ] Company knowledge base (upload documents, retrieval as a tool)
- [ ] Cost and token accounting per run, per employee
- [ ] Human approval gate for chosen actions (opt-in per company)
