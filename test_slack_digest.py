"""Tests for the Slack memo summary in slack_digest.py.

Run: uv run python -m pytest test_slack_digest.py -v
"""

from datetime import date

from slack_digest import SECTION_LIMIT, build_payload, leading_list, section, to_mrkdwn

MEMO = """# Daily Memo (16-Oct-2026)

## Key Themes

- **The curve is pricing a Fed that wins** (the [10Y–3M spread](https://fred.stlouisfed.org/series/T10Y3M) fell to 0.82).
  - **What's mispriced:** inflation compensation, *not* growth.
  - **Confirm:** breakevens rising with oil. **Kill:** oil back below $90.
- **Real spending slowed sharply in September.**

## Key News

- Something that should not appear in the summary.

## Positioning Summary

- **Long the 2Y (hold; stop above 4.90%)** because 94bp over funds is up to about four hikes.
- **Add short TIPS (STIP/VTIP)** because the 2.32% breakeven prices oil as transitory.
  - This pairs with the 2Y long.

**Key Tells**
- **Oct 28 FOMC:** a hike that leaves December open means a longer cycle.

## Upcoming Catalysts

- Oct 28 FOMC
"""


def text_of(payload: dict) -> str:
    return "\n".join(b["text"]["text"] for b in payload["blocks"] if "text" in b)


class TestSections:
    def test_extracts_section_body(self):
        body = section(MEMO, "Key Themes")
        assert body.startswith("- **The curve")
        assert "Key News" not in body and "should not appear" not in body

    def test_missing_section(self):
        assert section(MEMO, "Nonexistent Heading") is None

    def test_tolerates_heading_drift(self):
        assert section("### **Key Themes:**\n\n- a\n\n## Next\n", "Key Themes") == "- a"

    def test_leading_list_drops_key_tells(self):
        tilts = leading_list(section(MEMO, "Positioning Summary"))
        assert "Long the 2Y" in tilts and "This pairs with the 2Y long" in tilts
        assert "Key Tells" not in tilts and "Oct 28 FOMC" not in tilts

    def test_leading_list_keeps_preamble(self):
        assert leading_list("Intro line.\n\n- a\n- b\n\nAfter.") == "Intro line.\n\n- a\n- b"


class TestMrkdwn:
    def test_bold_italic_and_links(self):
        out = to_mrkdwn("**Bold** and *italic* with [a link](https://x.com/a_b?c=1&d=2)")
        assert out == "*Bold* and _italic_ with <https://x.com/a_b?c=1&amp;d=2|a link>"

    def test_nested_bullets(self):
        out = to_mrkdwn("- top\n  - nested\n    - deeper\n- top again")
        assert out.splitlines() == ["• top", "    ◦ nested", "        ▪ deeper", "• top again"]

    def test_four_space_nesting(self):
        assert to_mrkdwn("- top\n    - nested").splitlines() == ["• top", "    ◦ nested"]

    def test_escapes_slack_control_characters(self):
        assert to_mrkdwn("S&P < 5000 > 4000") == "S&amp;P &lt; 5000 &gt; 4000"

    def test_headings_become_bold(self):
        assert to_mrkdwn("#### Rates & Fed") == "*Rates &amp; Fed*"

    def test_table_rows(self):
        out = to_mrkdwn("| Tilt | Why |\n|---|---|\n| Long 2Y | hikes overpriced |")
        assert out.splitlines() == ["*Tilt · Why*", "• Long 2Y · hikes overpriced"]


class TestPayload:
    URL = "https://michaelv2.github.io/zeitgeist/2026/10/16/"

    def test_summary_content(self):
        payload = build_payload(MEMO, date(2026, 10, 16), self.URL)
        text = text_of(payload)
        assert payload["blocks"][0]["text"]["text"] == "Zeitgeist Daily Memo (16-Oct-2026)"
        assert "*Key Themes*" in text and "*Positioning Summary*" in text
        assert "<https://fred.stlouisfed.org/series/T10Y3M|10Y–3M spread>" in text
        assert "Key Tells" not in text and "should not appear" not in text and "Upcoming" not in text
        assert payload["blocks"][-1]["text"]["text"] == f"<{self.URL}|Read the full memo →>"
        assert self.URL in payload["text"]

    def test_missing_sections_still_links(self):
        payload = build_payload("# Daily Memo\n\nNo usual sections today.", date(2026, 10, 16), self.URL)
        assert [b["type"] for b in payload["blocks"]] == ["header", "section"]

    def test_long_section_splits_under_limit(self):
        bullets = "\n".join(f"- **Tilt {i}** because " + "x" * 200 for i in range(40))
        payload = build_payload(f"## Positioning Summary\n\n{bullets}\n", date(2026, 10, 16), self.URL)
        sections = [b for b in payload["blocks"] if b["type"] == "section"]
        assert len(sections) > 2
        assert all(len(b["text"]["text"]) <= SECTION_LIMIT for b in sections)
        assert sum(t.count("•") for t in map(lambda b: b["text"]["text"], sections)) == 40
