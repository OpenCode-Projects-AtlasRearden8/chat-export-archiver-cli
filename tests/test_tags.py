"""Tests for tags.toml loading and matching."""

from pathlib import Path

import pytest

from chat_archiver.parse import Conversation, Message
from chat_archiver.tags import TagsError, load_tags, match_tags, write_default_tags


def test_load_tags_missing_creates_starter(tmp_path: Path):
    path = tmp_path / "tags.toml"
    tags = load_tags(path)
    assert path.exists()
    assert "tags" in path.read_text(encoding="utf-8")
    assert "gardening" in tags


def test_load_tags_parses(tmp_path: Path):
    path = tmp_path / "tags.toml"
    path.write_text(
        '[tags]\nsports = ["chess", "garden"]\nwork = 42\nempty = []\n',
        encoding="utf-8",
    )
    tags = load_tags(path)
    assert tags == {"sports": ["chess", "garden"]}


def test_load_tags_malformed_raises(tmp_path: Path):
    path = tmp_path / "tags.toml"
    path.write_text("[tags\nbroken = =", encoding="utf-8")
    with pytest.raises(TagsError):
        load_tags(path)


def test_load_tags_no_tags_table(tmp_path: Path):
    path = tmp_path / "tags.toml"
    path.write_text('[other]\nx = ["y"]\n', encoding="utf-8")
    assert load_tags(path) == {}


def test_match_tags_checks_title_and_content():
    settings = {
        "books": ["ebay", "textbook"],
        "games": ["chess"],
        "nothing": ["zebra"],
    }
    conv = Conversation(
        title="eBay listing brainstorm",
        messages=[
            Message(role="user", content="Chess set pricing?"),
            Message(role="assistant", content="Compare sold listings."),
        ],
    )
    tags = match_tags(conv, settings)
    assert tags == ["books", "games"]


def test_write_default_tags(tmp_path: Path):
    path = write_default_tags(tmp_path / "somewhere" / "tags.toml")
    assert path.exists()
    assert "[tags]" in path.read_text(encoding="utf-8")
