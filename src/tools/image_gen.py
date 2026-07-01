"""Pluggable image generation — a stable facade over swappable providers.

Callers use `generate_image(...)`; the backend is chosen by the IMAGE_PROVIDER env
var (default "fal"). Adding a provider means registering a name -> factory and
setting IMAGE_PROVIDER — no caller changes. See src/tools/image_providers/.
"""
from __future__ import annotations

import os
from importlib import import_module
from typing import Callable, Protocol


class ImageProvider(Protocol):
    def generate(
        self, prompt: str, out_path: str, reference_paths: list[str] | None = None
    ) -> str: ...


# name -> "module:Class" (lazy-imported) or a zero-arg factory. Lazy import keeps a
# provider's optional deps off the import path until that provider is selected.
_REGISTRY: dict[str, "str | Callable[[], ImageProvider]"] = {
    "fal": "src.tools.image_providers.fal:FalImageProvider",
}


def register_provider(name: str, factory: "str | Callable[[], ImageProvider]") -> None:
    """Register an image provider: a 'module:Class' import path or a zero-arg factory."""
    _REGISTRY[name] = factory


def get_provider(name: str | None = None) -> ImageProvider:
    name = name or os.environ.get("IMAGE_PROVIDER", "fal")
    try:
        entry = _REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"unknown image provider: {name!r} (registered: {sorted(_REGISTRY)})"
        ) from None
    if callable(entry):
        return entry()
    module_path, _, class_name = entry.partition(":")
    return getattr(import_module(module_path), class_name)()


def generate_image(
    prompt: str, out_path: str, reference_paths: list[str] | None = None
) -> str:
    """Generate an image with the configured provider; write JPEG to out_path. Raises on failure."""
    return get_provider().generate(prompt, out_path, reference_paths)
