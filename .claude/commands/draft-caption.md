Draft a single Instagram caption from a post brief.

**Usage:** `/draft-caption <brief>`

**Example:** `/draft-caption oat milk flat white, goal: drive weekend foot traffic, format: carousel`

Produce JSON matching this schema exactly — no prose outside the object:

```json
{
  "caption": "<string, ≤ 2200 chars, brand voice, 1 on-brand emoji max>",
  "hashtags": ["<5–10 relevant tags>"],
  "cta": "<one clear call to action>",
  "confidence": "<float 0–1>"
}
```

Apply brand voice from @docs/brand-voice.md.
If confidence < 0.7, add a `"review_reason"` field explaining what is uncertain.
