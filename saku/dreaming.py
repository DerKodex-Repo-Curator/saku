"""Dreaming: promote durable memories from journal/monologue into MEMORY.md.

Runs periodically (e.g., daily). Reads short-term records (journal/monologue),
has the LLM extract important, reusable memories, and appends them to MEMORY.md
under the appropriate section (append-only, no duplication).

This is the "memory promotion" layer: raw experience (journal/monologue) -> durable
memory (MEMORY.md). Unlike the nightly reflection (which updates principles/ and
meta.md), dreaming distills facts and patterns that should persist long-term.

Growth is not only accumulation. Promoted entries carry an importance score and a
last-seen date (as an HTML comment, so Obsidian rendering stays clean). Re-mentioning
an item reinforces it (score up, last-seen refreshed), and a review pass decays stale
low-score entries into an archive section -- moved, never deleted.
"""

import re
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from saku import core as agent
from saku.agent_loop import run_agent_loop

# category -> MEMORY.md ## section heading
MEMORY_SECTIONS = {
    "永続的な事実": "永続的な事実（Owner・環境）",
    "好み・傾向": "好み・傾向",
    "重要な学び": "重要な学び",
    "進行中プロジェクト": "進行中のプロジェクト",
    "方針・決定": "方針・決定",
}

MEMORY_HEADER = """# MEMORY — 長期記憶

dreaming が journal/monologue から重要な記憶を昇格させた場所。
追記のみ。既存内容は編集しない。

## 永続的な事実（Owner・環境）

## 好み・傾向

## 重要な学び

## 進行中のプロジェクト

## 方針・決定

"""

_MEMORY_ITEM_RE = re.compile(
    r"\[MEMORY\]\s*category:\s*(.+?)\s*content:\s*(.+?)\s*\[/MEMORY\]",
    re.DOTALL,
)

# An entry line: "- 2026-08-03: some text <!-- s:3 last:2026-08-30 -->"
# The metadata comment is optional so that pre-existing (legacy) entries still parse.
_ENTRY_RE = re.compile(
    r"^\s*- (?P<date>\d{4}-\d{2}-\d{2}): (?P<text>.*?)"
    r"(?:\s*<!--\s*s:(?P<score>\d+)\s+last:(?P<last>\d{4}-\d{2}-\d{2})\s*-->)?\s*$"
)

# Category weight for the heuristic importance score (no extra LLM call).
# Decisions and durable facts outlive preferences and work-in-progress items.
CATEGORY_WEIGHTS = {
    "永続的な事実": 3,
    "方針・決定": 3,
    "重要な学び": 2,
    "好み・傾向": 2,
    "進行中プロジェクト": 1,
}
DEFAULT_SCORE = 1


def score_for(category: str, reinforcements: int = 0) -> int:
    """Heuristic importance score for a promoted item.

    Base weight comes from the category; each re-mention adds one.
    """
    return CATEGORY_WEIGHTS.get(category, DEFAULT_SCORE) + max(0, reinforcements)


def format_entry(date: str, text: str, score: int, last: str | None = None) -> str:
    """Render a MEMORY.md entry line with its score/last-seen metadata."""
    return f"- {date}: {text} <!-- s:{score} last:{last or date} -->"


def parse_entry(line: str) -> dict | None:
    """Parse an entry line. Returns None if the line is not an entry.

    ``score``/``last`` are None for legacy entries written before metadata existed.
    """
    m = _ENTRY_RE.match(line)
    if not m:
        return None
    return {
        "date": m.group("date"),
        "text": m.group("text").strip(),
        "score": int(m.group("score")) if m.group("score") else None,
        "last": m.group("last"),
    }


def _days_since(last: str, today: str) -> int:
    """Days between ``last`` and ``today`` (0 when either cannot be parsed)."""
    try:
        return (
            datetime.strptime(today, "%Y-%m-%d").date()
            - datetime.strptime(last, "%Y-%m-%d").date()
        ).days
    except ValueError:
        return 0


def _replace_lines(content: str, lines: list[str]) -> str:
    """Join ``lines`` back into content, preserving a trailing newline."""
    out = "\n".join(lines)
    if content.endswith("\n") and not out.endswith("\n"):
        out += "\n"
    return out


