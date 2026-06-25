"""Provider-agnostic chat completion.

Lets the agent nodes call Claude (Anthropic SDK) or any OpenRouter model (e.g.
GLM via z-ai/glm-5.2) through one `complete()` call, without changing node code.
The Anthropic path is untouched — it's just one of two backends here.

Config (env):
    LLM_PROVIDER     anthropic | openrouter   (default: openrouter)
    OPENROUTER_API_KEY   required when provider=openrouter
    OPENROUTER_MODEL     OpenRouter model slug (default: z-ai/glm-5.2)

Callers pass their Anthropic model id; it is used only when the provider is
anthropic. On OpenRouter the OPENROUTER_MODEL is used instead.
"""
from __future__ import annotations

import json
import os

import anthropic
import httpx

from src import tracing

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_OPENROUTER_MODEL = "z-ai/glm-5.2"
# Reasoning models (GLM-5.2 etc.) spend completion tokens on a hidden reasoning
# pass before the answer, so a caller's max_tokens can be fully consumed before
# any content is emitted. Add headroom on the OpenRouter path so JSON outputs
# aren't starved or truncated.
_REASONING_HEADROOM = 1024


class LLMError(RuntimeError):
    """A provider call failed or returned no usable content."""


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "openrouter").strip().lower()


def complete(*, system: str, messages: list[dict], model: str, max_tokens: int = 1024) -> str:
    """Return the assistant's text for a system prompt + user/assistant messages.

    `model` is the Anthropic model id, used only when LLM_PROVIDER=anthropic; on
    OpenRouter the OPENROUTER_MODEL is used. The call is traced to Langfuse as a
    generation (model + token usage).
    """
    provider = _provider()
    gen_model = model if provider == "anthropic" else os.environ.get("OPENROUTER_MODEL", _DEFAULT_OPENROUTER_MODEL)
    with tracing.generation(
        name=f"llm.{provider}",
        model=gen_model,
        input={"system": system, "messages": messages},
        metadata={"provider": provider},
    ) as gen:
        if provider == "anthropic":
            text, usage = _anthropic_complete(system, messages, model, max_tokens)
        else:
            text, usage = _openrouter_complete(system, messages, gen_model, max_tokens)
        gen.update(output=text, usage_details=usage)
        return text


def extract_json(raw: str) -> str:
    """Pull the first {...} object out of a model reply, tolerating code fences/prose."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("no JSON object in model output", raw or "", 0)
    return raw[start : end + 1]


def _anthropic_complete(system: str, messages: list[dict], model: str, max_tokens: int) -> tuple[str, dict]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    usage = {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}
    return resp.content[0].text, usage


def _openrouter_complete(system: str, messages: list[dict], model: str, max_tokens: int) -> tuple[str, dict]:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    payload = {
        "model": model,
        "max_tokens": max_tokens + _REASONING_HEADROOM,
        "messages": [{"role": "system", "content": system}, *messages],
    }
    try:
        resp = httpx.post(
            _OPENROUTER_URL,
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=120,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(f"OpenRouter request failed: {exc}") from exc

    data = resp.json()
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"OpenRouter returned no choices: {data}") from exc
    if not content:
        raise LLMError(
            f"OpenRouter returned empty content (finish_reason={choice.get('finish_reason')}) "
            f"for model {model} — likely max_tokens exhausted by reasoning"
        )
    u = data.get("usage") or {}
    usage = {
        k: v
        for k, v in {
            "input": u.get("prompt_tokens"),
            "output": u.get("completion_tokens"),
            "total": u.get("total_tokens"),
        }.items()
        if v is not None
    }
    return content, usage
