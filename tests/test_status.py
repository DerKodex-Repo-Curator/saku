#!/usr/bin/env python3
"""
Tests for saku.status (read-only growth summary).

No LLM: reads a temporary memory root only.
"""

import sys
import tempfile
from pathlib import Path

CODE_ROOT = Path(__file__).parent
sys.path.append(str(CODE_ROOT))
_REPO_ROOT = CODE_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from saku import status


def _make_root():
    root = Path(tempfile.mkdtemp())
    (root / "MEMORY.md").write_text(
        "# MEMORY — 長期記憶\n\n"
        "## 好み・傾向\n"
        "- 2026-08-20: 朝の会話を好む <!-- s:2 last:2026-08-20 -->\n\n"
        "## 重要な学び\n"
        "- 2026-08-21: 学びA <!-- s:5 last:2026-08-21 -->\n"
        "- 2026-08-22: 学びB\n\n"
        "## Archive\n"
        "- 2026-01-01: 古い項目 <!-- s:1 last:2026-01-01 -->\n",
        encoding="utf-8",
    )
    (root / "principles").mkdir()
    (root / "principles" / "a.md").write_text("x", encoding="utf-8")
    (root / "journal").mkdir()
    (root / "journal" / "2026-08-20.md").write_text("x", encoding="utf-8")
    (root / "journal" / "2026-08-25.md").write_text("x", encoding="utf-8")
    (root / "wiki").mkdir()
    (root / "wiki" / "note.md").write_text("x", encoding="utf-8")
    return root


def test_memory_stats_counts_and_archive():
    root = _make_root()
    stats = status.memory_stats(root)
    assert stats["total"] == 4
    assert stats["scored"] == 3
    assert stats["archived"] == 1
    assert stats["scores"] == [2, 5, 1]


def test_memory_stats_missing_file():
    root = Path(tempfile.mkdtemp())
    assert status.memory_stats(root) == {"total": 0, "scored": 0, "archived": 0, "scores": []}


def test_status_lines_summary():
    root = _make_root()
    out = "\n".join(status.status_lines(root, root / "wiki"))
    assert "4 entries (3 scored, 1 archived)" in out
    assert "wiki           : 1 note(s)" in out
    assert "principles     : 1 file(s)" in out
    assert "latest 2026-08-25" in out
    # counts only: no personal content leaks into the summary
    assert "朝の会話" not in out


def test_latest_date_handles_gaps():
    root = Path(tempfile.mkdtemp())
    assert status._latest_date(root / "journal") == "-"


def run_tests():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"    -> PASS: {fn.__name__}")
    print(f"[*] All {len(tests)} status tests PASSED!")


if __name__ == "__main__":
    run_tests()
