import urllib.request
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

class DDGLiteParser(HTMLParser):
    """Extract (title, url, snippet) triples from DuckDuckGo search HTML.

    DuckDuckGo serves two variants with different class names:
    ``lite.duckduckgo.com`` uses ``result-link`` / ``result-snippet`` and
    ``html.duckduckgo.com`` uses ``result__a`` / ``result__snippet``. Links and
    snippets live in separate elements, so both are collected in document order and
    paired afterwards. Only the element that opened a snippet is tracked, so nested
    markup (e.g. ``<b>`` inside a snippet) no longer breaks the pairing.
    """

    LINK_CLASSES = ("result-link", "result__a")
    SNIPPET_CLASSES = ("result-snippet", "result__snippet")

    def __init__(self):
        super().__init__()
        self.links = []
        self.snippets = []
        self._in_link = False
        self._link_href = ""
        self._link_text = []
        self._snippet_tag = ""
        self._snippet_depth = 0
        self._snippet_text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")
        if tag == "a" and any(c in cls for c in self.LINK_CLASSES):
            self._in_link = True
            href = attrs_dict.get("href", "")
            if href.startswith("//"):
                href = "https:" + href
            self._link_href = href
            self._link_text = []
        elif self._snippet_tag:
            if tag == self._snippet_tag:
                self._snippet_depth += 1
        elif any(c in cls for c in self.SNIPPET_CLASSES):
            self._snippet_tag = tag
            self._snippet_depth = 1
            self._snippet_text = []

    def handle_endtag(self, tag):
        if self._in_link and tag == "a":
            self._in_link = False
            title = "".join(self._link_text).strip()
            if title:
                self.links.append((self._link_href, title))
        elif self._snippet_tag and tag == self._snippet_tag:
            self._snippet_depth -= 1
            if self._snippet_depth == 0:
                self.snippets.append(" ".join("".join(self._snippet_text).split()))
                self._snippet_tag = ""
                self._snippet_text = []

    def handle_data(self, data):
        if self._in_link:
            self._link_text.append(data)
        elif self._snippet_tag:
            self._snippet_text.append(data)

    def results(self) -> list[dict]:
        """Pair link titles with snippets in document order."""
        out = []
        for i, (href, title) in enumerate(self.links):
            out.append({
                "title": title,
                "url": href,
                "snippet": self.snippets[i] if i < len(self.snippets) else "",
            })
        return out

def _extract_real_url(href: str) -> str:
    """Unwrap DuckDuckGo redirect (//duckduckgo.com/l/?uddg=...)."""
    if "uddg=" in href:
        try:
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            real = qs.get("uddg", [""])[0]
            if real:
                return urllib.parse.unquote(real)
        except Exception:
            pass
    if href.startswith("//"):
        return "https:" + href
    return href


def _fetch_and_parse(query: str, url: str, timeout: int = 15) -> list[dict]:
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="replace")
    parser = DDGLiteParser()
    parser.feed(html)
    results = parser.results()
    # Unwrap redirect URLs
    for r in results:
        if "url" in r:
            r["url"] = _extract_real_url(r["url"])
    return results


DEFAULT_RESULT_LIMIT = 5
MAX_RESULT_LIMIT = 10


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


def _dedupe_by_domain(results: list[dict]) -> list[dict]:
    """Keep the first result per domain, then the rest (diversity first).

    A generic query ("latest local LLM 2026") can fill every slot with one
    aggregator site and bury specific, newer sources. Ranking distinct domains
    first keeps room for them (refs #31).
    """
    seen = set()
    primary, rest = [], []
    for r in results:
        d = _domain(r.get("url", ""))
        if d and d not in seen:
            seen.add(d)
            primary.append(r)
        else:
            rest.append(r)
    return primary + rest


def _format_results(results: list[dict], limit: int = DEFAULT_RESULT_LIMIT) -> str:
    """Format search results as numbered title/URL/summary blocks."""
    formatted = []
    for i, r in enumerate(_dedupe_by_domain(results)[:limit]):
        title = r.get("title", "No Title")
        link = r.get("url", "")
        snippet = r.get("snippet", "")
        formatted.append(f"[{i+1}] {title}\nURL: {link}\nSummary: {snippet}\n")
    return "\n".join(formatted)


def run(base: Path, path: str = "", body: str = "", **kwargs) -> str:
    query = body.strip() or kwargs.get("query", "").strip()
    if not query:
        return "[ERROR] Query is empty."

    try:
        limit = int(str(kwargs.get("limit", DEFAULT_RESULT_LIMIT)))
    except ValueError:
        limit = DEFAULT_RESULT_LIMIT
    limit = max(1, min(limit, MAX_RESULT_LIMIT))

    print(f"[*] Web searching for: {query}")
    urls = [
        "https://lite.duckduckgo.com/lite/",
        "https://html.duckduckgo.com/html/",
    ]
    last_error = ""
    for url in urls:
        try:
            results = _fetch_and_parse(query, url, timeout=15)
            if results:
                return _format_results(results, limit)
            last_error = "No results found."
        except Exception as e:
            last_error = str(e)
            continue

    if last_error == "No results found.":
        return "No results found."
    return f"[ERROR] Web search failed: {last_error} (tried lite + html endpoints)"
