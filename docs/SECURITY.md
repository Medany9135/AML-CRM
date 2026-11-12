# Security notes

Where Sanad stands on the usual launch checklist, and what still has to change before it holds real
customer data. The public demo (sanad-demo.streamlit.app) uses fictional data only.

| Item | Status | Notes |
|---|---|---|
| Authentication | Open: no login on main | Anyone with the link can see and change everything. A demo sign-in with roles exists on the `login-demo` branch, but it uses one public password. For real data, use proper sign-in (Streamlit's `st.login` with Google or Microsoft, or the Community Cloud viewer allow-list). |
| API keys | OK | `ANTHROPIC_API_KEY` is read from Streamlit secrets only. `.streamlit/secrets.toml` is in `.gitignore`, and no key has ever been committed (git history checked). The AI daily cap is counted in its own file (`ai_usage.db`) so "Reset to fresh dummy data" cannot reset it. |
| Database access | Demo-grade | SQLite file on the server, reached only through the app; every query uses placeholders (no SQL injection). All visitors share one database and anyone can reset it. On Community Cloud the file is wiped when the app restarts. For real data: a managed database (e.g. Postgres) with its own credentials in secrets, backups, and login first. |
| HTTPS | OK on Streamlit Community Cloud | The platform serves HTTPS only. If hosted elsewhere, put it behind a reverse proxy or load balancer that terminates TLS and redirects HTTP to HTTPS (with HSTS). |
| Password hashing | Not applicable yet | Main stores no passwords. If you add your own accounts, store only salted hashes (bcrypt or argon2), never the passwords. Single sign-on avoids storing passwords at all. |
| Server-side validation | Added | `db.py` checks every save, whatever screen it came from: allowed fields only, customer type, name required, length limits, valid dates, non-negative volume, shareholding 0-100%, known KYC statuses, rationale required, and approval blocked while sanctions alerts are open, a true match exists, or documents are missing. |
| XSS | OK | Streamlit never runs HTML or scripts typed into the app (tested). `ui.md()` also stops typed text from turning into links, remote images or formatting. Printable HTML reports escape all text. Excel exports neutralise text that starts with `=`, `+`, `-` or `@` so it cannot run as a formula. |

Also set in `.streamlit/config.toml`: visitors see short error messages without code or file paths,
uploads are capped at 25 MB, and Streamlit's cross-site request protection is kept on.
