import json

import pytest

from app import categorize, store
from tests.helpers.fake_anthropic import FakeAnthropic


def test_propose_returns_subdir_and_tags():
    fake_json = json.dumps({
        "subdir": "multiturbo",
        "tags": [
            {"name": "Darwin Henao", "type": "person"},
            {"name": "multiturbo", "type": "topic"},
            {"name": "2026 Q2 roadmap", "type": "project"},
        ],
    })
    client = FakeAnthropic(text=fake_json)

    proposal = categorize.propose(
        transcript="[00:00:15 Darwin Henao] hola",
        knowledge="# Knowledge\nmultiturbo status...",
        commitments="# Commitments\nDarwin owns X",
        existing_subdirs=["multiturbo", "check-in"],
        known_names=["Darwin Henao", "David Fuller"],
        client=client,
    )
    assert proposal.subdir == "multiturbo"
    assert len(proposal.tags) == 3
    assert store.Tag(name="Darwin Henao", type="person") in proposal.tags


def test_propose_wraps_response_in_xml_when_no_json():
    fake_json = '<response>' + json.dumps({"subdir": "foo", "tags": []}) + '</response>'
    client = FakeAnthropic(text=fake_json)
    proposal = categorize.propose(
        transcript="t", knowledge="k", commitments="c",
        existing_subdirs=[], known_names=[],
        client=client,
    )
    assert proposal.subdir == "foo"
    assert proposal.tags == []


def test_propose_strips_unknown_tag_types():
    fake_json = json.dumps({
        "subdir": "x",
        "tags": [
            {"name": "keep", "type": "person"},
            {"name": "drop", "type": "weird"},
        ],
    })
    client = FakeAnthropic(text=fake_json)
    proposal = categorize.propose(
        transcript="t", knowledge="k", commitments="c",
        existing_subdirs=[], known_names=[],
        client=client,
    )
    names = [t.name for t in proposal.tags]
    assert "keep" in names
    assert "drop" not in names


def test_propose_sends_existing_subdirs_in_prompt():
    client = FakeAnthropic(text=json.dumps({"subdir": "x", "tags": []}))
    categorize.propose(
        transcript="t", knowledge="k", commitments="c",
        existing_subdirs=["multiturbo", "check-in"],
        known_names=["Darwin Henao"],
        client=client,
    )
    kwargs = client.messages.last_kwargs
    user_msg = kwargs["messages"][0]["content"]
    assert "multiturbo" in user_msg
    assert "check-in" in user_msg
    assert "Darwin Henao" in user_msg
