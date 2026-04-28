import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import {
  createServerClient as createSsrClient,
  type CookieOptions,
} from "@supabase/ssr";
import { cookies } from "next/headers";

// ---------------------------------------------------------------------------
// Admin client. Uses the service-role key and bypasses RLS. Server-only --
// every consumer is a Server Component, Server Action, or Route Handler.
// Never import this from a "use client" boundary; the service-role key must
// not appear in any browser bundle.
// ---------------------------------------------------------------------------
export function createSupabaseAdminClient(): SupabaseClient {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) {
    throw new Error(
      "createSupabaseAdminClient: NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set",
    );
  }
  return createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
    db: { schema: "public" },
  });
}

// ---------------------------------------------------------------------------
// SSR session client. Uses the anon key + the request cookie store so that
// it can read the currently logged-in user's session. Use this when you
// need to know who is signed in (e.g. server actions that should respect
// RLS). For unfiltered data reads, prefer createSupabaseAdminClient().
// ---------------------------------------------------------------------------
export async function createSupabaseSsrClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error(
      "createSupabaseSsrClient: NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set",
    );
  }
  const cookieStore = await cookies();
  type CookieMutation = { name: string; value: string; options: CookieOptions };
  return createSsrClient(url, anonKey, {
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll: (cookieList: CookieMutation[]) => {
        try {
          for (const { name, value, options } of cookieList) {
            cookieStore.set({ name, value, ...options });
          }
        } catch {
          // Server Components cannot set cookies; ignore -- middleware
          // refreshes the session cookie on the next request instead.
        }
      },
    },
  });
}
