"""Output guard: keep degenerate LLM output out of the journal (issue #41).

A local LLM occasionally falls into a repetition loop and emits the same code
block four or five times in a row. Writing that into the journal turns a model
glitch into "memory", and later reflections read it back as if it were content.

The guard is pure (no I/O, no LLM call) so it can be unit tested without a model:
it detects a repeated block (or a run of identical long lines), keeps the first
occurrence plus a short note saying what happened, and caps a single record's
length. Thresholds come from ``[guard]`` in config.toml (see config.GuardConfig).
"""

import re
from dataclasses import dataclass

from saku import config as saku_config


@dataclass
class GuardResult:
    """``text`` is what may be recorded; ``reason`` is empty when it was clean."""

    text: str
    reason: str = ""


def _blocks(text: str) -> list[str]:
    """Split on blank lines, preserving order."""
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def find_repetition(
    text: str, min_unit_chars: int, max_repeat: int, min_line_repeats: int | None = None
) -> tuple[str, int]:
    """Return (unit, occurrences) for the most repeated unit, or ("", 0).

    Two shapes are detected: a run of identical lines (a loop emitting one line
    over and over) and a block repeated the configured number of times. Blocks
    shorter than ``min_unit_chars`` are ignored so that ordinary short repeats
    ("- ", "OK") do not trigger the guard.

    Line runs are judged by count instead (#50): a loop that emits "了解しました"
    thirty times is degenerate even though each line is only six characters. Such
    a run needs ``min_line_repeats`` consecutive identical lines; longer lines
    still trip the guard at ``max_repeat``.
    """
    if min_line_repeats is None:
        min_line_repeats = max_repeat
    previous, run = "", 0
    lines = text.split("\n")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            previous, run = "", 0
            continue
        run = run + 1 if stripped == previous else 1
        previous = stripped
        long_enough = len(stripped) >= min_unit_chars
        if (run >= max_repeat and long_enough) or run >= min_line_repeats:
            # Count the whole run so the note reports the real repetition count.
            next_index = index + 1
            while next_index < len(lines) and lines[next_index].strip() == stripped:
                run += 1
                next_index += 1
            return stripped, run

    counts: dict[str, int] = {}
    for block in _blocks(text):
        if len(block) >= min_unit_chars:
            counts[block] = counts.get(block, 0) + 1
    if counts:
        unit, count = max(counts.items(), key=lambda kv: kv[1])
        if count >= max_repeat:
            return unit, count
    return "", 0


def normalize(text: str, cfg: "saku_config.GuardConfig | None" = None) -> GuardResult:
    """Return text safe to record, compressed if it degenerated.

    The result is idempotent: applying the guard to its own output changes
    nothing, so callers may guard at more than one layer safely.
    """
    cfg = cfg or saku_config.GuardConfig()
    if not cfg.enabled or not text:
        return GuardResult(text)

    reasons: list[str] = []
    unit, count = find_repetition(text, cfg.min_unit_chars, cfg.max_repeat, cfg.min_line_repeats)
    if unit:
        cut = text.find(unit) + len(unit)
        text = text[:cut].rstrip()
        reasons.append(f"同一ブロック×{count}（{len(unit)}文字の反復）")

    if len(text) > cfg.max_chars:
        text = text[: cfg.max_chars].rstrip()
        reasons.append(f"{cfg.max_chars}文字で切り詰め")

    if not reasons:
        return GuardResult(text)

    note = "（出力が退化したため圧縮: " + "、".join(reasons) + "）"
    return GuardResult(f"{text}\n\n{note}", " / ".join(reasons))
