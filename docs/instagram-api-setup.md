# Instagram API Setup — Instagram Login path

How to enable Instagram publishing for this project using **Meta Developer tools**.

We use the **Instagram API with Instagram Login** (`graph.instagram.com`), *not* the
Facebook-Login Graph API (`graph.facebook.com`). This matters: the Facebook-Login path
routes through a linked Facebook Page, and Pages on the **New Pages Experience (NPE)**
reject user access tokens — a dead end. The Instagram Login path logs in *as the Instagram
account directly*, so **no Facebook Page is required** and NPE never enters the picture.

Token prefixes tell the paths apart: `EAA...` = Facebook-Login (NPE-blocked here);
`IGAA...` = Instagram-Login (what we want).

---

## Prerequisites

- An Instagram **Business or Creator** account (personal accounts have no API access).
- A Meta developer account at <https://developers.facebook.com>.

---

## Step 1 — Make the Instagram account Professional

Instagram app → **Settings → Account type and tools → Switch to professional account** →
choose **Business** (or Creator). Confirm the profile shows a Professional dashboard.

## Step 2 — Add the Instagram product to a Meta app

1. <https://developers.facebook.com> → **My Apps → Create App** (use case: *Other* →
   type *Business*), or open an existing app.
2. App dashboard → **Add Product** → **Instagram** → open the panel
   **"API setup with Instagram login"**.
3. Copy the **Instagram App ID** and **Instagram App Secret** shown there.
   > These are **distinct** from the app's Facebook App ID/Secret. Use the Instagram ones.

## Step 3 — Configure Business login settings

In the same panel → **Business login settings**:

- **OAuth redirect URI**: `https://localhost/` (exact match is enforced later; keep the
  trailing slash). For production, use a real HTTPS URL you control.
- **Scopes / permissions** requested by the app must include:
  - `instagram_business_basic`
  - `instagram_business_content_publish`
  - (optional) `instagram_business_manage_comments`,
    `instagram_business_manage_messages`, `instagram_business_manage_insights`

While the app is in **Development mode**, the app owner / added testers get all standard
scopes without App Review. Public use later requires App Review + Advanced Access.

## Step 4 — Get an authorization code

Open this URL in a browser (substitute your Instagram App ID), log in as the target
Instagram account, and approve:

```
https://www.instagram.com/oauth/authorize
  ?client_id=<INSTAGRAM_APP_ID>
  &redirect_uri=https://localhost/
  &response_type=code
  &scope=instagram_business_basic,instagram_business_content_publish
```

The browser redirects to `https://localhost/?code=XXXX...#_` (the page won't load — fine).
Copy the `code` value. **Strip the trailing `#_`.** The code is **single-use** and expires
in ~1 hour, so use it immediately in Step 5.

## Step 5 — Exchange code → short-lived token (+ real user ID)

```bash
curl -X POST https://api.instagram.com/oauth/access_token \
  -F client_id=<INSTAGRAM_APP_ID> \
  -F client_secret=<INSTAGRAM_APP_SECRET> \
  -F grant_type=authorization_code \
  -F redirect_uri=https://localhost/ \
  -F code=<CODE>
```

Response:

```json
{"access_token":"IGAA...","user_id":17841400000000000,
 "permissions":["instagram_business_basic","instagram_business_content_publish", ...]}
```

- `user_id` is your **real `IG_USER_ID`** (Instagram-scoped account ID).
  > Common trap: this is **not** the App ID. Using the App ID as `IG_USER_ID` makes every
  > call fail with "object does not exist."
- `permissions` confirms which scopes were actually granted.

`redirect_uri` must match Step 4 exactly. `"authorization code has been used/expired"`
→ redo Step 4 for a fresh code.

## Step 6 — Upgrade to a 60-day long-lived token

```bash
curl -s "https://graph.instagram.com/access_token\
?grant_type=ig_exchange_token\
&client_secret=<INSTAGRAM_APP_SECRET>\
&access_token=<SHORT_LIVED_TOKEN>"
```

Response: `{"access_token":"IGAA...","token_type":"bearer","expires_in":5184000}`
(~60 days). This is your `INSTAGRAM_ACCESS_TOKEN`.

## Step 7 — Validate

```bash
curl -s "https://graph.instagram.com/v22.0/<IG_USER_ID>\
?fields=user_id,username,account_type,media_count\
&access_token=<LONG_LIVED_TOKEN>"
```

Success looks like:

```json
{"user_id":"178414...","username":"voodoomomo","account_type":"BUSINESS",
 "media_count":0,"id":"17841400000000000"}
```

`username` matching the account = the full chain works.

---

## Put it in `.env`

```
INSTAGRAM_ACCESS_TOKEN=IGAA...        # 60-day token from Step 6
IG_USER_ID=17841400000000000          # from Step 5 (NOT the App ID)
META_APP_SECRET=<instagram_app_secret>
```

Never commit `.env`. `.env.example` holds placeholders only.

---

## Token refresh (before 60-day expiry)

Long-lived tokens last ~60 days and can be refreshed once they're **24h+ old**:

```bash
curl -s "https://graph.instagram.com/refresh_access_token\
?grant_type=ig_refresh_token&access_token=<CURRENT_LONG_LIVED_TOKEN>"
```

This project ships a helper — see `scripts/refresh_ig_token.py` — that calls
`src.tools.meta_graph.refresh_long_lived_token()` and prints the new token to paste into
`.env`. Run it on a monthly cron well before expiry.

---

## Publishing endpoints (reference)

All on `https://graph.instagram.com/v22.0`:

| Action | Call |
|---|---|
| Create media container | `POST /<IG_USER_ID>/media` (`image_url`, `caption`) |
| Poll container status | `GET /<container_id>?fields=status_code` |
| Publish container | `POST /<IG_USER_ID>/media_publish` (`creation_id`) — note `media_publish`, not `media/publish` |
| Media insights | `GET /<media_id>/insights?metric=...` |

> `image_url` must be a **public HTTPS JPEG** — Instagram's servers fetch it; you can't upload
> raw bytes. Host it on Supabase Storage (public bucket), S3/R2, or your VPS.

---

## Gotchas we hit (don't repeat)

1. **Wrong API path.** Started on the Facebook-Login Graph API (`graph.facebook.com`), whose
   Page hop is blocked by New Pages Experience. The Instagram-Login path
   (`graph.instagram.com`) needs no Page and isn't blocked. Token prefix is the tell:
   `EAA…` = Facebook-Login, `IGAA…` = Instagram-Login.
2. **App ID used as `IG_USER_ID`.** The real Instagram-scoped ID comes from the Step-5 token
   exchange response. Using the App ID gives "object does not exist" on every call.
3. **`media/publish` vs `media_publish`.** The publish endpoint is `media_publish` (no slash).
4. **Forgot to strip `#_`** from the redirected auth code.
5. **Auth code is single-use, ~1h.** Reusing or delaying it → "code has been used/expired";
   redo the authorize step for a fresh one.
6. **Secrets in `.env.example`.** Real token + IDs were pasted into the git-tracked
   `.env.example` (twice). Secrets go in `.env` (gitignored) only; `.env.example` is
   placeholders. Always check `git status`/`git diff` before committing.
