"""Parsers that turn exported chat files into normalized Conversation objects.

Supported input formats (auto-detected):

* OpenAI ChatGPT ``conversations.json`` (mapping tree export)
* Open WebUI / Ollama-style single-chat JSON (``chat.history.messages``)
* Generic JSON exports:
    - a list of ``{"role": ..., "content": ...}`` messages
    - ``{"title": ..., "messages": [...]}``
    - ``{"conversations": [...]}`` / ``{"data": [...]}`` wrappers
* Plain Markdown exports using role headings or bold role labels
  (``## user``, ``**Assistant:**``, ``You:`` ...)

Nothing here talks to the network; parsed conversations stay local.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROLE_ALIASES = {
    "user": "user",
    "me": "user",
    "you": "user",
    "human": "user",
    "prompt": "user",
    "assistant": "assistant",
    "ai": "assistant",
    "gpt": "assistant",
    "bot": "assistant",
    "chatgpt": "assistant",
    "claude": "assistant",
    "system": "system",
    "tool": "tool",
    "function": "tool",
}
"""Words that may show up as role names in various exports."""

MESSAGE_KEYS = ("role", "sender", "author")
CONTENT_KEYS = ("content", "text", "message", "value")
TIMESTAMP_KEYS = ("timestamp", "create_time", "created_at", "createdAt", "time", "date")
MODEL_KEYS = ("model", "modelId", "model_id", "modelName", "model_name")


class FormatError(ValueError):
    """Raised when an input file is not a recognized export format."""


@dataclass
class Message:
    """One chat turn, normalized to plain Markdown text."""

    role: str
    content: str
    timestamp: float | None = None
    model: str | None = None

    def to_markdown(self) -> str:
        """Render this turn for archive bodies."""
        lines = [f"## {self.role}"]
        if self.timestamp:
            lines.append(f"_{_fmt_ts(self.timestamp)}_")
            lines.append("")
        body = self.content.strip() or "(empty message)"
        lines.append(body)
        return "\n".join(lines)


@dataclass
class Conversation:
    """A whole conversation plus its metadata."""

    title: str
    messages: list[Message] = field(default_factory=list)
    created: float | None = None
    model: str | None = None
    source: str = ""
    fmt: str = "unknown"

    @property
    def created_dt(self) -> dt.datetime | None:
        """Creation time as an aware UTC datetime, if known."""
        if self.created is None:
            return None
        return dt.datetime.fromtimestamp(self.created, tz=dt.UTC)

    @property
    def date_str(self) -> str:
        """``YYYY-MM-DD`` creation date or the empty string."""
        d = self.created_dt
        return d.strftime("%Y-%m-%d") if d else ""

    @property
    def created_str(self) -> str:
        """Human-readable creation time, ``"unknown"`` when missing."""
        d = self.created_dt
        return d.strftime("%Y-%m-%d %H:%M:%S UTC") if d else "unknown"

    @property
    def user_content(self) -> str:
        """Plain text of the first user message (index snippets)."""
        for m in self.messages:
            if m.role == "user" and m.content.strip():
                return m.content.strip()
        return ""

    @property
    def plain_title(self) -> str:
        """Title without surrounding whitespace."""
        t = self.title.strip()
        return re.sub(r"\s+", " ", t) if t else "Untitled conversation"


def parse_file(path: Path) -> list[Conversation]:
    """Parse one exported file and return its conversations.

    Raises FormatError for missing, invalid, or unrecognized files.
    """
    if not path.exists():
        raise FormatError(f"source file not found: {path}")
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip("\ufeff \t\r\n")
    if stripped.startswith(("{", "[")):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FormatError(f"{path.name}: invalid JSON ({exc})") from exc
        return parse_json(data, path)
    return parse_markdown(text, path)


def parse_json(data: object, path: Path) -> list[Conversation]:
    """Dispatch on the recognized JSON shape."""
    wrapper = None
    if isinstance(data, dict):
        for key in ("conversations", "data", "items", "chats"):
            if isinstance(data.get(key), list):
                wrapper = data[key]
                break
        if wrapper is not None:
            convs: list[Conversation] = []
            for i, item in enumerate(wrapper):
                convs.extend(parse_json(item, path))
            return convs
        if isinstance(data.get("mapping"), dict):
            return [parse_chatgpt(data, path)]
        if isinstance(data.get("chat"), dict):
            return [parse_openwebui(data, path)]
        if isinstance(data.get("messages"), list):
            return [parse_generic_conversation(data, path)]
        raise FormatError(f"{path.name}: unrecognized JSON export shape")
    if isinstance(data, list):
        if not data:
            return []
        if all(isinstance(x, dict) and _lookup(x, MESSAGE_KEYS) for x in data):
            return [parse_generic_conversation({"messages": data}, path)]
        if any(isinstance(x, dict) for x in data):
            convs = []
            for i, item in enumerate(data):
                if isinstance(item, dict):
                    convs.extend(parse_json(item, path))
            if not convs:
                raise FormatError(f"{path.name}: no recognizable conversations")
            return convs
        raise FormatError(f"{path.name}: unrecognized JSON export shape")
    raise FormatError(f"{path.name}: expected a JSON object or list")


def parse_generic_conversation(data: dict, path: Path) -> Conversation:
    """Parse one ``{"title": ..., "messages": [...]}``-shaped object."""
    messages: list[Message] = []
    for raw in data.get("messages", []):
        if not isinstance(raw, dict):
            continue
        role_raw = _lookup(raw, MESSAGE_KEYS)
        content = _lookup_content(raw)
        role = _norm_role(role_raw) if role_raw else "user"
        if not content and not role:
            continue
        messages.append(
            Message(
                role=role,
                content=content,
                timestamp=_norm_ts(_lookup(raw, TIMESTAMP_KEYS)),
                model=_lookup(raw, MODEL_KEYS),
            )
        )
    conv = Conversation(
        title=_lookup(data, ("title", "name")) or "",
        messages=messages,
        model=_lookup(data, MODEL_KEYS),
        source=path.name,
        fmt="json-generic",
    )
    conv.created = _norm_ts(_lookup(data, TIMESTAMP_KEYS))
    if conv.created is None:
        conv.created = next(
            (m.timestamp for m in messages if m.timestamp is not None), None
        )
    _derive_title(conv, data)
    return conv


def parse_chatgpt(data: dict, path: Path) -> Conversation:
    """Parse a ChatGPT export node: ``mapping`` + metadata."""
    root = _chatgpt_root(data["mapping"])
    messages: list[Message] = []
    current = root
    while True:
        value = data["mapping"][current]
        msg = value.get("message") or {}
        role_raw = (msg.get("author") or {}).get("role")
        content = _chatgpt_content(msg.get("content") or {})
        if role_raw and content:
            model = msg.get("metadata", {}).get("model_slug") or None
            if _norm_role(role_raw) in ("user", "assistant", "tool", "system"):
                messages.append(
                    Message(
                        role=_norm_role(role_raw),
                        content=content,
                        timestamp=_norm_ts(msg.get("create_time")),
                        model=model if _norm_role(role_raw) == "assistant" else None,
                    )
                )
        children = value.get("children") or []
        if not children:
            break
        current = children[0]
    conv = Conversation(
        title=data.get("title") or "",
        messages=messages,
        source=path.name,
        fmt="openai-chatgpt",
    )
    if isinstance(data.get("create_time"), (int, float)):
        conv.created = float(data["create_time"])
    elif messages and messages[0].timestamp:
        conv.created = messages[0].timestamp
    conv.model = next(
        (m.model for m in reversed(messages) if m.role == "assistant" and m.model),
        None,
    )
    _derive_title(conv, data)
    return conv


def _chatgpt_content(content: dict) -> str:
    """Flatten a ChatGPT ``content`` object to plain Markdown text."""
    parts = content.get("parts")
    if isinstance(parts, list):
        texts = []
        for part in parts:
            if isinstance(part, str):
                texts.append(part)
            elif isinstance(part, dict):
                inner = _chatgpt_content(part)
                if inner:
                    texts.append(inner)
        if texts:
            return "\n".join(t for t in texts if t).strip()
    text = content.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return ""


def _chatgpt_root(mapping: dict) -> str:
    """Find the id of the root node in a ChatGPT mapping tree."""
    for node_id, node in mapping.items():
        if node.get("parent") is None:
            return node_id
    first = next(iter(mapping))
    return first


def parse_openwebui(data: dict, path: Path) -> Conversation:
    """Parse Open WebUI / Ollama-style ``{"chat": {"history": {...}}}`` files."""
    chat = data.get("chat") or {}
    history = chat.get("history") or {}
    raw_msgs = history.get("messages") or chat.get("messages") or []
    messages: list[Message] = []
    for raw in raw_msgs:
        if not isinstance(raw, dict):
            continue
        role = _norm_role(_lookup(raw, MESSAGE_KEYS) or "")
        content = _lookup_content(raw)
        if not content:
            continue
        messages.append(
            Message(
                role=role,
                content=content,
                timestamp=_norm_ts(_lookup(raw, TIMESTAMP_KEYS)),
                model=raw.get("model") if role == "assistant" else None,
            )
        )
    conv = Conversation(
        title=_lookup(data, ("title", "name")) or _lookup(chat, ("title", "name")) or "",
        messages=messages,
        source=path.name,
        fmt="openwebui-json",
    )
    conv.created = _norm_ts(_lookup(data, TIMESTAMP_KEYS) or _lookup(chat, TIMESTAMP_KEYS))
    model = next(
        (m.model for m in messages if m.role == "assistant" and m.model), None
    )
    if not model:
        models = chat.get("models")
        if isinstance(models, list) and models:
            model = models[0]
    conv.model = model or None
    _derive_title(conv, data)
    return conv


def parse_markdown(text: str, path: Path) -> list[Conversation]:
    """Parse a Markdown export using role headings or bold labels."""
    conv = Conversation(title="", source=path.name, fmt="markdown")
    messages: list[Message] = []
    current_role: str | None = None
    current_lines: list[str] = []
    found_roles = False
    in_fence = False

    def flush() -> None:
        nonlocal current_role
        if current_role is None:
            return
        content = "\n".join(current_lines).strip()
        if content or messages:
            messages.append(Message(role=current_role, content=content))
        current_role = None
        current_lines.clear()

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            if current_role is not None:
                current_lines.append(line)
            continue
        if in_fence:
            if current_role is not None:
                current_lines.append(line)
            continue
        match = _role_line(line)
        if match:
            flush()
            found_roles = True
            current_role, inline = match
            if inline:
                current_lines.append(inline)
            continue
        if current_role is None:
            head = _heading_text(line)
            if head and not conv.title:
                conv.title = head
            continue
        current_lines.append(line)
    flush()
    if not found_roles and text.strip():
        conv = Conversation(
            title="", source=path.name, fmt="markdown",
            messages=[Message(role="user", content=text.strip())],
        )
    else:
        conv.messages = messages
    _derive_title(conv, text)
    return [conv]


def _role_line(line: str) -> tuple[str, str] | None:
    """Return (role, inline-content) when *line* opens a message, else None.

    Recognized openers: ``## user``, ``**Assistant:** ...``, ``You: ...``.
    Bold/italic markers are stripped before matching so exports from
    different tools still line up.
    """
    stripped = line.strip()
    if not stripped or re.match(r"^(\||```|~~~|>)", stripped):
        return None
    head, sep, rest = stripped.partition(":")
    if sep:
        label = head.strip().lstrip("#").strip().strip("*_").strip()
        if label and len(label.split()) <= 2 and label.lower() in ROLE_ALIASES:
            return ROLE_ALIASES[label.lower()], rest.lstrip("*_ ").strip()
    heading = _heading_text(stripped)
    if heading:
        label = heading.strip().strip("*_").strip().rstrip(":").strip()
        if label and len(label.split()) <= 2 and label.lower() in ROLE_ALIASES:
            return ROLE_ALIASES[label.lower()], ""
    return None


def _heading_text(line: str, numbered: bool = True) -> str | None:
    """Return heading text of *line* when it is a heading, else None."""
    match = re.match(r"^\s*#{1,6}\s+(?P<text>.+?)(?:\s*#+\s*)?$", line)
    if not match:
        return None
    return match.group("text").strip()


def _derive_title(conv: Conversation, data: object) -> None:
    """Fill conv.title from first user message or source when missing."""
    if not conv.title:
        first_user = ""
        for m in conv.messages:
            if m.role == "user":
                first_user = _first_line(m.content)
                break
        conv.title = first_user or ""
    if not conv.title and conv.source:
        conv.title = conv.source.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
    if not conv.title:
        conv.title = "Untitled conversation"


def _first_line(text: str, width: int = 80) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#*_>-").strip()
        if line:
            return line[:width]
    return ""


def _lookup(data: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _lookup_content(raw: dict) -> str:
    """Read message text from whatever key the export uses."""
    for key in CONTENT_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _chatgpt_content(value)
            if nested:
                return nested
        if isinstance(value, list):
            texts = [p for p in value if isinstance(p, str) and p.strip()]
            if texts:
                return "\n".join(texts).strip()
    return ""


def _norm_role(role_raw: object) -> str:
    if not isinstance(role_raw, str):
        return "user"
    return ROLE_ALIASES.get(role_raw.strip().lower(), role_raw.strip().lower() or "user")


def _norm_ts(value: object) -> float | None:
    """Normalize a timestamp allegedly in seconds or milliseconds."""
    seconds = None
    if isinstance(value, (int, float)) and value > 0:
        seconds = float(value)
    elif isinstance(value, str):
        seconds = _parse_date_str(value)
    if seconds is None:
        return None
    if seconds > 1e12:
        seconds /= 1000.0
    if seconds > 1e11:
        seconds /= 1000.0
    return seconds


def _parse_date_str(value: str) -> float | None:
    value = value.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            parsed = dt.datetime.strptime(value[:26], fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.UTC)
            return parsed.timestamp()
        except ValueError:
            continue
    return None


def _fmt_ts(seconds: float) -> str:
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
