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

    def test_video_render_lifecycle(self):
        a = PostAsset(campaign_id="c1", media_type="video", image_url="https://x/y.jpg")
        assert a.needs_render
        assert a.publish_url is None  # a video has nothing to publish until its clip lands
        a.start_render("req_1")
        assert a.render_request_id == "req_1" and a.needs_render
        a.mark_rendered("https://x/clip.mp4")
        assert not a.needs_render
        assert a.publish_url == "https://x/clip.mp4"  # video wins once present


class TestVideoPublish:
    def test_video_asset_uses_reel_container(self):
        asset = PostAsset(campaign_id="c1", media_type="video",
                          video_url="https://x/clip.mp4", caption="rainy evening momos")
        with patch("src.agents.publishing.find_published_media", return_value=None), \
             patch("src.agents.publishing.create_reel_container") as crc, \
             patch("src.agents.publishing.create_media_container") as cmc, \
             patch("src.agents.publishing.wait_for_container") as wait, \
             patch("src.agents.publishing.publish_media") as pub, \
             patch("src.agents.publishing.store_post"):
            crc.return_value = type("C", (), {"container_id": "cont_1"})()
            wait.return_value = type("S", (), {"status_code": "FINISHED"})()
            pub.return_value = type("R", (), {"media_id": "m1", "permalink": "https://p"})()
            updated, err = _publish_asset(asset)
        assert err is None and updated.published_media_id == "m1"
        crc.assert_called_once()       # reel path used
        cmc.assert_not_called()        # image path skipped


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


class TestPerPostApprovalGate:
    def _state(self, status):
        asset = PostAsset(campaign_id="c1", caption="hi", image_url="https://x/y.jpg",
                          approval_status=status)
        return {"approved": True, "campaign_id": "c1", "manual_publish_queue": [],
                "errors": [], "creative_assets": [asset.model_dump(mode="json")]}

    def test_rejected_asset_is_never_published(self):
        with patch("src.agents.publishing.find_published_media", return_value=None), \
             patch("src.agents.publishing.create_media_container") as cmc:
            result = publishing_node(self._state("rejected"))
        cmc.assert_not_called()  # compliance: a rejected post must never reach the Meta API
        assert result["creative_assets"][0]["approval_status"] == "rejected"

    def test_scheduled_asset_is_not_published_in_this_run(self):
        with patch("src.agents.publishing.find_published_media", return_value=None), \
             patch("src.agents.publishing.create_media_container") as cmc:
            publishing_node(self._state("scheduled"))
        cmc.assert_not_called()  # future-dated posts publish via the dispatch cron, not here

    def test_approved_asset_is_published(self):
        with patch("src.agents.publishing.find_published_media", return_value=None), \
             patch("src.agents.publishing.create_media_container") as cmc, \
             patch("src.agents.publishing.wait_for_container") as wait, \
             patch("src.agents.publishing.publish_media") as pub, \
             patch("src.agents.publishing.store_post"):
            cmc.return_value = type("C", (), {"container_id": "cont_1"})()
            wait.return_value = type("S", (), {"status_code": "FINISHED"})()
            pub.return_value = type("R", (), {"media_id": "m1", "permalink": "https://p"})()
            result = publishing_node(self._state("approved"))
        cmc.assert_called_once()
        assert result["creative_assets"][0]["approval_status"] == "published"


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