def _reinforce_entry(content: str, text: str, date: str, delta: int = 1) -> str:
    """Bump score and refresh last-seen for an existing entry with metadata.

    Entries without metadata (legacy) are left untouched and returned as-is.
    """
    lines = content.splitlines()
    changed = False
    for i, line in enumerate(lines):
        parsed = parse_entry(line)
        if not parsed or parsed["score"] is None:
            continue
        if parsed["text"] != text.strip():
            continue
        last = max(parsed["last"] or date, date)
        lines[i] = format_entry(parsed["date"], parsed["text"], parsed["score"] + delta, last)
        changed = True
    return _replace_lines(content, lines) if changed else content


def review(
    memory_path: Path,
    *,
    today: str,
    ttl_days: int,
    min_score: int,
    archive_section: str = "Archive",
) -> list[str]:
    """Decay review: move stale, low-score entries into the archive section.

    Only entries carrying metadata are considered, so entries written before
    scoring existed are never touched. Content is moved, never deleted.
    Returns the list of moved entry texts.
    """
    if not memory_path.exists():
        return []

    content = memory_path.read_text(encoding="utf-8")
    kept: list[str] = []
    decayed: list[str] = []

    for line in content.splitlines():
        parsed = parse_entry(line)
        stale = (
            parsed is not None
            and parsed["score"] is not None
            and parsed["last"] is not None
            and parsed["score"] <= min_score
            and _days_since(parsed["last"], today) > ttl_days
        )
        (decayed if stale else kept).append(line)

    if not decayed:
        return []

    new_content = _replace_lines(content, kept)
    anchor = f"## {archive_section}"
    if anchor in new_content:
        for entry in decayed:
            new_content = _insert_after_heading(new_content, archive_section, entry)
    else:
        new_content = new_content.rstrip() + f"\n\n{anchor}\n" + "\n".join(decayed) + "\n"

    memory_path.write_text(new_content, encoding="utf-8")
    return [parse_entry(line)["text"] for line in decayed]


def extract_items(target_date: str, journal: str, monologue: str) -> list[tuple[str, str]]:
    """Ask the LLM to extract durable memory items as [[MEMORY]] blocks."""
    system_prompt = agent.build_system_prompt()
    user_prompt = f"""[system] 夢見（dreaming）の時間です。あなたの短期的な記録から、
長期的に残す価値のある記憶を抽出してください。

【対象日 ({target_date}) の日記】
{journal if journal else "(空)"}

【対象日 ({target_date}) の独り言】
{monologue if monologue else "(空)"}

抽出するもの:
1. Ownerや環境に関する永続的な事実（好み、環境、重要な出来事）
2. 繰り返し出てくる関心事・テーマ・方針
3. 重要な学び・決定（principles/ に未反映のもの）
4. 進行中のプロジェクトやタスクの現状

除外するもの:
- 一時的な思考・感情の揺れ・その場限りの感想
- 既に principles/ や meta.md に記録済みの内容

出力形式（ツールは使わない。この形式のみ出力。※必ず単括弧を使うこと）:
[MEMORY]
category: 永続的な事実|好み・傾向|重要な学び|進行中プロジェクト|方針・決定
content: 一行で簡潔に
[/MEMORY]

複数あるなら複数出力。無ければ [NO_MEMORY] とだけ出力。
"""

    history = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = run_agent_loop(
        history,
        agent._current_llm,
        agent.context_config,
        agent.MEMORY_ROOT,
        agent.CODE_ROOT,
        max_turns=1,
    )

    items = []
    for m in _MEMORY_ITEM_RE.finditer(result.last_raw):
        category = m.group(1).strip()
        content = m.group(2).strip()
        if category in MEMORY_SECTIONS and content:
            items.append((category, content))
    return items


def _insert_after_heading(content: str, heading: str, entry: str) -> str:
    """Insert `entry` as a list item right after the `## heading` section."""
    anchor = f"## {heading}"
    pos = content.find(anchor)
    if pos == -1:
        # append a new section at the end
        return content.rstrip() + f"\n\n{anchor}\n{entry}\n"
    # find the end of the heading line, then the first blank line after it
    line_end = content.find("\n", pos)
    after = line_end + 1 if line_end != -1 else len(content)
    return content[:after] + f"{entry}\n" + content[after:]


