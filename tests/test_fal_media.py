"""Unit tests for the fal.ai client — error mapping + payload parsing, no network."""
from unittest.mock import MagicMock, patch

import httpx

from src.tools.fal_media import (
    FalError,
    FalErrorCode,
    FalJob,
    FalResult,
    _handle_response,
    parse_webhook,
    submit_image_to_video,
)


def test_auth_error_maps():
    result = _handle_response(httpx.Response(401, json={"detail": "bad key"}))
    assert isinstance(result, FalError)
    assert result.code == FalErrorCode.AUTH_REQUIRED
    assert result.recovery == "refresh_fal_key"


def test_rate_limit_maps_with_retry_hint():
    result = _handle_response(httpx.Response(429, headers={"Retry-After": "30"}, json={}))
    assert isinstance(result, FalError)
    assert result.code == FalErrorCode.RATE_LIMITED
    assert result.recovery == "retry_after_30s"


def test_submit_returns_request_id(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "k")
    resp = httpx.Response(200, json={"request_id": "req_1", "status_url": "https://s"})
    client = MagicMock()
    client.__enter__.return_value.post.return_value = resp
    with patch("src.tools.fal_media.httpx.Client", return_value=client):
        job = submit_image_to_video("animate this", "https://img.jpg")
    assert isinstance(job, FalJob)
    assert job.request_id == "req_1"


def test_submit_passes_webhook_url(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "k")
    resp = httpx.Response(200, json={"request_id": "req_2"})
    client = MagicMock()
    post = client.__enter__.return_value.post
    post.return_value = resp
    with patch("src.tools.fal_media.httpx.Client", return_value=client):
        submit_image_to_video("p", "https://img.jpg", webhook_url="https://cb/webhooks/fal?x=1")
    assert post.call_args.kwargs["params"] == {"fal_webhook": "https://cb/webhooks/fal?x=1"}


def test_parse_webhook_ok_extracts_video():
    body = {"request_id": "r", "status": "OK", "payload": {"video": {"url": "https://v.mp4"}}}
    result = parse_webhook(body)
    assert isinstance(result, FalResult)
    assert result.video_url == "https://v.mp4"


def test_parse_webhook_error_maps_to_generation_failed():
    body = {"request_id": "r", "status": "ERROR", "error": "model exploded"}
    result = parse_webhook(body)
    assert isinstance(result, FalError)
    assert result.code == FalErrorCode.GENERATION_FAILED


def test_parse_webhook_missing_video_is_error():
    result = parse_webhook({"request_id": "r", "status": "OK", "payload": {}})
    assert isinstance(result, FalError)
    assert result.code == FalErrorCode.GENERATION_FAILED
