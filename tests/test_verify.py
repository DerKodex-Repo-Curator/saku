#!/usr/bin/env python3
"""
Unit tests for report verification (saku.verify, issues #39 / #52).

No LLM: the module only compares a claimed write path against the filesystem.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

CODE_ROOT = Path(__file__).parent
sys.path.append(str(CODE_ROOT))
_REPO_ROOT = CODE_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from saku import verify

_PASS = 0
_FAIL = 0


def test_claims_are_detected():
    text = (
        "`principles/2026-10-16-chat-archive.md` に教訓を記録しました。\n"
        "meta.md の「最近の出来事」を更新した。\n"
    )
    assert verify.claimed_writes(text) == [
        "principles/2026-10-16-chat-archive.md",
        "meta.md",
    ]


def test_plans_and_passive_mentions_are_not_claims():
    """A plan ("記録します") or a passive mention is not a claim that a write happened."""
    text = (
        "principles/2026-10-16-x.md に記録します。\n"
        "journal/2026-10-15.md に記録されています。\n"
        "必要な情報は wiki/index.md を確認しました。\n"
    )
    assert verify.claimed_writes(text) == []


def test_bare_verb_at_line_end_is_a_claim():
    """How the failed archive read in the log: a bullet ending in the bare verb."""
    text = "- principles/2026-10-16-chat-archive.md に教訓を記録\n"
    assert verify.claimed_writes(text) == ["principles/2026-10-16-chat-archive.md"]


def test_missing_file_is_unbacked():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        assert verify.unbacked_writes(
            "principles/absent.md に記録しました。", root, time.time() - 1
        ) == ["principles/absent.md"]


def test_stale_file_is_unbacked_and_fresh_file_is_backed():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "principles").mkdir()
        stale = root / "principles" / "old.md"
        stale.write_text("- 昔の記録\n", encoding="utf-8")
        old = time.time() - 600
        os.utime(stale, (old, old))

        assert verify.unbacked_writes("principles/old.md に記録しました。", root, time.time() - 1) == [
            "principles/old.md"
        ]

        since = time.time() - 1
        stale.write_text("- 新しい記録\n", encoding="utf-8")  # written during the turn
        assert verify.unbacked_writes("principles/old.md に記録しました。", root, since) == []


def test_reading_a_file_is_not_a_write_claim():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "meta.md").write_text("# meta\n", encoding="utf-8")
        assert verify.claimed_writes("meta.md を読みました。内容は次のとおりです。") == []


def run_tests():
    global _PASS, _FAIL
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        try:
            fn()
            print(f"    -> PASS: {fn.__name__}")
            _PASS += 1
        except Exception as e:
            print(f"    -> FAIL: {fn.__name__}: {e}")
            _FAIL += 1
    print(f"[*] All {_PASS + _FAIL} verify tests {'PASSED!' if _FAIL == 0 else f'FAILED ({_FAIL})'}")
    return _FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
