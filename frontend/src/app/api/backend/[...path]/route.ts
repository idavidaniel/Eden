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

  const forwarded = new Headers();
  for (const header of [
    "content-type",
    "authorization",
    "cookie", // the session lives here; without it every call is anonymous
    "user-agent", // so "where you are signed in" can name the device
    "x-forwarded-for",
    "x-refresh-token",
    "mcp-protocol-version",
    "accept",
    "last-event-id", // lets a reconnecting EventSource resume where it left off
  ]) {
    const value = request.headers.get(header);
    if (value) forwarded.set(header, value);
  }

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers: forwarded,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      // Required by undici when streaming a request body through.
      duplex: "half",
      cache: "no-store",
    } as RequestInit);

    const headers = new Headers({
      "content-type": upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-cache, no-transform",
    });

    // Session cookies are set by the API and have to survive this hop, or
    // signing in appears to work and then does not. `getSetCookie` returns each
    // one separately; reading the header would fold them into one string and
    // corrupt any cookie containing a comma.
    for (const cookie of upstream.headers.getSetCookie?.() ?? []) {
      headers.append("set-cookie", cookie);
    }

    // Streamed straight through, so server-sent events arrive event by event.
    return new Response(upstream.body, { status: upstream.status, headers });
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
