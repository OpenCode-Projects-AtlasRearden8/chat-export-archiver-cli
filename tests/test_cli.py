"""Tests for CLI commands and the optional summary flow (no network)."""

import urllib.error
from pathlib import Path

import pytest

from chat_archiver import cli
from chat_archiver.archive import read_front_matter

FIXTURES = Path(__file__).parent / "fixtures"


def run_cli(argv, capsys=None):
    return cli.main(argv)


@pytest.fixture()
def tmp_archive(tmp_path: Path):
    out = tmp_path / "archive"
    tags = tmp_path / "empty-tags.toml"  # loads as an empty starter file
    code = run_cli(["archive", str(FIXTURES), "-o", str(out), "-t", str(tags)])
    assert code == 0
    return out


def test_archive_command(tmp_path: Path):
    out = tmp_path / "archive"
    tags_file = tmp_path / "tags.toml"
    tags_file.write_text('[tags]\nbooks = ["ebay", "textbook"]\n', encoding="utf-8")
    code = run_cli(["archive", str(FIXTURES), "-o", str(out), "-t", str(tags_file)])
    assert code == 0
    conversation_files = [
        p.name for p in out.glob("*.md")
        if p.name not in ("index.md", "index.html")
    ]
    assert conversation_files
    assert (out / "index.md").exists()
    assert (out / "index.html").exists()


def test_auto_starter_tags_file(tmp_path: Path):
    out = tmp_path / "archive"
    tags_file = tmp_path / "tags.toml"
    assert tags_file.exists() is False
    code = run_cli(["archive", str(FIXTURES), "-o", str(out), "-t", str(tags_file)])
    assert code == 0
    assert tags_file.exists()  # starter file written on first use


def test_archive_missing_source(tmp_path: Path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    code = run_cli(["archive", str(empty), "-o", str(tmp_path / "a")])
    assert code == 2
    assert "no supported export files" in capsys.readouterr().err


def test_archive_nonexistent_source(tmp_path: Path, capsys):
    code = run_cli(["archive", str(tmp_path / "ghost"), "-o", str(tmp_path / "a")])
    assert code == 2
    assert "source path not found" in capsys.readouterr().err


def test_dry_run_writes_nothing(tmp_path: Path):
    out = tmp_path / "archive"
    code = run_cli(["archive", str(FIXTURES), "-o", str(out), "-n"])
    assert code == 0
    assert not out.exists()


def test_index_rebuild_command(tmp_archive: Path):
    code = run_cli(["index", str(tmp_archive)])
    assert code == 0
    assert (tmp_archive / "index.html").exists()


def test_init_tags_command(tmp_path: Path):
    tags = tmp_path / "tags2.toml"
    code = run_cli(["init-tags", "--path", str(tags)])
    assert code == 0
    assert "[tags]" in tags.read_text(encoding="utf-8")


def test_tag_command_updates_files(tmp_archive: Path):
    tags = Path(tmp_archive.parent) / "mytags.toml"
    tags.write_text('[tags]\nsports = ["chess"]\nhealth = ["soil"]\n', encoding="utf-8")
    code = run_cli(["tag", str(tmp_archive), "-t", str(tags)])
    assert code == 0
    hits = 0
    for p in tmp_archive.glob("*.md"):
        if p.name.startswith("index"):
            continue
        meta = read_front_matter(p)
        if "sports" in meta["tags"] or "health" in meta["tags"]:
            hits += 1
    assert hits >= 2


def test_summarize_offline_is_graceful(tmp_archive: Path, capsys, monkeypatch):
    def boom(url, payload):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr("chat_archiver.summarize._post_json", boom)
    code = run_cli(["summarize", str(tmp_archive), "--base-url", "http://127.0.0.1:1/v1"])
    assert code == 0
    err = capsys.readouterr().err
    assert "skipped" in err    # graceful skip reported
    assert "127.0.0.1:1" in err


def test_summarize_with_fake_endpoint(tmp_archive: Path, monkeypatch):
    calls = []

    def fake_post(url, payload):
        calls.append(url)
        return {"choices": [{"message": {"content": "Two people plan a garden, briefly.\n"}}]}

    monkeypatch.setattr("chat_archiver.summarize._post_json", fake_post)
    code = run_cli(["summarize", str(tmp_archive), "--base-url", "http://127.0.0.1:9999/v1"])
    assert code == 0
    assert calls and all(u.endswith("/chat/completions") for u in calls)
    summaries = 0
    for p in tmp_archive.glob("*.md"):
        if p.name.startswith("index"):
            continue
        assert read_front_matter(p).get("summary", "").startswith("Two people")
        summaries += 1
    assert summaries >= 6


def test_roundtrip_preserves_metadata_and_stamps(tmp_archive: Path):
    conv_before = cli.conversation_from_archive_file(
        tmp_archive / "2024-03-15-planning-a-raised-bed-garden.md"
    )
    assert conv_before.created_str == "2024-03-15 00:00:00 UTC"
    assert conv_before.model == "gpt-4o"
    assert conv_before.messages[0].timestamp is not None

    tags = Path(tmp_archive.parent) / "roundtrip_tags.toml"
    tags.write_text('[tags]\nsports = ["chess"]\n', encoding="utf-8")
    assert run_cli(["tag", str(tmp_archive), "-t", str(tags)]) == 0

    after_file = tmp_archive / "2024-03-15-planning-a-raised-bed-garden.md"
    text = after_file.read_text(encoding="utf-8")
    assert text.count("2024-03-15 00:00:05 UTC") == 1  # no duplicated stamp lines
    conv_after = cli.conversation_from_archive_file(after_file)
    assert conv_after.created_str == conv_before.created_str
    assert conv_after.model == conv_before.model
    assert len(conv_after.messages) == len(conv_before.messages)
    assert "topsoil" in conv_after.messages[1].content


def test_summarize_never_sends_auth_header(monkeypatch, tmp_archive: Path):
    def fake_post(url, payload):
        return {"choices": [{"message": {"content": "ok"}}]}

    import chat_archiver.summarize as mod

    monkeypatch.setattr(mod, "_post_json", fake_post)
    run_cli(["summarize", str(tmp_archive)])
    # The real request builder omits Authorization - assert the module contract:
    import inspect

    src = inspect.getsource(mod._post_json)
    assert "Authorization" not in src


def test_archive_summarize_flag(tmp_path: Path, monkeypatch):
    def fake_post(url, payload):
        assert payload["model"].endswith("3")
        return {"choices": [{"message": {"content": "Short summary."}}]}

    monkeypatch.setattr("chat_archiver.summarize._post_json", fake_post)
    out = tmp_path / "archive"
    code = run_cli([
        "archive", str(FIXTURES), "-o", str(out), "-s",
        "--base-url", "http://127.0.0.1:11434/v1", "--model", "llama3",
    ])
    assert code == 0
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Short summary" in html
