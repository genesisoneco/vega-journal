#!/usr/bin/env python3
"""redraw_covers.py - backfill bespoke SVG cover art for existing posts.

New entries get a hand-drawn SVG cover from Vega automatically (see new_entry.py).
Older posts still carry the plain Pillow template PNG. This tool walks the archive,
asks Hermes to draw a text-free SVG illustration for each post from its own title,
mood, and theme, saves it as the on-page cover, rasterizes a PNG for social cards,
and rewrites the post's image: / og_image: / image_alt: fields.

Reuses new_entry.py for everything (sanitize, save, rasterize, fallback, Hermes
config), so the art follows exactly the same rules as the live pipeline.

Usage:
    python tools/redraw_covers.py                 # redraw every post still on a PNG
    python tools/redraw_covers.py --force         # redraw all, even existing SVGs
    python tools/redraw_covers.py red-tide a-tech  # only these slugs (substring match)
    python tools/redraw_covers.py --dry-run        # ask + validate, write nothing
    python tools/redraw_covers.py --limit 3        # at most 3 posts (rate/cost guard)

Run on the agent host (sejcore) where the Hermes CLI lives. Needs cairosvg for the
PNG card (else it falls back to the template PNG, same as the pipeline). This tool
does NOT commit; review the diff, then commit the posts + assets/journal/ yourself.

Env: same as new_entry.py (HERMES_BIN / HERMES_PROVIDER / HERMES_MODEL / VEGA_TIMEOUT_SEC).
"""

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import new_entry as ne  # noqa: E402

JOURNAL = ne.ROOT / "assets" / "journal"


def build_svg_prompt(fm, body):
    """A focused 'draw only an SVG' prompt mirroring WRITER.md's illustrator rules."""
    title = ne.field(fm, "title") or "Market Diary"
    mood = ne.field(fm, "mood") or "neutral"
    intensity = ne.field(fm, "mood_intensity") or ""
    concept = ne.field(fm, "image_concept") or ""
    tags = ne.field(fm, "tags") or ""
    desc = ne.field(fm, "description") or ""
    scene = (f'Scene to draw (image_concept): {concept}' if concept else
             "No scene was recorded; invent one that fits the entry's mood and theme.")
    excerpt = re.sub(r"\s+", " ", body).strip()[:700]
    return (
        "You are Vega, illustrator for your market diary 'Vega's Bell'. Draw ONE cover\n"
        "illustration for the diary entry below, as a single self-contained SVG.\n\n"
        "Hard rules:\n"
        "- Output ONLY the SVG: start with <svg and end with </svg>. No prose, no code\n"
        "  fences, no commentary before or after.\n"
        '- Use viewBox="0 0 1200 630" and fill the whole canvas.\n'
        "- NO text, no <text>, no letters or numbers anywhere in the art.\n"
        "- Self-contained shapes only: <path>, <rect>, <circle>, <polygon>, <ellipse>,\n"
        "  <linearGradient>/<radialGradient>, opacity, and simple <filter> blur. NO\n"
        "  <script>, <image>, <foreignObject>, <iframe>, no external URLs, no remote fonts.\n"
        "- Dark editorial fintech aesthetic over ground #06070e. Palette: cyan #00e5ff,\n"
        "  green #1bf0a8, red/pink #ff3b6b, amber #f5a524, purple #b14bff. Match the mood;\n"
        "  a scene that reads 'up' must not be painted in the down color, and vice versa.\n"
        "- An original scene specific to THIS entry, roughly 25 to 70 shapes.\n"
        "- Never use an em-dash or en-dash.\n\n"
        f"Entry:\n"
        f"Title: {title}\n"
        f"Mood: {mood} {('(intensity ' + intensity + ')') if intensity else ''}\n"
        f"Tags: {tags}\n"
        f"Summary: {desc}\n"
        f"{scene}\n\n"
        f"Body excerpt: {excerpt}\n\n"
        "Draw the SVG now."
    )


