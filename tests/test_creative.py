"""Unit tests for Caption schema validation and creative_node.

These tests exercise Pydantic validators only — no API calls.
"""
import pytest
from unittest.mock import patch

from src.agents.creative import Caption, PostBrief, creative_node, CONFIDENCE_THRESHOLD

VALID_HASHTAGS = [
    "#VoodooMomo", "#PuneSpecialtyMomo", "#WagholiEats",
    "#AchariMomo", "#MomoTime", "#PuneFood", "#StreetFoodPune", "#MomoLovers",
]

VALID_CAPTION_FEED = "Steaming hot momos, made fresh every evening. Come find us. 🥟"


class TestCaptionSchema:
    def test_valid_caption_passes(self):
        c = Caption(
            caption=VALID_CAPTION_FEED,
            hashtags=VALID_HASHTAGS,
            cta="Come find us.",
            confidence=0.85,
        )
        assert c.confidence == 0.85

    def test_caption_too_long_rejected(self):
        with pytest.raises(ValueError, match="too long"):
            Caption(
                caption="x" * 2201,
                hashtags=VALID_HASHTAGS,
                cta="See you.",
                confidence=0.8,
            )

    def test_too_few_hashtags_rejected(self):
        with pytest.raises(ValueError, match="out of range"):
            Caption(
                caption=VALID_CAPTION_FEED,
                hashtags=VALID_HASHTAGS[:3],
                cta="See you.",
                confidence=0.8,
            )

    def test_too_many_hashtags_rejected(self):
        with pytest.raises(ValueError, match="out of range"):
            Caption(
                caption=VALID_CAPTION_FEED,
                hashtags=VALID_HASHTAGS + ["#extra1", "#extra2", "#extra3", "#extra4", "#extra5"],
                cta="See you.",
                confidence=0.8,
            )

    def test_banned_hashtag_rejected(self):
        bad_tags = VALID_HASHTAGS[:7] + ["#Love"]
        with pytest.raises(ValueError, match="banned hashtags"):
            Caption(caption=VALID_CAPTION_FEED, hashtags=bad_tags, cta="See you.", confidence=0.8)

    def test_missing_core_hashtag_rejected(self):
        # Remove #VoodooMomo and replace with a neutral tag
        tags_without_core = [t for t in VALID_HASHTAGS if t != "#VoodooMomo"] + ["#WagholiFood"]
        with pytest.raises(ValueError, match="missing required core hashtags"):
            Caption(caption=VALID_CAPTION_FEED, hashtags=tags_without_core, cta="See you.", confidence=0.8)

    def test_banned_phrase_rejected(self):
        with pytest.raises(ValueError, match="banned phrase"):
            Caption(
                caption="Best momos in Pune. Come try us.",
                hashtags=VALID_HASHTAGS,
                cta="Come try us.",
                confidence=0.8,
            )

    def test_banned_phrase_case_insensitive(self):
        with pytest.raises(ValueError, match="banned phrase"):
            Caption(
                caption="You deserve the best momos.",
                hashtags=VALID_HASHTAGS,
                cta="Come try.",
                confidence=0.8,
            )

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(ValueError, match="0.0–1.0"):
            Caption(
                caption=VALID_CAPTION_FEED,
                hashtags=VALID_HASHTAGS,
                cta="See you.",
                confidence=1.5,
            )

    def test_review_reason_required_below_threshold(self):
        # Caption with low confidence should still be valid schema-wise;
        # review_reason is optional in schema but the creative_node sets human_review_required
        c = Caption(
            caption=VALID_CAPTION_FEED,
            hashtags=VALID_HASHTAGS,
            cta="See you.",
            confidence=0.5,
            review_reason="Uncertain about tone for this variety.",
        )
        assert c.review_reason is not None


class TestPostBrief:
    def test_valid_brief(self):
        b = PostBrief(product="Kurkure Momo", goal="weekend foot traffic", format="feed_post")
        assert b.format == "feed_post"

    def test_invalid_format_rejected(self):
        with pytest.raises(ValueError):
            PostBrief(product="Momo", goal="awareness", format="reel")


