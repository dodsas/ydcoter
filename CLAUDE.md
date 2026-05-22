# Repo conventions for Claude

## Git workflow

- **Commit, but don't push.** When the user asks for a change, finish the work *and* create the commit yourself (no need to wait for "commit it"). Leave pushing to the user — they want to gate what reaches `origin`.
- Use the standard commit-message protocol (HEREDOC, `Co-Authored-By: Claude Opus ...` trailer). One commit per logical change; don't bundle unrelated edits.
- Never run `git push` unless the user explicitly says so in that turn.

## Runtime notes

- This app runs against **Turso (libSQL) in production** via `TURSO_DATABASE_URL`. Locally it can be either sqlite or Turso depending on `.env`. Turso uses the Hrana HTTP protocol, which **drops idle streams** — never hold a `get_conn()` connection across a slow external call (LLM, third-party HTTP). Split into read-phase / external-call / write-phase with separate `with get_conn()` blocks.
- `app/database.py` adapts libsql to a sqlite3-compatible surface. Params must be tuples on the libsql path (`tuple(params)` in `_Connection.execute`).

## Dev server

- Use `uvicorn app.main:app --port 8000 --host 127.0.0.1 --reload` so edits hot-reload. Logs land in `/tmp/ydocter-uvicorn.log` when started via `nohup ... &`.
