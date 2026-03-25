"""Tests for PII stripping in email_briefing.py.

Run: uv run python -m pytest test_email_briefing.py -v
"""

from email_briefing import strip_pii, _extract_briefing_content, _FOOTER_MARKERS


class TestStripPii:
    def test_email_addresses(self):
        text = "Contact us at support@datatrek.com or john.doe@gmail.com"
        result = strip_pii(text)
        assert "support@datatrek.com" not in result
        assert "john.doe@gmail.com" not in result
        assert "[redacted]" in result

    def test_phone_numbers(self):
        for phone in ["212-555-1234", "(212) 555-1234", "+1 212 555 1234", "212.555.1234"]:
            result = strip_pii(f"Call us at {phone}")
            assert phone not in result, f"Phone not stripped: {phone}"

    def test_greeting_lines(self):
        text = "Dear Michael,\n\nHere is your briefing.\nMarkets rallied today."
        result = strip_pii(text)
        assert "Michael" not in result
        assert "Markets rallied" in result

    def test_greeting_variations(self):
        for greeting in ["Hello John", "Hi Sarah", "Hey Mike"]:
            result = strip_pii(f"{greeting},\n\nContent here.")
            assert greeting.split()[1] not in result

    def test_subscriber_ids(self):
        for pattern in [
            "Subscriber ID: ABC-12345",
            "Account #98765",
            "Member number: XY789",
            "Customer No. 42",
        ]:
            result = strip_pii(pattern)
            assert "[redacted]" in result

    def test_us_addresses(self):
        text = "DataTrek Research\n123 Main Street, Suite 400\nNew York, NY 10001"
        result = strip_pii(text)
        assert "10001" not in result

    def test_tracking_urls_removed(self):
        for url in [
            "https://click.mailchimp.com/abc123",
            "https://email.sendgrid.net/track/xyz",
            "https://datatrek.list-manage.com/unsubscribe?id=abc",
            "https://campaign-archive.com/view?id=xyz",
        ]:
            result = strip_pii(f"Visit {url}")
            assert url not in result

    def test_legitimate_urls_preserved(self):
        url = "https://fred.stlouisfed.org/series/UNRATE"
        result = strip_pii(f"See {url}")
        assert url in result

    def test_content_preserved(self):
        """Ensure market/financial content passes through intact."""
        content = (
            "S&P 500 rose 1.2% to 5,450. Fed held rates at 5.25-5.50%. "
            "10Y yield at 4.35%. WTI crude $78.50/bbl. "
            "PCE came in at 2.6% YoY, below consensus 2.7%."
        )
        result = strip_pii(content)
        assert result == content

    def test_whitespace_collapse(self):
        text = "Paragraph one.\n\n\n\n\nParagraph two."
        result = strip_pii(text)
        assert "\n\n\n" not in result

    def test_prepared_for_line(self):
        text = "Header\nPrepared only for: Michael Wagg, michael@example.com\n\nContent here."
        result = strip_pii(text)
        assert "Michael Wagg" not in result
        assert "Content here" in result

    def test_prepared_for_variations(self):
        for line in [
            "Prepared for: John Smith, john@co.com",
            "Prepared only for: Jane Doe",
            "  Prepared for John Smith",
        ]:
            result = strip_pii(line)
            assert "Smith" not in result or "Doe" not in result

    def test_combined_pii(self):
        """Simulate a realistic footer with mixed PII."""
        text = (
            "DATATREK MORNING BRIEFING\n\n"
            "Markets Overview: S&P up 0.5%\n\n"
            "Dear Michael,\n"
            "Here is your briefing for today.\n\n"
            "The Fed held rates steady.\n\n"
            "Prepared only for: Michael Wagg, mwagg@gmail.com\n"
            "Subscriber ID: DTR-98765\n"
            "Contact: support@datatrekresearch.com\n"
            "Call us: (212) 555-0100\n"
            "123 Park Avenue, Suite 200\nNew York, NY 10017\n"
        )
        result = strip_pii(text)
        assert "Michael" not in result
        assert "Wagg" not in result
        assert "DTR-98765" not in result
        assert "support@datatrekresearch.com" not in result
        assert "mwagg@gmail.com" not in result
        assert "555-0100" not in result
        assert "10017" not in result
        # Content preserved
        assert "S&P up 0.5%" in result
        assert "Fed held rates steady" in result


class TestExtractBriefingContent:
    def test_extracts_after_marker(self):
        text = "Junk header\nDATATREK MORNING BRIEFING\nActual content here."
        result = _extract_briefing_content(text)
        assert result.startswith("DATATREK MORNING BRIEFING")
        assert "Actual content here" in result
        assert "Junk header" not in result

    def test_truncates_at_footer(self):
        text = (
            "DATATREK MORNING BRIEFING\n"
            "Good content.\n"
            "More good content.\n"
            "Unsubscribe from this list"
        )
        result = _extract_briefing_content(text)
        assert "Good content" in result
        assert "Unsubscribe" not in result

    def test_no_marker_returns_all(self):
        text = "Some content without the marker.\nMore content."
        result = _extract_briefing_content(text)
        assert "Some content" in result

    def test_multiple_footer_markers_uses_earliest(self):
        text = (
            "DATATREK MORNING BRIEFING\n"
            "Content.\n"
            "You are receiving this because...\n"
            "More footer.\n"
            "Unsubscribe here."
        )
        result = _extract_briefing_content(text)
        assert "Content" in result
        assert "You are receiving this" not in result

    def test_datatrek_promo_sections_cut(self):
        """DataTrek-specific promotional sections are treated as footer."""
        for marker in ["MIND CANDY", "CHECK OUT OUR YOUTUBE CHANNEL", "DATATREK MERCH", "Spread the word!"]:
            text = f"DATATREK MORNING BRIEFING\nGood analysis.\n{marker}\nPromo junk."
            result = _extract_briefing_content(text)
            assert "Good analysis" in result
            assert "Promo junk" not in result
