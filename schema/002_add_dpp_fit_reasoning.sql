-- 002_add_dpp_fit_reasoning.sql -- Add DPP fit reasoning column to companies
ALTER TABLE companies ADD COLUMN IF NOT EXISTS dpp_fit_reasoning TEXT;
