"""Report formatters for Telegram messages."""

import asyncio
import html
import re
from html.parser import HTMLParser
from typing import Any

# Allowed HTML tags in Telegram
ALLOWED_TAGS = {"b", "i", "code", "pre", "a", "s", "u"}


def sanitize_telegram_html(text: str) -> str:
    """Sanitize HTML for Telegram, keeping only allowed tags.

    Telegram supports: <b>, <i>, <code>, <pre>, <a>, <s>, <u>

    Args:
        text: Raw HTML text from Claude

    Returns:
        Sanitized HTML safe for Telegram
    """
    if not text:
        return ""

    # First, escape any raw < > that are not part of tags
    # This regex matches < or > not followed/preceded by tag patterns
    result = []
    i = 0
    while i < len(text):
        if text[i] == "<":
            # Check if this looks like a valid tag
            tag_match = re.match(r"</?([a-zA-Z]+)(?:\s[^>]*)?>", text[i:])
            if tag_match:
                tag_name = tag_match.group(1).lower()
                if tag_name in ALLOWED_TAGS:
                    # Keep the allowed tag
                    result.append(tag_match.group(0))
                    i += len(tag_match.group(0))
                    continue
                else:
                    # Escape disallowed tag
                    result.append("&lt;")
                    i += 1
                    continue
            else:
                # Not a valid tag pattern, escape
                result.append("&lt;")
                i += 1
                continue
        elif text[i] == ">":
            # Standalone > should be escaped
            result.append("&gt;")
            i += 1
        elif text[i] == "&":
            # Check if already escaped
            entity_match = re.match(r"&(amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);", text[i:])
            if entity_match:
                result.append(entity_match.group(0))
                i += len(entity_match.group(0))
            else:
                result.append("&amp;")
                i += 1
        else:
            result.append(text[i])
            i += 1

    return "".join(result)


def validate_telegram_html(text: str) -> bool:
    """Validate that HTML tags are properly closed.

    Args:
        text: HTML text to validate

    Returns:
        True if valid, False otherwise
    """
    tag_stack = []
    tag_pattern = re.compile(r"<(/?)([a-zA-Z]+)(?:\s[^>]*)?>")

    for match in tag_pattern.finditer(text):
        is_closing = match.group(1) == "/"
        tag_name = match.group(2).lower()

        if tag_name not in ALLOWED_TAGS:
            continue

        if is_closing:
            if not tag_stack or tag_stack[-1] != tag_name:
                return False
            tag_stack.pop()
        else:
            tag_stack.append(tag_name)

    return len(tag_stack) == 0


def truncate_html(text: str, max_length: int = 4096) -> str:
    """Truncate HTML text while keeping tags balanced.

    Args:
        text: HTML text
        max_length: Maximum length (Telegram limit is 4096)

    Returns:
        Truncated text with balanced tags
    """
    return _truncate_html_consumed(text, max_length)[0]


def _truncate_html_consumed(text: str, max_length: int) -> tuple[str, int]:
    """Truncate like truncate_html, also returning how many characters
    of the ORIGINAL text the chunk covers — the decorated chunk gains
    an ellipsis and closing tags, so its own length is useless for
    advancing a split cursor.
    """
    if len(text) <= max_length:
        return text, len(text)

    # Find a safe cut point
    cut_point = max_length - 50  # Leave room for closing tags and ellipsis

    # Don't cut in the middle of a tag
    last_open = text.rfind("<", 0, cut_point)
    last_close = text.rfind(">", 0, cut_point)

    if last_open > last_close:
        # We're in the middle of a tag, cut before it
        cut_point = last_open

    truncated = text[:cut_point]

    # Close any open tags
    tag_pattern = re.compile(r"<(/?)([a-zA-Z]+)(?:\s[^>]*)?>")
    open_tags = []

    for match in tag_pattern.finditer(truncated):
        is_closing = match.group(1) == "/"
        tag_name = match.group(2).lower()

        if tag_name not in ALLOWED_TAGS:
            continue

        if is_closing and open_tags and open_tags[-1] == tag_name:
            open_tags.pop()
        elif not is_closing:
            open_tags.append(tag_name)

    # Add closing tags in reverse order
    closing_tags = "".join(f"</{tag}>" for tag in reversed(open_tags))

    return truncated + "..." + closing_tags, cut_point


def format_process_report(report: dict[str, Any]) -> str:
    """Format processing report for Telegram HTML.

    The report from Claude is expected to be in HTML format.
    We sanitize it to ensure only Telegram-safe tags are used.

    Args:
        report: Processing report from ClaudeProcessor

    Returns:
        Formatted HTML message for Telegram
    """
    if "error" in report:
        error_msg = html.escape(str(report["error"]))
        return f"❌ <b>Ошибка:</b> {error_msg}"

    if "report" in report:
        raw_report = report["report"]

        # Sanitize HTML, keeping allowed tags
        sanitized = sanitize_telegram_html(raw_report)

        # Validate tag balance
        if not validate_telegram_html(sanitized):
            # Fall back to plain text if tags are broken
            return html.escape(raw_report)

        # Truncate if too long
        return truncate_html(sanitized, max_length=4096)

    return "✅ <b>Обработка завершена</b>"


def format_error(error: str) -> str:
    """Format error message for Telegram.

    Args:
        error: Error message

    Returns:
        Formatted HTML error message
    """
    return f"❌ <b>Ошибка:</b> {html.escape(error)}"


def format_empty_daily() -> str:
    """Format message for empty daily file.

    Returns:
        Formatted HTML message
    """
    return (
        "📭 <b>Нет записей для обработки</b>\n\n"
        "<i>Добавьте голосовые сообщения или текст в течение дня</i>"
    )


# ── Telegram delivery (shared by chat handler and cron runner) ────────

MAX_RESPONSE_LENGTH = 4096


class _PlainTextParser(HTMLParser):
    """Extract text from sanitized Telegram HTML for the plain-text fallback."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


async def send_response(bot: Any, chat_id: int, text: str) -> None:
    """Send a Claude reply: sanitize HTML, split to 4096-char chunks,
    fall back to plain text when Telegram rejects the markup."""
    sanitized = sanitize_telegram_html(text)
    if not validate_telegram_html(sanitized):
        sanitized = html.escape(text)

    chunks = split_text(sanitized, MAX_RESPONSE_LENGTH)
    for i, chunk in enumerate(chunks):
        try:
            await bot.send_message(chat_id, chunk)
        except Exception:
            # Parse the sanitized fragment before sending without HTML, so users
            # see readable text instead of markup and escaped entities.
            parser = _PlainTextParser()
            parser.feed(chunk)
            parser.close()
            await bot.send_message(chat_id, "".join(parser.parts), parse_mode=None)
        if i < len(chunks) - 1:
            await asyncio.sleep(0.3)


def split_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks respecting Telegram limits."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        chunk, consumed = _truncate_html_consumed(remaining, max_len)
        if consumed <= 0:
            # Safety: force split to avoid infinite loop
            chunks.append(remaining[:max_len])
            remaining = remaining[max_len:]
        else:
            chunks.append(chunk)
            remaining = remaining[consumed:]
    return chunks
