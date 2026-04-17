from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": False})


def render(text: str) -> str:
    return _md.render(text or "")