class TestCreativeNode:
    def _mock_caption(self) -> Caption:
        return Caption(
            caption="Hot Kurkure Momos — crispy outside, soft inside. 🥟 See you this evening.",
            hashtags=VALID_HASHTAGS,
            cta="See you this evening.",
            confidence=0.88,
        )

    def test_node_returns_asset(self):
        state = {
            "campaign_id": "test-001",
            "status": "draft",
            "brief": {"product": "Kurkure Momo", "goal": "awareness", "format": "feed_post"},
            "strategy": None,
            "creative_assets": [],
            "approved": False,
            "human_review_required": False,
            "confidence_score": 0.0,
            "brand_profile": {},
            "past_posts": [],
            "errors": [],
            "manual_publish_queue": [],
        }
        with patch("src.agents.creative.draft_caption", return_value=self._mock_caption()), \
             patch("src.agents.creative._render_post_image", return_value="https://img.test/x.jpg"):
            result = creative_node(state)

        assert len(result["creative_assets"]) == 1
        assert result["confidence_score"] == 0.88
        assert result["human_review_required"] is False

    def test_node_flags_low_confidence(self):
        low_conf = Caption(
            caption=VALID_CAPTION_FEED,
            hashtags=VALID_HASHTAGS,
            cta="See you.",
            confidence=CONFIDENCE_THRESHOLD - 0.1,
            review_reason="Uncertain tone.",
        )
        state = {
            "campaign_id": "test-002",
            "status": "draft",
            "brief": {"product": "Achari Momo", "goal": "traffic", "format": "carousel"},
            "strategy": None,
            "creative_assets": [],
            "approved": False,
            "human_review_required": False,
            "confidence_score": 0.0,
            "brand_profile": {},
            "past_posts": [],
            "errors": [],
            "manual_publish_queue": [],
        }
        with patch("src.agents.creative.draft_caption", return_value=low_conf), \
             patch("src.agents.creative._render_post_image", return_value="https://img.test/x.jpg"):
            result = creative_node(state)

        assert result["human_review_required"] is True
        assert result["creative_assets"][0]["review_reason"] == "Uncertain tone."

    def test_node_handles_invalid_brief(self):
        state = {
            "campaign_id": "test-003",
            "status": "draft",
            "brief": {"product": "Momo", "goal": "traffic", "format": "reel"},  # invalid format
            "strategy": None,
            "creative_assets": [],
            "approved": False,
            "human_review_required": False,
            "confidence_score": 0.0,
            "brand_profile": {},
            "past_posts": [],
            "errors": [],
            "manual_publish_queue": [],
        }
        result = creative_node(state)
        assert result["human_review_required"] is True
        assert len(result["errors"]) == 1


def _fanout_state(strategy=None, brief=None):
    return {
        "campaign_id": "camp-fan",
        "status": "draft",
        "brief": brief or {"product": "Momo", "goal": "awareness", "format": "feed_post"},
        "strategy": strategy,
        "creative_assets": [],
        "approved": False,
        "human_review_required": False,
        "confidence_score": 0.0,
        "brand_profile": {},
        "past_posts": [],
        "errors": [],
        "manual_publish_queue": [],
    }


_CAL = {
    "week_start": "2026-07-06",
    "goal": "foot_traffic",
    "posts": [
        {"day_offset": 0, "pillar": "product_spotlight", "format": "feed_post",
         "topic": "Achari Momo", "brief": "tangy evening", "variety": "Achari"},
        {"day_offset": 2, "pillar": "behind_the_scenes", "format": "feed_post",
         "topic": "Steamer in action", "brief": "prep shot", "variety": None},
        {"day_offset": 4, "pillar": "community", "format": "carousel",
         "topic": "Wagholi regulars", "brief": "local love", "variety": None},
    ],
}


class TestCreativeFanOut:
    def _cap(self, conf=0.9):
        return Caption(caption=VALID_CAPTION_FEED, hashtags=VALID_HASHTAGS,
                       cta="Come find us.", confidence=conf, image_prompt="momos")

    def test_fans_out_all_calendar_posts(self):
        with patch("src.agents.creative.draft_caption", return_value=self._cap()), \
             patch("src.agents.creative._render_post_image", return_value="https://img.test/x.jpg"):
            result = creative_node(_fanout_state(strategy=_CAL))
        assets = result["creative_assets"]
        assert len(assets) == 3
        assert [a["topic"] for a in assets] == ["Achari Momo", "Steamer in action", "Wagholi regulars"]
        assert [a["format"] for a in assets] == ["feed_post", "feed_post", "carousel"]
        assert assets[0]["variety"] == "Achari"

    def test_scheduled_at_follows_day_offset(self):
        with patch("src.agents.creative.draft_caption", return_value=self._cap()), \
             patch("src.agents.creative._render_post_image", return_value="https://img.test/x.jpg"):
            result = creative_node(_fanout_state(strategy=_CAL))
        dates = [a["scheduled_at"][:10] for a in result["creative_assets"]]
        assert dates == ["2026-07-06", "2026-07-08", "2026-07-10"]

    def test_empty_calendar_falls_back_to_single_brief(self):
        with patch("src.agents.creative.draft_caption", return_value=self._cap()), \
             patch("src.agents.creative._render_post_image", return_value="https://img.test/x.jpg"):
            result = creative_node(_fanout_state(strategy={"posts": []}))
        assert len(result["creative_assets"]) == 1
        assert result["creative_assets"][0]["topic"] == "Momo"

    def test_one_low_confidence_post_flags_review(self):
        caps = [self._cap(0.9), self._cap(0.5), self._cap(0.9)]
        with patch("src.agents.creative.draft_caption", side_effect=caps), \
             patch("src.agents.creative._render_post_image", return_value="https://img.test/x.jpg"):
            result = creative_node(_fanout_state(strategy=_CAL))
        assert result["human_review_required"] is True
        assert result["confidence_score"] == 0.5
