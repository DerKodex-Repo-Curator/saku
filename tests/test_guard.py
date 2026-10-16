#!/usr/bin/env python3
"""
Unit tests for the output guard (saku.guard, issue #41).

The 06:41 tick on 2026-10-16 journalled the same code block four times (1.6 KB of
repetition). These tests pin the guard that keeps such output out of the journal.
No LLM is involved: the guard is pure and the core-level test patches SAKU_ROOT.
"""

import sys
import tempfile
from pathlib import Path

CODE_ROOT = Path(__file__).parent
sys.path.append(str(CODE_ROOT))
_REPO_ROOT = CODE_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from saku import guard
from saku import config as saku_config

_PASS = 0
_FAIL = 0

_CFG = saku_config.GuardConfig()


def _degenerate_block() -> str:
    """The shape of the real 06:41 output: one block emitted four times."""
    return (
        'print("A2A構造化委譲:")\n'
        'print(json.dumps(a2a_task, indent=2, ensure_ascii=False))\n'
        'print("\\n現在のデリゲート:")  # 現在の委譲状態を表示\n'
        'print(current_delegate)  # 現在の委譲先を出力する\n'
        'print("\\n分析:")\n'
        'print("A2Aプロトコルは、親エージェントが子エージェントにタスクを委譲する仕組み。")'
    )


def test_clean_text_is_untouched():
    text = "今日はA2Aの構造化委譲について調べました。\n\n- 学び1\n- 学び2\n"
    result = guard.normalize(text, _CFG)
    assert result.text == text, result.text
    assert result.reason == ""


def test_repeated_block_is_compressed():
    """A block repeated 4 times keeps its first occurrence plus a note."""
    text = "\n\n".join([_degenerate_block()] * 4)
    result = guard.normalize(text, _CFG)
    assert result.reason, "a block repeated 4 times must be detected"
    assert "同一ブロック×4" in result.text, result.text
    assert result.text.count("A2A構造化委譲:") == 1, "the repetition was not dropped"
    assert len(result.text) < len(text) / 2, (len(result.text), len(text))


def test_repeated_block_below_threshold_is_kept():
    text = "\n\n".join([_degenerate_block()] * 2)
    result = guard.normalize(text, _CFG)
    assert result.reason == "", "2 repeats must not trip the default threshold"
    assert result.text == text


def test_repeated_long_line_is_compressed():
    line = "print('A2A構造化委譲の設計案を検討します')  # 同じ行が繰り返される"
    text = "\n".join([line] * 5)
    result = guard.normalize(text, _CFG)
    assert result.reason
    assert result.text.count(line) == 1
    assert "同一ブロック×5" in result.text


def test_short_units_do_not_trigger_the_guard():
    """Ordinary short repeats must stay (no false positives on lists/acks)."""
    text = "\n\n".join(["OK"] * 20)
    result = guard.normalize(text, _CFG)
    assert result.reason == "", result.reason
    assert result.text == text

    bullets = "\n".join(["- 未着手", "- 未着手のまま"] * 6)
    assert guard.normalize(bullets, _CFG).reason == ""


def test_consecutive_short_lines_are_compressed():
    """#50: 30 identical short lines are degenerate output, not content."""
    text = "\n".join(["了解しました"] * 30)
    result = guard.normalize(text, _CFG)
    assert result.reason, "a short-line loop was not detected"
    assert result.text.count("了解しました") == 1, result.text
    assert "同一ブロック×30" in result.text, result.text


def test_short_line_threshold_is_configurable():
    text = "\n".join(["はい"] * 3)
    assert guard.normalize(text, _CFG).reason == "", "3 short lines must stay below the default"
    cfg = saku_config.GuardConfig(min_line_repeats=3)
    assert guard.normalize(text, cfg).reason, "min_line_repeats=3 must detect 3 lines"


def test_short_distinct_lines_are_kept():
    """A normal list must never be mistaken for a loop."""
    text = "\n".join(f"- 項目{i}: 説明{i}" for i in range(10))
    result = guard.normalize(text, _CFG)
    assert result.reason == "", result.reason
    assert result.text == text


def test_oversized_output_is_capped():
    text = "あ" * (_CFG.max_chars + 500)
    result = guard.normalize(text, _CFG)
    assert "文字で切り詰め" in result.text
    assert len(result.text) < _CFG.max_chars + 100, len(result.text)


def test_disabled_guard_is_a_no_op():
    text = "\n\n".join([_degenerate_block()] * 4)
    cfg = saku_config.GuardConfig(enabled=False)
    result = guard.normalize(text, cfg)
    assert result.text == text and result.reason == ""


def test_normalize_is_idempotent():
    text = "\n\n".join([_degenerate_block()] * 4)
    once = guard.normalize(text, _CFG).text
    twice = guard.normalize(once, _CFG)
    assert twice.text == once, twice.text
    assert twice.reason == "", twice.reason


def test_thresholds_are_configurable():
    text = "\n\n".join([_degenerate_block()] * 2)
    cfg = saku_config.GuardConfig(max_repeat=2)
    assert guard.normalize(text, cfg).reason, "max_repeat=2 must detect 2 repeats"


def test_journal_write_uses_the_guard():
    """save_autonomous_log must not write the repetition verbatim (issue #41)."""
    from saku import core

    original_root = core.SAKU_ROOT
    text = "\n\n".join([_degenerate_block()] * 4)
    with tempfile.TemporaryDirectory() as tmp:
        core.SAKU_ROOT = Path(tmp)
        try:
            core.save_autonomous_log("定期自律アクション", text)
        finally:
            core.SAKU_ROOT = original_root
        written = next((Path(tmp) / "journal").glob("*.md")).read_text(encoding="utf-8")

    assert written.count("A2A構造化委譲:") == 1, written
    assert "出力が退化したため圧縮" in written, written


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
    print(f"[*] All {_PASS + _FAIL} guard tests {'PASSED!' if _FAIL == 0 else f'FAILED ({_FAIL})'}")
    return _FAIL == 0


if __name__ == "__main__":
    run_tests()
