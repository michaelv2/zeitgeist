"""Fetch and sanitize the DataTrek Morning Briefing from Gmail via IMAP.

All subscriber-identifying information is stripped before the content
leaves this module, since the synthesized reports are published publicly.
"""

from __future__ import annotations

import email
import email.message
import imaplib
import logging as log
import re
from datetime import date
from email.header import decode_header
from html.parser import HTMLParser


SENDER = "DataTrekMorningBriefing@datatrekresearch.com"
CONTENT_START_MARKER = "DATATREK MORNING BRIEFING"

# ── PII patterns ─────────────────────────────────────────────────────────────
# Each pattern targets a specific class of personally-identifying information.
# We replace rather than delete where a placeholder helps preserve readability.

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
_TRACKING_URL_RE = re.compile(
    r"https?://[^\s)]*"
    r"(?:click|track|unsubscrib|manage|preference|opt.?out"
    r"|list-manage|mailchimp|sendgrid|constantcontact|campaign-archive)"
    r"[^\s)]*",
    re.I,
)
_GREETING_RE = re.compile(r"^\s*(?:dear|hello|hi|hey)\s+[A-Z][a-z]+.*$", re.I | re.M)
_PREPARED_FOR_RE = re.compile(r"^\s*Prepared\s+(?:only\s+)?for:?\s+.+$", re.I | re.M)
_SUBSCRIBER_ID_RE = re.compile(
    r"(?:subscriber|account|member|customer)\s*(?:id|#|number|no\.?)\s*:?\s*[\w-]+", re.I
)
_US_ADDRESS_RE = re.compile(
    r"\d{1,5}\s+[\w\s]+(?:street|st|avenue|ave|road|rd|boulevard|blvd"
    r"|drive|dr|lane|ln|way|court|ct|suite|ste|floor|fl)\b"
    r".*?\d{5}(?:-\d{4})?",
    re.I | re.DOTALL,
)

# Lines containing these (case-insensitive) signal the start of non-content sections.
# Includes both generic email footer markers and DataTrek-specific promotional sections.
_FOOTER_MARKERS = [
    # Generic email footer
    "unsubscribe",
    "email preferences",
    "manage your subscription",
    "you are receiving this",
    "this email was sent to",
    "to stop receiving",
    "opt out",
    "opt-out",
    "privacy policy",
    "view in browser",
    "view this email",
    "forward this email",
    "update your preferences",
    "all rights reserved",
    # DataTrek promotional sections
    "mind candy",
    "check out our youtube",
    "datatrek merch",
    "spread the word",
    "DataTrek Research, LLC",
]


# ── HTML → plain text (stdlib only) ──────────────────────────────────────────

class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip = True
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self._skip = False
        elif tag in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _html_to_text(html: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


# ── Email parsing ────────────────────────────────────────────────────────────

def _extract_body(msg: email.message.Message) -> str:
    """Return the best text representation of a MIME message."""
    if msg.is_multipart():
        text_part = html_part = None
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and text_part is None:
                text_part = part
            elif ct == "text/html" and html_part is None:
                html_part = part
        chosen = text_part or html_part
        if chosen is None:
            return ""
    else:
        chosen = msg

    payload = chosen.get_payload(decode=True)
    if payload is None:
        return ""
    charset = chosen.get_content_charset() or "utf-8"
    text = payload.decode(charset, errors="replace")
    if chosen.get_content_type() == "text/html":
        text = _html_to_text(text)
    return text


def _extract_briefing_content(text: str) -> str:
    """Isolate the briefing body between the header marker and the footer.

    Footer markers are matched only at the start of a line (after stripping
    whitespace) to avoid false positives from inline mentions like
    "curated links and mind candy".
    """
    idx = text.upper().find(CONTENT_START_MARKER)
    if idx != -1:
        text = text[idx:]

    lines = text.split("\n")
    cut_line = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if not stripped:
            continue
        for marker in _FOOTER_MARKERS:
            if stripped.startswith(marker):
                cut_line = i
                break
        if cut_line < len(lines):
            break

    # Strip each line individually, then collapse runs of blank lines
    cleaned = [line.strip() for line in lines[:cut_line]]
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── PII stripping ────────────────────────────────────────────────────────────

def strip_pii(text: str) -> str:
    """Remove all subscriber-identifying information from the text.

    This is the critical safety gate: anything that passes through this
    function may end up on a public GitHub Pages site.
    """
    # Order matters: remove named lines before general email pattern
    # so "Dear John" doesn't become "Dear [redacted]"
    text = _PREPARED_FOR_RE.sub("", text)
    text = _GREETING_RE.sub("", text)
    text = _EMAIL_RE.sub("[redacted]", text)
    text = _PHONE_RE.sub("[redacted]", text)
    text = _SUBSCRIBER_ID_RE.sub("[redacted]", text)
    text = _US_ADDRESS_RE.sub("[redacted]", text)
    text = _TRACKING_URL_RE.sub("", text)

    # Collapse whitespace artifacts left by removals
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# ── Public API ───────────────────────────────────────────────────────────────

def fetch_briefing(
    gmail_user: str,
    gmail_app_password: str,
    *,
    target_date: date | None = None,
    mailbox: str = "datatrek",
) -> str | None:
    """Fetch today's DataTrek Morning Briefing via Gmail IMAP.

    Returns sanitized briefing text, or None if not found / credentials missing.
    """
    target_date = target_date or date.today()
    date_str = target_date.strftime("%d-%b-%Y")

    try:
        conn = imaplib.IMAP4_SSL("imap.gmail.com")
        conn.login(gmail_user, gmail_app_password)
        conn.select(mailbox, readonly=True)

        # Try exact date first
        status, data = conn.search(None, f'(FROM "{SENDER}" ON {date_str})')
        if status != "OK" or not data[0]:
            # Fall back to SINCE (handles timezone edge cases)
            status, data = conn.search(None, f'(FROM "{SENDER}" SINCE {date_str})')

        if status != "OK" or not data[0]:
            log.warning(f"No DataTrek briefing found for {date_str}")
            conn.logout()
            return None

        # Most recent match
        latest_id = data[0].split()[-1]
        status, msg_data = conn.fetch(latest_id, "(RFC822)")
        conn.logout()

        if status != "OK":
            log.error("Failed to fetch email body from IMAP")
            return None

        msg = email.message_from_bytes(msg_data[0][1])
        body = _extract_body(msg)
        content = _extract_briefing_content(body)

        if not content:
            log.warning("DataTrek email found but no briefing content extracted")
            return None

        sanitized = strip_pii(content)
        log.info(f"Fetched DataTrek briefing ({len(sanitized)} chars)")
        return sanitized

    except imaplib.IMAP4.error as e:
        log.error(f"IMAP error fetching DataTrek briefing: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error fetching DataTrek briefing: {e}")
        return None
