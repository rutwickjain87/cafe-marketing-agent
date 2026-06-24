"""Unit tests for Meta API error mapping — no network calls."""
import httpx

from src.tools.meta_graph import _handle_response, MetaError, MetaErrorCode


def test_dm_window_expired_is_mapped_and_not_retryable():
    resp = httpx.Response(200, json={"error": {"code": 551, "message": "window closed"}})
    result = _handle_response(resp)
    assert isinstance(result, MetaError)
    assert result.code == MetaErrorCode.DM_WINDOW_EXPIRED
    assert result.recovery == "discard_reply_do_not_retry"  # compliance: discard, never retry


def test_permission_error_maps_to_page_auth():
    resp = httpx.Response(200, json={"error": {"code": 200, "message": "no perm"}})
    result = _handle_response(resp)
    assert isinstance(result, MetaError)
    assert result.code == MetaErrorCode.PAGE_PUBLISH_AUTH_REQUIRED


def test_unknown_error_is_generic_api_error():
    resp = httpx.Response(200, json={"error": {"code": 999, "message": "boom"}})
    result = _handle_response(resp)
    assert isinstance(result, MetaError)
    assert result.code == MetaErrorCode.API_ERROR


def test_trending_audio_maps_to_audio_unavailable():
    resp = httpx.Response(200, json={"error": {"code": 9007, "error_subcode": 2207026,
                                                "message": "media format"}})
    result = _handle_response(resp)
    assert isinstance(result, MetaError)
    assert result.code == MetaErrorCode.AUDIO_UNAVAILABLE
    assert result.recovery == "route_to_manual_queue"
