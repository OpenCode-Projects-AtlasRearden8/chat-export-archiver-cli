"""Building a searchable local index page for the archive.

The HTML index is a single self-contained file: no CDN, no fonts, no
network requests of any kind. It embeds the conversation list as JSON
and filters it with a tiny vanilla-JS text search. Safe to open with
``file://`` or host with ``python -m http.server``, entirely offline.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path

from .archive import read_front_matter

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chat Archive Index</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; max-width: 56rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
  h1 { margin-bottom: 0.25rem; }
  .meta { color: #888; font-size: 0.9rem; margin-bottom: 1.5rem; }
  #q { width: 100%; padding: 0.6rem 0.8rem; font-size: 1rem; border: 1px solid #999; border-radius: 0.5rem; }
  #count { font-size: 0.9rem; color: #888; margin: 0.75rem 0; }
  ul { list-style: none; padding: 0; }
  li { padding: 0.75rem 0; border-bottom: 1px solid rgba(128,128,128,0.25); }
  .title { font-weight: 600; }
  .title a { text-decoration: none; }
  .sub { color: #888; font-size: 0.85rem; }
  .summary { font-size: 0.9rem; margin-top: 0.25rem; }
  .snippet { font-size: 0.85rem; margin-top: 0.25rem; opacity: 0.85; }
  mark { background: gold; color: black; }
  .hidden { display: none; }
</style>
</head>
<body>
<h1>Chat Archive Index</h1>
<p class="meta">Generated @@GENERATED@@ by chat-archiver &middot; @@TOTAL@@ conversations &middot; everything here stays on your machine</p>
<input id="q" type="search" placeholder="Type to search titles, tags, summaries, text..." autofocus aria-label="Search conversations">
<p id="count" role="status"></p>
<ul id="list">
@@ITEMS@@
</ul>
<noscript><p>JavaScript is off, so live search is unavailable - the full list above still works.</p></noscript>
<script>
"use strict";
const DATA = @@ENTRIES@@;
const q = document.getElementById("q");
const list = document.getElementById("list");
const count = document.getElementById("count");
function norm(s) { return (s || "").toLowerCase(); }
function mark(text, needle) {
  if (!needle) return text;
  const low = norm(text);
  let out = "";
  let i = 0;
  while (i < text.length) {
    const idx = low.indexOf(needle, i);
    if (idx < 0) { out += text.slice(i); break; }
    out += text.slice(i, idx) + "<mark>" + text.slice(idx, idx + needle.length) + "</mark>";
    i = idx + needle.length;
  }
  return out;
}
function render() {
  const needle = norm(q.value.trim());
  let shown = 0;
  DATA.forEach((d, i) => {
    const li = list.children[i];
    li.querySelectorAll("mark").forEach(m => m.replaceWith(m.textContent));
    if (!needle) {
      li.classList.remove("hidden");
      shown++;
      return;
    }
    const hay = [d.title, d.tags.join(" "), d.summary, d.text].join("  ").toLowerCase();
    const hit = hay.includes(needle);
    li.classList.toggle("hidden", !hit);
    if (hit) {
      shown++;
      const t = li.querySelector(".title");
      if (t) t.innerHTML = mark(d.title, needle);
      const sm = li.querySelector(".snippet");
      if (sm) sm.innerHTML = d.text.toLowerCase().includes(needle) ? mark(d.text, needle) : d.text;
      const tg = li.querySelector(".tags");
      if (tg) tg.innerHTML = d.tags.map(x => mark(x, needle)).join(", ") || tg.innerHTML;
    }
  });
  count.textContent = needle ? shown + " of " + DATA.length + " conversations match" : DATA.length + " conversations";
}
q.addEventListener("input", render);
count.textContent = DATA.length + " conversations";
</script>
</body>
</html>
"""


def _snippet_text(text: str, limit: int = 240) -> str:
    """Flatten a message body into a small plain-text snippet."""
    cleaned = text.replace("```", " ").replace("\n", " ")
    return cleaned[:limit].strip()


def collect_entries(archive_dir: Path) -> list[dict]:
    """Read every archive Markdown file's front matter into index entries."""
    entries = []
    for path in sorted(archive_dir.glob("*.md")):
        if path.name in ("index.md", "index.html"):
            continue
        meta = read_front_matter(path)
        text = path.read_text(encoding="utf-8")
        body_start = text.find("\n---", 3)
        body = text[body_start + 4:] if body_start >= 0 else text
        entry = {
            "title": str(meta.get("title") or path.stem),
            "date": str(meta.get("created") or ""),
            "model": str(meta.get("model") or "unknown"),
            "tags": list(meta.get("tags") or []),
            "summary": str(meta.get("summary") or ""),
            "source": str(meta.get("source") or ""),
            "file": path.name,
            "text": _snippet_text(body.strip().removeprefix("#")),
        }
        entries.append(entry)
    return entries


def _render_items(entries: list[dict]) -> str:
    """Server-render the list items so the page works without JS too."""
    items = []
    for entry in entries:
        tags = ", ".join(entry["tags"])
        summary = f'<div class="summary">{html.escape(entry["summary"])}</div>' if entry["summary"] else ""
        items.append(
            "<li>"
            f'<div class="title"><a href="{html.escape(entry["file"])}">{html.escape(entry["title"])}</a></div>'
            f'<div class="tags sub">{html.escape(tags)}</div>'
            f'<div class="sub">{html.escape(entry["date"])} &middot; model: {html.escape(entry["model"])} &middot; source: {html.escape(entry["source"])}</div>'
            f"{summary}"
            f'<div class="snippet">{html.escape(entry["text"])}</div>'
            "</li>"
        )
    return "\n".join(items)


def build_index(archive_dir: Path, conversations: list | None = None) -> tuple[Path, Path]:
    """Write ``index.md`` and ``index.html`` for *archive_dir*.

    When *conversations* is provided (fresh archiving run), entries are built
    from them in memory; otherwise front matter of existing files is read.
    """
    if conversations:
        entries = [
            {
                "title": conv.plain_title,
                "date": conv.created_str,
                "model": conv.model or "unknown",
                "tags": tags,
                "summary": summary or "",
                "source": conv.source,
                "file": path.name,
                "text": _snippet_text(conv.user_content),
            }
            for conv, path, tags, summary in conversations
        ]
    else:
        entries = collect_entries(archive_dir)

    archive_dir.mkdir(parents=True, exist_ok=True)
    generated = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")

    md_lines = [
        "# Chat Archive Index",
        "",
        f"Generated {generated} by chat-archiver - {len(entries)} conversations, all local.",
        "",
        "| Title | Date | Model | Tags | File |",
        "|-------|------|-------|------|------|",
    ]
    for entry in entries:
        title = entry["title"].replace("|", "\\|")
        md_lines.append(
            f"| [{title}]({entry['file']}) | {entry['date']} | {entry['model']} "
            f"| {', '.join(entry['tags'])} | source: {entry['source']} |"
        )
    md_lines.append("")
    (archive_dir / "index.md").write_text("\n".join(md_lines), encoding="utf-8")

    payload = json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")
    page = (
        TEMPLATE.replace("@@ENTRIES@@", payload)
        .replace("@@ITEMS@@", _render_items(entries))
        .replace("@@GENERATED@@", generated)
        .replace("@@TOTAL@@", str(len(entries)))
    )
    (archive_dir / "index.html").write_text(page, encoding="utf-8")
    return archive_dir / "index.md", archive_dir / "index.html"
