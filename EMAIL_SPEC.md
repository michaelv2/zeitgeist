# Add optional email distribution for daily reports

## Context

Zeitgeist generates a daily HTML investment memo and publishes it to GitHub Pages. The user wants to also email the report to a distribution list, with minimal code changes. Currently there is no config file in the project — all settings are either hardcoded constants or env vars. Python 3.12 is used.

## Approach

**Zero new dependencies.** Use only stdlib modules:
- `tomllib` (Python 3.12 builtin) for config parsing
- `smtplib` + `email.mime` (stdlib) for sending HTML email

### 1. Add `config.toml` (new file, gitignored)

```toml
[email]
recipients = [
    "alice@example.com",
    "bob@example.com",
]
```

Optional fields with sensible defaults:
- `subject_prefix` — defaults to `"Daily Memo"`
- `from` — overrides `SMTP_USER` as sender if set

### 2. SMTP credentials via env vars

Follows existing pattern (env vars + GitHub Secrets blanket injection):
- `SMTP_HOST` (e.g., `smtp.gmail.com`)
- `SMTP_PORT` (default `587`)
- `SMTP_USER`
- `SMTP_PASS`

### 3. Changes to `zeitgeist.py` (~30 lines)

Add a `send_report_email(html: str)` function after report generation (around line 303). Logic:
1. Try to load `config.toml` — if missing or no `[email]` section, return silently
2. Check SMTP env vars — if missing, log warning and return
3. Build a `MIMEMultipart` email with the HTML report as body
4. Connect via `SMTP_SSL` or `starttls`, send to each recipient
5. Log success/failure per recipient

Call it after `output_file.write_text(html)` at line 303, inside the existing `main()`.

### 4. Add `config.toml` to `.gitignore`

Keeps email addresses out of the repo (like `.env`).

### Files modified
- `zeitgeist.py` — add `send_report_email()`, call it from `main()`
- `.gitignore` — add `config.toml`

### Files created
- `config.toml.example` — template with placeholder addresses

## Verification
1. Run `uv run python zeitgeist.py` with no `config.toml` — should behave identically to today
2. Create `config.toml` with a test address, set `SMTP_*` env vars, run again — should send email
3. Create `config.toml` but omit SMTP vars — should log a warning and skip gracefully
