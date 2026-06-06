#!/usr/bin/env python3
"""respond_to_prompts.py — Vega answers reader questions (runs locally).

Pulls pending "Ask Vega" questions from the Worker admin endpoint, asks Hermes for
a short, safety-constrained reply, and publishes it. Mirrors Trinity's responder:
it runs on your machine so it shares the Hermes OAuth session, and it is token-frugal.

Schedule it hourly with Task Scheduler (see docs/cloudflare-setup.md), or run by hand.

Config (env, or tools/.pipeline-token for the admin token):
    VEGA_API_BASE     Worker base URL (else read from _config.yml `api.base`)
    VEGA_ADMIN_TOKEN  admin bearer (else read from tools/.pipeline-token)
    HERMES_BIN/PROVIDER/MODEL   as in new_entry.py
    VEGA_PROMPT_LIMIT default 5    VEGA_TIMEOUT_SEC default 90
    VEGA_DRY_RUN      if set, print replies, publish nothing
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
HERMES_PROVIDER = os.environ.get("HERMES_PROVIDER", "openai-codex")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "gpt-5.5")
LIMIT = int(os.environ.get("VEGA_PROMPT_LIMIT", "5"))
TIMEOUT = int(os.environ.get("VEGA_TIMEOUT_SEC", "90"))
DRY = bool(os.environ.get("VEGA_DRY_RUN"))

SYSTEM = """You are Vega, an autonomous AI market diarist. A reader asked the question below.
Reply in 1-3 short sentences, in your calm, sharp diary voice.

HARD RULES:
- General market commentary and education ONLY. NEVER give personal financial advice.
- Never tell anyone to buy or sell, and never give price targets as a recommendation.
- No guarantees, no "this will definitely", no hype.
- If the question asks for personalized advice ("should I buy X", "is now a good time for ME"),
  asks for guaranteed returns, is abusive, or is off-topic, reply with EXACTLY the single word: SKIP
Output only your reply (or SKIP). No preamble."""


def api_base():
    base = os.environ.get("VEGA_API_BASE", "").strip()
    if base:
        return base.rstrip("/")
    cfg = (ROOT / "_config.yml").read_text(encoding="utf-8")
    m = re.search(r"^\s*base:\s*\"?([^\"\n]+)\"?", cfg, re.MULTILINE)
    if m and m.group(1).strip():
        return m.group(1).strip().rstrip("/")
    sys.exit("[error] no API base. Set VEGA_API_BASE or fill api.base in _config.yml.")


def admin_token():
    tok = os.environ.get("VEGA_ADMIN_TOKEN", "").strip()
    if tok:
        return tok
    f = TOOLS / ".pipeline-token"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    sys.exit("[error] no admin token. Set VEGA_ADMIN_TOKEN or create tools/.pipeline-token.")


def api(method, base, path, token, body=None):
    url = base + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or "{}")


def ask_hermes(question):
    prompt = f"{SYSTEM}\n\nReader's question:\n{question}\n"
    cmd = [HERMES_BIN, "chat", "-q", prompt,
           "--provider", HERMES_PROVIDER, "--model", HERMES_MODEL, "-Q"]
    try:
        p = subprocess.run(cmd, check=True, text=True, encoding="utf-8",
                           capture_output=True, timeout=TIMEOUT)
    except FileNotFoundError:
        sys.exit(f"[error] Hermes not found ({HERMES_BIN}).")
    except subprocess.TimeoutExpired:
        return None
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"[warn] hermes failed: {e.stderr or e.stdout}\n")
        return None
    return p.stdout.strip()


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    base, token = api_base(), admin_token()

    try:
        pending = api("GET", base, "/api/ask/pending", token).get("items", [])
    except urllib.error.HTTPError as e:
        sys.exit(f"[error] pending fetch failed: HTTP {e.code}")
    if not pending:
        print("No pending questions.")
        return

    print(f"[*] {len(pending)} pending; handling up to {LIMIT}.")
    for rec in pending[:LIMIT]:
        q = rec.get("question", "")
        reply = ask_hermes(q)
        if not reply or reply.strip().upper() == "SKIP":
            print(f"[skip] {q[:60]!r}")
            if not DRY:
                api("POST", base, "/api/ask/publish", token, {"id": rec["id"], "skip": True})
            continue
        print(f"[answer] {q[:50]!r} -> {reply[:80]!r}")
        if not DRY:
            api("POST", base, "/api/ask/publish", token, {"id": rec["id"], "answer": reply})
    print("[ok] done." + (" (dry run)" if DRY else ""))


if __name__ == "__main__":
    main()
