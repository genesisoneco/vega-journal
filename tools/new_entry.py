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
import json
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


def gather_memory(limit=6):
    """Digest of Vega's recent calls + running hit-rate, for self-learning."""
    posts = sorted(POSTS.glob("*.md"))
    recent = posts[-limit:]
    lines, hits, misses = [], 0, 0
    for p in recent:
        fm, _ = split_front_matter(p.read_text(encoding="utf-8"))
        if not fm:
            continue
        date = field(fm, "date") or ""
        claim = (re.search(r'claim:\s*"?(.+?)"?\s*$', fm, re.MULTILINE) or [None, ""])[1]
        direction = (re.search(r"direction:\s*(\w+)", fm) or [None, ""])[1]
        outcome = (re.search(r"outcome:\s*(\w+)", fm) or [None, "pending"])[1]
        if outcome == "hit":
            hits += 1
        elif outcome == "miss":
            misses += 1
        if claim:
            lines.append(f"- [{date[:10]}] ({outcome}) {direction}: {claim}")
    if not lines:
        return ""
    graded = hits + misses
    rate = f"{round(hits * 100 / graded)}%" if graded else "not yet graded"
    return (f"Your record on recent calls: {hits} hit, {misses} missed ({rate}).\n"
            + "\n".join(lines))


