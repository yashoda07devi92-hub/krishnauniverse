# One-time token setup — browser only, no terminal

The two maintenance buttons in the Actions tab —
**Fix Old Video Titles** and **Slot Report** — need a token the daily upload
token does not provide.

**Why a second token:** a Google token carries a *scope*, a list of what it is
allowed to do. `YT_TOKEN_JSON` has the `youtube.upload` scope, so it can publish
videos and nothing else. Editing an existing video's title, or reading your own
channel's view statistics, requires `youtube.force-ssl`. That is a genuinely more
powerful scope — it can also delete videos — which is why it is kept separate and
only used by manual, button-triggered jobs.

You never need a terminal. Everything below happens in the browser, once.

---

## Step 1 — allow the OAuth Playground to use your credentials

1. Open [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials)
2. Make sure the project selected at the top is the one this channel uses
3. Under **OAuth 2.0 Client IDs**, click your existing client
4. Under **Authorised redirect URIs**, click **ADD URI** and paste exactly:
   ```
   https://developers.google.com/oauthplayground
   ```
5. **SAVE**
6. Keep this tab open — you need the **Client ID** and **Client secret** shown on
   the right in a moment

> Changes to redirect URIs can take a few minutes to take effect. If step 3 below
> gives a `redirect_uri_mismatch` error, wait five minutes and retry.

---

## Step 2 — publish the consent screen (do not skip this)

1. Go to **APIs & Services → OAuth consent screen**
2. If the **Publishing status** says *Testing*, click **PUBLISH APP** and confirm

**Why this matters:** while the consent screen is in Testing mode, Google expires
every refresh token after **7 days**. Your buttons would work for a week and then
start failing with `invalid_grant`. In Production the token keeps working
indefinitely. This is the single most common reason these setups break.

---

## Step 3 — mint the token

1. Open the [Google OAuth 2.0 Playground](https://developers.google.com/oauthplayground/)
2. Click the **gear icon** (⚙) at the top right
3. Tick **Use your own OAuth credentials**
4. Paste your **Client ID** and **Client secret** from Step 1
5. Close the gear panel
6. In the box on the left labelled *Input your own scopes*, paste exactly:
   ```
   https://www.googleapis.com/auth/youtube.force-ssl
   ```
7. Click **Authorize APIs**
8. Sign in with **the Google account that owns the Sweet Soul Stories channel** —
   not any other account — and click through the permission screens
9. Back in the Playground, click **Exchange authorization code for tokens**
10. On the right you will now see a JSON response. Copy the value of
    **`refresh_token`** and the value of **`access_token`**

---

## Step 4 — assemble the secret

Paste the four values into this template. Keep the quotes and the commas exactly
as shown:

```json
{
  "token": "PASTE_ACCESS_TOKEN_HERE",
  "refresh_token": "PASTE_REFRESH_TOKEN_HERE",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "PASTE_CLIENT_ID_HERE",
  "client_secret": "PASTE_CLIENT_SECRET_HERE",
  "scopes": ["https://www.googleapis.com/auth/youtube.force-ssl"],
  "universe_domain": "googleapis.com"
}
```

The `access_token` expires in an hour, which is fine — the scripts use the
`refresh_token` to mint a new one automatically every run. It just has to be
present and valid JSON the first time.

---

## Step 5 — store it in GitHub

1. Open the repository → **Settings**
2. **Secrets and variables → Actions**
3. **New repository secret**
4. Name — exactly this, it is case sensitive:
   ```
   YT_MANAGE_TOKEN_JSON
   ```
5. Secret — the whole JSON block from Step 4
6. **Add secret**

---

## Step 6 — check it works

1. Repository → **Actions**
2. Left sidebar → **Slot Report (which upload time actually works)**
3. **Run workflow** → leave the defaults → **Run workflow**
4. Open the run and read the log

Slot Report is read-only, so it is the safe way to confirm the token before
touching anything. If it prints a table of publish hours and view counts, the
token is good.

Then, and only then, use **Fix Old Video Titles** — and run it in `dry-run` mode
first.

---

## If something goes wrong

| Error | Cause | Fix |
|---|---|---|
| `Secret YT_MANAGE_TOKEN_JSON is not set` | Secret missing or misspelled | Re-check the name in Step 5; it is case sensitive |
| `redirect_uri_mismatch` | Step 1 not saved, or not yet propagated | Confirm the URI has no trailing slash, wait 5 minutes |
| `invalid_grant` | Consent screen still in Testing, so the refresh token expired | Do Step 2, then redo Step 3 |
| `insufficientPermissions` | Token was minted with the wrong scope | Redo Step 3 and check the scope string carefully |
| `403 quotaExceeded` | The day's 10,000 API units are spent | Wait for the reset at midnight US Pacific, then use a smaller `limit` |
| Signed in as the wrong account | Token belongs to a different channel | Sign out of Google entirely, redo Step 3 |

---

## Security notes

- This token can edit and delete videos on the channel. Treat it like a password.
- It lives only in GitHub Secrets, which are encrypted and are never printed in
  workflow logs. Both maintenance workflows check that the secret exists without
  ever echoing its value.
- The scheduled reel and long-form workflows do **not** use this token — they keep
  using the narrower upload-only one. Only the two manual buttons touch it.
- To revoke it at any time: [Google Account → Third-party access](https://myaccount.google.com/connections)
