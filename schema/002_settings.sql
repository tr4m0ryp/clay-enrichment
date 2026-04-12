-- 002_settings.sql -- Settings and sender accounts

BEGIN;

CREATE TABLE settings (
    key         TEXT        PRIMARY KEY,
    value       TEXT        NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sender_accounts (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT        NOT NULL UNIQUE,
    password    TEXT        NOT NULL,
    daily_limit INTEGER     NOT NULL DEFAULT 10,
    is_active   BOOLEAN     NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_sender_accounts_updated_at
    BEFORE UPDATE ON sender_accounts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
