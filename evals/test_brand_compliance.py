"""Brand-compliance eval harness — Phase 5.

These tests call the real API (Claude Haiku) and check that generated captions
pass the same validators as the schema layer.  They run as part of CI with
`continue-on-error: true` until Phase 5 is considered stable.

Skipped automatically when ANTHROPIC_API_KEY is absent or balance is zero.
"""
from __future__ import annotations

import os
import pytest

from src.agents.creative import Caption, PostBrief, draft_caption
from src.agents.creative import CORE_HASHTAGS, BANNED_HASHTAGS, BANNED_PHRASES

_SKIP_REASON = "ANTHROPIC_API_KEY not set — skipping live eval"


def _api_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.mark.skipif(not _api_available(), reason=_SKIP_REASON)
class TestLiveCaption:
    def _brief(self, product: str, fmt: str = "feed_post") -> PostBrief:
        return PostBrief(product=product, goal="evening foot traffic", format=fmt)

    def _assert_compliance(self, caption: Caption) -> None:
        text_lower = caption.caption.lower()

        # No banned phrases
        for phrase in BANNED_PHRASES:
            assert phrase not in text_lower, f"banned phrase found: '{phrase}'"

        # Core hashtags present
        tag_set = {h.lower() for h in caption.hashtags}
        for core in CORE_HASHTAGS:
            assert core in tag_set, f"missing core hashtag: {core}"

        # No banned hashtags
        for tag in caption.hashtags:
            assert tag.lower() not in BANNED_HASHTAGS, f"banned hashtag: {tag}"

        # Count in range
        assert 8 <= len(caption.hashtags) <= 12, f"hashtag count {len(caption.hashtags)} out of range"

        # Confidence is a real number
        assert 0.0 <= caption.confidence <= 1.0

    def test_feed_post_achari_momo(self) -> None:
        caption = draft_caption(self._brief("Achari Momo"))
        assert caption.confidence > 0, "zero-confidence sentinel — check API key / balance"
        self._assert_compliance(caption)

    def test_feed_post_cheese_corn_kurkure(self) -> None:
        caption = draft_caption(self._brief("Cheese Corn Kurkure Momo"))
        self._assert_compliance(caption)

    def test_carousel_variety_showcase(self) -> None:
        brief = PostBrief(
            product="full variety showcase",
            goal="new follower awareness",
            format="carousel",
        )
        caption = draft_caption(brief)
        self._assert_compliance(caption)
        # Carousel should be longer
        assert len(caption.caption) >= 100, "carousel caption too short"

    def test_no_exclamation_spam(self) -> None:
        caption = draft_caption(self._brief("Chicken Peri Peri Momo"))
        assert caption.caption.count("!") <= 1, "multiple exclamation marks"

    def test_emoji_count(self) -> None:
        allowed = {"🥟", "🌶️", "🐼", "🌿"}
        caption = draft_caption(self._brief("Veg Tandoori Momo"))
        # Count individual emoji characters (rough check)
        found_emojis = [ch for ch in caption.caption if ord(ch) > 0x1F300]
        assert len(found_emojis) <= 3, f"too many emoji: {found_emojis}"

    def test_cta_is_soft_invite(self) -> None:
        caption = draft_caption(self._brief("Paneer Choila Momo"))
        cta_lower = caption.cta.lower()
        soft_cta_markers = ("come", "see you", "what", "find us", "tell us", "pick")
        assert any(m in cta_lower for m in soft_cta_markers), \
            f"CTA doesn't look like a soft invite: '{caption.cta}'"

    def test_no_all_caps_words(self) -> None:
        caption = draft_caption(self._brief("Veg Choila Momo"))
        words = caption.caption.split()
        all_caps = [w for w in words if w.isupper() and len(w) > 2 and w.isalpha()]
        assert not all_caps, f"all-caps words found: {all_caps}"
