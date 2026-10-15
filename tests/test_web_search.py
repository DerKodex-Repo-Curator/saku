#!/usr/bin/env python3
"""
Unit tests for saku.tools.web_search (result formatting / diversity).

No network: only the pure helpers are exercised.
"""

import sys
from pathlib import Path

CODE_ROOT = Path(__file__).parent
sys.path.append(str(CODE_ROOT))
_REPO_ROOT = CODE_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from saku.tools import web_search


def _results():
    return [
        {"title": "Aggregator A", "url": "https://agg.example/a", "snippet": "s1"},
        {"title": "Aggregator B", "url": "https://agg.example/b", "snippet": "s2"},
        {"title": "Blog", "url": "https://blog.example/blog", "snippet": "s3"},
        {"title": "News", "url": "https://news.example/news", "snippet": "s4"},
    ]


def test_dedupe_puts_distinct_domains_first():
    ranked = web_search._dedupe_by_domain(_results())
    domains = [web_search._domain(r["url"]) for r in ranked]
    # The second agg.example hit must not occupy the second slot.
    assert domains[:3] == ["agg.example", "blog.example", "news.example"]
    # Nothing is dropped, it is only reordered.
    assert len(ranked) == 4
    assert domains[3] == "agg.example"


def test_format_results_limits_and_numbers():
    out = web_search._format_results(_results(), limit=2)
    assert "[1] Aggregator A" in out
    assert "[2] Blog" in out
    assert "URL: https://blog.example/blog" in out
    assert "[3]" not in out


def test_format_results_handles_missing_fields():
    out = web_search._format_results([{}], limit=5)
    assert "[1] No Title" in out
    assert "Summary: " in out


def test_run_rejects_empty_query():
    assert web_search.run(Path("."), body="") == "[ERROR] Query is empty."


_LITE_HTML = """
<table>
<tr><td>1.</td><td><a rel="nofollow" href="https://a.example/1" class='result-link'>Title <b>One</b></a></td></tr>
<tr><td>&nbsp;</td><td class='result-snippet'>Snippet with <b>bold</b> text one.</td></tr>
<tr><td>2.</td><td><a href="//b.example/2" class='result-link'>Title Two</a></td></tr>
<tr><td>&nbsp;</td><td class='result-snippet'>Snippet two.</td></tr>
<tr><td>3.</td><td><a href="https://c.example/3" class='result-link'>Title Three</a></td></tr>
<tr><td>&nbsp;</td><td class='result-snippet'>Snippet three.</td></tr>
</table>
"""

_HTML_HTML = """
<div class="result__body"><h2 class="result__title">
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fd.example%2Fx">Title Four</a>
</h2><div class="result__snippet">Snippet <b>four</b>.</div></div>
"""


def test_parser_handles_nested_markup_in_snippets():
    """Regression: <b> tags in a snippet used to break result pairing."""
    parser = web_search.DDGLiteParser()
    parser.feed(_LITE_HTML)
    results = parser.results()
    assert len(results) == 3
    assert results[0]["title"] == "Title One"
    assert results[0]["snippet"] == "Snippet with bold text one."
    assert results[1]["url"] == "https://b.example/2"
    assert results[2]["snippet"] == "Snippet three."


def test_parser_supports_html_endpoint_classes():
    parser = web_search.DDGLiteParser()
    parser.feed(_HTML_HTML)
    results = parser.results()
    assert len(results) == 1
    assert results[0]["title"] == "Title Four"
    assert web_search._extract_real_url(results[0]["url"]) == "https://d.example/x"


def run_tests():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"    -> PASS: {fn.__name__}")
    print(f"[*] All {len(tests)} web_search tests PASSED!")


if __name__ == "__main__":
    run_tests()
