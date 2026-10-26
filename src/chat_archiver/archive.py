"""Writing normalized conversations to per-conversation Markdown files."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .parse import Conversation, FormatError, parse_file
from .tags import apply_tags

UNSAFE_TITLE_CHARS = re.compile(r"[^A-Za-z0-9]+")


def slugify(title: str) -> str:
    """Turn a conversation title into a short, filesystem-safe slug."""
    text = unicodedata.normalize("NFKD", title)
    text = text.encode("ascii", "ignore").decode("ascii") or "conversation"
    words = [w for w in UNSAFE_TITLE_CHARS.split(text.lower()) if w][:8]
    return "-".join(words) or "conversation"


def conversation_filename(conv: Conversation, used: set[str]) -> str:
    """Generate a unique archive filename for *conv* (date + slug)."""
    slug = slugify(conv.plain_title)
    date_part = conv.date_str or "no-date"
    base = f"{date_part}-{slug}"
    candidate = f"{base}.md"
    n = 2
    while candidate in used:
        candidate = f"{base}-{n}.md"
        n += 1
    used.add(candidate)
    return candidate


def _yaml_str(value: str | None) -> str:
    """Serialize one scalar as a double-quoted YAML-compatible string."""
    if value is None:
        return '""'
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _yaml_list(values: list[str]) -> str:
    return "[" + ", ".join(_yaml_str(v) for v in values) + "]"


def front_matter(conv: Conversation, path_str: str, tags: list[str], summary: str | None) -> str:
    """Render the YAML front matter block for one archive file."""
    lines = [
        "---",
        f"title: {_yaml_str(conv.plain_title)}",
        f"created: {_yaml_str(conv.created_str)}",
        f"model: {_yaml_str(conv.model or 'unknown')}",
        f"source: {_yaml_str(conv.source)}",
        f"format: {_yaml_str(conv.fmt)}",
        f"message_count: {len(conv.messages)}",
        f"tags: {_yaml_list(tags)}",
    ]
    if summary:
        lines.append(f"summary: {_yaml_str(summary)}")
    lines.append(f"archive_path: {_yaml_str(path_str)}")
    lines.append("---")
    return "\n".join(lines)


def render_conversation(
    conv: Conversation, path_str: str, tags: list[str] | None = None, summary: str | None = None
) -> str:
    """Render one archive-ready Markdown document for *conv*."""
    tags = tags or []
    parts = [front_matter(conv, path_str, tags, summary), "", f"# {conv.plain_title}", ""]
    meta_bits = [conv.created_str, f"model: {conv.model or 'unknown'}", f"source: {conv.source}"]
    parts.append("*" + " | ".join(meta_bits) + "*")
    parts.append("")
    if tags:
        parts.append("*tags: " + ", ".join(tags) + "*")
        parts.append("")
    if summary:
        parts.append("> " + summary.replace("\n", " ").strip())
        parts.append("")
    for msg in conv.messages:
        parts.append(msg.to_markdown())
        parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"


def read_front_matter(path: Path) -> dict:
    """Read simple YAML front matter (flat keys / string lists) from a file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    block = text[3:end]
    meta: dict = {}
    for line in block.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        value: object
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            value = [v.strip().strip('"') for v in inner.split(",") if v.strip()] if inner else []
        elif raw.isdigit() if raw else False:
            value = int(raw)
        elif raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            value = (
                raw[1:-1]
                .replace("\\\\", "\x00")
                .replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace("\\t", "\t")
                .replace("\x00", "\\")
            )
        else:
            value = raw
        meta[key] = value
    return meta


def write_conversations(
    src: Path,
    out: Path,
    tag_settings: dict[str, list[str]] | None = None,
    summaries: dict[str, str] | None = None,
    dry_run: bool = False,
) -> list[tuple[Conversation, Path, list[str], str | None]]:
    """Parse every supported export in *src*, then write Markdown files to *out*.

    Returns (conversation, written path, applied tags, summary) rows in
    file order. With ``dry_run=True`` nothing is written and nothing is
    created on disk.
    """
    if not src.exists():
        raise FormatError(f"source path not found: {src}")
    files = sorted(
        p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in (".json", ".md", ".markdown", ".txt")
    )
    if not files:
        raise FormatError(f"no supported export files (.json, .md, .txt) found under {src}")
    if dry_run:
        return []
    out.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    written: list[tuple[Conversation, Path, list[str], str | None]] = []
    for path in files:
        for conv in parse_file(path):
            tags = apply_tags(conv, tag_settings or {})
            rel = conversation_filename(conv, used)
            summary = (summaries or {}).get(rel)
            (out / rel).write_text(render_conversation(conv, rel, tags, summary), encoding="utf-8")
            written.append((conv, out / rel, tags, summary))
    return written
