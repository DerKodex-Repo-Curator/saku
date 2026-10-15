#!/usr/bin/env python3
"""
Unit tests for the daemon's time-aware scheduling (saku.daemon).

Focuses on the midnight reflection gate, which used to depend on a 5-minute
window (02:00-02:05) and silently skipped the day when missed. No LLM is
involved: the reflection runner is mocked.
"""

import sys
from datetime import datetime
from pathlib import Path

CODE_ROOT = Path(__file__).parent
sys.path.append(str(CODE_ROOT))
_REPO_ROOT = CODE_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from saku import daemon as daemon_mod

_PASS = 0
_FAIL = 0


def _mock_state(**overrides):
    state = {
        "last_reflection_date": "",
        "last_dream_date": "",
    }
    state.update(overrides)
    return state


def _patch(fn_name, impl):
    original = getattr(daemon_mod, fn_name)
    setattr(daemon_mod, fn_name, impl)
    return original


def _restore(fn_name, original):
    setattr(daemon_mod, fn_name, original)


def test_reflection_fires_when_started_after_2am():
    """Daemon started at 03:30 on a fresh day must run the midnight reflection."""
    ran = []

    class _Refl:
        @staticmethod
        def run_reflection(d):
            ran.append(d)

    orig_reflection = _patch("reflection", _Refl())
    orig_initiate = _patch("saku_self_initiate", lambda reason: None)
    orig_state = _patch("load_chat_state", lambda: _mock_state())
    saved = {}
    orig_save = _patch("save_chat_state", lambda s: saved.update(s))
    try:
        daemon_mod.check_and_run_midnight_reflection(datetime(2026, 8, 5, 3, 30))
    finally:
        _restore("reflection", orig_reflection)
        _restore("saku_self_initiate", orig_initiate)
        _restore("load_chat_state", orig_state)
        _restore("save_chat_state", orig_save)
    assert ran, "reflection did not run when started after 02:00"
    assert saved.get("last_reflection_date") == "2026-08-05"


def test_reflection_waits_until_2am():
    """Daemon started at 01:00 must NOT run reflection yet."""
    ran = []

    class _Refl:
        @staticmethod
        def run_reflection(d):
            ran.append(d)

    orig_reflection = _patch("reflection", _Refl())
    orig_initiate = _patch("saku_self_initiate", lambda reason: None)
    orig_state = _patch("load_chat_state", lambda: _mock_state())
    try:
        daemon_mod.check_and_run_midnight_reflection(datetime(2026, 8, 5, 1, 30))
    finally:
        _restore("reflection", orig_reflection)
        _restore("saku_self_initiate", orig_initiate)
        _restore("load_chat_state", orig_state)
    assert ran == [], "reflection ran before 02:00"


def test_reflection_runs_once_per_day():
    """After running once, later passes on the same day are skipped."""
    ran = []

    class _Refl:
        @staticmethod
        def run_reflection(d):
            ran.append(d)

    orig_reflection = _patch("reflection", _Refl())
    orig_initiate = _patch("saku_self_initiate", lambda reason: None)
    orig_state = _patch("load_chat_state", lambda: _mock_state(last_reflection_date="2026-08-05"))
    try:
        daemon_mod.check_and_run_midnight_reflection(datetime(2026, 8, 5, 23, 59))
    finally:
        _restore("reflection", orig_reflection)
        _restore("saku_self_initiate", orig_initiate)
        _restore("load_chat_state", orig_state)
    assert ran == [], "reflection ran twice on the same day"


def test_dreaming_catchup_on_startup():
    """Dreaming runs on the next loop after a date change (once per day)."""
    ran = []

    class _Dream:
        @staticmethod
        def run_dreaming(d):
            ran.append(d)
            return []

    orig_dreaming = _patch("dreaming", _Dream())
    orig_state = _patch("load_chat_state", lambda: _mock_state())
    saved = {}
    orig_save = _patch("save_chat_state", lambda s: saved.update(s))
    try:
        daemon_mod.check_and_run_dreaming()
    finally:
        _restore("dreaming", orig_dreaming)
        _restore("load_chat_state", orig_state)
        _restore("save_chat_state", orig_save)
    assert len(ran) == 1
    assert saved.get("last_dream_date")


