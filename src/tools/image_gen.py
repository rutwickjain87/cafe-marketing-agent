"""Gemini image generation (Nano Banana) — Creative node image tool.

Renders a post image from a text prompt plus optional reference images (e.g. the
panda mascot) to keep brand assets consistent. Always writes a JPEG, since
Instagram's publishing API rejects PNG.
"""
from __future__ import annotations

import mimetypes
import os
from io import BytesIO
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

# Nano Banana 2: reference-capable, strong character consistency, free tier + ~$0.04/image.
_MODEL = "gemini-3.1-flash-image"


def _client() -> genai.Client:
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY is not set")
    return genai.Client(api_key=key)


def generate_image(
    prompt: str,
    out_path: str,
    reference_paths: list[str] | None = None,
) -> str:
    """Generate an image and write it as JPEG to out_path. Raises on failure.

    reference_paths are passed to the model as visual references for brand
    consistency (mascot, palette). A missing image must stop a publish, so this
    raises rather than returning a sentinel.
    """
    contents: list = [prompt]
    for ref in reference_paths or []:
        ref_path = Path(ref)
        if not ref_path.is_file():
            raise FileNotFoundError(f"reference image not found: {ref}")
        mime = mimetypes.guess_type(ref_path.name)[0] or "image/jpeg"
        contents.append(types.Part.from_bytes(data=ref_path.read_bytes(), mime_type=mime))

    response = _client().models.generate_content(
        model=_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(response_modalities=["Image"]),
    )

    raw = _extract_image_bytes(response)
    if raw is None:
        raise RuntimeError("Gemini returned no image data (possibly blocked or text-only)")

    Image.open(BytesIO(raw)).convert("RGB").save(out_path, format="JPEG", quality=90)
    return out_path


def _extract_image_bytes(response) -> bytes | None:
    for candidate in response.candidates or []:
        parts = getattr(candidate.content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data
    return None
