#!/usr/bin/env python3
"""
Tests for saku.recall (memory prefetch for the light prompt, refs #32).

No LLM: recall is a pure keyword search over a temporary memory root.
"""

import sys
import tempfile
from pathlib import Path

CODE_ROOT = Path(__file__).parent
sys.path.append(str(CODE_ROOT))
_REPO_ROOT = CODE_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from saku import recall
from saku import config as cfg_mod

MEMORY_MD = """# MEMORY — 長期記憶

## 好み・傾向
- 2026-08-20: Ownerは朝の会話を好む <!-- s:2 last:2026-08-20 -->

## 進行中のプロジェクト
- 2026-08-25: ローカルLLMのベンチマークを進行中 <!-- s:1 last:2026-08-25 -->
"""

PRINCIPLE = "# 原則\n\n- 推測で断定しない\n"


def _make_root():
    tmp = tempfile.mkdtemp()
    root = Path(tmp)
    (root / "MEMORY.md").write_text(MEMORY_MD, encoding="utf-8")
    (root / "principles").mkdir()
    (root / "principles" / "2026-08-01-honesty.md").write_text(PRINCIPLE, encoding="utf-8")
    (root / "wiki").mkdir()
    (root / "wiki" / "local-llm.md").write_text(
        "# ローカルLLM 2026\nQwen3.8-Flash-Next が候補。\n", encoding="utf-8"
    )
    return root


def test_terms_filters_common_words():
    ts = recall.terms("これはローカルLLMの話です")
    assert "ローカルllm" in ts or "ローカル" in ts
    assert "です" not in ts
    assert "これ" not in ts


def test_recall_returns_relevant_lines():
    root = _make_root()
    block = recall.recall(root, "ローカルLLMの状況は？")
    assert "関連する記憶" in block
    assert "ローカルLLM" in block
    assert "SEARCH_NOTES" in block


def test_recall_respects_item_budget():
    root = _make_root()
    block = recall.recall(root, "ローカルLLM 進行中 朝の会話", items=1)
    assert block.count("- (") == 1


def test_recall_respects_char_budget():
    root = _make_root()
    block = recall.recall(root, "ローカルLLMの状況は？", items=10, max_chars=60)
    assert len(block) < 400  # a couple of entries at most, not the whole file


def test_recall_empty_when_no_match():
    root = _make_root()
    assert recall.recall(root, "まったく無関係な話題xyz") == ""


def test_recall_strips_entry_metadata():
    root = _make_root()
    block = recall.recall(root, "朝の会話")
    assert "<!--" not in block
    assert "Ownerは朝の会話を好む" in block


def test_load_recall_config_defaults():
    d = cfg_mod.load_recall_config({})
    assert d.enabled is True
    assert d.items == 3
    assert d.max_chars == 600
    custom = cfg_mod.load_recall_config({"recall": {"enabled": False, "items": 1}})
    assert custom.enabled is False
    assert custom.items == 1


def run_tests():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"    -> PASS: {fn.__name__}")
    print(f"[*] All {len(tests)} recall tests PASSED!")


if __name__ == "__main__":
    run_tests()
