#!/usr/bin/env python3
"""notify_subscribers.py — email the latest entry to subscribers (runs locally).

Pulls the subscriber list from the Worker admin endpoint and emails them a link to
the newest post. Email delivery is pluggable: if RESEND_API_KEY is set it sends via
Resend; otherwise it runs as a dry run and just prints what it would send — so the
feature is wired end to end and you only add a provider key when you're ready.

It records the last-notified post in tools/.last_notified so re-runs don't double-send.

Config (env):
    VEGA_API_BASE / VEGA_ADMIN_TOKEN   as in respond_to_prompts.py
    RESEND_API_KEY   optional; enables real sending
    VEGA_FROM_EMAIL  e.g. "Vega <vega@yourdomain.com>" (required to actually send)
    VEGA_DRY_RUN     force dry run even if a key is present
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
POSTS = ROOT / "_posts"
STATE = TOOLS / ".last_notified"

RESEND_KEY = os.environ.get("RESEND_API_KEY", "").strip()
FROM = os.environ.get("VEGA_FROM_EMAIL", "Vega <onboarding@resend.dev>")
DRY = bool(os.environ.get("VEGA_DRY_RUN")) or not RESEND_KEY


def cfg(key, default=""):
    m = re.search(rf"^\s*{key}:\s*\"?([^\"\n]+)\"?", (ROOT / "_config.yml").read_text(encoding="utf-8"), re.MULTILINE)
    return m.group(1).strip() if m else default


def api_base():
    return (os.environ.get("VEGA_API_BASE") or cfg("base")).rstrip("/")


def admin_token():
    tok = os.environ.get("VEGA_ADMIN_TOKEN", "").strip()
    if not tok and (TOOLS / ".pipeline-token").exists():
        tok = (TOOLS / ".pipeline-token").read_text(encoding="utf-8").strip()
    if not tok:
        sys.exit("[error] no admin token (VEGA_ADMIN_TOKEN or tools/.pipeline-token).")
    return tok


def latest_post():
    files = sorted(POSTS.glob("*.md"))
    if not files:
        sys.exit("[error] no posts found.")
    f = files[-1]
    text = f.read_text(encoding="utf-8")
    title = (re.search(r'^title:\s*"?(.+?)"?\s*$', text, re.MULTILINE) or [None, f.stem])[1]
    desc = (re.search(r'^description:\s*"?(.+?)"?\s*$', text, re.MULTILINE) or [None, ""])[1]
    # Build the post URL from filename + permalink (/:year/:month/:day/:title/).
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})-(.+)\.md$", f.name)
    base_url = cfg("url").rstrip("/") + cfg("baseurl")
    url = f"{base_url}/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}/" if m else base_url
    return f.name, title, desc, url


def get_subscribers(base, token):
    req = urllib.request.Request(base + "/api/subscribers",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or "{}").get("items", [])


def send_resend(to_email, subject, html):
    body = json.dumps({"from": FROM, "to": [to_email], "subject": subject, "html": html}).encode()
    req = urllib.request.Request("https://api.resend.com/emails", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {RESEND_KEY}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status in (200, 201)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    fname, title, desc, url = latest_post()
    if STATE.exists() and STATE.read_text(encoding="utf-8").strip() == fname:
        print(f"[skip] already notified for {fname}.")
        return

    base, token = api_base(), admin_token()
    subs = [s["email"] for s in get_subscribers(base, token) if s.get("email")]
    if not subs:
        print("No subscribers.")
        STATE.write_text(fname, encoding="utf-8")
        return

    subject = f"Vega: {title}"
    html = (f'<p>New entry from Vega:</p>'
            f'<h2><a href="{url}">{title}</a></h2>'
            f'<p>{desc}</p>'
            f'<p><a href="{url}">Read it →</a></p>'
            f'<hr><p style="font-size:12px;color:#888">Automated commentary, not financial advice.</p>')

    print(f"[*] latest: {title}\n[*] {len(subs)} subscribers; "
          f"{'DRY RUN (no RESEND_API_KEY)' if DRY else 'sending via Resend'}.")
    sent = 0
    for email in subs:
        if DRY:
            print(f"  would email: {email}")
            continue
        try:
            if send_resend(email, subject, html):
                sent += 1
        except urllib.error.HTTPError as e:
            sys.stderr.write(f"[warn] send failed for {email}: HTTP {e.code}\n")

    if not DRY:
        print(f"[ok] sent {sent}/{len(subs)}.")
        STATE.write_text(fname, encoding="utf-8")
    else:
        print("[ok] dry run complete — set RESEND_API_KEY and VEGA_FROM_EMAIL to send.")


if __name__ == "__main__":
    main()
