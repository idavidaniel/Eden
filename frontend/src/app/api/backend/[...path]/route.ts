// Same-origin proxy to the FastAPI backend.
//
// The browser never talks to the backend directly: that keeps the backend URL a
// server-side concern (so it can differ per environment without a rebuild, and
// `backend:8000` inside Docker resolves correctly) and avoids CORS entirely.

const API_URL = process.env.API_URL ?? "http://localhost:8000";

type Params = { params: Promise<{ path: string[] }> };

async function proxy(request: Request, { params }: Params) {
  const { path } = await params;
  const target = new URL(`${API_URL}/${path.join("/")}`);
  target.search = new URL(request.url).search;

  const headers = new Headers();
  for (const header of [
    "content-type",
    "authorization",
    "mcp-protocol-version",
    "accept",
    "last-event-id", // lets a reconnecting EventSource resume where it left off
  ]) {
    const value = request.headers.get(header);
    if (value) headers.set(header, value);
  }

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      // Required by undici when streaming a request body through.
      duplex: "half",
      cache: "no-store",
    } as RequestInit);

    // Streamed straight through, so server-sent events arrive event by event.
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        "cache-control": "no-cache, no-transform",
      },
    });
  } catch (error) {
    return Response.json(
      { detail: `Cannot reach the platform API at ${API_URL}: ${(error as Error).message}` },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
export const dynamic = "force-dynamic";
