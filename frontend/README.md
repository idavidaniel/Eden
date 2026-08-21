# Eden dashboard

Next.js App Router frontend for the AI-company platform. See the
[root README](../README.md) for the whole stack.

```bash
npm install
npm run dev      # http://localhost:3000
```

## Layout

| Path | Surface |
| --- | --- |
| `src/app/page.tsx` | Companies dashboard |
| `src/app/companies/[companyId]/` | Company shell (sidebar, live feed) + overview |
| `.../people`, `.../people/[employeeId]` | Roster, org chart, profile with credentials |
| `.../projects`, `.../projects/[projectId]` | Project list and the kanban board |
| `.../projects/[projectId]/code` | Git workspace: file tree, editor, commit diffs |
| `.../wiki`, `.../wiki/[documentId]` | Wiki spaces, pages and version history |
| `.../chat`, `.../settings` | Team channels, company profile and tools |
| `src/app/api/backend/[...path]/route.ts` | Server-side proxy to the FastAPI backend |

`src/lib/api.ts` is the typed client, `src/lib/hooks.ts` has the polling and
live-activity (SSE) hooks, and `src/components/` holds the surfaces.

The browser only ever calls `/api/backend/*`. The backend location is a
server-side setting (`API_URL`, default `http://localhost:8000`), so pointing at
a different environment needs no rebuild.
