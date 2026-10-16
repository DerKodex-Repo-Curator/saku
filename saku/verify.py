"""Verify that a report matches what actually happened (issues #39, #52).

The model writes confident reports ("`principles/2026-10-16-chat-archive.md` に
教訓を記録しました") whether or not the tool call behind them ran — with a
single-bracket tool call it never ran at all. The filesystem is ground truth: a
file the report says it wrote must exist *and* must have been touched during the
turn. This module is pure; it only reads the filesystem.
"""

import re
from pathlib import Path

# A path the report may be talking about: relative, with a known extension.
_PATH_RE = re.compile(r"`?([A-Za-z0-9_][A-Za-z0-9_./\-]*\.(?:md|py|json|toml|txt|log))`?")

# Verbs in the *past/completed* form: "記録しました" claims the write happened,
# "記録します" (a plan) and "記録されています" (passive: something was recorded
# earlier by someone) do not. A line that ends in the bare verb still claims it
# ("…に教訓を記録"), which is how the archive failure reads in the log.
_WRITE_VERB_RE = re.compile(
    r"(?:記録|作成|更新|保存|追記|書き込)(?:しました|した|済み)"
    r"|完了しました"
    r"|(?:記録|作成|更新|保存|追記)\s*[。.]?$"
)


def claimed_writes(text: str) -> list[str]:
    """Return the paths ``text`` claims to have written, in order of first mention."""
    claims: list[str] = []
    for line in text.splitlines():
        if not _WRITE_VERB_RE.search(line):
            continue
        for match in _PATH_RE.finditer(line):
            path = match.group(1).lstrip("./")
            if path and path not in claims:
                claims.append(path)
    return claims


def unbacked_writes(text: str, memory_root: Path, since: float) -> list[str]:
    """Return claimed paths that were neither created nor modified since ``since``.

    ``since`` is the wall-clock time the turn started (``time.time()``).
    """
    unbacked: list[str] = []
    for path in claimed_writes(text):
        target = memory_root / path
        try:
            if not target.exists() or target.stat().st_mtime < since:
                unbacked.append(path)
        except OSError:
            unbacked.append(path)
    return unbacked
