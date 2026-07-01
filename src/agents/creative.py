from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from src.llm import complete, extract_json
from src.memory.brand_memory import upload_image
from src.schemas import PostAsset
from src.state import AgentState
from src.tools.image_gen import generate_image
from src.tracing import observe

_log = logging.getLogger(__name__)

# Mascot reference for character-consistent brand imagery; only fed to the image
# model for personality/community posts (see _render_post_image).
_MASCOT_REF = Path(__file__).resolve().parents[2] / "assets" / "brand" / "mascot-panda.jpeg"

# Appended to every image prompt so generated photos stay on-brand. Hard rules:
# momos are the hero, NO people, and the background is the Voodoo Momo palette.
_IMAGE_STYLE_ANCHOR = (
    "The momos are the sole hero of the shot. ABSOLUTELY NO people, no hands, no human "
    "figures, no crowds, no diners in frame or background. Background is a clean, styled "
    "surface and backdrop in the Voodoo Momo brand palette — warm gold, deep red, and "
    "orange — with subtle Himalayan warmth (prayer-flag colours, temple-gate tones), "
    "never a busy restaurant or street scene. Street-food styling, appetising, natural "
    "steam, shallow depth of field. No text, captions, or logos in the image."
)

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

Menu (31 varieties across 4 categories — use for specificity):
Veg: Steam, Fry, Butter Grill, Tandoori, Peri Peri, Chilly, Kurkure, Choila, Achari
Paneer: Steam, Fry, Butter Grill, Tandoori, Peri Peri, Chilly, Kurkure, Choila, Achari
Chicken: Steam, Fry, Butter Grill, Tandoori, Peri Peri, Chilly, Kurkure, Choila, Achari
Cheese Corn: Steam, Fry, Peri-Peri, Kurkure

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
  "image_prompt": "<vivid, specific description of the photo to generate: the dish, framing, mood. Keep the momos the hero with a clean background in the brand palette (warm gold/deep red/orange). NEVER include people, hands, or crowds. Mention the panda mascot ONLY for personality/community posts — never force it into a plain product shot>",
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
            "image_prompt": "Close-up, top-down of steaming Achari momos in a dark ceramic bowl, tangy spiced glaze, fresh steam rising, warm evening light on a rustic wooden table",
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
                "31 varieties. One Wagholi kitchen.\n"
                "Whether it's an after-college craving or a rainy evening comfort, "
                "we've got the momo for the moment.\nWhat's your go-to? 🌶️"
            ),
            "hashtags": [
                "#VoodooMomo", "#PuneSpecialtyMomo", "#WagholiEats",
                "#MomoLovers", "#HimalayanFood", "#MomoTime", "#PuneFood", "#StreetFoodPune",
            ],
            "cta": "What's your go-to?",
            "image_prompt": "Overhead spread of many momo varieties on rustic plates — steamed, fried, tandoori — a vibrant assortment with dipping sauces, cozy Himalayan-style table setting",
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
    image_prompt: str | None = None
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


@observe(name="draft_caption")
def draft_caption(brief: PostBrief) -> Caption:
    """Draft a caption (LLM pass); retry up to MAX_RETRIES on validation failure."""
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

        last_raw = complete(
            system=_SYSTEM_PROMPT,
            messages=messages,
            model=_DRAFT_MODEL,
            max_tokens=512,
        ).strip()

        try:
            data = json.loads(extract_json(last_raw))
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


def _render_post_image(image_prompt: str, post_id: str) -> str:
    """Generate the post image via the configured provider and upload it as a public JPEG; return its URL.

    The mascot reference is fed only when the prompt actually calls for the panda, so
    plain product shots aren't forced to include him. Raises on any failure — a missing
    image must stop the publish, never ship silently.
    """
    prompt = f"{image_prompt}. {_IMAGE_STYLE_ANCHOR}"
    wants_mascot = any(w in image_prompt.lower() for w in ("panda", "mascot"))
    refs = [str(_MASCOT_REF)] if wants_mascot and _MASCOT_REF.is_file() else None

    out = Path(tempfile.gettempdir()) / f"{post_id}.jpg"
    try:
        generate_image(prompt, str(out), reference_paths=refs)
        return upload_image(str(out))
    finally:
        out.unlink(missing_ok=True)


def _fallback_image_prompt(brief: PostBrief) -> str:
    return f"{brief.product}, close-up, fresh and steaming, appetising street-food styling"


def creative_node(state: AgentState) -> AgentState:
    """Drafts one caption + generates the post image for the brief in state."""
    brief_data = state.get("brief", {})
    errors = list(state.get("errors", []))

    try:
        brief = PostBrief(**brief_data)
    except ValueError as exc:
        return {
            **state,
            "errors": errors + [f"Invalid post brief: {exc}"],
            "human_review_required": True,
            "confidence_score": 0.0,
        }

    caption = draft_caption(brief)

    # Never downgrade an upstream review flag (e.g. a degraded strategy run).
    needs_review = caption.confidence < CONFIDENCE_THRESHOLD or state.get("human_review_required", False)
    post = PostAsset(
        campaign_id=state.get("campaign_id", ""),
        format=brief.format,
        topic=brief.product,
        variety=brief.variety,
        caption=caption.caption,
        hashtags=caption.hashtags,
        cta=caption.cta,
        image_prompt=caption.image_prompt,
        confidence=caption.confidence,
        approval_status="draft" if needs_review else "pending_approval",
    )
    asset = post.model_dump(mode="json")
    if caption.review_reason:
        asset["review_reason"] = caption.review_reason

    image_prompt = caption.image_prompt or _fallback_image_prompt(brief)
    try:
        asset["image_url"] = _render_post_image(image_prompt, post.post_id)
    except Exception as exc:  # external boundary: surface, flag for review, never ship blind
        _log.warning("Image generation failed for %s: %s", post.post_id, exc)
        errors.append(f"{post.post_id}: image generation failed — {exc}; flagged for human review")
        needs_review = True

    return {
        **state,
        "creative_assets": [asset],
        "confidence_score": caption.confidence,
        "human_review_required": needs_review,
        "errors": errors,
    }
