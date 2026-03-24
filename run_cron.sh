#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

cd ~/projects/zeitgeist

# Load env vars
set -a
source ~/.bashrc_env
set +a

uv run python zeitgeist.py

cd .reports
git add -A
git commit -m "Report $(date +%Y-%m-%d)" || true  # no-op if nothing changed
git push
