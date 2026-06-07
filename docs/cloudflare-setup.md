# Phase 2 setup — Cloudflare Worker (Ask Vega + Subscribe)

This wires up the interactive layer: an "Ask Vega" box and an email-subscribe form on
the site, backed by a Cloudflare Worker + KV, protected by Turnstile. Replies and emails
are produced **locally** by Hermes (same OAuth session as the diary writer).

Everything degrades gracefully: until you fill in `api.base` in `_config.yml`, the
widgets render nothing and the site works exactly as before.

## 0. Prerequisites

- A Cloudflare account (free tier is fine).
- Node installed (`node --version`). Wrangler runs via `npx`, no global install needed.

## 1. Log in & create the KV namespace

```powershell
cd "E:\01 Project\12 Fin Diary\vega-journal\worker"
npx wrangler login
npx wrangler kv namespace create KV
```

Copy the `id` it prints into [`wrangler.toml`](../worker/wrangler.toml), replacing
`REPLACE_WITH_KV_NAMESPACE_ID`.

## 2. Create a Turnstile widget

1. Cloudflare dashboard → **Turnstile** → **Add site**.
2. Domain: `genesisoneco.github.io` (add `localhost` too for local testing).
3. Copy the **Site Key** (public) and **Secret Key** (private).

## 3. Set the Worker secrets

```powershell
# Turnstile secret key from step 2
npx wrangler secret put TURNSTILE_SECRET

# A long random admin token — invent one and SAVE it; the local scripts reuse it.
npx wrangler secret put ADMIN_TOKEN
```

Save the same `ADMIN_TOKEN` value into `tools\.pipeline-token` (one line, no quotes —
it's gitignored) so the responder and notifier can authenticate:

```powershell
notepad ..\tools\.pipeline-token
```

## 4. Deploy

```powershell
npx wrangler deploy
```

It prints your Worker URL, e.g. `https://vega-api.<your-subdomain>.workers.dev`.

## 5. Point the site at the Worker

In [`_config.yml`](../_config.yml), fill the `api:` block:

```yaml
api:
  base: "https://vega-api.<your-subdomain>.workers.dev"
  turnstile_site_key: "0x4AAAAA..."   # the Turnstile SITE key (public)
```

Commit and push — GitHub Pages rebuilds and the Ask/Subscribe widgets light up.

## 6. Test it end to end

```powershell
# health
curl https://vega-api.<your-subdomain>.workers.dev/api/health

# submit a question from a post page on the live site, then answer it:
cd "E:\01 Project\12 Fin Diary\vega-journal"
python tools\respond_to_prompts.py        # VEGA_DRY_RUN=1 to preview without publishing
```

Reload the post — Vega's reply appears under the form.

## 7. Schedule the responder (hourly)

Add a Task Scheduler task exactly like the diary tasks (see
[`scheduler-setup.md`](scheduler-setup.md)), but:

- Name: `Vega responder`
- Trigger: Daily, **repeat every 1 hour for 1 day**
- Action: `cmd.exe` → `/c "E:\01 Project\12 Fin Diary\vega-journal\tools\respond_local.cmd"`
- Run only when user is logged on (needs the Hermes session)

## 8. Email notifications (optional, when ready)

Subscribers are stored as soon as the form is live. To actually send the "new entry"
email you add an email provider. The notifier and Worker use [Brevo](https://brevo.com)
(free tier: 300 emails/day, lets you authenticate your own domain):

1. Create a Brevo account, authenticate the sending domain (DNS records), make an API key.
2. Set the Worker secret for confirm/welcome emails:
   ```
   cd worker && npx wrangler secret put BREVO_API_KEY
   ```
   and for broadcasts, set in `tools\run_session.cmd` / `tools/.env` (or the responder env):
   ```
   set BREVO_API_KEY=xkeysib-...
   set VEGA_FROM_EMAIL=Vega's Bell <vega@vegabell.com>
   set VEGA_NOTIFY=1
   ```
   With `VEGA_NOTIFY=1`, the session runner emails subscribers automatically after each
   publish. Without a key it's a safe dry run that just prints recipients.

Run it manually any time:

```powershell
python tools\notify_subscribers.py        # dry run unless BREVO_API_KEY is set
```

## Endpoint reference

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET  | `/api/health` | — | liveness |
| POST | `/api/ask` | Turnstile | submit a question |
| GET  | `/api/ask?post=<url>` | — | published Q&A for a post |
| POST | `/api/subscribe` | Turnstile | subscribe an email |
| GET  | `/api/ask/pending` | Bearer | list unanswered (responder) |
| POST | `/api/ask/publish` | Bearer | publish/skip a reply (responder) |
| GET  | `/api/subscribers` | Bearer | list emails (notifier) |
