-- 008_add_embedding_only_status.sql
-- Multi-API diagnostic showed 23% of 'quota_exceeded' keys are alive
-- on gemini-embedding-001 (just project-frozen on generateContent).
-- Add 'embedding_only' as a first-class validation status so the
-- validator can distinguish "really dead" from "generate-blocked but
-- embed-live".
--
-- Only potential_keys has a check constraint on validation_status;
-- validated_keys.status is unconstrained text. Widen the one we have.

begin;

alter table potential_keys
  drop constraint if exists potential_keys_validation_status_check;
alter table potential_keys
  add constraint potential_keys_validation_status_check
  check (validation_status in (
    'pending','valid','invalid','quota_reached','quota_exceeded','embedding_only'
  ));

commit;
