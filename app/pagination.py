from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class PageInfo:
    items: list
    page: int
    per_page: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool


def paginate(items: list, page: int, per_page: int = 20) -> PageInfo:
    """Slice items for 1-based page + return navigation metadata.

    Clamps page to [1, total_pages]. total_pages is always >= 1 even for
    empty input so the template can render "Page 1 of 1" consistently.
    """
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    page = max(1, page)
    total = len(items)
    total_pages = max(1, ceil(total / per_page))
    page = min(page, total_pages)
    start = (page - 1) * per_page
    end = start + per_page
    return PageInfo(
        items=items[start:end],
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )
