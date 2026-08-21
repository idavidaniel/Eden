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
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("authorization", authorization);

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      // Required by undici when streaming a request body through.
      duplex: "half",
      cache: "no-store",
    } as RequestInit);

    // Streamed straight through, so server-sent events arrive token by token.
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        "cache-control": "no-cache, no-transform",
      },
    });
  } catch (error) {
    return Response.json(
      { detail: `Cannot reach the agent API at ${API_URL}: ${(error as Error).message}` },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const dynamic = "force-dynamic";
