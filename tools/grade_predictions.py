#!/usr/bin/env python3
"""grade_predictions.py — close the self-learning loop.

Finds entries whose prediction horizon has elapsed but are still `outcome: pending`,
fetches a fresh market brief, and asks Hermes to judge each past claim against what
actually happened: HIT, MISS, or UNCLEAR. It writes hit/miss back into the post's front
matter so the Predictions page (and the writer's self-learning memory) reflect a real
record. UNCLEAR is left pending.

Runs locally (shares the Hermes session). Schedule it daily, or run by hand.

    python tools/grade_predictions.py            # grade what's due, commit
    python tools/grade_predictions.py --dry-run  # show verdicts, write nothing

Env: HERMES_* as in new_entry.py; VEGA_NO_PUSH to skip pushing.
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
POSTS = ROOT / "_posts"
TZ = timezone(timedelta(hours=9))

HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
HERMES_PROVIDER = os.environ.get("HERMES_PROVIDER", "openai-codex")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "gpt-5.5")
TIMEOUT = int(os.environ.get("VEGA_TIMEOUT_SEC", "120"))


def split_fm(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    return (m.group(1), m.end()) if m else (None, 0)


def field(fm, key):
    # Allow leading whitespace so nested keys (e.g. prediction.horizon) are found.
    m = re.search(rf"^\s*{key}\s*:\s*(.+)$", fm, re.MULTILINE)
    return m.group(1).strip().strip('"').strip("'") if m else None


def horizon_days(h):
    """Rough horizon -> days. '1 week' -> 7, '3 days' -> 3, 'by Friday' -> 5."""
    if not h:
        return 7
    h = h.lower()
    m = re.search(r"(\d+)\s*(day|week|month)", h)
    if m:
        n = int(m.group(1))
        return n * {"day": 1, "week": 7, "month": 30}[m.group(2)]
    if "month" in h:
        return 30
    if "week" in h:
        return 7
    return 5  # "by Friday", "end of week", etc.


def post_date(fm):
    d = field(fm, "date")
    try:
        return datetime.strptime(d, "%Y-%m-%d %H:%M:%S %z")
    except Exception:  # noqa: BLE001
        return None


def current_brief():
    try:
        subprocess.run([sys.executable, str(TOOLS / "fetch_market.py"), "--session", "adhoc",
                        "--out", str(TOOLS)], check=True, stdout=subprocess.DEVNULL)
        return (TOOLS / "market_brief.md").read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        sys.exit(f"[error] could not fetch current market brief: {e}")


def judge(claim, made_on, brief):
    prompt = (
        "You are a strict, impartial judge of a market prediction. Given the prediction, "
        "the date it was made, and the CURRENT market data below, decide whether it has "
        "clearly come true.\n\n"
        f"Prediction (made {made_on}): \"{claim}\"\n\n"
        f"Current market data:\n{brief}\n\n"
        "Answer with exactly one word: HIT if it clearly came true, MISS if it clearly did "
        "not, or UNCLEAR if it cannot be determined yet. One word only."
    )
    cmd = [HERMES_BIN, "chat", "-q", prompt, "--provider", HERMES_PROVIDER,
           "--model", HERMES_MODEL, "-Q"]
    try:
        p = subprocess.run(cmd, check=True, text=True, encoding="utf-8",
                           capture_output=True, timeout=TIMEOUT)
    except FileNotFoundError:
        sys.exit(f"[error] Hermes not found ({HERMES_BIN}).")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[warn] judge failed: {e}\n")
        return "UNCLEAR"
    out = (p.stdout or "").strip().upper()
    for v in ("HIT", "MISS", "UNCLEAR"):
        if v in out:
            return v
    return "UNCLEAR"


def main():
    ap = argparse.ArgumentParser(description="Grade due predictions via Hermes.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    now = datetime.now(TZ)
    due = []
    for p in sorted(POSTS.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        fm, _ = split_fm(text)
        if not fm or "prediction:" not in fm:
            continue
        outcome = (re.search(r"outcome:\s*(\w+)", fm) or [None, "pending"])[1]
        if outcome != "pending":
            continue
        dt = post_date(fm)
        if not dt:
            continue
        claim = (re.search(r'claim:\s*"?(.+?)"?\s*$', fm, re.MULTILINE) or [None, ""])[1]
        horizon = field(fm, "horizon")
        if now >= dt + timedelta(days=horizon_days(horizon)):
            due.append((p, dt, claim))

    if not due:
        print("No predictions are due for grading.")
        return

    print(f"[*] {len(due)} prediction(s) due. Fetching current market...")
    brief = current_brief()
    changed = 0
    for p, dt, claim in due:
        verdict = judge(claim, dt.strftime("%Y-%m-%d"), brief)
        print(f"  [{verdict}] {p.name}: {claim[:70]!r}")
        if verdict in ("HIT", "MISS") and not args.dry_run:
            text = p.read_text(encoding="utf-8")
            text = re.sub(r"(\n\s*outcome:\s*)pending", r"\1" + verdict.lower(), text, count=1)
            p.write_text(text, encoding="utf-8", newline="\n")
            changed += 1

    if args.dry_run:
        print("[ok] dry run, nothing written.")
        return
    if changed:
        subprocess.run(["git", "-C", str(ROOT), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(ROOT), "commit", "-m",
                        f"Vega: graded {changed} prediction(s)"], check=True)
        if not os.environ.get("VEGA_NO_PUSH"):
            subprocess.run(["git", "-C", str(ROOT), "push"], check=True)
        print(f"[ok] graded and committed {changed} prediction(s).")
    else:
        print("[ok] nothing conclusive to record yet.")


if __name__ == "__main__":
    main()
