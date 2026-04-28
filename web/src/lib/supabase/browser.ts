"use client";

import { createBrowserClient } from "@supabase/ssr";

// ---------------------------------------------------------------------------
// Browser client. Uses the anon key only (safe to ship to the browser).
// Used by the /login page to call supabase.auth.signInWithPassword().
// ---------------------------------------------------------------------------
export function createSupabaseBrowserClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error(
      "createSupabaseBrowserClient: NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set",
    );
  }
  return createBrowserClient(url, anonKey);
}
