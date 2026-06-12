# zeitgeist
Simple script to go from prediction markets -> LLM -> Macro report

## Today's Report
- <https://michaelv2.github.io/zeitgeist/>

### Install & run
```shell
git clone git@github.com:michaelv2/zeitgeist.git
cd zeitgeist
uv run python zeitgeist.py
```

### Daily run
Generated daily by a local cron running `run_cron.sh`, which writes the report into the `gh-pages` worktree at `.reports/` and pushes to GitHub Pages.