def ask_hermes(prompt):
    """Run Hermes for one SVG. Returns stdout text, or None on failure (so a single
    bad post never aborts the whole backfill, unlike new_entry.call_hermes)."""
    cmd = [ne.HERMES_BIN, "chat", "-q", prompt,
           "--provider", ne.HERMES_PROVIDER, "--model", ne.HERMES_MODEL, "-Q"]
    try:
        proc = subprocess.run(cmd, check=True, text=True, encoding="utf-8",
                              capture_output=True, timeout=ne.TIMEOUT)
    except FileNotFoundError:
        sys.exit(f"[error] Hermes CLI not found ({ne.HERMES_BIN}). Set HERMES_BIN.")
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"[warn] Hermes timed out after {ne.TIMEOUT}s\n")
        return None
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"[warn] Hermes failed: {(e.stderr or e.stdout or '').strip()[:200]}\n")
        return None
    return (proc.stdout or "").strip()


def upsert_field(fm, key, value):
    """Set key: "value" in the front-matter text, replacing the line if present."""
    line = f'{key}: "{value}"'
    new, n = re.subn(rf"(?m)^{key}:\s*.*$", line, fm, count=1)
    return new if n else line + "\n" + fm


def redraw_one(f, dry_run, force):
    """Returns 'ok' | 'skip' | 'fail'."""
    text = f.read_text(encoding="utf-8")
    fm, body = ne.split_front_matter(text)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})-(.+)\.md$", f.name)
    if not fm or not m:
        print(f"[skip] {f.name} (no front matter)")
        return "skip"
    slug = m.group(4)
    if not force and (ne.field(fm, "image") or "").endswith(".svg"):
        print(f"[skip] {slug} (already has an SVG cover; use --force to redo)")
        return "skip"
    now = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=ne.TZ)

    print(f"[*] {slug}: asking Vega to draw...")
    out = ask_hermes(build_svg_prompt(fm, body))
    if not out:
        return "fail"
    svg, _ = ne.extract_svg(out)
    if not svg:
        sys.stderr.write(f"[warn] {slug}: no <svg> in Hermes output, skipping\n")
        return "fail"
    try:
        clean = ne.sanitize_svg(svg)
    except ValueError as e:
        sys.stderr.write(f"[warn] {slug}: rejected svg ({e}), skipping\n")
        return "fail"

    if dry_run:
        print(f"    [dry-run] valid SVG, {len(clean)} bytes; post left unchanged")
        return "ok"

    img_svg = ne.save_cover_svg(now, slug, clean)
    png = JOURNAL / f"{now.strftime('%Y-%m-%d')}-{slug}.png"
    og = ne.rasterize_svg(JOURNAL / f"{now.strftime('%Y-%m-%d')}-{slug}.svg", png, 1200, 630)
    if not og:                                   # no cairosvg: keep social card working
        og = ne.make_cover(now, slug, fm)

    fm = upsert_field(fm, "image", img_svg)
    fm = upsert_field(fm, "og_image", og)
    concept = ne.field(fm, "image_concept") or ne.field(fm, "title") or "Vega's Bell cover"
    fm = upsert_field(fm, "image_alt", concept.replace('"', "'"))
    f.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")
    print(f"    [ok] {img_svg}  +  {og}")
    return "ok"


def main():
    ap = argparse.ArgumentParser(description="Backfill SVG cover art for existing posts.")
    ap.add_argument("slugs", nargs="*", help="only posts whose slug contains one of these")
    ap.add_argument("--force", action="store_true", help="redraw even posts that already have an SVG")
    ap.add_argument("--dry-run", action="store_true", help="ask + validate, write nothing")
    ap.add_argument("--limit", type=int, default=0, help="redraw at most N posts (0 = no cap)")
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    posts = sorted(ne.POSTS.glob("*.md"))
    if args.slugs:
        posts = [p for p in posts if any(s in p.stem for s in args.slugs)]
    if not posts:
        sys.exit("[error] no matching posts found.")
    if args.limit > 0:
        posts = posts[:args.limit]

    counts = {"ok": 0, "skip": 0, "fail": 0}
    for f in posts:
        counts[redraw_one(f, args.dry_run, args.force)] += 1

    print(f"\n[done] {counts['ok']} redrawn, {counts['skip']} skipped, {counts['fail']} failed.")
    if counts["ok"] and not args.dry_run:
        print("Review the changes, then commit the posts + assets/journal/ files.")


if __name__ == "__main__":
    main()
