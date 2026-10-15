#!/usr/bin/env python3
"""
Guard tests for meta.md (the self-model) — see issue #40.

The heading structure used to be protected by prompt text only, and the
reflection prompt contradicted the system prompt, so the model could rewrite
meta.md wholesale (dropping `## 現在の状態`, `## 得意なこと`, ...). These tests
pin the code-level guard, the single-source update rule, and the template.
"""

import re
import sys
import tempfile
from pathlib import Path

CODE_ROOT = Path(__file__).parent
sys.path.append(str(CODE_ROOT))
_REPO_ROOT = CODE_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from saku import config as cfg_mod
from saku import core as core_mod
from saku import reflection as refl_mod
from saku.tools import write_file

_PASS = 0
_FAIL = 0


def _writable_policy():
    return cfg_mod.load_path_policy(
        {
            "paths": {
                "write_allowed": cfg_mod.DEFAULT_WRITE_ALLOWED + ["meta.md"],
                "write_denied_exact": [],
            }
        }
    )


def _canonical_meta() -> str:
    return "\n".join(f"## {h}\n\n- x\n" for h in cfg_mod.META_SECTION_HEADINGS)


def test_headings_match_the_template():
    """The guard's heading list must match memory/meta.template.md."""
    template = _REPO_ROOT / "memory" / "meta.template.md"
    text = template.read_text(encoding="utf-8")
    found = [m.group(1).strip() for m in re.finditer(r"^##[ \t]+(.+?)[ \t]*$", text, re.MULTILINE)]
    assert found == cfg_mod.META_SECTION_HEADINGS, f"template drift: {found} != {cfg_mod.META_SECTION_HEADINGS}"


def test_write_file_rejects_changed_headings_when_policy_allows_overwrite():
    original = cfg_mod._policy_cache
    cfg_mod._policy_cache = _writable_policy()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed = write_file.run(root, "meta.md", "## 最近の出来事\n\n- 構造を壊す\n")
            assert "[DENY]" in changed, changed
            assert "見出し" in changed, changed

            dropped = write_file.run(root, "meta.md", "## 状態\n\n## 最近の出来事\n")
            assert "[DENY]" in dropped, dropped

            added = write_file.run(root, "meta.md", _canonical_meta() + "\n## 追加セクション\n")
            assert "[DENY]" in added, added

            kept = write_file.run(root, "meta.md", _canonical_meta())
            assert "[OK]" in kept, kept

            h3_ok = write_file.run(root, "meta.md", _canonical_meta().replace("- x", "- x\n\n### 小見出し"))
            assert "[OK]" in h3_ok, f"a ### subheading must not be mistaken for a ## section: {h3_ok}"
    finally:
        cfg_mod._policy_cache = original


def test_write_file_still_denies_meta_md_under_the_default_policy():
    original = cfg_mod._policy_cache
    cfg_mod._policy_cache = cfg_mod.load_path_policy({})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            res = write_file.run(Path(tmp), "meta.md", _canonical_meta())
            assert "[DENY]" in res and "APPEND_FILE" in res, res
    finally:
        cfg_mod._policy_cache = original


def test_meta_update_rule_follows_the_policy_and_the_reflection_prompt_agrees():
    """The reflection prompt must not contradict the system prompt (issue #40)."""
    original = cfg_mod._policy_cache
    try:
        cases = [
            (cfg_mod.load_path_policy({}), True),
            (_writable_policy(), False),
        ]
        for policy, append_only in cases:
            cfg_mod._policy_cache = policy
            rule = core_mod.meta_update_rule()
            prompt = refl_mod.build_reflection_prompt("2026-08-05", "journal", "monologue")
            assert rule in prompt, "the reflection prompt must use meta_update_rule()"
            if append_only:
                assert "禁止" in rule, rule
                assert "WRITE_FILE" in rule, rule
            else:
                assert "上書き可能" in rule, rule
                assert "上書きは禁止" not in prompt, "the reflection prompt contradicts the writable policy"
    finally:
        cfg_mod._policy_cache = original


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
    print(f"[*] All {_PASS + _FAIL} meta guard tests {'PASSED!' if _FAIL == 0 else f'FAILED ({_FAIL})'}")
    return _FAIL == 0


if __name__ == "__main__":
    run_tests()
