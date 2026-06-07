#!/usr/bin/env python3
"""verify_cron.py - confirm Vega's scheduled jobs exist (run on sejcore).

Reads the active crontab and reports which of the expected jobs are present:
  REQUIRED
  1. open      session writer   (run_session.sh open  /  new_entry.py --session open)
  2. close     session writer   (run_session.sh close /  new_entry.py --session close)
  3. responder hourly Q&A        (respond_to_prompts.py)
  4. grader    daily grading     (grade_predictions.py)
  OPTIONAL (newer features; absence is reported but does not fail)
  5. radar     topical pieces    (new_entry.py --session radar)
  6. reflect   self-improvement  (reflect.py)

Exit code 0 if all REQUIRED jobs are found, 1 otherwise. Pure stdlib; Linux-safe.
"""

import re
import subprocess
import sys

CHECKS = [
    ("open writer",   r"(run_session\.sh\s+open|new_entry\.py.*--session\s+open)"),
    ("close writer",  r"(run_session\.sh\s+close|new_entry\.py.*--session\s+close)"),
    ("responder",     r"respond_to_prompts\.py"),
    ("grader",        r"grade_predictions\.py"),
]
OPTIONAL_CHECKS = [
    ("radar",   r"new_entry\.py.*--session\s+radar"),
    ("reflect", r"reflect\.py"),
]


def read_crontab():
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        sys.exit("[error] 'crontab' not found - are you on the Linux (sejcore) host?")
    if out.returncode != 0:
        # "no crontab for user" prints to stderr with rc=1
        msg = (out.stderr or out.stdout).strip()
        print(f"[warn] crontab read returned {out.returncode}: {msg}")
        return ""
    return out.stdout


def main():
    cron = read_crontab()
    active = [l for l in cron.splitlines() if l.strip() and not l.strip().startswith("#")]
    print(f"[*] {len(active)} active crontab entr{'y' if len(active)==1 else 'ies'} found.\n")

    ok = True
    for label, pat in CHECKS:
        match = next((l for l in active if re.search(pat, l)), None)
        if match:
            sched = " ".join(match.split()[:5])
            print(f"  [OK]      {label:12s} -> {sched}")
        else:
            ok = False
            print(f"  [MISSING] {label:12s}")

    print("")
    for label, pat in OPTIONAL_CHECKS:
        match = next((l for l in active if re.search(pat, l)), None)
        if match:
            sched = " ".join(match.split()[:5])
            print(f"  [OK]      {label:12s} (optional) -> {sched}")
        else:
            print(f"  [absent]  {label:12s} (optional)")

    print("\n" + ("[ok] all 4 required jobs scheduled." if ok
                  else "[fail] some required jobs are missing. See docs/sejcore-cron-setup.md."))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
