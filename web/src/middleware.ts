import { NextResponse, type NextRequest } from "next/server";
import { createServerClient, type CookieOptions } from "@supabase/ssr";

// ---------------------------------------------------------------------------
// Auth gate. Every request that does not have a valid Supabase session is
// redirected to /login. The matcher excludes Next.js internals, the health
// API route, and the favicon. The /login page itself is allowed through so
// the user can sign in.
// ---------------------------------------------------------------------------
// Behind a reverse proxy (nginx -> next start --hostname 127.0.0.1), neither
// req.url nor req.nextUrl reflect the public host. Build the redirect URL
// from the forwarded headers so the Location points at the public origin.
function redirectTo(req: NextRequest, pathname: string) {
  const proto = req.headers.get("x-forwarded-proto") ?? "http";
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host") ?? req.nextUrl.host;
  return NextResponse.redirect(`${proto}://${host}${pathname}`);
}

export async function middleware(req: NextRequest) {
  const res = NextResponse.next({ request: req });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    // Fail closed -- if env is misconfigured, send everyone to /login so
    // we never accidentally serve unauthenticated dashboard pages.
    if (req.nextUrl.pathname.startsWith("/login")) return res;
    return redirectTo(req, "/login");
  }

  type CookieMutation = { name: string; value: string; options: CookieOptions };
  const supabase = createServerClient(url, anonKey, {
    cookies: {
      getAll: () => req.cookies.getAll(),
      setAll: (cookieList: CookieMutation[]) => {
        for (const { name, value, options } of cookieList) {
          req.cookies.set({ name, value, ...options });
          res.cookies.set({ name, value, ...options });
        }
      },
    },
  });

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const isLoginPath = req.nextUrl.pathname.startsWith("/login");
  if (!user && !isLoginPath) {
    return redirectTo(req, "/login");
  }
  if (user && isLoginPath) {
    return redirectTo(req, "/");
  }
  return res;
}

export const config = {
  matcher: ["/((?!_next|api/health|favicon.ico).*)"],
};
