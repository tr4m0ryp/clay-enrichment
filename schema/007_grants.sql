-- 007_grants.sql
-- Tables and views created via raw SQL migrations don't inherit Supabase's
-- default privileges; we have to GRANT explicitly. Without this, even
-- `service_role` (which bypasses RLS) sees "permission denied" because the
-- underlying GRANT is missing. RLS policies on tables only kick in AFTER
-- the GRANT check passes.

begin;

grant usage on schema public to service_role, authenticated, anon;

-- service_role: full access. BYPASSRLS handles row-filtering separately.
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;

-- authenticated: full access on the table objects; the RLS
-- `authenticated_all` policies (D5, single-user model) gate which rows are
-- visible. Without a GRANT, RLS is never even evaluated.
grant select, insert, update, delete on all tables in schema public to authenticated;
grant usage, select on all sequences in schema public to authenticated;
grant execute on all functions in schema public to authenticated;

-- Default privileges so future tables / sequences / functions in public
-- inherit the same access. Avoids re-running this script for every
-- migration that adds a table.
alter default privileges in schema public
  grant select, insert, update, delete on tables to service_role, authenticated;
alter default privileges in schema public
  grant usage, select on sequences to service_role, authenticated;
alter default privileges in schema public
  grant execute on functions to service_role, authenticated;

commit;
