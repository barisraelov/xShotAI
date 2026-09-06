# Live schema migrations

These files are for a **new Staging database only**.

- Do not run them against Production.
- Do not use Production `DATABASE_URL`.
- This round does **not** apply the migration.

On a brand-new empty Staging DB, `Base.metadata.create_all` at backend boot
(`backend/main.py`) will also create `live_sessions` and `live_shots`.
The SQL in `001_live_sessions.sql` is the explicit equivalent for operators
who prefer a migration step before first Staging traffic.
