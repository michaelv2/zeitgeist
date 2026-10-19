#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

cd ~/projects/zeitgeist

# Load env vars
set -a
source ~/.bashrc_env
set +a

export ZEITGEIST_PROD=1  # full run, not the dev quick-test (which caps each market source at ~200)

uv run python zeitgeist.py

cd .reports
git add -A
git commit -m "Report $(date +%Y-%m-%d)" || true  # no-op if nothing changed
git push
cd ..

# Post the memo summary only after the push, so its link is live; a Slack failure doesn't fail the run
if [[ -f .slack_payload.json && -n "${SLACK_WEBHOOK_URL:-}" ]]; then
    curl -sS --fail-with-body -X POST -H 'Content-type: application/json' \
        --data @.slack_payload.json "$SLACK_WEBHOOK_URL" \
        || echo "Slack post failed; the report itself was published" >&2
    echo
    rm -f .slack_payload.json
fi
