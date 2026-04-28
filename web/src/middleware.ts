import { NextResponse, type NextRequest } from "next/server";
import { createServerClient, type CookieOptions } from "@supabase/ssr";

// ---------------------------------------------------------------------------
// Auth gate. Every request that does not have a valid Supabase session is
// redirected to /login. The matcher excludes Next.js internals, the health
// API route, and the favicon. The /login page itself is allowed through so
// the user can sign in.
// ---------------------------------------------------------------------------
export async function middleware(req: NextRequest) {
  const res = NextResponse.next({ request: req });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    // Fail closed -- if env is misconfigured, send everyone to /login so
    // we never accidentally serve unauthenticated dashboard pages.
    if (req.nextUrl.pathname.startsWith("/login")) return res;
    return NextResponse.redirect(new URL("/login", req.url));
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
    return NextResponse.redirect(new URL("/login", req.url));
  }
  if (user && isLoginPath) {
    return NextResponse.redirect(new URL("/", req.url));
  }
  return res;
}

export const config = {
  matcher: ["/((?!_next|api/health|favicon.ico).*)"],
};
