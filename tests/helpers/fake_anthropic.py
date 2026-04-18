"""Minimal drop-in stub for the anthropic.Anthropic client used by app/categorize.py.

Returns a canned text response. Tests inject one of these via dependency.
"""
from dataclasses import dataclass


@dataclass
class _Block:
    text: str


@dataclass
class _Message:
    content: list

    def __post_init__(self):
        if not isinstance(self.content, list):
            self.content = [self.content]


class FakeMessages:
    def __init__(self, text: str):
        self._text = text
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _Message(content=[_Block(text=self._text)])


class FakeAnthropic:
    def __init__(self, text: str):
        self.messages = FakeMessages(text)
