"""Tests for export detection and parsing."""

import json
from pathlib import Path

import pytest

from chat_archiver.parse import FormatError, parse_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_chatgpt_mapping_tree():
    convs = parse_file(FIXTURES / "chatgpt_conversations.json")
    assert len(convs) == 2
    garden = convs[0]
    assert garden.plain_title == "Planning a raised bed garden"
    assert garden.fmt == "openai-chatgpt"
    assert garden.date_str == "2024-03-15"
    roles = [m.role for m in garden.messages]
    assert roles == ["user", "assistant"]  # empty system node dropped
    assert "topsoil" in garden.messages[1].content
    assert garden.messages[1].model == "gpt-4o"
    assert garden.model == "gpt-4o"
    chess = convs[1]
    assert chess.messages[1].content.startswith("Drill two ideas")
    assert chess.model == "gpt-4o-mini"


def test_openwebui_chat():
    [conv] = parse_file(FIXTURES / "openwebui_chat.json")
    assert conv.title == "Ollama model ideas"
    assert conv.fmt == "openwebui-json"
    assert conv.model == "llama3"
    assert conv.messages[0].timestamp is not None
    assert conv.date_str == "2024-05-01"


def test_generic_message_list():
    [conv] = parse_file(FIXTURES / "generic_messages.json")
    assert conv.fmt == "json-generic"
    assert [m.role for m in conv.messages] == ["user", "assistant"]
    assert "bookkeeping" in conv.messages[0].content
    assert conv.date_str == "2024-05-22"


def test_wrapper_conversations():
    convs = parse_file(FIXTURES / "generic_conversations.json")
    assert len(convs) == 2
    titles = [c.plain_title for c in convs]
    assert titles == ["Budget check-in", "eBay listing brainstorm"]
    assert convs[0].model == "mistral"


def test_markdown_export_roles():
    [conv] = parse_file(FIXTURES / "markdown_export.md")
    assert conv.title == "Exported conversation"
    assert conv.fmt == "markdown"
    roles = [m.role for m in conv.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert conv.messages[1].content.startswith("Check three sold listings")
    assert conv.messages[3].content.startswith("Weigh the book")


def test_markdown_code_fence_survives():
    [conv] = parse_file(FIXTURES / "markdown_export.md")
    assistant = conv.messages[1].content
    assert "median(sold prices)" in assistant
    assert "seller_fees" in assistant
    assert assistant.count("```") == 2
    assert all(m.role != "note" for m in conv.messages)


def test_markdown_without_role_markers_still_parses(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text("# My seed bank\n\nPeppers and whatnot.\n", encoding="utf-8")
    [conv] = parse_file(path)
    assert conv.title == "My seed bank"
    assert len(conv.messages) == 1
    assert conv.messages[0].role == "user"
    assert "Peppers" in conv.messages[0].content


def test_title_fallback_from_first_user_message(tmp_path: Path):
    path = tmp_path / "no_title.json"
    path.write_text(
        json.dumps([
            {"role": "user", "content": "Need a pergola plan for a small yard.<br>"},
            {"role": "assistant", "content": "Sure."},
        ]),
        encoding="utf-8",
    )
    [conv] = parse_file(path)
    assert conv.title.startswith("Need a pergola plan")


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FormatError):
        parse_file(tmp_path / "does_not_exist.json")


def test_invalid_json_raises(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text('{"half a thought', encoding="utf-8")
    with pytest.raises(FormatError):
        parse_file(path)


def test_unrecognized_json_shape_raises(tmp_path: Path):
    path = tmp_path / "weird.json"
    path.write_text(json.dumps({"hello": [1, 2, 3]}), encoding="utf-8")
    with pytest.raises(FormatError):
        parse_file(path)


def test_empty_source_folder_errors(tmp_path: Path):
    with pytest.raises(FormatError):
        parse_file(tmp_path / "does_not_exist.json")