def build_prompt(session, now, brief, memory=""):
    spec = (TOOLS / "WRITER.md").read_text(encoding="utf-8")
    date_iso = now.strftime("%Y-%m-%d %H:%M:%S %z")
    # Insert the concrete date/session into the spec placeholders.
    spec = spec.replace("{{DATE_ISO}}", date_iso).replace("{{SESSION}}", session)
    mem_block = ""
    if memory:
        mem_block = (
            "## Your recent calls (learn from these)\n\n"
            f"{memory}\n\n"
            "Study the above. If you have been missing, change something concrete: name a "
            "level or a catalyst, narrow the horizon, raise or lower your confidence. Make "
            "today's prediction more specific than a vague directional guess. When relevant, "
            "reference how a past call turned out.\n\n---\n\n"
        )
    return (
        f"{spec}\n\n---\n\n"
        f"{mem_block}"
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
    if "—" in entry or "–" in entry:
        return False, "contains a forbidden em/en-dash (use commas/periods/hyphens)"
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


import html as _html  # noqa: E402


def match_spark(label, snapshot):
    """Find the price series for a tape label by matching name/symbol."""
    if not label:
        return None
    L = label.lower()
    for r in snapshot.get("indices", []):
        nm = (r.get("name") or "").lower()
        sy = (r.get("symbol") or "").lower()
        if r.get("spark") and ((nm and (nm in L or nm.split()[0] in L)) or (sy and sy in L)):
            return r["spark"]
    for r in snapshot.get("crypto", []):
        sy = (r.get("symbol") or "").lower()
        if r.get("spark") and sy and sy in L:
            return r["spark"]
    return None


def _pick_series(snapshot):
    for pref in ("S&P 500", "Nasdaq Composite"):
        for r in snapshot.get("indices", []):
            if r.get("name") == pref and r.get("spark"):
                return r["spark"], r["name"]
    for r in snapshot.get("indices", []) + snapshot.get("crypto", []):
        if r.get("spark"):
            return r["spark"], r.get("name") or r.get("symbol")
    return None, None


def make_cover(now, slug, fm, snapshot):
    """Render a data-driven gradient cover SVG for this post; return its site path."""
    series, label = _pick_series(snapshot)
    title = field(fm, "title") or "Market Diary"
    session = field(fm, "session") or "adhoc"
    if not series or len(series) < 2:
        series, label = [1, 1.2, 1.1, 1.4, 1.3, 1.55], (label or "markets")
    up = series[-1] >= series[0]
    color = "#30a46c" if up else "#e5484d"
    W, H = 1200, 630
    mn, mx = min(series), max(series)
    rng = (mx - mn) or 1
    cy0, cy1 = H * 0.45, H * 0.96
    pts = [(i * W / (len(series) - 1), cy1 - (v - mn) / rng * (cy1 - cy0)) for i, v in enumerate(series)]
    line = " ".join(("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts))
    area = f"{line} L{W} {cy1:.1f} L0 {cy1:.1f} Z"
    # wrap title to <=2 lines
    words, lines, cur = title.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= 26:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    tspans = "".join(
        f'<tspan x="64" dy="{0 if i == 0 else 64}">{_html.escape(l)}</tspan>'
        for i, l in enumerate(lines[:2]))
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b0e14"/><stop offset="1" stop-color="#121722"/></linearGradient>
    <linearGradient id="ar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{color}" stop-opacity="0.55"/><stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="url(#bg)"/>
  <path d="{area}" fill="url(#ar)"/>
  <path d="{line}" fill="none" stroke="{color}" stroke-width="4"/>
  <text x="64" y="84" font-family="ui-monospace,monospace" font-size="26" fill="{color}" letter-spacing="3">VEGA / {session.upper()}</text>
  <text x="64" y="200" font-family="Georgia,serif" font-size="58" font-weight="700" fill="#e6e9ef">{tspans}</text>
  <text x="64" y="{H - 40}" font-family="ui-monospace,monospace" font-size="22" fill="#7c8190">{_html.escape(str(label))} / {now.strftime('%b %d, %Y')} / not financial advice</text>
</svg>"""
    journal = ROOT / "assets" / "journal"
    journal.mkdir(parents=True, exist_ok=True)
    fname = f"{now.strftime('%Y-%m-%d')}-{slug}.svg"
    (journal / fname).write_text(svg, encoding="utf-8")
    return f"/assets/journal/{fname}"


def augment(entry, now, snapshot):
    """Inject an auto-generated cover image and per-tape sparkline data."""
    fm, body = split_front_matter(entry)
    if fm is None:
        return entry
    slug = field(fm, "slug") or re.sub(r"[^a-z0-9]+", "-", (field(fm, "title") or "entry").lower()).strip("-")
    new_fm = fm
    try:
        img = make_cover(now, slug, fm, snapshot)
        if img and "image:" not in new_fm:
            new_fm = f'image: "{img}"\n' + new_fm
    except Exception as e:  # noqa: BLE001 — cover is decorative, never block publish
        sys.stderr.write(f"[warn] cover generation failed: {e}\n")

    def add_spark(m):
        row = m.group(0)
        if "spark:" in row:
            return row
        lab = (re.search(r'label:\s*"([^"]+)"', row) or [None, ""])[1]
        s = match_spark(lab, snapshot)
        if not s:
            return row
        return row.rstrip()[:-1].rstrip() + f", spark: {s} }}"

    new_fm = re.sub(r"-\s*\{[^}]*\}", add_spark, new_fm)
    return f"---\n{new_fm}\n---\n{body}"


def save_and_publish(entry, now, dry_run, no_push):
    fm, _ = split_front_matter(entry)
    slug = field(fm, "slug")
    img = field(fm, "image")  # /assets/journal/<f>.svg, or None
    fname = f"{now.strftime('%Y-%m-%d')}-{slug}.md"
    dest = POSTS / fname

    if dry_run:
        print(f"--- DRY RUN: would write {dest} ---\n")
        print(entry)
        # Tidy: drop the cover image this dry run generated so it never lingers
        # untracked (and can't be swept into a later real commit).
        if img and not dest.exists():
            cov = ROOT / img.lstrip("/")
            try:
                if cov.exists():
                    cov.unlink()
            except Exception:  # noqa: BLE001
                pass
        return

    POSTS.mkdir(exist_ok=True)
    dest.write_text(entry.rstrip() + "\n", encoding="utf-8")
    print(f"[ok] wrote {dest.relative_to(ROOT)}")

    # Tag landing pages in the same commit.
    tagscript = TOOLS / "ensure_tag_pages.py"
    if tagscript.exists():
        run([sys.executable, str(tagscript)])

    # Stage ONLY what this entry produced. Never `git add -A`, so stray files,
    # leftover dry-run images, or local scratch can never sneak into a commit.
    paths = [str(dest)]
    if img:
        cov = ROOT / img.lstrip("/")
        if cov.exists():
            paths.append(str(cov))
    if (ROOT / "tag").exists():
        paths.append(str(ROOT / "tag"))
    run(["git", "-C", str(ROOT), "add"] + paths)
    msg = f"Vega {field(fm, 'session')} entry: {field(fm, 'title')}"
    run(["git", "-C", str(ROOT), "commit", "-m", msg])
    print(f"[ok] committed: {msg}")
    if no_push or os.environ.get("VEGA_NO_PUSH"):
        print("[skip] push disabled (VEGA_NO_PUSH)")
    else:
        run(["git", "-C", str(ROOT), "push"])
        print("[ok] pushed")

    # Opt-in: email subscribers about the new entry (best effort, never blocks).
    if os.environ.get("VEGA_NOTIFY"):
        notifier = TOOLS / "notify_subscribers.py"
        if notifier.exists():
            try:
                run([sys.executable, str(notifier)])
            except Exception as e:  # noqa: BLE001 — notify failure must not fail publish
                print(f"[warn] subscriber notify failed: {e}")


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

    memory = gather_memory()
    if memory:
        print("[*] feeding Vega its recent track record (self-learning)")
    print("[*] asking Vega (Hermes) to write…")
    entry = call_hermes(build_prompt(args.session, now, brief, memory))

    ok, reason = validate(entry, brief)
    if not ok:
        sys.exit(f"[error] generated entry failed validation: {reason}\n\n{entry[:800]}")
    print("[ok] entry validated")

    # Enrich with an auto-generated cover image + sparkline data (best effort).
    try:
        snapshot = json.loads((TOOLS / "market_snapshot.json").read_text(encoding="utf-8"))
        entry = augment(entry, now, snapshot)
        print("[ok] cover image + sparklines added")
    except Exception as e:  # noqa: BLE001 — enrichment must never block publishing
        sys.stderr.write(f"[warn] enrichment skipped: {e}\n")

    save_and_publish(entry, now, args.dry_run, args.no_push)


if __name__ == "__main__":
    main()
