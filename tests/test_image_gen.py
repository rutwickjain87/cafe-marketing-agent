"""Unit tests for the pluggable image tool — provider selection + fal payloads.

No network: httpx is mocked. A real fal call is exercised separately in verification.
"""
from io import BytesIO
from unittest.mock import MagicMock, patch

import httpx
import pytest
from PIL import Image

from src.tools.image_gen import generate_image, get_provider, register_provider
from src.tools.image_providers.fal import FalImageProvider


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 8), (200, 40, 20)).save(buf, format="PNG")
    return buf.getvalue()


def _mock_client(gen_json: dict, image_bytes: bytes) -> MagicMock:
    """A mocked httpx.Client whose .post returns the fal JSON and .get returns image bytes."""
    client = MagicMock()
    ctx = client.__enter__.return_value
    ctx.post.return_value = httpx.Response(200, json=gen_json)
    ctx.get.return_value = httpx.Response(200, content=image_bytes)
    return client, ctx


# --- provider registry -----------------------------------------------------

def test_get_provider_defaults_to_fal(monkeypatch):
    monkeypatch.delenv("IMAGE_PROVIDER", raising=False)
    assert isinstance(get_provider(), FalImageProvider)


def test_get_provider_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown image provider"):
        get_provider("does-not-exist")


def test_register_provider_is_pluggable():
    sentinel = object()
    register_provider("dummy", lambda: sentinel)
    assert get_provider("dummy") is sentinel


# --- fal: product shot (no reference) --------------------------------------

def test_no_reference_uses_base_model_without_image_url(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.delenv("FAL_IMAGE_MODEL", raising=False)
    out = tmp_path / "post.jpg"
    client, ctx = _mock_client({"images": [{"url": "https://cdn/img.jpg"}]}, _png_bytes())

    with patch("src.tools.image_providers.fal.httpx.Client", return_value=client):
        result = generate_image("steaming momos", str(out))

    url = ctx.post.call_args.args[0]
    body = ctx.post.call_args.kwargs["json"]
    assert url.endswith("fal-ai/flux/dev")
    assert body["prompt"] == "steaming momos"
    assert "image_url" not in body
    assert result == str(out)


# --- fal: mascot post (reference present) -----------------------------------

def test_reference_uses_edit_model_with_data_uri(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.delenv("FAL_IMAGE_EDIT_MODEL", raising=False)
    ref = tmp_path / "mascot.jpg"
    Image.new("RGB", (8, 8), (10, 10, 10)).save(ref, format="JPEG")
    out = tmp_path / "post.jpg"
    client, ctx = _mock_client({"images": [{"url": "https://cdn/img.jpg"}]}, _png_bytes())

    with patch("src.tools.image_providers.fal.httpx.Client", return_value=client):
        generate_image("panda with momos", str(out), reference_paths=[str(ref)])

    url = ctx.post.call_args.args[0]
    body = ctx.post.call_args.kwargs["json"]
    assert url.endswith("fal-ai/flux-pro/kontext")
    assert body["image_url"].startswith("data:image/jpeg;base64,")


def test_missing_reference_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    with pytest.raises(FileNotFoundError):
        generate_image("x", str(tmp_path / "o.jpg"), reference_paths=["/nope/missing.jpg"])


# --- fal: output + errors ---------------------------------------------------

def test_writes_valid_jpeg_from_returned_url(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    out = tmp_path / "post.jpg"
    client, _ = _mock_client({"images": [{"url": "https://cdn/img.jpg"}]}, _png_bytes())

    with patch("src.tools.image_providers.fal.httpx.Client", return_value=client):
        generate_image("momos", str(out))

    assert out.is_file()
    with Image.open(out) as im:
        assert im.format == "JPEG"


def test_fal_error_status_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    client = MagicMock()
    client.__enter__.return_value.post.return_value = httpx.Response(422, json={"detail": "bad"})
    with patch("src.tools.image_providers.fal.httpx.Client", return_value=client):
        with pytest.raises(RuntimeError, match="fal image"):
            generate_image("momos", str(tmp_path / "o.jpg"))


def test_empty_images_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    client, _ = _mock_client({"images": []}, _png_bytes())
    with patch("src.tools.image_providers.fal.httpx.Client", return_value=client):
        with pytest.raises(RuntimeError, match="no image"):
            generate_image("momos", str(tmp_path / "o.jpg"))


def test_missing_fal_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("FAL_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FAL_KEY"):
        generate_image("momos", str(tmp_path / "o.jpg"))
