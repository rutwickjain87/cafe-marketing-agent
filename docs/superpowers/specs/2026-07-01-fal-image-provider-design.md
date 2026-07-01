# Design: Pluggable image generation on fal.ai

**Date:** 2026-07-01
**Status:** Approved (brainstorming)

## Goal

Replace Gemini ("Nano Banana") image generation with fal.ai, behind a **modular,
plug-and-play provider interface** so a different image backend (another fal model,
Midjourney proxy, etc.) can be swapped in by config with zero changes to callers.
Video already runs on fal — out of scope. OpenCut (editing) shelved: it has no
headless mode today, and the pipeline has no editing step.

## Scope

- **Changes:** the image tool layer only.
- **Unchanged:** `creative.py` (keeps calling `generate_image(...)`), video path,
  publishing, approval, scheduling, engagement, analytics.

## Architecture

Provider seam with one implementation today. Selection by env var `IMAGE_PROVIDER`
(default `fal`). Adding a provider = new module + one registry entry; no caller edits.

```
src/tools/image_gen.py              # stable facade + interface + registry
  - ImageProvider (Protocol): generate(prompt, out_path, reference_paths) -> str
  - _REGISTRY: {name -> "module:Class"} (lazy import)
  - register_provider(name, import_path)
  - get_provider(name=None) -> ImageProvider   # env IMAGE_PROVIDER, default "fal"
  - generate_image(prompt, out_path, reference_paths=None) -> str   # delegates

src/tools/image_providers/fal.py    # FalImageProvider (self-contained, portable)
```

`generate_image` keeps its exact current signature and contract (writes a JPEG to
`out_path`, raises on failure), so `creative.py` — including the `wants_mascot`
reference logic — does not change.

## Provider contract

```python
class ImageProvider(Protocol):
    def generate(
        self, prompt: str, out_path: str, reference_paths: list[str] | None = None
    ) -> str: ...   # returns out_path; raises on any failure
```

Raise-on-failure is deliberate: `creative_node` already catches, logs, and sets
`human_review_required` — a missing image must never ship silently.

## FalImageProvider behaviour

Model chosen by whether a reference image is passed (mirrors today's logic):

| Case | fal model (env override) | Notes |
|---|---|---|
| No reference (product shot) | `FAL_IMAGE_MODEL`, default `fal-ai/flux/dev` | cheapest; bump to `flux-pro/v1.1-ultra` via env later |
| Reference present (mascot/community) | `FAL_IMAGE_EDIT_MODEL`, default `fal-ai/flux-pro/kontext` | character consistency |

- **Transport:** synchronous `POST https://fal.run/{model}` (images are seconds — no
  queue/webhook like video). Auth `Authorization: Key {FAL_KEY}` (shared with video).
- **Reference, no hosting:** the local mascot JPEG is read and passed inline as a
  base64 **data URI** in `image_url` (Kontext accepts data URIs — confirmed). No
  Supabase/fal upload.
- **Request:** `{prompt, image_size|aspect_ratio, output_format: "jpeg", num_images: 1}`;
  Kontext adds `image_url`. Default framing `square_hd` / `1:1` (Instagram feed).
- **Response:** `{"images": [{"url": ...}]}` → download first image → PIL → save
  RGB JPEG q90 to `out_path` (guarantees Instagram-safe JPEG).

## Errors

- Missing reference file → `FileNotFoundError`.
- fal non-2xx, non-JSON, or empty `images` → `RuntimeError` with fal's detail.
- Missing `FAL_KEY` → `RuntimeError`.
All surface to `creative_node`'s existing handler.

## Config / env

- `FAL_KEY` — reused from video.
- `IMAGE_PROVIDER` — default `fal`.
- `FAL_IMAGE_MODEL` — default `fal-ai/flux/dev`.
- `FAL_IMAGE_EDIT_MODEL` — default `fal-ai/flux-pro/kontext`.
- **Removed:** `GOOGLE_API_KEY` (only image_gen used it), `google-genai` dependency.

## Testing

`tests/test_image_gen.py`, httpx mocked (no live key):
1. No-ref → posts to `FAL_IMAGE_MODEL`, body has `prompt`, no `image_url`.
2. With-ref → posts to `FAL_IMAGE_EDIT_MODEL`, `image_url` starts `data:image/jpeg;base64,`.
3. Returned image URL is fetched and written as a valid JPEG at `out_path`.
4. fal non-200 / empty `images` → raises `RuntimeError`.
5. `get_provider("fal")` resolves; unknown name raises.

Plus one live verification call (real `FAL_KEY`) before claiming done.

## Out of scope / later

- Video provider seam (already fal; refactor only if a second video backend appears).
- Real embeddings, analytics writeback (tracked separately).
