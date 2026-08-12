"""Converts HTML email bodies to plain text for rendering and keyword scanning.

evidence_text.py
================
Project : email-evidence-tools
Purpose : Shared HTML-to-text conversion. Both render_mbox_to_markdown.py and
          scan_mbox_for_evidence.py have to turn an HTML-only message body into
          readable, matchable text, and they must agree on the result: a hit the
          scanner reports has to be findable in the rendered document.

          The converter preserves line breaks at block boundaries and appends
          hyperlink targets in angle brackets, so a link's destination survives
          into the evidence record instead of being silently dropped with the
          markup.
"""

import re
from html.parser import HTMLParser


class _HtmlToText(HTMLParser):
    """Minimal HTML stripper that preserves line breaks and hyperlink URLs."""

    BLOCK_TAGS = {
        "p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre", "table", "thead", "tbody",
    }
    SKIP_TAGS = {"script", "style", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts = []
        self._skip_depth = 0
        self._last_link = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == "a":
            for k, v in attrs:
                if k == "href":
                    self._last_link = v
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")
        if tag == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "a" and self._last_link:
            self._parts.append(f" <{self._last_link}>")
            self._last_link = None
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self):
        out = "".join(self._parts)
        # Strip trailing whitespace from each line (Outlook HTML often produces
        # "<p>&nbsp;</p>" which decodes to a line containing only   / spaces).
        out = "\n".join(line.rstrip() for line in out.splitlines())
        # Collapse runs of >2 blank lines down to 2.
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()


def html_to_text(html: str) -> str:
    """Return the visible text of an HTML fragment, with hyperlink targets kept inline."""
    p = _HtmlToText()
    try:
        p.feed(html)
        p.close()
    except Exception as e:
        return f"[html-to-text parse error: {e!r}]\n\n{html}"
    return p.text()
