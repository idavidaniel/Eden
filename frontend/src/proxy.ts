import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * The first gate: nobody sees an application page without a session cookie.
 *
 * This is a redirect, not a security boundary. It cannot verify the token —
 * that needs the signing key, which belongs on the API — so a forged cookie
 * gets past it and is then refused by the backend on the first request. What
 * it buys is that a signed-out person lands on /login instead of watching a
 * dashboard flash up and then fill with error states.
 *
 * `middleware.ts` was renamed to `proxy.ts` in Next 16; same behaviour.
 */

const PUBLIC = ["/login", "/signup", "/2fa", "/forgot-password"];
const ACCESS_COOKIE = "eden_access";
const REFRESH_COOKIE = "eden_refresh";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // An access token expires every fifteen minutes, so its absence does not mean
  // signed out — the refresh cookie lasts a week and the client will exchange
  // it. Treat either as "probably signed in" and let the API be the judge.
  const hasSession =
    request.cookies.has(ACCESS_COOKIE) || request.cookies.has(REFRESH_COOKIE);
  const isPublic = PUBLIC.some((path) => pathname.startsWith(path));

  if (!hasSession && !isPublic) {
    const login = new URL("/login", request.url);
    // Come back to where they were trying to go, rather than dumping them home.
    if (pathname !== "/") login.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(login);
  }

  if (hasSession && isPublic && pathname !== "/2fa") {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  // Everything except the API proxy, Next's own assets, and static files.
  // Without the exclusions this would redirect the stylesheet to /login.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|ico)$).*)"],
};
