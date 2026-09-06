-- Live session schema (LIVE-18).
-- Additive only: CREATE TABLE IF NOT EXISTS + indexes + unique/FK.
-- No DROP, no ALTER of existing users/sessions/jobs tables.
-- Production: run once after a restore-point backup. Do not use create_all
-- as a substitute for this file.

CREATE TABLE IF NOT EXISTS live_sessions (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES users(id),
    status VARCHAR NOT NULL DEFAULT 'prepare',
    generation INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    history_session_id VARCHAR REFERENCES sessions(id),
    result JSONB
);

CREATE INDEX IF NOT EXISTS ix_live_sessions_user_id ON live_sessions (user_id);

CREATE TABLE IF NOT EXISTS live_shots (
    id VARCHAR PRIMARY KEY,
    live_session_id VARCHAR NOT NULL REFERENCES live_sessions(id),
    shot_id VARCHAR NOT NULL,
    result VARCHAR NOT NULL,
    decision_frame INTEGER,
    payload JSONB NOT NULL,
    degraded BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_live_shot_id UNIQUE (live_session_id, shot_id)
);

CREATE INDEX IF NOT EXISTS ix_live_shots_live_session_id ON live_shots (live_session_id);
