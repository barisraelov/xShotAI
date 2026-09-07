-- Email verification for user accounts.
-- Additive only: ADD COLUMN IF NOT EXISTS + index. No DROP, no rewrite of
-- existing user data.
-- Production: run once after a restore-point backup. Base.metadata.create_all
-- creates NEW tables only and will not add these columns to an existing
-- `users` table, so this file must be applied by hand on every environment
-- whose database predates the feature.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS verification_token VARCHAR;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS verification_token_expires_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_users_verification_token
    ON users (verification_token);

-- Backfill: every account that already exists predates email verification, so
-- treat it as verified. New unverified signups always carry a token, which
-- this WHERE clause protects if the migration is ever re-run.
UPDATE users
    SET is_verified = TRUE
    WHERE is_verified = FALSE
      AND verification_token IS NULL;
