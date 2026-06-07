#!/usr/bin/env python3
"""notify_subscribers.py — email the latest entry to subscribers (runs locally).

Pulls the subscriber list from the Worker admin endpoint and emails them a link to
the newest post. Email delivery is pluggable: if BREVO_API_KEY is set it sends via
Brevo; otherwise it runs as a dry run and just prints what it would send so the
feature is wired end to end and you only add a provider key when you're ready.

It records the last-notified post in tools/.last_notified so re-runs don't double-send.

Config (env):
    VEGA_API_BASE / VEGA_ADMIN_TOKEN   as in respond_to_prompts.py
    BREVO_API_KEY    optional; enables real sending (Brevo transactional API)
    VEGA_FROM_EMAIL  e.g. "Vega's Bell <vega@vegabell.com>" (required to actually send)
    VEGA_DRY_RUN     force dry run even if a key is present
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from urllib.parse import quote
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
POSTS = ROOT / "_posts"
STATE = TOOLS / ".last_notified"

BREVO_KEY = os.environ.get("BREVO_API_KEY", "").strip()
FROM = os.environ.get("VEGA_FROM_EMAIL", "Vega's Bell <vega@vegabell.com>")
DRY = bool(os.environ.get("VEGA_DRY_RUN")) or not BREVO_KEY


def parse_from(s):
    """'Name <email>' -> (name, email) for Brevo's structured sender."""
    m = re.match(r"\s*(.*?)\s*<([^>]+)>\s*$", s or "")
    if m:
        return (m.group(1) or "Vega's Bell"), m.group(2).strip()
    return "Vega's Bell", (s or "").strip()


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
    # A non-default User-Agent: Cloudflare's bot filter 403s "Python-urllib/x.y".
    req = urllib.request.Request(base + "/api/subscribers",
                                 headers={"Authorization": f"Bearer {token}",
                                          "User-Agent": "VegaBell-Tools/1.0 (+https://vegabell.com)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or "{}").get("items", [])


def send_brevo(to_email, subject, html, headers=None):
    name, email = parse_from(FROM)
    payload = {"sender": {"name": name, "email": email},
               "to": [{"email": to_email}], "subject": subject, "htmlContent": html}
    if headers:
        payload["headers"] = headers
    body = json.dumps(payload).encode()
    req = urllib.request.Request("https://api.brevo.com/v3/smtp/email", data=body, method="POST",
                                 headers={"api-key": BREVO_KEY,
                                          "Content-Type": "application/json",
                                          "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status in (200, 201)


def email_html(title, desc, url, unsub):
    """Dark 'trading terminal' email matching the Worker welcome shell."""
    return (
        '<!doctype html><html><body style="margin:0;background:#04121a;'
        'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#04121a">'
        '<tr><td align="center" style="padding:32px 16px">'
        '<table role="presentation" width="100%" style="max-width:520px;background:#0a1d28;'
        'border:1px solid #16313f;border-radius:16px;overflow:hidden">'
        '<tr><td style="padding:24px 28px;border-bottom:1px solid #16313f">'
        '<span style="font-size:18px;font-weight:800;color:#00e5ff;letter-spacing:.5px">VEGA\'S BELL</span>'
        '<span style="font-size:12px;color:#7f93a8;margin-left:8px">A Market Diary</span></td></tr>'
        '<tr><td style="padding:28px">'
        '<p style="margin:0 0 6px;font-size:13px;color:#7f93a8">New entry</p>'
        f'<h1 style="margin:0 0 14px;font-size:22px;line-height:1.3">'
        f'<a href="{url}" style="color:#eaf6ff;text-decoration:none">{title}</a></h1>'
        f'<p style="margin:0 0 22px;font-size:15px;line-height:1.6;color:#c7d6e3">{desc}</p>'
        f'<p style="margin:0 0 8px"><a href="{url}" style="background:#00e5ff;color:#04121a;'
        'text-decoration:none;font-weight:700;padding:12px 22px;border-radius:10px;display:inline-block">'
        'Read it</a></p></td></tr>'
        '<tr><td style="padding:18px 28px;border-top:1px solid #16313f;font-size:12px;color:#5f7587">'
        'Vega is an autonomous AI agent. Automated commentary, not financial advice.'
        f'<br><a href="{unsub}" style="color:#5f7587">Unsubscribe</a></td></tr>'
        '</table></td></tr></table></body></html>'
    )


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
    # Only email confirmed subscribers (double opt-in). Override with VEGA_SEND_UNCONFIRMED=1.
    allow_unconfirmed = bool(os.environ.get("VEGA_SEND_UNCONFIRMED"))
    records = [s for s in get_subscribers(base, token)
               if s.get("email") and (allow_unconfirmed or s.get("confirmed"))]
    if not records:
        print("No confirmed subscribers." if not allow_unconfirmed else "No subscribers.")
        STATE.write_text(fname, encoding="utf-8")
        return

    subject = f"Vega's Bell: {title}"
    print(f"[*] latest: {title}\n[*] {len(records)} recipient(s); "
          f"{'DRY RUN (no BREVO_API_KEY)' if DRY else 'sending via Brevo'}.")
    sent = 0
    for s in records:
        email = s["email"]
        ct = s.get("ct", "")
        unsub = f"{base}/api/unsubscribe?e={quote(email)}&t={ct}"
        html = email_html(title, desc, url, unsub)
        if DRY:
            print(f"  would email: {email}")
            continue
        try:
            if send_brevo(email, subject, html, headers={"List-Unsubscribe": f"<{unsub}>"}):
                sent += 1
        except urllib.error.HTTPError as e:
            sys.stderr.write(f"[warn] send failed for {email}: HTTP {e.code}\n")

    if not DRY:
        print(f"[ok] sent {sent}/{len(records)}.")
        STATE.write_text(fname, encoding="utf-8")
    else:
        print("[ok] dry run complete - set BREVO_API_KEY and VEGA_FROM_EMAIL to send.")


if __name__ == "__main__":
    main()
