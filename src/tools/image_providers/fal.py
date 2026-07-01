"""fal.ai image provider — FLUX dev for product shots, FLUX Kontext for mascot reference.

Self-contained (no fal SDK, no project imports) so the module is portable to other
projects. Uses fal's synchronous `fal.run` endpoint: image generation takes seconds,
so the Creative node stays synchronous (unlike the async video path in fal_media.py).

Environment:
    FAL_KEY               — fal.ai API key (shared with the video tool)
    FAL_IMAGE_MODEL       — text-to-image model; default below
    FAL_IMAGE_EDIT_MODEL  — reference-guided (character consistency) model; default below
"""
from __future__ import annotations

import base64
import mimetypes
import os
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

_RUN_BASE = "https://fal.run"
_DEFAULT_MODEL = "fal-ai/flux/dev"
_DEFAULT_EDIT_MODEL = "fal-ai/flux-pro/kontext"
_TIMEOUT = 120


class FalImageProvider:
    """Text-to-image via FLUX dev; reference-guided edits via FLUX Kontext."""

    def generate(
        self, prompt: str, out_path: str, reference_paths: list[str] | None = None
    ) -> str:
        key = os.environ.get("FAL_KEY", "")
        if not key:
            raise RuntimeError("FAL_KEY is not set")

        if reference_paths:
            model = os.environ.get("FAL_IMAGE_EDIT_MODEL") or _DEFAULT_EDIT_MODEL
            body = {
                "prompt": prompt,
                # Kontext accepts a base64 data URI, so the local mascot needs no hosting.
                "image_url": _data_uri(reference_paths[0]),
                "aspect_ratio": "1:1",
                "output_format": "jpeg",
                "num_images": 1,
            }
        else:
            model = os.environ.get("FAL_IMAGE_MODEL") or _DEFAULT_MODEL
            body = {
                "prompt": prompt,
                "image_size": "square_hd",
                "output_format": "jpeg",
                "num_images": 1,
            }

        headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{_RUN_BASE}/{model}", headers=headers, json=body)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"fal image generation failed ({resp.status_code}): {_detail(resp)}"
                )
            url = _first_image_url(resp.json())
            if not url:
                raise RuntimeError(f"fal returned no image for prompt: {prompt[:80]}")
            img = client.get(url)

        # Re-encode through PIL to guarantee an Instagram-safe RGB JPEG.
        Image.open(BytesIO(img.content)).convert("RGB").save(out_path, format="JPEG", quality=90)
        return out_path


def _data_uri(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"reference image not found: {path}")
    mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _first_image_url(payload: object) -> str | None:
    images = payload.get("images") if isinstance(payload, dict) else None
    if isinstance(images, list) and images and isinstance(images[0], dict):
        return images[0].get("url")
    return None


def _detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:200]
    return (str(data.get("detail") or data) if isinstance(data, dict) else str(data))[:300]
