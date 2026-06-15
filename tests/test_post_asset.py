"""Unit tests for PostAsset, publish idempotency, and the engagement policy gate.

No API calls — the Meta tools are patched out.
"""
import pytest
from unittest.mock import patch

from src.schemas import PostAsset
from src.agents.publishing import _publish_asset, publishing_node
from src.agents.engagement.engagement import _reply_passes_policy, IncomingMessage


class TestPostAsset:
    def test_ids_and_helpers(self):
        a = PostAsset(campaign_id="c1", caption="hot momos", hashtags=["#VoodooMomo", "#WagholiEats"])
        assert a.post_id.startswith("post_")
        assert a.caption_with_hashtags() == "hot momos\n\n#VoodooMomo #WagholiEats"
        assert a.is_published is False

    def test_publish_attempt_and_mark_published(self):
        a = PostAsset(campaign_id="c1")
        attempt = a.start_publish_attempt()
        assert attempt.startswith("pub_") and a.approval_status == "publishing"
        a.mark_published("media_42", "https://insta/p/x")
        assert a.is_published and a.published_media_id == "media_42"
        assert a.approval_status == "published"


class TestPublishIdempotency:
    def test_skips_when_already_published_in_state(self):
        asset = PostAsset(campaign_id="c1", image_url="https://x/y.jpg",
                          caption="hi", published_media_id="m1")
        with patch("src.agents.publishing.create_media_container") as cmc:
            updated, err = _publish_asset(asset)
        assert err is None
        assert updated.approval_status == "published"
        cmc.assert_not_called()  # never hit the API for an already-published post

    def test_skips_when_db_has_prior_publish(self):
        asset = PostAsset(campaign_id="c1", image_url="https://x/y.jpg", caption="hi")
        with patch("src.agents.publishing.find_published_media", return_value="m999"), \
             patch("src.agents.publishing.create_media_container") as cmc:
            updated, err = _publish_asset(asset)
        assert updated.published_media_id == "m999"
        cmc.assert_not_called()

    def test_publishing_node_requires_approval(self):
        with pytest.raises(PermissionError):
            publishing_node({"approved": False, "creative_assets": []})


class TestEngagementPolicyGate:
    def _msg(self, text="nice place"):
        return IncomingMessage(id="1", type="comment", text=text)

    def test_blocks_banned_phrase_in_reply(self):
        ok, reason = _reply_passes_policy(self._msg(), "you deserve the best momos")
        assert not ok and reason == "banned_phrase_in_reply"

    def test_blocks_escalation_keyword_in_message(self):
        ok, reason = _reply_passes_policy(self._msg("I want a refund"), "sure, happy to help")
        assert not ok and reason == "keyword_match"

    def test_blocks_empty_reply(self):
        ok, reason = _reply_passes_policy(self._msg(), "   ")
        assert not ok and reason == "empty_reply"

    def test_allows_clean_reply(self):
        ok, reason = _reply_passes_policy(self._msg("love this"), "Thanks. See you in Wagholi.")
        assert ok and reason == ""
