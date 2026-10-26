"""chat-archiver - turn exported AI chats into a tidy local Markdown archive.

Everything is local by default. The only network call this tool can ever
make is an optional summary request to an OpenAI-compatible endpoint that
*you* point it at (default: Ollama on localhost:11434/v1). No API keys
are ever sent, stored, or accepted. No uploads, no telemetry.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import __version__
from .archive import (
    read_front_matter,
    render_conversation,
    write_conversations,
)
from .index import build_index
from .parse import Conversation, FormatError, Message, _norm_ts, parse_file
from .summarize import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    SummaryError,
    summaries_for,
    summarize_conversation,
)
from .tags import TagsError, load_tags, match_tags, write_default_tags

SUPPORTED_SUFFIXES = (".json", ".md", ".markdown", ".txt")
INDEX_NAMES = ("index.md", "index.html")


def cmd_archive(args: argparse.Namespace) -> int:
    """Parse source exports, write per-conversation files, build indexes."""
    src = Path(args.src)
    out = Path(args.out)

    tag_settings: dict[str, list[str]] = {}
    if args.tags:
        try:
            tag_settings = load_tags(Path(args.tags))
        except TagsError as exc:
            print(f"tag error: {exc}", file=sys.stderr)
            return 2

    summaries: dict[str, str] = {}
    if args.summarize:
        try:
            convs = [conv for path in _source_files(src) for conv in parse_file(path)]
        except (FormatError, OSError) as exc:
            print(f"parse error: {exc}", file=sys.stderr)
            return 2
        results = summaries_for(convs, args.base_url, args.model)
        summaries = {k: v for k, v in results.items() if v}
        print(f"requested {len(convs)} summary/s from {args.base_url} (model: {args.model}); "
              f"got {len(summaries)}")

    try:
        written = write_conversations(src, out, tag_settings, summaries, dry_run=args.dry_run)
    except (FormatError, OSError) as exc:
        print(f"archive error: {exc}", file=sys.stderr)
        return 2
    print(f"archived {len(written)} conversation(s) into {out}")
    for conv, path, tags, summary in written:
        tag_note = f" [tags: {', '.join(tags)}]" if tags else ""
        sum_note = " [summarized]" if summary else ""
        print(f"  {path.name} - {conv.plain_title} ({len(conv.messages)} messages){tag_note}{sum_note}")
    if args.dry_run:
        return 0
    md_path, html_path = build_index(out, conversations=written)
    print(f"index: {md_path}")
    print(f"index: {html_path} (searchable offline; open in any browser)")
    return 0


def _source_files(src: Path):
    for path in sorted(src.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def cmd_rebuild_index(args: argparse.Namespace) -> int:
    """Rebuild index.md / index.html from an existing archive directory."""
    archive = Path(args.dir)
    if not archive.is_dir():
        print(f"not a directory: {archive}", file=sys.stderr)
        return 2
    md_path, html_path = build_index(archive)
    print(f"index rebuilt: {md_path}")
    print(f"index rebuilt: {html_path}")
    return 0


def conversation_from_archive_file(path: Path) -> Conversation:
    """Reconstruct a Conversation from one archived Markdown file.

    Restores title, model, source, format, creation time and per-message
    timestamps that ``archive`` rendered into the file, so re-rendering
    (re-tagging, summarizing) does not lose or duplicate anything.
    """
    meta = read_front_matter(path)
    text = path.read_text(encoding="utf-8")
    body_start = text.find("\n---", 3)
    body = text[body_start + 5:] if body_start >= 0 else text
    stamp_re = re.compile(r"^_(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC_$")
    messages: list[Message] = []
    role: str | None = None
    chunks: list[str] = []
    msg_ts: float | None = None
    header_seen = False
    first_ts: float | None = None

    def flush_msg() -> None:
        nonlocal role, chunks, msg_ts
        if role is None:
            return
        messages.append(Message(role=role, content="\n".join(chunks).strip(), timestamp=msg_ts))
        role, chunks, msg_ts = None, [], None

    for line in body.splitlines():
        header = line.strip()
        stamp = stamp_re.match(header)
        if header.startswith("## ") and header[3:].strip() in ("user", "assistant", "system", "tool"):
            header_seen = True
            flush_msg()
            role = header[3:].strip()
        elif stamp:
            ts = _norm_ts(stamp.group(1))
            first_ts = first_ts or ts
            if role is not None:
                msg_ts = ts if msg_ts is None else msg_ts
        elif role is not None:
            chunks.append(line)
    flush_msg()
    if not messages or not header_seen:
        messages = [Message(role="user", content=body.strip())]
    conv = Conversation(
        title=str(meta.get("title") or path.stem),
        messages=messages,
        model=str(meta.get("model") or "") or None,
        source=str(meta.get("source") or path.name),
        fmt=str(meta.get("format") or "archive"),
    )
    created = _norm_ts(str(meta.get("created") or ""))
    conv.created = created or first_ts
    return conv


def cmd_tag_existing(args: argparse.Namespace) -> int:
    """Re-apply tags from tags.toml to files already in the archive."""
    archive = Path(args.dir)
    if not archive.is_dir():
        print(f"not a directory: {archive}", file=sys.stderr)
        return 2
    try:
        tag_settings = load_tags(Path(args.tags))
    except TagsError as exc:
        print(f"tag error: {exc}", file=sys.stderr)
        return 2
    rebuilt = 0
    for path in sorted(archive.glob("*.md")):
        if path.name in INDEX_NAMES:
            continue
        conv = conversation_from_archive_file(path)
        tags = match_tags(conv, tag_settings)
        summary = str(read_front_matter(path).get("summary") or "") or None
        path.write_text(render_conversation(conv, path.name, tags, summary), encoding="utf-8")
        tag_note = f" [tags: {', '.join(tags)}]" if tags else ""
        print(f"  {path.name}{tag_note}")
        rebuilt += 1
    print(f"re-tagged {rebuilt} file(s)")
    md_path, html_path = build_index(archive)
    print(f"index updated: {md_path}")
    print(f"index updated: {html_path}")
    return 0


def cmd_summarize_archive(args: argparse.Namespace) -> int:
    """Add summaries to conversations already in an archive directory."""
    archive = Path(args.dir)
    if not archive.is_dir():
        print(f"not a directory: {archive}", file=sys.stderr)
        return 2
    count = 0
    for path in sorted(archive.glob("*.md")):
        if path.name in INDEX_NAMES:
            continue
        conv = conversation_from_archive_file(path)
        try:
            summary = summarize_conversation(conv, args.base_url, args.model)
        except SummaryError as exc:
            print(f"skipped {path.name}: {exc}", file=sys.stderr)
            continue
        tags = list(read_front_matter(path).get("tags") or [])
        path.write_text(render_conversation(conv, path.name, tags, summary), encoding="utf-8")
        print(f"  summarized {path.name}")
        count += 1
    print(f"summarized {count} file(s) via {args.base_url} (model: {args.model})")
    if count:
        md_path, html_path = build_index(archive)
        print(f"index updated: {md_path}")
        print(f"index updated: {html_path}")
    return 0


def cmd_init_tags(args: argparse.Namespace) -> int:
    """Write a starter tags.toml for the user to hand-edit."""
    path = write_default_tags(Path(args.path))
    print(f"wrote starter tags file: {path}")
    print("Open it and edit the tags to match your own topics; "
          "chat-archiver matches keywords case-insensitively, all offline.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chat-archiver",
        description="Turn exported AI chats into a tidy, searchable local Markdown archive.",
        epilog=f"Summary endpoint defaults to Ollama ({DEFAULT_BASE_URL}); any OpenAI-compatible "
               "base_url works. No API keys are ever sent or stored.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("archive", help="parse exported chats and write the archive")
    p.add_argument("src", help="folder with exported conversation files (.json/.md/.txt)")
    p.add_argument("-o", "--out", default="archive", help="output directory (default: ./archive)")
    p.add_argument("-t", "--tags", metavar="FILE", help="your tags.toml for topic tagging")
    p.add_argument("-n", "--dry-run", action="store_true",
                   help="list what would be written without writing anything")
    p.add_argument("-s", "--summarize", action="store_true",
                   help="request short summaries from an OpenAI-compatible endpoint "
                        "(data goes only to the endpoint you configure)")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, metavar="URL",
                   help=f"summary endpoint base_url (default: {DEFAULT_BASE_URL})")
    p.add_argument("--model", default=DEFAULT_MODEL, metavar="NAME",
                   help=f"model name on the summary endpoint (default: {DEFAULT_MODEL})")
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("index", help="rebuild index.md and index.html for an existing archive")
    p.add_argument("dir", nargs="?", default="archive", help="archive directory (default: ./archive)")
    p.set_defaults(func=cmd_rebuild_index)

    p = sub.add_parser("tag", help="re-apply tags from a tags.toml to an existing archive")
    p.add_argument("dir", nargs="?", default="archive", help="archive directory (default: ./archive)")
    p.add_argument("-t", "--tags", default="tags.toml", help="tags file (default: ./tags.toml)")
    p.set_defaults(func=cmd_tag_existing)

    p = sub.add_parser("summarize", help="add summaries to an existing archive (requires an endpoint)")
    p.add_argument("dir", nargs="?", default="archive", help="archive directory (default: ./archive)")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, metavar="URL",
                   help=f"summary endpoint base_url (default: {DEFAULT_BASE_URL})")
    p.add_argument("--model", default=DEFAULT_MODEL, metavar="NAME",
                   help=f"model name (default: {DEFAULT_MODEL})")
    p.set_defaults(func=cmd_summarize_archive)

    p = sub.add_parser("init-tags", help="create a starter tags.toml you can edit")
    p.add_argument("--path", default="tags.toml", help="where to write it (default: ./tags.toml)")
    p.set_defaults(func=cmd_init_tags)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
