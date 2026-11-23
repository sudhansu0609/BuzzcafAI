# Posting reels to Instagram: setup

The Story Desk can post a packaged reel (`publish/instagram/`: `reel.mp4`
with its own audio, `cover.jpg`, `caption.txt`) straight to Instagram as a
Reel, on request ("Post to Instagram" on a record) or on a schedule after the
nightly batch, through the official Instagram API with Facebook Login
(Graph API). This needs a one-time setup per Instagram account, below.
Nothing posts until you do this: Auto Story's Instagram settings start
disconnected and auto-posting starts off.

Code: `backend/integrations/instagram_publish.py`. Settings page: **Settings
→ Instagram Reels**.

Settings are **named accounts**, not one slot per Studio channel, because a
channel can post to more than one Instagram account: Life3Baje's ordinary
reels and Life3Baje's **mood reels** (the no-face, calmer "good vibes"
format) are different content and go to different accounts. A **routing
table** decides which account a reel posts to, keyed by `"Channel"` or (when
it needs to be more specific) `"Channel/format"` -- the more specific route
always wins. Out of the box the Studio already has one route waiting for
you: `Life3Baje/mood_reel → khayal3bajefeels`. That account is simply
unconnected (no token) until you do the steps below and name the account you
connect `khayal3bajefeels` -- nothing posts there, or anywhere, before that.

## 1. Switch the Instagram account to Professional

In the Instagram app: **Profile → Menu (≡) → Settings and privacy → Account
type and tools → Switch to professional account**, then pick **Creator**
(or **Business** -- either works for the API). Follow the prompts; a
category can be anything.

## 2. Create or link a Facebook Page

Still in the Instagram app, during the same switch (or later under **Account
→ Linked accounts**), connect the professional account to a **Facebook
Page** you control. If you do not have one, Instagram offers to create one
for you -- accept that, it does not need to be public or promoted.

## 3. Create a Meta developer app

1. Go to **developers.facebook.com → My Apps → Create App**.
2. App type: **Business** (not Consumer).
3. Give it any name (e.g. "Buzzcaf Studio Publisher") and finish creation.
4. Note the **App ID** and **App Secret** (**Settings → Basic**) -- paste
   both into the Studio's Instagram Reels panel later. The app secret is
   needed to refresh the long-lived token automatically.

## 4. Add the Instagram Graph API product

In the app's dashboard, under **Add products**, add **Instagram Graph API**
(sometimes listed as **Instagram API with Facebook Login**). No extra setup
is needed on that product's own page; it just needs to be added so the app
is allowed to call it.

## 5. Generate a token in Graph API Explorer

1. Go to **developers.facebook.com/tools/explorer**.
2. Pick your app (top right) and the Facebook Page you connected (the
   "User or Page" dropdown).
3. Under **Permissions**, add: `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement`.
4. Click **Generate Access Token** and approve the permissions when Facebook
   asks (log in as the account that manages the Page if prompted).
5. Copy the token Explorer shows -- this is a **short-lived** token (about an
   hour), good enough for step 6.

## 6. Exchange it for a long-lived token

Short-lived tokens are not enough for an unattended Studio. Exchange it once
(this also tells you how long it will last):

```
https://graph.facebook.com/v21.0/oauth/access_token?
  grant_type=fb_exchange_token&
  client_id=<your App ID>&
  client_secret=<your App Secret>&
  fb_exchange_token=<the short-lived token from step 5>
```

Paste that URL into a browser or `curl` it. The response's `access_token` is
the **long-lived token** (about 60 days); that is what goes into the Studio.
The Studio refreshes it by itself (same exchange, with the saved App
ID/Secret) once it is under 10 days from expiring -- the Health page shows
"Token expires in N days" or "expired" if that ever needs your attention
(e.g. the app secret was removed).

## 7. Paste into the Studio, name the account, and route channels to it

1. Open **Settings → Instagram Reels**.
2. Paste the **App ID**, **App Secret** and the **long-lived token** from
   steps 3 and 6, then click **Discover accounts** -- this lists every
   Instagram professional account reachable from that token's Facebook
   Pages.
3. Next to the account you want, type a **name** for it and click **Save as
   account**. The name is yours to pick; it is what the routing table (next
   step) points at, not the Instagram handle. For Life3Baje's mood-reel
   account, name it `khayal3bajefeels` so the Studio's default route finds
   it; any other account (e.g. Life3Baje's own, Raat3Baje's) can be named
   anything, for instance the channel's own name.
4. Repeat for every Instagram account you have (one Meta app and one token
   can cover several, if the same Facebook user manages every Page).
5. Under **Accounts**, for each saved account set **Post times** (e.g.
   `19:30, 21:30`) and turn on **Auto-post nightly** if you want it to post
   the oldest unposted packaged reel in its queue by itself after the
   nightly batch.
6. Under **Routing**, point each channel (and, where it needs its own
   account, a channel/format pair) at the account that should post it --
   e.g. `Life3Baje → life3baje_main` and the already-present
   `Life3Baje/mood_reel → khayal3bajefeels`. A channel with no route at all
   stays unrouted: "Post to Instagram" stays disabled for it and the
   scheduler skips it.

The Story Desk's "Post to Instagram" button lights up once a record's
channel (and format) routes to a connected account; a record still lets you
post it by hand at any time, and posting a record once more after it
already has a permalink does nothing unless you force it.

## Troubleshooting

- **No `instagram_business_account` found for this page.** The Facebook Page
  is not actually linked to the Instagram account, or the account is not yet
  Professional. Redo steps 1-2; "Discover accounts" relies on that link.
- **Permissions missing / "Provide valid app ID".** Graph API Explorer did
  not actually grant one of the four permissions in step 5 (it silently
  drops one sometimes) -- regenerate the token and re-check every box before
  generating.
- **`(#10) This endpoint requires the 'pages_show_list' permission` or
  similar, or "the app is in development mode".** A Business app starts in
  **development mode**: it can only act for its own admins, developers and
  testers (**App roles → Roles** in the dashboard). That is enough for your
  own accounts -- just make sure the Facebook account that owns the Page and
  Instagram account is listed as an **Admin** of the app. You do **not** need
  to submit the app for Meta's App Review or switch it to "Live" to post to
  your own accounts this way.
- **Posting fails with a publishing-limit message.** Instagram allows 50
  published posts per account per 24 hours; the Studio checks this before
  every post and refuses with that message instead of wasting the call --
  try again after the window rolls over.
- **"No Instagram account is routed for ..." / the Story Desk button stays
  disabled.** That channel (or that channel/format pair) has no entry in the
  routing table yet, or its route points at an account you have not saved a
  token for. Add or fix the route under **Settings → Instagram Reels →
  Routing** -- remember the `Channel/format` route (if one exists) always
  wins over the plain `Channel` one, so check both.
