# Live schema migrations

`001_live_sessions.sql` is additive only (`CREATE TABLE IF NOT EXISTS`,
indexes, unique/FK). It does not drop or rewrite existing user/session/job
data.

- Run once per database, after a restore-point backup on Production.
- Do not use `Base.metadata.create_all` as a substitute for this file.
- Do not copy Production `DATABASE_URL` onto Staging.
