-- Reverts 002_email_verification.sql (email verification feature removed).
-- Additive-safe: DROP ... IF EXISTS, so this is a no-op on any database that
-- never applied 002. Run once on every database where 002 was applied.

DROP INDEX IF EXISTS ix_users_verification_token;

ALTER TABLE users DROP COLUMN IF EXISTS verification_token_expires_at;
ALTER TABLE users DROP COLUMN IF EXISTS verification_token;
ALTER TABLE users DROP COLUMN IF EXISTS is_verified;
