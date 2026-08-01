# Google Cloud setup required before W-CAL can work in production

Everything below is read from the deployed configuration and the production database, not assumed.

## 0. Which project / client to open

| | |
|---|---|
| GCP project number | **311800663906** |
| OAuth client ID | **311800663906-dr1q62…….apps.googleusercontent.com** |
| Client type | Web application (server-side code flow) |

## 1. Enable this API — **this is the one that breaks at runtime if missed**

**APIs & Services → Library**

| API | Status | Needed for |
|---|---|---|
| **Google Calendar API** | **MUST ENABLE — new** | `calendar.events` insert, `calendars().get` (timezone), `freebusy().query` |
| Gmail API | already enabled | `gmail.modify` / `send` / `labels` — proven working, mail syncs today |

A granted scope with the API disabled does **not** fail at consent — it fails later, per call, with
`403 accessNotConfigured` / *"Google Calendar API has not been used in project 311800663906 before
or it is disabled"*. That is exactly the runtime error class you want gone, so enable it first.

## 2. OAuth consent screen → Data access → Add or remove scopes

Add the **one** new scope. The other six are already granted in production (verified against the
`GmailAccount.scopes` column) and must be left in place.

| # | Scope (paste exactly) | Google tier | State |
|---|---|---|---|
| 1 | `https://www.googleapis.com/auth/calendar.events` | **Sensitive** | **ADD THIS** |
| 2 | `https://www.googleapis.com/auth/gmail.modify` | Restricted | already granted |
| 3 | `https://www.googleapis.com/auth/gmail.send` | Restricted | already granted |
| 4 | `https://www.googleapis.com/auth/gmail.labels` | Sensitive | already granted |
| 5 | `openid` | — | already granted |
| 6 | `https://www.googleapis.com/auth/userinfo.email` | — | already granted |
| 7 | `https://www.googleapis.com/auth/userinfo.profile` | — | already granted |

`calendar.events` (not full `calendar`) is deliberate: it grants events access without read/write
over calendar settings and sharing. Do not substitute the broader scope — the code requests exactly
this string, and Google returns only what was requested.

## 3. Credentials → the OAuth client → Authorized redirect URIs

Must match **byte-for-byte**, including scheme, host, path and absence of a trailing slash:

```
https://5cb5f0620.abacusai.cloud/api/auth/google/callback
```

This is the value of `GOOGLE_OAUTH_REDIRECT_URI` actually loaded by the running API process (I read
it from `/proc/<pid>/environ`, not just the `.env` file). A mismatch produces
`Error 400: redirect_uri_mismatch` at consent time.

*Optional:* this VM also serves `aether-brand.abacusai.cloud`. Only add
`https://aether-brand.abacusai.cloud/api/auth/google/callback` if you intend to move the app there —
the backend only ever sends the URI above.

**Authorized JavaScript origins: leave empty.** This is a server-side code flow; no browser-side
token exchange happens, so an origin entry is not required.

## 4. Publishing status — read this before onboarding paying users

**Audience** (formerly "Publishing status") governs how long consent lasts:

* **Testing** — refresh tokens are **revoked by Google after 7 days**, so every user silently drops
  to a broken connection roughly weekly no matter what the app does. Also capped at 100 named test
  users, each of whom must be listed individually. If the app is in Testing, that alone will
  reproduce "reconnect your Google account" forever, and no amount of application-side work fixes it.
* **In production** — refresh tokens persist. But `gmail.modify` and `gmail.send` are **Restricted**
  scopes, so an external-facing production app needs Google verification **plus an annual CASA
  security assessment**. Until verified, users see the "Google hasn't verified this app" interstitial
  and the app is capped at 100 users.

Since real paying users are being onboarded, this is a launch dependency, not a detail: verification
review takes days-to-weeks. Worth starting now, in parallel.

## 5. Current production state (facts, for comparison after you change it)

* 2 Gmail accounts connected: `sarkar.vikram@gmail.com`, `melbvicduque@gmail.com`
* Both hold refresh tokens (`refreshTokenCipher` populated) and `syncStatus = 'synced'`
* Granted scopes today: `gmail.modify`, `gmail.send`, `gmail.labels`, `userinfo.email`,
  `userinfo.profile` — **no `calendar.events`**, as expected
* `GoogleCredential` table is empty; Google tokens live on `GmailAccount`

Because the app uses **incremental authorization** (`include_granted_scopes=true`), reconnecting
after you add the scope **adds** calendar to the existing grant rather than replacing it — Gmail
keeps working throughout.

## 6. What I will verify once you say it is done

1. The generated consent URL contains `calendar.events` **and** `include_granted_scopes=true`.
2. A full OAuth round trip completes with no `redirect_uri_mismatch` and no `invalid_scope`.
3. Persisted scopes equal what Google **actually granted**, not what was requested (this is the
   fabrication guard W-CAL built — a declined calendar tick must persist as *not granted*).
4. Declining calendar still leaves Gmail fully working (the oauthlib scope-change trap).
5. An interview creates a **real** Calendar event and returns a confirmable event id.
6. Free/busy returns real availability.
7. Settings shows a truthful connection + scope status.
8. Zero `ERROR`/`Traceback`/5xx in `aether-api` logs across the whole exercise — including no
   `accessNotConfigured`, which is what a missed step 1 looks like.
