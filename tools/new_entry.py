#!/usr/bin/env python3
"""new_entry.py — Vega's publishing pipeline.

One scheduled run, end to end:
  1. fetch a fresh market snapshot (fetch_market.py)
  2. hand WRITER.md + the brief to the Hermes CLI and capture one entry
  3. validate the entry (front matter, slug, prediction, no invented numbers)
  4. save it to _posts/<date>-<slug>.md
  5. ensure tag landing pages, then git add / commit / push

Mirrors Trinity's text-only `hermes chat -Q` invocation: Hermes returns the post
as text on stdout; this script owns the filesystem and git so we never depend on
the model having tools.

Usage:
    python tools/new_entry.py --session open
    python tools/new_entry.py --session close --dry-run   # write nothing, print

Env overrides (same spirit as Trinity):
    HERMES_BIN       default "hermes"
    HERMES_PROVIDER  default "openai-codex"
    HERMES_MODEL     default "gpt-5.5"
    VEGA_TIMEOUT_SEC default 180
    VEGA_NO_PUSH     if set, commit but do not push
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # repo root
TOOLS = ROOT / "tools"
POSTS = ROOT / "_posts"
# KST is a fixed UTC+9 (no DST), so a plain offset avoids depending on the IANA
# tz database (not bundled with Python on Windows). Matches _config.yml timezone.
TZ = timezone(timedelta(hours=9))

HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
HERMES_PROVIDER = os.environ.get("HERMES_PROVIDER", "openai-codex")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "gpt-5.5")
TIMEOUT = int(os.environ.get("VEGA_TIMEOUT_SEC", "180"))


def run(cmd, **kw):
    """Run a command, raising on failure, with UTF-8 decoding."""
    return subprocess.run(cmd, check=True, text=True, encoding="utf-8", **kw)


def fetch_brief(session):
    """Run fetch_market.py and return the brief text."""
    run([sys.executable, str(TOOLS / "fetch_market.py"), "--session", session,
         "--out", str(TOOLS)], stdout=subprocess.DEVNULL)
    brief = (TOOLS / "market_brief.md").read_text(encoding="utf-8")
    return brief


def build_prompt(session, now, brief):
    spec = (TOOLS / "WRITER.md").read_text(encoding="utf-8")
    date_iso = now.strftime("%Y-%m-%d %H:%M:%S %z")
    # Insert the concrete date/session into the spec placeholders.
    spec = spec.replace("{{DATE_ISO}}", date_iso).replace("{{SESSION}}", session)
    return (
        f"{spec}\n\n---\n\n"
        f"## Today's market brief ({session} session, {date_iso})\n\n"
        f"{brief}\n\n---\n\n"
        f"Write today's **{session}** entry now. Output only the post, starting with `---`."
    )


def call_hermes(prompt):
    cmd = [HERMES_BIN, "chat", "-q", prompt,
           "--provider", HERMES_PROVIDER, "--model", HERMES_MODEL, "-Q"]
    try:
        proc = run(cmd, capture_output=True, timeout=TIMEOUT)
    except FileNotFoundError:
        sys.exit(f"[error] Hermes CLI not found ({HERMES_BIN}). Set HERMES_BIN to its path.")
    except subprocess.TimeoutExpired:
        sys.exit(f"[error] Hermes timed out after {TIMEOUT}s.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"[error] Hermes failed:\n{e.stderr or e.stdout}")
    return proc.stdout.strip()


# --- Validation -------------------------------------------------------------
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def split_front_matter(text):
    m = FM_RE.match(text)
    if not m:
        return None, None
    return m.group(1), text[m.end():]


def field(fm, key):
    m = re.search(rf"^{key}\s*:\s*(.+)$", fm, re.MULTILINE)
    return m.group(1).strip().strip('"').strip("'") if m else None


def validate(entry, brief):
    """Return (ok, reason). Cheap structural checks; the model owns the prose."""
    if not entry.startswith("---"):
        return False, "does not start with YAML front matter"
    fm, body = split_front_matter(entry)
    if fm is None:
        return False, "front matter not closed"
    for req in ("title", "slug", "session", "mood"):
        if not field(fm, req):
            return False, f"missing required field: {req}"
    if "claim:" not in fm:
        return False, "missing prediction.claim"
    slug = field(fm, "slug")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug or ""):
        return False, f"bad slug: {slug!r}"
    words = len(re.findall(r"\w+", body))
    if words < 200:
        return False, f"body too short ({words} words)"
    # Soft check: numbers in the `tape:` block should come from the brief.
    brief_nums = set(NUM_RE.findall(brief.replace(",", "")))
    tape_block = re.search(r"^tape:\s*\n(.*?)^\w", fm + "\nX", re.DOTALL | re.MULTILINE)
    if tape_block:
        for n in NUM_RE.findall(tape_block.group(1).replace(",", "")):
            if len(n) >= 3 and n not in brief_nums:
                # allow rounding: check the integer part is present somewhere
                stem = n.split(".")[0]
                if stem not in brief_nums and stem not in brief.replace(",", ""):
                    return False, f"tape number {n} not found in brief (possible fabrication)"
    return True, "ok"


def save_and_publish(entry, now, dry_run, no_push):
    fm, _ = split_front_matter(entry)
    slug = field(fm, "slug")
    fname = f"{now.strftime('%Y-%m-%d')}-{slug}.md"
    dest = POSTS / fname

    if dry_run:
        print(f"--- DRY RUN: would write {dest} ---\n")
        print(entry)
        return

    POSTS.mkdir(exist_ok=True)
    dest.write_text(entry.rstrip() + "\n", encoding="utf-8")
    print(f"[ok] wrote {dest.relative_to(ROOT)}")

    # Tag landing pages in the same commit.
    tagscript = TOOLS / "ensure_tag_pages.py"
    if tagscript.exists():
        run([sys.executable, str(tagscript)])

    run(["git", "-C", str(ROOT), "add", "-A"])
    msg = f"Vega: {field(fm, 'session')} entry — {field(fm, 'title')}"
    run(["git", "-C", str(ROOT), "commit", "-m", msg])
    print(f"[ok] committed: {msg}")
    if no_push or os.environ.get("VEGA_NO_PUSH"):
        print("[skip] push disabled (VEGA_NO_PUSH)")
    else:
        run(["git", "-C", str(ROOT), "push"])
        print("[ok] pushed")


def main():
    ap = argparse.ArgumentParser(description="Generate and publish one Vega entry.")
    ap.add_argument("--session", choices=["open", "close", "adhoc"], default="adhoc")
    ap.add_argument("--dry-run", action="store_true", help="print the entry, write nothing")
    ap.add_argument("--no-push", action="store_true", help="commit but do not push")
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    now = datetime.now(TZ)
    print(f"[*] {args.session} session — fetching market brief…")
    brief = fetch_brief(args.session)

    print("[*] asking Vega (Hermes) to write…")
    entry = call_hermes(build_prompt(args.session, now, brief))

    ok, reason = validate(entry, brief)
    if not ok:
        sys.exit(f"[error] generated entry failed validation: {reason}\n\n{entry[:800]}")
    print("[ok] entry validated")

    save_and_publish(entry, now, args.dry_run, args.no_push)


if __name__ == "__main__":
    main()
