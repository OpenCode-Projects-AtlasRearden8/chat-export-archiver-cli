# STATUS.md - chat-archiver

## What was built

**chat-archiver** - a local-first Python CLI that turns exported AI chat
conversations (JSON or Markdown from chat tools and local-model UIs) into a
tidy, searchable local archive. Built by Asdale Dynamics, LLC for the
beginner-friendly AI tools line (Python 3.11+, zero third-party runtime
dependencies).

Features:

- **Format detection & parsing** for: OpenAI ChatGPT `conversations.json`
  (mapping-tree), Open WebUI / Ollama-style single-chat JSON, generic
  `[{"role", "content"}]` exports, wrapper formats like
  `{"conversations": [...]}`, and Markdown exports using role headings or
  bold labels (`## user`, `**Assistant:**`, `You:`).
- **Normalization to plain Markdown**: one file per conversation, named
  `YYYY-MM-DD-title-slug.md` (collisions numbered, no date -> `no-date-`),
  with YAML front matter (title, created, model, source, format,
  message_count, tags, optional summary) and `## user` / `## assistant`
  bodies with UTC timestamp lines. Timestamps normalize from seconds,
  milliseconds, and ISO strings; missing dates never block archiving.
- **Searchable index page**: self-contained `index.html` (vanilla JS, no
  CDN, no network) plus a plain `index.md` table. Client-side search
  filters/titles/tags/snippets/summaries with highlighting; the page works
  with JavaScript disabled too. All content is HTML-escaped and closing
  tags in JSON payloads are escaped to prevent injection.
- **Topic tags you write**: `tags.toml` (TOML, hand-edited; a starter file
  is auto-created on first use or via `init-tags`). Keywords match
  case-insensitively against titles and text; `archive -t` and
  `chat-archiver tag` re-apply tags in place and refresh the index.
- **Optional summary indexing**: opt-in (`-s` on `archive`, or `summarize`
  subcommand) via any OpenAI-compatible endpoint. Default is Ollama
  (`http://localhost:11434/v1`, model `llama3`); `--base-url`/`--model` are
  configurable. **No API key is ever sent, stored, or accepted** - the
  request deliberately omits `Authorization`. Unreachable endpoints degrade
  gracefully (files summarize as "skipped", archive still succeeds).
- **Commands**: `archive`, `index` (rebuild), `tag` (re-apply), `summarize`,
  `init-tags`, plus `--version`/`--help` and `--dry-run`.

## How to run it

```bash
pip install -e .           # then use the chat-archiver command
# or without installing: PYTHONPATH=src python3 -m chat_archiver.cli ...
```

Typical flow:

```bash
chat-archiver init-tags                       # starter tags.toml
chat-archiver archive my-exports -o archive -t tags.toml
chat-archiver archive my-exports -n           # dry run (writes nothing)
chat-archiver archive my-exports -o archive -s  # + summaries via Ollama
chat-archiver archive my-exports -o archive -s --base-url http://127.0.0.1:9001/v1 --model mymodel
chat-archiver tag archive -t tags.toml        # re-apply edited tags
chat-archiver index archive                   # rebuild index pages
chat-archiver summarize archive               # add summaries later
open archive/index.html                       # searchable, offline
```

## Verification results

- `pytest`: **41 passed** - format detection, ChatGPT mapping-tree
  traversal, Open WebUI/generic/Markdown parsers (including code-fence
  handling), filename generation/collisions, slugification, front-matter
  round-trips (multiline summaries, timestamps), index HTML escaping of
  `</script>`, dry-run behavior, graceful summary failures, and a
  test asserting `Authorization` never appears in the request code.
- `ruff check src tests`: **all checks passed**.
- `compileall`: clean.
- Manual end-to-end via `pip install -e .` + console script: archive (7/7
  fixture conversations), reindex, re-tag (created date and per-message
  timestamps preserved, no duplicated stamps), and `summarize` against a
  live stub OpenAI-compatible HTTP server (summaries landed in front
  matter and the HTML index). Against a dead endpoint, all 7 files skip
  gracefully and exit 0.
- No secrets, API keys, or personal data anywhere in the repo; `index.html`
  contains no external `http(s)` references. Fixtures use invented,
  non-personal example content.

## Known gaps

- Format detection is heuristic: unusual container variants (e.g., nested
  branches in ChatGPT mappings - only the first child path is followed per
  node, which matches linear conversations) or wholly new export shapes
  may need small additions to the dispatchers in `src/chat_archiver/parse.py`.
- Markdown role detection recognizes common patterns (`## user`,
  `**User:**`, `You:`); exotic or unnamed-role layouts may be missed.
- Images, files, and tool-call blocks are skipped (text parts are kept);
  multimodal payloads are flattened to their text components only.
- The `tag` command re-renders files; any free-form Markdown a user adds
  to archive files after generation would be re-normalized.
- Summaries are not batched (one request per conversation) - fine for
  Ollama, conservative for larger endpoints; no auto-retry loops beyond
  splash-free skip-and-continue.
- Shebang-free `python3 -m chat_archiver.cli` works, but the tab-completion
  and shell polish (none yet) could be added later.

## Privacy statement

Default operation performs **zero network I/O**. With `--summarize`, text
of each summarized conversation is sent only to the configured base_url.
No API keys are accepted or stored; no telemetry exists. This tool only
organizes files on your own disk.
