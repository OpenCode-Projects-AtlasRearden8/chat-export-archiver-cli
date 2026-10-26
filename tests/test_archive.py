"""End-to-end tests for archiving output and index building."""

from pathlib import Path

from chat_archiver.archive import (
    conversation_filename,
    read_front_matter,
    render_conversation,
    slugify,
    write_conversations,
)
from chat_archiver.index import build_index
from chat_archiver.parse import parse_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_slugify():
    assert slugify("Chess: cleaning up my openings!") == "chess-cleaning-up-my-openings"
    assert slugify("邮箱 garden plan") == "garden-plan"
    assert slugify("!!") == "conversation"


def test_conversation_filename_collision():
    convs = [c for c in parse_file(FIXTURES / "generic_conversations.json")]
    assert len(convs) >= 2
    used: set[str] = set()
    names = [conversation_filename(c, used) for c in convs]
    assert len(set(names)) == len(names)
    assert all(n.endswith(".md") for n in names)


def test_write_conversations_end_to_end(tmp_path: Path):
    out = tmp_path / "archive"
    tag_settings = {"books": ["ebay", "textbook"]}
    written = write_conversations(FIXTURES, out, tag_settings)
    files = [path for _, path, _, _ in written]
    assert len(written) >= 6
    assert len({p.name for p in files}) == len(written)
    assert not any(p.name.startswith("index") for p in files)
    garden = next(p for p in files if "garden" in p.name)
    text = garden.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "# Planning a raised bed garden" in text
    assert "## user" in text and "## assistant" in text
    meta = read_front_matter(garden)
    assert meta["title"] == "Planning a raised bed garden"
    assert meta["model"] == "gpt-4o"
    assert meta["message_count"] == 2

    eBay = next(p for p in files if "ebay" in p.name)
    assert read_front_matter(eBay)["tags"] == ["books"]


def test_write_conversations_dry_run(tmp_path: Path):
    out = tmp_path / "archive"
    written = write_conversations(FIXTURES, out, dry_run=True)
    assert written == []
    assert not out.exists()


def test_summary_winds_up_in_front_matter(tmp_path: Path):
    out = tmp_path / "archive"
    # Mirror write_conversations' ordering exactly: sorted files, all convs.
    temp_used: set[str] = set()
    summaries = {}
    for source in sorted(p for p in FIXTURES.iterdir() if p.suffix in (".json", ".md")):
        for conv in parse_file(source):
            summaries[conversation_filename(conv, temp_used)] = "Tiny fake summary."
    written = write_conversations(FIXTURES, out, {}, summaries)
    for _, path, _, _ in written:
        assert read_front_matter(path)["summary"] == "Tiny fake summary."


def test_render_escapes_multiline_summary():
    from chat_archiver.parse import Conversation, Message

    conv = Conversation(
        title="Funny <bold> title",
        messages=[Message(role="user", content="Hello world with `code`.")],
    )
    body = render_conversation(conv, "x.md", ["tag1"], 'He said "really"\nno and then')
    assert "\n---\n" in body
    assert "<bold>" in body  # markdown kept as-is in conversation files
    # the summary survives a front-matter roundtrip, newlines included
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x.md"
        path.write_text(body, encoding="utf-8")
        assert read_front_matter(path)["summary"] == 'He said "really"\nno and then'


def test_build_index_html_and_md(tmp_path: Path):
    out = tmp_path / "archive"
    write_conversations(FIXTURES, out)
    md_path, html_path = build_index(out)
    md = md_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")
    assert "| Title | Date | Model | Tags |" in md
    assert (
        "[Planning a raised bed garden](2024-03-15-planning-a-raised-bed-garden.md)" in md
    )
    assert "Chat Archive Index" in html
    assert "const DATA = [" in html
    assert "llama3" in html
    assert "http://" not in html and "https://" not in html  # fully offline page


def test_build_index_reads_back_files(tmp_path: Path):
    out = tmp_path / "archive"
    write_conversations(FIXTURES, out)
    build_index(out)
    # rebuild from files only (simulating a re-index)
    _md2, html2 = build_index(out)
    html2_text = html2.read_text(encoding="utf-8")
    assert "Ollama model ideas" in html2_text


def test_index_html_escapes_close_script(tmp_path: Path):
    out = tmp_path / "archive"
    source = tmp_path / "evil.json"
    source.write_text(
        '[{"role": "user", "content": "x</script><script>alert(1)</script>"}]',
        encoding="utf-8",
    )
    write_conversations(source.parent, out)
    _, html_path = build_index(out)
    text = html_path.read_text(encoding="utf-8")
    assert "const DATA = [" in text
    assert "<\\/script>" in text  # closing tags inside JSON are escaped
    assert "alert(1)" in text  # data preserved, just inert


def test_markup_like_code_is_preserved(tmp_path: Path):
    source = tmp_path / "code.json"
    source.write_text(
        '[{"role": "user", "content": "```python\\nmatch x:\\n    case 1:\\n" },'
        '{"role": "assistant", "content": "Looks good."}]',
        encoding="utf-8",
    )
    written = write_conversations(source.parent, tmp_path / "archive")
    text = written[0][1].read_text(encoding="utf-8")
    assert "match x:" in text
