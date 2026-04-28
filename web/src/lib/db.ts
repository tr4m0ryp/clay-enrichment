// Tombstone -- the previous postgres.js client lived here. All callers
// now go through @/lib/queries (typed Supabase reads/writes) or
// @/lib/supabase/server (raw clients). Keeping this re-export so any
// stragglers still resolve to the new admin client.

export { createSupabaseAdminClient } from "./supabase/server";
