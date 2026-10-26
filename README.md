# chat-archiver

A small Python CLI that turns exported AI chat conversations into a tidy,
searchable, local-first archive - brought to you by **Asdale Dynamics, LLC**
(as part of Dylan Asdale's beginner-friendly AI projects).

Drop in the JSON or Markdown exports you get from chat tools and local-model
UIs, and get back:

- **One clean Markdown file per conversation**, with a title, date, model, and
  other metadata in YAML front matter
- **A searchable index page** (`index.html`) that works fully offline in any
  browser - plus a plain `index.md` list for skimming
- **Topic tags** driven by a tiny TOML notes file *you* write
- **Optional one-line summaries** via any OpenAI-compatible endpoint you point
  it at (default: Ollama on `localhost:11434/v1`)

## The privacy promise

Everything lives on your machine. **The tool never sends anything anywhere**
unless you deliberately pass `--summarize` (or run the `summarize`
subcommand), in which case conversation text goes to one place only: the
OpenAI-compatible endpoint you configured. There are no API keys - not
accepted, not stored, not peeked for. No telemetry, no accounts, no uploads,
no phoning home.

## Quick start

Requires Python 3.11+ (no third-party runtime dependencies).

```bash
pip install -e .
```

After installing, you get a `chat-archiver` command:

```bash
# 1. Start from your exports folder (JSON or Markdown files, any layout)
chat-archiver init-tags                 # writes a starter tags.toml you edit

# 2. Archive everything into ./archive, applying your tags
chat-archiver archive exports -o archive -t tags.toml

# 3. Open archive/index.html in a browser - type to search. Done.
```

For a real look before archiving:

```bash
chat-archiver archive exports -n        # dry run: shows what would be written
```

## Supported export formats (auto-detected)

| Export type | Example | Status |
|---|---|---|
| OpenAI ChatGPT `conversations.json` | node-mapping JSON | supported |
| Open WebUI / Ollama-style single chat | `{"chat": {"history": ...}}` | supported |
| Generic message lists | `[{"role", "content"}]` | supported |
| Generic conversation wrappers | `{"conversations": [...]}` | supported |
| Markdown role exports | `**User:** ...` / `## assistant` | supported |

Dates may arrive in seconds, milliseconds, or ISO strings; all are
normalized to UTC. Conversations without dates sort under `no-date-...`
file names rather than getting dropped or guessed.

## Commands

```
chat-archiver archive SRC [-o OUT] [-t tags.toml] [-n] [-s] [--base-url URL] [--model NAME]
chat-archiver index [DIR]        # rebuild both index pages for an existing archive
chat-archiver tag [DIR] [-t tags.toml]   # re-apply your topic tags in place
chat-archiver summarize [DIR] [--base-url URL] [--model NAME]
chat-archiver init-tags [--path tags.toml]
```

What each archive file looks like:

```markdown
---
title: "Planning a raised bed garden"
created: "2024-03-15 00:00:00 UTC"
model: "gpt-4o"
source: "chatgpt_conversations.json"
format: "openai-chatgpt"
message_count: 2
tags: ["gardening"]
archive_path: "2024-03-15-planning-a-raised-bed-garden.md"
---

# Planning a raised bed garden

*2024-03-15 00:00:00 UTC | model: gpt-4o | source: chatgpt_conversations.json*

*tags: gardening*

## user
_2024-03-15 00:00:00 UTC_

What soil mix should I use for a raised bed?

## assistant
_2024-03-15 00:00:05 UTC_

A simple mix: 40% topsoil, 30% compost, 30% aeration material like perlite.
```

## Topic tagging (your notes, your rules)

Tags live in a plain TOML file you edit by hand. A conversation gets a tag
when any keyword appears in its title or text (case-insensitive, all local):

```toml
# tags.toml - one tag per topic, one line per keyword list
[tags]
gardening  = ["garden", "plant", "soil", "seed"]
chess      = ["italian opening", "sicilian", "tactics"]
bookkeeping = ["budget", "expense", "invoice", "bookkeeping"]
ffxiv      = ["ffxiv", "final fantasy", "duty", "raid"]
```

Re-apply any time with `chat-archiver tag archive -t tags.toml`; files and
the index update in place.

## Optional summaries (configurable, key-less)

Summaries are opt-in. `chat-archiver archive SRC -s` (or `chat-archiver
summarize archive`) posts each conversation to an OpenAI-compatible
`/chat/completions` endpoint and stores the answer as a one-liner in front
matter and on the index page.

Default endpoint: **Ollama** at `http://localhost:11434/v1` with model
`llama3`. Any OpenAI-compatible `base_url` works:

```bash
# local Ollama (default):
chat-archiver summarize archive
# a different OpenAI-compatible server:
chat-archiver summarize archive --base-url http://127.0.0.1:9001/v1 --model mistral7b
```

The `Authorization` header is never sent - the design explicitly assumes a
key-less endpoint, keeping key management out of your archive tool.

## Tests

```bash
pip install -e ".[dev]"   # installs pytest
pytest                    # 41 tests, all offline; endpoint calls are stubbed
```

## Privacy checklist

- [x] No network calls unless you opt into summaries
- [x] Summaries go only to the endpoint you configured
- [x] No API keys anywhere in code, config, or docs
- [x] No telemetry, puzzles, "check for updates", nor accounts
- [x] Blocked HTML injection on the index page (content is escaped)

## License

MIT - see [LICENSE](LICENSE). Copyright (c) 2026 Asdale Dynamics, LLC.

Chat archives can contain personal data; this tool only helps you organize
files on your own disk. As with anything AI-related, double-check anything a
model told you - it is a friend explaining, not an oracle.