def test_owner_message_gets_reply_appended():
    """chat.md message ending with '>' must produce an appended SAKU reply."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        chat = Path(tmp) / "chat.md"
        header = daemon_mod.CHAT_RESET_HEADER
        chat.write_text(header, encoding="utf-8")
        state = {"last_mtime": chat.stat().st_mtime, "last_content": header, "turn_count": 0}
        prompts = {}

        def _fake_loop(prompt, log_action_name, extra_history=None, **kw):
            prompts["prompt"] = prompt
            prompts["light"] = kw.get("light")
            return True, "おかえりなさい。"

        originals = {
            "CHAT_FILE": daemon_mod.CHAT_FILE,
            "load_chat_state": daemon_mod.load_chat_state,
            "save_chat_state": daemon_mod.save_chat_state,
            "run_agent_loop": daemon_mod.run_agent_loop,
            "get_pending_requests": daemon_mod.get_pending_requests,
            "check_chat_archive_if_needed": daemon_mod.check_chat_archive_if_needed,
            "build_recall_message": daemon_mod.agent.build_recall_message,
        }
        daemon_mod.CHAT_FILE = chat
        daemon_mod.load_chat_state = lambda: state
        daemon_mod.save_chat_state = lambda s: None
        daemon_mod.run_agent_loop = _fake_loop
        daemon_mod.get_pending_requests = lambda: ""
        daemon_mod.check_chat_archive_if_needed = lambda s: None
        daemon_mod.agent.build_recall_message = lambda msg: None
        try:
            chat.write_text(header + "\n\n今日はどう？ >\n", encoding="utf-8")
            daemon_mod.check_chat_and_reply()
        finally:
            daemon_mod.CHAT_FILE = originals["CHAT_FILE"]
            daemon_mod.load_chat_state = originals["load_chat_state"]
            daemon_mod.save_chat_state = originals["save_chat_state"]
            daemon_mod.run_agent_loop = originals["run_agent_loop"]
            daemon_mod.get_pending_requests = originals["get_pending_requests"]
            daemon_mod.check_chat_archive_if_needed = originals["check_chat_archive_if_needed"]
            daemon_mod.agent.build_recall_message = originals["build_recall_message"]

        text = chat.read_text(encoding="utf-8")
        assert "**Owner**" in text, "Owner block was not formatted into chat.md"
        assert "**SAKU**" in text, "SAKU reply block missing"
        assert "おかえりなさい" in text
        assert prompts.get("prompt", "").find("今日はどう？") >= 0
        assert prompts.get("light") is True, "chat replies must use the light prompt"
        assert state["turn_count"] == 1


def test_owner_message_without_trigger_is_ignored():
    """A chat.md edit that does not end with '>' must not call the LLM."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        chat = Path(tmp) / "chat.md"
        header = daemon_mod.CHAT_RESET_HEADER
        chat.write_text(header, encoding="utf-8")
        state = {"last_mtime": chat.stat().st_mtime, "last_content": header}
        called = {"n": 0}

        originals = {
            "CHAT_FILE": daemon_mod.CHAT_FILE,
            "load_chat_state": daemon_mod.load_chat_state,
            "save_chat_state": daemon_mod.save_chat_state,
            "run_agent_loop": daemon_mod.run_agent_loop,
        }
        daemon_mod.CHAT_FILE = chat
        daemon_mod.load_chat_state = lambda: state
        daemon_mod.save_chat_state = lambda s: None
        daemon_mod.run_agent_loop = lambda *a, **k: called.__setitem__("n", called["n"] + 1)
        try:
            chat.write_text(header + "\n\n下書き中\n", encoding="utf-8")
            daemon_mod.check_chat_and_reply()
        finally:
            daemon_mod.CHAT_FILE = originals["CHAT_FILE"]
            daemon_mod.load_chat_state = originals["load_chat_state"]
            daemon_mod.save_chat_state = originals["save_chat_state"]
            daemon_mod.run_agent_loop = originals["run_agent_loop"]
        assert called["n"] == 0, "the LLM ran without a '>' trigger"
        assert "**SAKU**" not in chat.read_text(encoding="utf-8")


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
    print(f"[*] All {_PASS + _FAIL} daemon tests {'PASSED!' if _FAIL == 0 else f'FAILED ({_FAIL})'}")
    return _FAIL == 0


if __name__ == "__main__":
    run_tests()
