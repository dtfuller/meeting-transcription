import html as _html
import re

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": False})
_UNK_RE = re.compile(r"(Unknown Speaker \d+)")


def render(text: str) -> str:
    return _md.render(text or "")


def render_transcript(text: str) -> str:
    """HTML-escape the transcript, then wrap 'Unknown Speaker N' in <span class="unk">."""
    escaped = _html.escape(text or "")
    return _UNK_RE.sub(r'<span class="unk">\1</span>', escaped)
