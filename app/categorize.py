from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from app.store import Tag

_VALID_TAG_TYPES = {"person", "topic", "project"}
CATEGORIZE_MODEL = "claude-opus-4-6"
SYSTEM_PROMPT = (
    "You classify a meeting transcript. Return ONLY a JSON object with keys:\n"
    '  "subdir": string — pick one from the given list, or invent a short '
    "slug-case name if none fit.\n"
    '  "tags": array of {"name": string, "type": "person"|"topic"|"project"}.\n'
    "Include every person clearly named in the transcript (prefer full names). "
    "Include topic tags for the main subject(s). Include project tags only when a "
    "project name is explicitly referenced. Return no prose outside the JSON."
)


@dataclass(frozen=True)
class CategorizeProposal:
    subdir: str
    tags: list[Tag]


def _build_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def propose(
    transcript: str,
    knowledge: str,
    commitments: str,
    existing_subdirs: list[str],
    known_names: list[str],
    client=None,
) -> CategorizeProposal:
    if client is None:
        client = _build_client()

    subdirs_list = ", ".join(existing_subdirs) if existing_subdirs else "(none)"
    known_list = ", ".join(known_names) if known_names else "(none)"

    user_msg = (
        f"Existing subdirs: {subdirs_list}\n"
        f"Known speakers already in the voiceprint library: {known_list}\n\n"
        f"## Transcript\n{transcript[:8000]}\n\n"
        f"## Knowledge\n{knowledge}\n\n"
        f"## Commitments\n{commitments}\n"
    )

    response = client.messages.create(
        model=CATEGORIZE_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    data = _extract_json(text)
    subdir = str(data.get("subdir", "")).strip()
    raw_tags = data.get("tags", []) or []
    tags: list[Tag] = []
    for t in raw_tags:
        try:
            name = str(t["name"]).strip()
            ttype = str(t["type"]).strip()
        except (KeyError, TypeError):
            continue
        if not name or ttype not in _VALID_TAG_TYPES:
            continue
        tags.append(Tag(name=name, type=ttype))
    return CategorizeProposal(subdir=subdir, tags=tags)


def _extract_json(text: str) -> dict:
    # Strip optional <response>...</response> wrapper
    match = re.search(r"<response>(.*?)</response>", text, re.DOTALL)
    if match:
        text = match.group(1)
    # Find the outermost JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
