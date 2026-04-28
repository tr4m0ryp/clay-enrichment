import { createSupabaseAdminClient } from "../supabase/server";

// Shared helpers used by every queries/* submodule. The Supabase client
// is created lazily per call (the `@supabase/supabase-js` createClient
// returns a lightweight wrapper, no expensive setup).

export function client() {
  return createSupabaseAdminClient();
}

export function unwrap<T>(
  data: T | null,
  error: { message: string } | null,
): T {
  if (error) throw new Error(error.message);
  return (data ?? ([] as unknown as T)) as T;
}
