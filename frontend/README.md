# EaaS Control Plane (frontend)

Next.js App Router dashboard for the agent platform. See the
[root README](../README.md) for the full stack.

```bash
npm install
npm run dev      # http://localhost:3000
```

- `src/app/page.tsx` — page shell
- `src/components/ControlPlane.tsx` — task form, live reasoning stream, output
- `src/lib/api.ts` — typed API client, including SSE parsing
- `src/app/api/backend/[...path]/route.ts` — server-side proxy to FastAPI

The browser only ever calls `/api/backend/*`. The backend location is a
server-side setting (`API_URL`, default `http://localhost:8000`), so no rebuild
is needed to point at a different environment.
