"""Topic tagging driven by a small TOML notes file you write yourself.

``tags.toml`` looks like this::

    # Your topic notes. Keywords are matched case-insensitively
    # against every conversation's title and message text.
    [tags]
    gardening = ["garden", "plant", "seed"]
    budgeting = ["budget", "expenses", "invoice"]

Nothing leaves your machine: matching is a plain local keyword search.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None  # type: ignore[assignment]

DEFAULT_TAGS_TOML = '''\
# tags.toml - your local topic notes, edited by hand.
# Every tag is a list of keywords; a conversation gets the tag when
# any keyword shows up in its title or message text. Matching is
# case-insensitive and stays entirely on your machine.
#
# Tips:
#   - keep keywords lowercase (matching is case-insensitive anyway)
#   - one tag per topic, e.g. gardening, bookkeeping, ffxiv, chess
#   - delete tags you don't use; add as many as you like

[tags]
gardening = ["garden", "plant", "soil", "seed"]
budgeting = ["budget", "expense", "invoice", "bookkeeping"]
local_ai = ["ollama", "local model", "llama", "gguf"]
publishing = ["kdp", "kindle", "paperback", "draft2digital"]
'''


class TagsError(ValueError):
    """Raised when tags.toml is missing, malformed or empty."""


def load_tags(path: Path) -> dict[str, list[str]]:
    """Load a tags TOML file into ``{tag: [keywords]}``.

    Creates a starter ``tags.toml`` if *path* does not exist yet, so the
    first run is never a dead end.
    """
    if not path.exists():
        path.write_text(DEFAULT_TAGS_TOML, encoding="utf-8")  # starter file
    if tomllib is None:  # pragma: no cover
        raise TagsError("Python 3.11+ is required to read tags.toml")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # tomllib.TOMLDecodeError plus encoding errors
        raise TagsError(f"{path.name}: unreadable tags file ({exc})") from exc
    tags = data.get("tags", {})
    if not isinstance(tags, dict):
        raise TagsError(f"{path.name}: expected a [tags] table")
    clean: dict[str, list[str]] = {}
    for name, keywords in tags.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(keywords, list):
            continue
        kws = [str(k).lower() for k in keywords if str(k).strip()]
        if kws:
            clean[name.strip()] = kws
    return clean


def write_default_tags(path: Path) -> Path:
    """Write the starter tags.toml (used by ``init_tags``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_TAGS_TOML, encoding="utf-8")
    return path


def match_tags(conv, tag_settings: dict[str, list[str]]) -> list[str]:
    """Return the tags whose keywords appear in *conv*'s text."""
    haystack = (conv.plain_title + "\n" + "\n".join(m.content for m in conv.messages)).lower()
    applied = []
    for tag, keywords in (tag_settings or {}).items():
        for keyword in keywords:
            if re.search(re.escape(keyword), haystack):
                applied.append(tag)
                break
    return applied


def apply_tags(conv, tag_settings: dict[str, list[str]]) -> list[str]:
    """Convenience alias for match_tags."""
    return match_tags(conv, tag_settings)
