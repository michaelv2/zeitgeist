"""Build the Slack summary of a finished memo: its Key Themes and Positioning Summary tilts, plus a link to the
full report.

zeitgeist.py writes the payload to disk; run_cron.sh posts it to SLACK_WEBHOOK_URL only after the push, so the
link is live when the message lands.
"""

from __future__ import annotations

import re
from datetime import date

SECTION_LIMIT = 3000  # Slack's max text length for one section block
BULLETS = ("•", "◦", "▪")
BOLD = "\x00"  # placeholder for Slack's bold marker, so the italic pass can't mistake it for markdown emphasis


def section(md: str, heading: str) -> str | None:
    """Body of the memo's `## heading` section, or None if the memo has no such heading."""
    m = re.search(rf"^#{{1,6}}[ *]*{re.escape(heading)}\b[^\n]*\n(.*?)(?=^#{{1,6}}\s|\Z)", md, re.M | re.S)
    return m.group(1).strip() if m else None


def leading_list(body: str) -> str:
    """The section's opening bullet list, dropping whatever follows it (the Positioning Summary's Key Tells)."""
    out, seen_bullet = [], False
    for line in body.splitlines():
        is_bullet = bool(re.match(r"\s*([-*+]|\d+\.)\s", line))
        if seen_bullet and line.strip() and not is_bullet and not line[0].isspace():
            break
        seen_bullet = seen_bullet or is_bullet
        out.append(line)
    return "\n".join(out).strip()


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def to_mrkdwn(md: str) -> str:
    """Convert the memo's markdown subset (nested lists, bold/italic, links, headings, tables) to Slack mrkdwn."""
    md = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    md = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"<\2|\1>", md)
    is_separator = lambda s: bool(re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*", s))

    lines, stack, raw = [], [], md.splitlines()
    for i, line in enumerate(raw):
        if m := re.match(r"(\s*)[-*+]\s+(.*)", line):
            width = len(m.group(1).expandtabs(4))
            while stack and width < stack[-1]:
                stack.pop()
            if not stack or width > stack[-1]:
                stack.append(width)
            level = len(stack) - 1
            lines.append("    " * level + BULLETS[min(level, len(BULLETS) - 1)] + " " + m.group(2))
            continue
        stack = []
        if m := re.match(r"#{1,6}\s+(.*)", line):
            lines.append(BOLD + m.group(1).strip("* ") + BOLD)
        elif line.lstrip().startswith("|"):
            if is_separator(line):
                continue
            row = " · ".join(_cells(line))
            header = i + 1 < len(raw) and is_separator(raw[i + 1])
            lines.append(BOLD + row + BOLD if header else f"{BULLETS[0]} {row}")
        else:
            lines.append(line.strip())

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: BOLD + (m.group(1) or m.group(2)) + BOLD, text)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"_\1_", text)
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    return text.replace(BOLD, "*").strip()


def _section_blocks(title: str, text: str) -> list[dict]:
    """mrkdwn section blocks for one memo section, split at line boundaries to fit Slack's per-block limit."""
    chunks, cur = [], f"*{title}*"
    for line in text.splitlines():
        if len(cur) + 1 + len(line) > SECTION_LIMIT:
            chunks.append(cur)
            cur = line[:SECTION_LIMIT]
        else:
            cur += "\n" + line
    chunks.append(cur)
    return [{"type": "section", "text": {"type": "mrkdwn", "text": c}} for c in chunks]


def build_payload(report: str, day: date, url: str) -> dict:
    """Slack webhook payload: a header, the Key Themes, the Positioning Summary tilts, and a link to the full memo.
    A section the model didn't write is skipped rather than failing the summary."""
    title = f"Zeitgeist Daily Memo ({day.strftime('%d-%b-%Y')})"
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": title}}]
    if themes := section(report, "Key Themes"):
        blocks += _section_blocks("Key Themes", to_mrkdwn(themes))
    if positioning := section(report, "Positioning Summary"):
        blocks += [{"type": "divider"}] if len(blocks) > 1 else []
        blocks += _section_blocks("Positioning Summary", to_mrkdwn(leading_list(positioning)))
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"<{url}|Read the full memo →>"}})
    return {"text": f"{title}: {url}", "blocks": blocks, "unfurl_links": False, "unfurl_media": False}
