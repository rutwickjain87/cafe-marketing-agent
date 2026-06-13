"""Langfuse tracing shim.

Exports `observe` — a decorator that wraps Langfuse's @observe() when the
package is installed and LANGFUSE_PUBLIC_KEY is set, and falls back to a
no-op passthrough otherwise.  Import from here instead of langfuse directly
so local dev and CI without credentials work without any code changes.

Usage:
    from src.tracing import observe

    @observe(name="draft_caption")
    def draft_caption(brief: PostBrief) -> Caption:
        ...
"""
from __future__ import annotations

import functools
import os
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_LANGFUSE_ENABLED = False

try:
    if os.environ.get("LANGFUSE_PUBLIC_KEY"):
        from langfuse.decorators import observe as _langfuse_observe  # type: ignore[import]
        _LANGFUSE_ENABLED = True
except ImportError:
    pass


def observe(name: str | None = None, **kwargs: Any) -> Callable[[F], F]:
    """Decorator factory — wraps Langfuse @observe or is a transparent no-op."""
    if _LANGFUSE_ENABLED:
        from langfuse.decorators import observe as _langfuse_observe  # type: ignore[import]
        return _langfuse_observe(name=name, **kwargs)  # type: ignore[return-value]

    def _noop(fn: F) -> F:
        return fn

    return _noop
