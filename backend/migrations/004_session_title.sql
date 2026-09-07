-- Adds the user-editable `title` column to sessions (Edit Session Title).
-- Additive-safe: ADD COLUMN IF NOT EXISTS, no data rewrite. Existing rows
-- get NULL; the API/UI fall back to "Training Session" until the user sets one.
-- Run once on every database.

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS title VARCHAR(60);
