"""Optional summary indexing via an OpenAI-compatible chat endpoint.

Defaults to Ollama's local server (``http://localhost:11434/v1``).
Any OpenAI-compatible ``base_url`` works. No API key is ever sent,
kept or stored - only the base URL you configure. Summaries go into
your local archive files; nothing is published anywhere.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "llama3"
MAX_PROMPT_CHARS = 4000
TIMEOUT_SECONDS = 60


def _endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _post_json(url: str, payload: dict) -> dict:
    """POST *payload* as JSON and return the parsed response."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def build_prompt(conv, max_chars: int = MAX_PROMPT_CHARS) -> str:
    """Build a short summarization prompt from one conversation."""
    turns = []
    for message in conv.messages:
        if message.role in ("user", "assistant"):
            turns.append(f"{message.role}: {message.content.strip()[:800]}")
    text = "\n".join(turns)[:max_chars]
    if not text.strip():
        text = (conv.plain_title or "(no content)")
    return (
        "Summarize this conversation in one or two plain sentences, "
        "no bullet points, no markdown:\n\n"
        f"Title: {conv.plain_title}\n\n{text}"
    )


def summarize_conversation(conv, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL) -> str:
    """Ask the endpoint for a one-or-two sentence summary of *conv*."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You write one-sentence plain-English summaries of conversations."},
            {"role": "user", "content": build_prompt(conv)},
        ],
        "stream": False,
    }
    try:
        response = _post_json(_endpoint(base_url), payload)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise SummaryError(f"summary request to {base_url} failed: {exc}") from exc
    try:
        content = response["choices"][0]["message"]["content"]
        return str(content).strip().replace("\n", " ")
    except (KeyError, IndexError, TypeError) as exc:
        raise SummaryError(f"unexpected response from {base_url}: {json.dumps(response)[:200]}") from exc


class SummaryError(RuntimeError):
    """Raised when the summarization endpoint is unreachable or odd."""


def summaries_for(convs: list, base_url: str, model: str, verbose: object = None) -> dict[str, str]:
    """Summarize conversations; keyed by their eventual archive filename.

    The *verbose* argument is an optional ``print``-like callable used for
    progress reporting. Failures degrade gracefully to ``None`` summaries
    so archiving still completes when a model server is offline.
    """
    from .archive import conversation_filename

    say = verbose or (lambda *a: None)
    used: set[str] = set()
    results: dict[str, str | None] = {}
    for conv in convs:
        rel = conversation_filename(conv, used)  # writes only rel/archive name; no I/O
        try:
            results[rel] = summarize_conversation(conv, base_url, model)
            say(f"  summarized {rel}")
        except SummaryError as exc:
            say(f"  skipped {rel}: {exc}")
            results[rel] = None
    return results
