from __future__ import annotations

import json
import os
from typing import Literal

import anthropic
from pydantic import BaseModel, field_validator, model_validator

from src.state import AgentState

CONFIDENCE_THRESHOLD = 0.7
MAX_RETRIES = 2

BANNED_PHRASES = [
    "best momos in pune",
    "best momos in india",
    "best momos in the world",
    "best momos",
    "you deserve",
    "indulge yourself",
    "game-changer",
    "life-changing",
    "mind-blowing",
]

BANNED_HASHTAGS = {"#love", "#instagood", "#follow", "#foodphotography", "#foodie"}

CORE_HASHTAGS = {"#voodoomomo", "#punespecialtymomo", "#wagholieats"}

PostFormat = Literal["feed_post", "carousel"]

_CAPTION_LENGTH = {"feed_post": (80, 150), "carousel": (200, 280)}

# Model IDs per stack decision: Haiku for drafts, Sonnet for review passes
_DRAFT_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = """You are the social media voice for Voodoo Momo, a specialty momo shop at Nyati Commercial, near JSPM College, Wagholi, Pune. Instagram: @voodoomomo.

Brand identity:
- Tagline: "Taste the Himalayan Magic!"
- Mascot: a cool panda wearing sunglasses, eating momos — embody his swagger when humour fits
- Tone: warm, fun, street-style — approachable with a cool edge; NOT a polished café chain
- POV: first person "we" throughout
- Voice pillars: Inviting, Honest, Local, Playful

Varieties on menu (use for specificity): Achari, Choila, Pan-fried, Kurkure, Chilly.

Caption length:
- feed_post: 80–150 characters
- carousel: 200–280 characters

Style rules:
- Short declarative sentences
- Max 1 exclamation mark per post
- Emoji: max 3, use only from 🥟 🌶️ 🐼 🌿
- Always end with a soft invite CTA (e.g. "Come say hello." / "See you this evening." / "What's your pick?")
- Reference Wagholi, the neighbourhood, or the college crowd when it fits naturally

Hashtag rules (strict):
- Total count: 8–12
- ALWAYS include: #VoodooMomo #PuneSpecialtyMomo #WagholiEats
- Never use: #Love #Instagood #Follow #FoodPhotography #Foodie

Banned phrases (hard block — never output these):
- "best momos in [anywhere]"
- "you deserve"
- "indulge yourself"
- "game-changer", "life-changing", "mind-blowing"
- All-caps words, multiple exclamation marks

Output JSON ONLY — no prose, no markdown fences, just the raw JSON object:
{
  "caption": "<string>",
  "hashtags": ["<#tag>", ...],
  "cta": "<single soft-invite string, also appears at the end of caption>",
  "confidence": <float 0.0–1.0>
}
If confidence < 0.7, add: "review_reason": "<brief explanation of uncertainty>"
"""

_FEW_SHOT: list[dict] = [
    {
        "role": "user",
        "content": "Brief: product=Achari Momo, goal=drive evening foot traffic, format=feed_post",
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "caption": "Steaming hot. Made fresh. Achari or Choila — you pick. 🥟\nCome find us in Wagholi this evening.",
            "hashtags": [
                "#VoodooMomo", "#WagholiEats", "#PuneSpecialtyMomo",
                "#AchariMomo", "#ChoilaMomo", "#MomoTime", "#PuneFood", "#StreetFoodPune",
            ],
            "cta": "Come find us in Wagholi this evening.",
            "confidence": 0.92,
        }),
    },
    {
        "role": "user",
        "content": "Brief: product=full momo variety showcase, goal=new follower awareness, format=carousel",
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "caption": (
                "20 varieties. One Wagholi kitchen.\n"
                "Whether it's an after-college craving or a rainy evening comfort, "
                "we've got the momo for the moment.\nWhat's your go-to? 🌶️"
            ),
            "hashtags": [
                "#VoodooMomo", "#PuneSpecialtyMomo", "#WagholiEats",
                "#MomoLovers", "#HimalayanFood", "#MomoTime", "#PuneFood", "#StreetFoodPune",
            ],
            "cta": "What's your go-to?",
            "confidence": 0.88,
        }),
    },
]