def append_items(
    memory_path: Path,
    items: list[tuple[str, str]],
    date: str,
    *,
    scores: list[int] | None = None,
) -> list[str]:
    """Append items to MEMORY.md under their section. Returns newly added contents.

    Each entry is written with score/last-seen metadata. Re-promoting a known item
    reinforces it (score up, last-seen refreshed) instead of appending a duplicate.

    Recovers a missing, empty, or corrupted MEMORY.md by re-initializing the header.
    """
    if not memory_path.exists() or memory_path.stat().st_size == 0:
        memory_path.write_text(MEMORY_HEADER, encoding="utf-8")
    content = memory_path.read_text(encoding="utf-8")
    if "# MEMORY" not in content:
        content = MEMORY_HEADER + "\n" + content.lstrip()

    added = []
    changed = False
    for idx, (category, text) in enumerate(items):
        section = MEMORY_SECTIONS[category]
        clean = text.strip()
        if clean in content:
            # Already known: reinforce (refresh last-seen / raise score) instead.
            reinforced = _reinforce_entry(content, clean, date)
            if reinforced != content:
                content = reinforced
                changed = True
            continue
        score = scores[idx] if scores else score_for(category)
        content = _insert_after_heading(content, section, format_entry(date, clean, score, date))
        added.append(clean)
        changed = True

    if changed:
        memory_path.write_text(content, encoding="utf-8")
    return added


def run_dreaming(target_date: str | None = None) -> list[str]:
    """Run one dreaming cycle for the given date (default: today). Returns added items."""
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    journal_path = agent.SAKU_ROOT / "journal" / f"{target_date}.md"
    monologue_path = agent.SAKU_ROOT / "monologue" / f"{target_date}.md"
    journal = agent.load_file(journal_path)
    monologue = agent.load_file(monologue_path)

    if not journal and not monologue:
        print(f"[*] Dreaming: no journal/monologue for {target_date}. Skipped.")
        return []

    print(f"[*] Dreaming for {target_date}...")
    items = extract_items(target_date, journal, monologue)
    if not items:
        print("[*] Dreaming: no durable memory found.")
        return []

    memory_path = agent.SAKU_ROOT / "MEMORY.md"
    added = append_items(
        memory_path, items, target_date, scores=[score_for(cat) for cat, _ in items]
    )
    print(f"[*] Dreaming: promoted {len(added)} item(s) to MEMORY.md.")

    # Decay review: stale low-score entries move to the archive section (never deleted).
    try:
        from saku import config as cfg_mod

        cfg, _ = cfg_mod.load_config()
        dcfg = cfg_mod.load_dreaming_config(cfg)
        if dcfg.review_enabled:
            decayed = review(
                memory_path,
                today=target_date,
                ttl_days=dcfg.ttl_days,
                min_score=dcfg.min_score,
                archive_section=dcfg.archive_section,
            )
            if decayed:
                print(
                    f"[*] Dreaming: decayed {len(decayed)} stale item(s) "
                    f"to '{dcfg.archive_section}'."
                )
    except Exception as e:
        print(f"[!] Dreaming review failed: {e}")

    # Auto-wiki: create a daily wiki note from the same items so growth is visible
    try:
        from saku.wiki import create_note, regenerate_index
        from saku import config as cfg_mod

        if added:
            cfg, base = cfg_mod.load_config()
            wiki_root = cfg_mod.resolve_wiki_root(cfg, base, agent.SAKU_ROOT)
            title = f"{target_date} Learnings"
            body = "\n".join(f"- {cat}: {txt}" for cat, txt in items if txt in added)
            # Only create if not already exists for this date
            from saku.wiki import note_path

            if not note_path(wiki_root, title).exists():
                create_note(wiki_root, title, body, tags="auto,dreaming", links="[[MEMORY]]")
                print(f"[*] Dreaming: created wiki note {title} at {wiki_root}")
            regenerate_index(wiki_root)
    except Exception as e:
        print(f"[!] Dreaming wiki auto-create failed: {e}")

    return added


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    arg_date = args[0] if args else None
    run_dreaming(arg_date)
    return 0


if __name__ == "__main__":
    main()
