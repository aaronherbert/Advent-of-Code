"""Turn an adventofcode.com puzzle page into plain text for the generator.

Only the puzzle text that is sent to the model is produced here; it is never
committed or published. Lines that would reveal the user's own accepted answers
are stripped so they cannot leak into prompts.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_ARTICLE = re.compile(r'<article class="day-desc">(.*?)</article>', re.S)
_TITLE = re.compile(r"--- Day (\d+): (.*?) ---")
_ANSWER = re.compile(r"Your puzzle answer was\s*<code>(.*?)</code>", re.S)
_DROP_PREFIXES = ("Your puzzle answer was", "Both parts of this puzzle are complete",
                  "At this point, you should return to your Advent calendar")


class _ToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._buf: list[str] = []
        self._in_pre = False
        self._pre: list[str] = []
        self._li = False

    def _flush(self, prefix: str = "") -> None:
        text = "".join(self._buf).strip()
        self._buf = []
        if text:
            self.blocks.append(prefix + re.sub(r"[ \t]+", " ", text))

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self._flush()
            self._in_pre = True
            self._pre = []
        elif tag in ("p", "ul", "ol", "h2", "h3"):
            self._flush()
        elif tag == "li":
            self._flush()
            self._li = True
        elif tag == "code" and not self._in_pre:
            self._buf.append("`")
        elif tag == "em" and not self._in_pre:
            self._buf.append("*")
        elif tag == "br":
            self._buf.append("\n")

    def handle_endtag(self, tag):
        if tag == "pre":
            self.blocks.append("```\n" + "".join(self._pre).rstrip("\n") + "\n```")
            self._in_pre = False
        elif tag == "h2":
            self._flush("## ")
        elif tag == "h3":
            self._flush("### ")
        elif tag in ("p", "ul", "ol"):
            self._flush()
        elif tag == "li":
            self._flush("- ")
            self._li = False
        elif tag == "code" and not self._in_pre:
            self._buf.append("`")
        elif tag == "em" and not self._in_pre:
            self._buf.append("*")

    def handle_data(self, data):
        (self._pre if self._in_pre else self._buf).append(data)


def article_to_text(article_html: str) -> str:
    parser = _ToMarkdown()
    parser.feed(article_html)
    parser._flush()
    blocks = [b for b in parser.blocks if not b.lstrip("# ").startswith(_DROP_PREFIXES)]
    return "\n\n".join(blocks).strip()


def parse_puzzle_page(page: str) -> dict:
    """Return {title, parts, text (one string per part), verified (answers AoC accepted)}."""
    articles = _ARTICLE.findall(page)
    texts = [article_to_text(a) for a in articles]
    title = ""
    m = _TITLE.search(page)
    if m:
        title = html.unescape(m.group(2)).strip()
    verified = [html.unescape(re.sub(r"<[^>]+>", "", a)).strip() for a in _ANSWER.findall(page)]
    return {"title": title, "parts": len(texts), "text": texts, "verified": verified[:2]}
