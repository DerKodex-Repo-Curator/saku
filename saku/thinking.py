"""Separate thinking (<think>), visible parts, and tool-call syntax from the response text."""

import re

from .transport import strip_single_bracket_calls

TOOL_BLOCK_RE = re.compile(r"\[\[[A-Z_]+\s*[^\]]*\]\]\s*\n?.*?\[\[END\]\]", re.DOTALL)
UNCLOSED_TOOL_START_RE = re.compile(r"\[\[[A-Z_]+\s*[^\]]*\]\]", re.MULTILINE)


def split_thinking(text: str) -> tuple[str, str]:
    """Separate the response into (thinking, visible)."""
    think_blocks = re.findall(r"<think>(.*?)</think>", text, flags=re.DOTALL)
    thinking = "\n\n".join(block.strip() for block in think_blocks if block.strip())

    visible = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    visible = re.sub(r"\[thinking\.{0,3}\]\s*", "", visible)
    visible = visible.strip()

    return thinking, visible


def strip_tool_blocks(text: str) -> str:
    """Remove [[TOOL ...]] ... [[END]] blocks from visible text.

    Tool calls are execution instructions, not conversation content. They should
    not be shown to the user, stored in the journal, or echoed back into history.

    Unclosed start tags (e.g. a bare ``[[READ_FILE path="meta.md"]]`` left when
    the model forgot ``[[END]]``) are removed as well, so tool syntax never leaks
    into the visible output. Single-bracket calls (``[READ_FILE path="meta.md"]``,
    issue #47) are removed too — they used to leak into chat.md and journal.
    """
    cleaned = TOOL_BLOCK_RE.sub("", text)
    cleaned = UNCLOSED_TOOL_START_RE.sub("", cleaned)
    cleaned = strip_single_bracket_calls(cleaned)
    return cleaned.strip()
