"""Tests for the Opus puzzle-section insertion in zeitgeist.py.

Run: uv run python -m pytest test_puzzle_synthesis.py -v

Importing zeitgeist constructs the pydantic-ai agents and asserts the API-key env
vars exist; set harmless defaults first so the test runs without real credentials
(setdefault leaves real keys untouched when present). No agent is ever .run() here.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from zeitgeist import insert_puzzle_section

MEMO = "# Daily Memo (06-Jun-2026)\n\n## Key News\n- Iran talks\n\n## Macro\n- CPI hot\n"
SECTION = "## Cross-Currents\n#### Real incomes vs. nominal sales\n- detail\n"


class TestInsertPuzzleSection:
    def test_inserts_directly_under_h1_title(self):
        out = insert_puzzle_section(MEMO, SECTION)
        # Title remains the very first line.
        assert out.splitlines()[0] == "# Daily Memo (06-Jun-2026)"
        # Section lands above Key News but below the title.
        assert out.index("# Daily Memo") < out.index("## Cross-Currents") < out.index("## Key News")

    def test_strips_code_fences(self):
        fenced = "```markdown\n## Cross-Currents\n#### X\n- y\n```"
        out = insert_puzzle_section(MEMO, fenced)
        assert "```" not in out
        assert "## Cross-Currents" in out

    def test_prepends_when_no_h1_title(self):
        no_title = "## Key News\n- item\n"
        out = insert_puzzle_section(no_title, SECTION)
        assert out.startswith("## Cross-Currents")
        assert "## Key News" in out

    def test_does_not_match_h2_as_title(self):
        # An H2-only report must not be split mid-stream on a "## " line.
        h2_only = "## Key News\n- a\n## Macro\n- b\n"
        out = insert_puzzle_section(h2_only, SECTION)
        # Section is prepended whole; Key News stays ahead of Macro.
        assert out.startswith("## Cross-Currents")
        assert out.index("## Key News") < out.index("## Macro")

    def test_empty_section_returns_report_unchanged(self):
        assert insert_puzzle_section(MEMO, "   ") == MEMO
        assert insert_puzzle_section(MEMO, "```\n```") == MEMO