class PostBrief(BaseModel):
    product: str
    goal: str
    format: PostFormat
    variety: str | None = None


class Caption(BaseModel):
    caption: str
    hashtags: list[str]
    cta: str
    confidence: float
    review_reason: str | None = None

    @field_validator("caption")
    @classmethod
    def check_length(cls, v: str) -> str:
        if len(v) > 2200:
            raise ValueError(f"caption too long: {len(v)} chars (max 2200)")
        return v

    @field_validator("hashtags")
    @classmethod
    def check_hashtags(cls, v: list[str]) -> list[str]:
        if not (8 <= len(v) <= 12):
            raise ValueError(f"hashtag count {len(v)} out of range — need 8–12")
        banned = [h for h in v if h.lower() in BANNED_HASHTAGS]
        if banned:
            raise ValueError(f"banned hashtags present: {banned}")
        missing_core = [t for t in CORE_HASHTAGS if t not in {h.lower() for h in v}]
        if missing_core:
            raise ValueError(f"missing required core hashtags: {missing_core}")
        return v

    @field_validator("confidence")
    @classmethod
    def check_confidence_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be 0.0–1.0")
        return v

    @model_validator(mode="after")
    def check_banned_phrases(self) -> "Caption":
        lower = self.caption.lower()
        for phrase in BANNED_PHRASES:
            if phrase in lower:
                raise ValueError(f"banned phrase in caption: '{phrase}'")
        return self


def draft_caption(brief: PostBrief) -> Caption:
    """Call Claude Haiku to draft a caption; retry up to MAX_RETRIES on validation failure."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    messages: list[dict] = list(_FEW_SHOT) + [
        {
            "role": "user",
            "content": (
                f"Brief: product={brief.product}, goal={brief.goal}, format={brief.format}"
                + (f", variety={brief.variety}" if brief.variety else "")
            ),
        }
    ]

    last_error: str | None = None
    last_raw: str = ""

    for attempt in range(MAX_RETRIES + 1):
        if last_error:
            # Inject the failed attempt + repair instruction before retrying
            messages = messages + [
                {"role": "assistant", "content": last_raw},
                {
                    "role": "user",
                    "content": (
                        f"That output failed validation with error: {last_error}\n"
                        "Fix ONLY the failing part and return valid JSON only — no extra text."
                    ),
                },
            ]

        response = client.messages.create(
            model=_DRAFT_MODEL,
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )

        last_raw = response.content[0].text.strip()

        try:
            data = json.loads(last_raw)
            return Caption(**data)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = str(exc)

    # All attempts exhausted — return a zero-confidence sentinel for human review
    return Caption(
        caption="[CAPTION DRAFT FAILED — HUMAN REVIEW REQUIRED]",
        hashtags=[
            "#VoodooMomo", "#PuneSpecialtyMomo", "#WagholiEats",
            "#PuneFood", "#MomoLovers", "#WagholiFood", "#MomoTime", "#StreetFoodPune",
        ],
        cta="See you this evening.",
        confidence=0.0,
        review_reason=f"All {MAX_RETRIES + 1} attempts failed validation. Last error: {last_error}",
    )


def creative_node(state: AgentState) -> AgentState:
    """Drafts one caption for the brief in state. Phase 1 entry point."""
    brief_data = state.get("brief", {})

    try:
        brief = PostBrief(**brief_data)
    except ValueError as exc:
        return {
            **state,
            "errors": state.get("errors", []) + [f"Invalid post brief: {exc}"],
            "human_review_required": True,
            "confidence_score": 0.0,
        }

    caption = draft_caption(brief)

    asset: dict = {
        "caption": caption.caption,
        "hashtags": caption.hashtags,
        "cta": caption.cta,
        "confidence": caption.confidence,
    }
    if caption.review_reason:
        asset["review_reason"] = caption.review_reason

    return {
        **state,
        "creative_assets": [asset],
        "confidence_score": caption.confidence,
        "human_review_required": caption.confidence < CONFIDENCE_THRESHOLD,
    }
