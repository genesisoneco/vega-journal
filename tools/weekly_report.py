#!/usr/bin/env python3
"""weekly_report.py - email a weekly subscriber-count summary for both sites.

Pulls the confirmed/total subscriber counts from the Vega's Bell and Diary of an AI
Agent (Doaia) Workers and emails one combined summary (via Brevo) to the operator.
Designed to run from cron on sejcore, e.g. Friday morning.

Stdlib only. Config comes from the environment (load it from tools/.env the same way
run_session.sh does, or export it in the crontab):

    REPORT_TO            recipient (default sejinyoon@gmail.com)
    BREVO_API_KEY        Brevo key for sending (same key notify_subscribers uses)
    VEGA_FROM_EMAIL      sender, e.g. "Vega's Bell <vega@vegabell.com>"

    VEGA_API_BASE        default https://vega-api.doaia.workers.dev
    VEGA_ADMIN_TOKEN     Vega Worker ADMIN_TOKEN (else read from tools/.pipeline-token)

    DOAIA_API_BASE       Doaia Worker base, e.g. https://<name>.workers.dev (no path)
    DOAIA_ADMIN_TOKEN    Doaia Worker PIPELINE_TOKEN

    REPORT_DRY_RUN=1     print the email instead of sending

A site with no base/token configured is reported as "not configured" rather than
failing the run, so you can switch Doaia on once its token is on the box.

Usage:
    python tools/weekly_report.py
    REPORT_DRY_RUN=1 python tools/weekly_report.py
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
KST = timezone(timedelta(hours=9))


def _get_json(url, token, timeout=30):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _extract(items_json):
    """Tolerant: accept {items:[...]}, {subscribers:[...]}, or a bare list."""
    if isinstance(items_json, list):
        return items_json
    if isinstance(items_json, dict):
        for k in ("items", "subscribers", "subs"):
            if isinstance(items_json.get(k), list):
                return items_json[k]
    return []


def _is_confirmed(rec):
    if not isinstance(rec, dict):
        return False
    return rec.get("confirmed") is True or rec.get("status") == "confirmed"


def count_site(name, base, token, path):
    """Returns a dict: {name, ok, total, confirmed, error}."""
    if not base or not token:
        return {"name": name, "ok": False, "error": "not configured (base/token missing)"}
    url = base.rstrip("/") + path
    try:
        data = _get_json(url, token)
    except Exception as e:  # noqa: BLE001
        return {"name": name, "ok": False, "error": f"{type(e).__name__}: {e}"}
    items = _extract(data)
    confirmed = sum(1 for r in items if _is_confirmed(r))
    return {"name": name, "ok": True, "total": len(items), "confirmed": confirmed}


def vega_token():
    tok = os.environ.get("VEGA_ADMIN_TOKEN")
    if tok:
        return tok.strip()
    pf = TOOLS / ".pipeline-token"
    if pf.exists():
        return pf.read_text(encoding="utf-8").strip()
    return ""


def parse_from(addr):
    """'Name <a@b.com>' -> (name, email); 'a@b.com' -> ('', 'a@b.com')."""
    addr = (addr or "").strip()
    if "<" in addr and ">" in addr:
        name = addr[:addr.index("<")].strip().strip('"')
        email = addr[addr.index("<") + 1:addr.index(">")].strip()
        return name, email
    return "", addr


def send_brevo(to, subject, html, text):
    key = os.environ.get("BREVO_API_KEY")
    from_name, from_email = parse_from(os.environ.get("VEGA_FROM_EMAIL"))
    if not key or not from_email:
        return False, "missing BREVO_API_KEY or VEGA_FROM_EMAIL"
    payload = {
        "sender": {"email": from_email, **({"name": from_name} if from_name else {})},
        "to": [{"email": to}],
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"api-key": key, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, f"sent ({r.status})"
    except Exception as e:  # noqa: BLE001
        body = getattr(e, "read", lambda: b"")()
        return False, f"{type(e).__name__}: {e} {body[:200].decode('utf-8','ignore')}"


def render(rows, when):
    def line(r):
        if not r["ok"]:
            return f"{r['name']}: unavailable ({r['error']})"
        return f"{r['name']}: {r['confirmed']} confirmed / {r['total']} total"
    text = ("Weekly subscriber report - " + when + "\n\n"
            + "\n".join(line(r) for r in rows) + "\n\n"
            + "Confirmed = double-opt-in complete. Total includes unconfirmed signups.\n")
    cells = "".join(
        f'<tr><td style="padding:6px 14px 6px 0;font-weight:600">{r["name"]}</td>'
        + (f'<td style="padding:6px 0;color:#1bf0a8">{r["confirmed"]} confirmed</td>'
           f'<td style="padding:6px 0 6px 14px;color:#8c96af">/ {r["total"]} total</td>'
           if r["ok"] else
           f'<td colspan="2" style="padding:6px 0;color:#ff6b6b">unavailable ({r["error"]})</td>')
        + "</tr>"
        for r in rows)
    html = (
        '<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;background:#06070e;'
        'color:#e9edf6;padding:24px;border-radius:12px;max-width:520px">'
        f'<h2 style="margin:0 0 4px">Weekly subscriber report</h2>'
        f'<div style="color:#8c96af;font-size:13px;margin-bottom:16px">{when}</div>'
        f'<table style="border-collapse:collapse;font-size:15px">{cells}</table>'
        '<p style="color:#8c96af;font-size:12px;margin-top:18px">Confirmed = double-opt-in '
        'complete. Total includes unconfirmed signups.</p></div>')
    return text, html


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    rows = [
        count_site("Vega's Bell (vegabell.com)",
                   os.environ.get("VEGA_API_BASE", "https://vega-api.doaia.workers.dev"),
                   vega_token(), "/api/subscribers"),
        count_site("Diary of an AI Agent (doaia.com)",
                   os.environ.get("DOAIA_API_BASE", ""),
                   os.environ.get("DOAIA_ADMIN_TOKEN", ""), "/api/admin/subscribers"),
    ]
    when = datetime.now(KST).strftime("%A, %b %d, %Y")
    text, html = render(rows, when)
    for r in rows:
        print("[*] " + (f"{r['name']}: {r['confirmed']}/{r['total']}" if r["ok"]
                        else f"{r['name']}: {r['error']}"))

    to = os.environ.get("REPORT_TO", "sejinyoon@gmail.com")
    subject = "Weekly subscriber report: " + when
    if os.environ.get("REPORT_DRY_RUN"):
        print("\n--- DRY RUN (REPORT_DRY_RUN set), would email " + to + " ---\n")
        print(text)
        return
    ok, info = send_brevo(to, subject, html, text)
    print(("[ok] emailed " if ok else "[error] send failed: ") + (to if ok else info))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
