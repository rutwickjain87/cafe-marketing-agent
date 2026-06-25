"""Langfuse tracing (SDK v4).

Real tracing when LANGFUSE_PUBLIC_KEY is set and the package is installed;
transparent no-ops otherwise, so local dev / CI without credentials need no code
changes. Always import `observe` from here (not from langfuse) so the decorator
degrades gracefully.

- `observe`        — @observe decorator (span per function).
- `generation()`   — context manager wrapping a single LLM call as a Langfuse
                     generation (captures model + token usage), nested under the
                     current span.
- `flush()`        — flush buffered events (call on shutdown / before exit).

A global mask redacts the operator token if it ever lands in a traced value
(e.g. the fal webhook URL carries it as ?token=) — secrets never reach Langfuse.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_ENABLED = bool(os.environ.get("LANGFUSE_PUBLIC_KEY"))
_client = None

if _ENABLED:
    try:
        from langfuse import Langfuse, observe as _observe

        def _mask(*, data: Any, **_: Any) -> Any:
            """Redact the operator token wherever it appears in a traced value."""
            secret = os.environ.get("OPERATOR_API_TOKEN")
            if not secret:
                return data
            try:
                dumped = json.dumps(data)
            except (TypeError, ValueError):
                return data
            if secret in dumped:
                return json.loads(dumped.replace(secret, "***REDACTED***"))
            return data

        # Constructing Langfuse configures the global client; mask applies to all traces.
        _client = Langfuse(mask=_mask)
    except ImportError:
        _ENABLED = False


def tracing_enabled() -> bool:
    return _ENABLED


def observe(name: str | None = None, **kwargs: Any) -> Callable[[F], F]:
    """@observe decorator — a real Langfuse span when enabled, else a no-op."""
    if _ENABLED:
        return _observe(name=name, **kwargs)  # type: ignore[return-value]

    def _noop(fn: F) -> F:
        return fn

    return _noop


class _NoopGeneration:
    def update(self, **_: Any) -> None:
        pass


@contextmanager
def generation(*, name: str, model: str, input: Any, metadata: dict | None = None) -> Generator[Any]:
    """Record one LLM call as a Langfuse generation, nested under the active span.

    Yields a handle whose .update(output=..., usage_details=..., cost_details=...)
    sets the result. A no-op handle when tracing is disabled.
    """
    if not _ENABLED or _client is None:
        yield _NoopGeneration()
        return
    with _client.start_as_current_observation(
        as_type="generation", name=name, model=model, input=input, metadata=metadata
    ) as gen:
        yield gen


def flush() -> None:
    if _ENABLED and _client is not None:
        _client.flush()
