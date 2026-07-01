"""Operator API tests — auth guard, campaign pause/approve, Meta webhook verification.

The graph is mocked so no Anthropic/Meta/Supabase calls happen.
"""
import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.server import app as server  # noqa: E402

TOKEN = "test-operator-token"


def _snapshot(paused_at, status="draft", assets=None):
    return SimpleNamespace(
        next=(paused_at,) if paused_at else (),
        values={"status": status, "creative_assets": assets or []},
    )


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("OPERATOR_API_TOKEN", TOKEN)
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "verify-me")
    monkeypatch.setenv("META_APP_SECRET", "app-secret")
    return TestClient(server.app)


def test_campaign_requires_operator_token(client):
    resp = client.post("/campaigns", json={"brief": {}})
    assert resp.status_code == 401


def test_campaign_starts_and_pauses_at_approval(client):
    fake = MagicMock()
    fake.get_state.return_value = _snapshot("human_approval", assets=[{"post_id": "p1", "caption": "hi"}])
    with patch.object(server, "graph", fake), \
         patch.object(server, "send_approval_card") as card:
        resp = client.post("/campaigns", json={"brief": {"goal": "x"}}, headers={"X-Operator-Token": TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    assert body["paused_at"] == "human_approval"
    card.assert_called_once()


def test_resume_rejects_when_not_awaiting_approval(client):
    fake = MagicMock()
    fake.get_state.return_value = _snapshot(None, status="published")
    with patch.object(server, "graph", fake):
        resp = client.post("/runs/thread_1/resume", json={"approved": True},
                           headers={"X-Operator-Token": TOKEN})
    assert resp.status_code == 409


def test_resume_approve_advances(client):
    fake = MagicMock()
    fake.get_state.return_value = _snapshot("human_approval", status="published")
    with patch.object(server, "graph", fake), patch.object(server, "notify_text"):
        resp = client.post("/runs/thread_1/resume", json={"approved": True},
                           headers={"X-Operator-Token": TOKEN})
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"
    fake.update_state.assert_called_once()
    fake.invoke.assert_called_once()


def _telegram_tap(client, data, assets):
    fake = MagicMock()
    fake.get_state.return_value = _snapshot("human_approval", assets=assets)
    with patch.object(server, "graph", fake), patch.object(server, "notify_text"), \
         patch.object(server, "answer_callback_query"):
        resp = client.post(
            "/webhooks/telegram",
            json={"callback_query": {"id": "cq", "data": data}},
            headers={"X-Telegram-Bot-Api-Secret-Token": TOKEN},
        )
    return resp, fake


def test_per_post_tap_records_without_resuming_while_others_pending(client):
    resp, fake = _telegram_tap(
        client, "approve:thread_1:p1",
        assets=[{"post_id": "p1", "approval_status": "pending_approval"},
                {"post_id": "p2", "approval_status": "pending_approval"}],
    )
    assert resp.status_code == 200
    fake.invoke.assert_not_called()  # p2 still pending → do not resume/publish yet


def test_per_post_tap_resumes_once_all_decided(client):
    resp, fake = _telegram_tap(
        client, "reject:thread_1:p2",
        assets=[{"post_id": "p1", "approval_status": "approved"},
                {"post_id": "p2", "approval_status": "pending_approval"}],
    )
    assert resp.status_code == 200
    fake.invoke.assert_called_once()  # all decided → resume


def test_meta_verify_echoes_challenge(client):
    resp = client.get("/webhooks/meta", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "verify-me",
        "hub.challenge": "12345",
    })
    assert resp.status_code == 200
    assert resp.text == "12345"


def test_meta_verify_rejects_bad_token(client):
    resp = client.get("/webhooks/meta", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong",
        "hub.challenge": "12345",
    })
    assert resp.status_code == 403


def test_meta_webhook_rejects_bad_signature(client):
    resp = client.post("/webhooks/meta", content=b"{}",
                       headers={"X-Hub-Signature-256": "sha256=deadbeef"})
    assert resp.status_code == 401


def test_meta_webhook_runs_engagement_on_valid_signature(client):
    raw = b'{"entry":[{"changes":[{"field":"comments","value":{"id":"c1","text":"love it"}}]}]}'
    sig = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    with patch.object(server, "engagement_node", return_value={"escalated_messages": []}) as eng:
        resp = client.post("/webhooks/meta", content=raw,
                           headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["handled"] == 1
    eng.assert_called_once()


def test_fal_webhook_requires_token(client):
    resp = client.post("/webhooks/fal", params={"thread_id": "t", "post_id": "p", "token": "wrong"},
                       json={})
    assert resp.status_code == 401
