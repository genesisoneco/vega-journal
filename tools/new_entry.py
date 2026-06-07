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
import hashlib
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


def fetch_topic_brief(topic):
    """Run fetch_topic.py for a radar piece. Returns (brief, resolved_topic)."""
    cmd = [sys.executable, str(TOOLS / "fetch_topic.py"), "--out", str(TOOLS)]
    if topic:
        cmd += ["--topic", topic]
    run(cmd, stdout=subprocess.DEVNULL)
    brief = (TOOLS / "topic_brief.md").read_text(encoding="utf-8")
    resolved = topic
    try:
        snap = json.loads((TOOLS / "topic_snapshot.json").read_text(encoding="utf-8"))
        resolved = snap.get("topic") or topic
    except Exception:  # noqa: BLE001
        pass
    return brief, resolved


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


METHOD = ROOT / "method"


def read_playbook():
    """Vega's durable, self-maintained lessons. Fed into every prompt."""
    p = METHOD / "playbook.md"
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8").strip()
    # Skip the H1 title line; the rest is the substance.
    return re.sub(r"^#\s+.*\n", "", text, count=1).strip()


def gather_signal_feedback(min_graded=2):
    """From method/signal_stats.json, which signals have preceded correct calls.
    Returns a short coaching string for the prompt, or ''."""
    p = METHOD / "signal_stats.json"
    if not p.exists():
        return ""
    try:
        stats = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return ""
    rated = []
    for sig, d in stats.items():
        graded = d.get("hit", 0) + d.get("miss", 0)
        if graded >= min_graded:
            rated.append((sig, d["hit"] / graded, graded))
    if not rated:
        return ""
    rated.sort(key=lambda x: x[1], reverse=True)
    best = [f"{s} ({round(r*100)}%, n={n})" for s, r, n in rated[:3] if r >= 0.5]
    worst = [f"{s} ({round(r*100)}%, n={n})" for s, r, n in rated[-3:] if r < 0.5]
    out = []
    if best:
        out.append("Signals that have preceded your correct calls: " + ", ".join(best) + ".")
    if worst:
        out.append("Signals that have let you down: " + ", ".join(worst[::-1])
                   + ". Weight these less, or be more specific when you use them.")
    return " ".join(out)


def build_prompt(session, now, brief, memory="", topic=None):
    spec_file = "WRITER_RADAR.md" if session == "radar" else "WRITER.md"
    spec = (TOOLS / spec_file).read_text(encoding="utf-8")
    date_iso = now.strftime("%Y-%m-%d %H:%M:%S %z")
    # Insert the concrete date/session/topic into the spec placeholders.
    spec = (spec.replace("{{DATE_ISO}}", date_iso)
                .replace("{{SESSION}}", session)
                .replace("{{TOPIC}}", topic or ""))
    brief_heading = (f"## Research brief for: {topic}" if session == "radar"
                     else f"## Today's market brief ({session} session, {date_iso})")
    play = read_playbook()
    play_block = f"## Your playbook (your own durable lessons)\n\n{play}\n\n---\n\n" if play else ""

    mem_block = ""
    if memory:
        sig = gather_signal_feedback()
        sig_line = f"\n\n{sig}" if sig else ""
        mem_block = (
            "## Your recent calls (learn from these)\n\n"
            f"{memory}{sig_line}\n\n"
            "Study the above. If you have been missing, change something concrete: name a "
            "level or a catalyst, narrow the horizon, raise or lower your confidence. Make "
            "today's prediction more specific than a vague directional guess. When relevant, "
            "reference how a past call turned out.\n\n---\n\n"
        )
    closer = (f"Write your **On the Radar** piece on {topic} now."
              if session == "radar"
              else f"Write today's **{session}** entry now.")
    return (
        f"{spec}\n\n---\n\n"
        f"{play_block}"
        f"{mem_block}"
        f"{brief_heading}\n\n"
        f"{brief}\n\n---\n\n"
        f"{closer} Output only the post, starting with `---`."
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
    # Count prose words only: strip the cover-art SVG (and any fenced block) so the
    # illustration markup can't pad a thin entry past the minimum.
    prose = re.sub(r"<svg\b.*?</svg>", "", body, flags=re.DOTALL | re.IGNORECASE)
    prose = re.sub(r"```.*?```", "", prose, flags=re.DOTALL)
    words = len(re.findall(r"\w+", prose))
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


def _mood_color(mood):
    """Mood -> (hex color, UPPER label) from _data/moods.yml, with a fallback."""
    fb = {"risk-off": ("#ff3b6b", "RISK-OFF"), "fearful": ("#ff3b6b", "FEARFUL"),
          "risk-on": ("#1bf0a8", "RISK-ON"), "greedy": ("#1bf0a8", "GREEDY"),
          "cautious": ("#f5a524", "CAUTIOUS"), "vigilant": ("#4ea1ff", "VIGILANT"),
          "coiled": ("#b14bff", "COILED"), "neutral": ("#7c8190", "NEUTRAL")}
    try:
        import yaml
        m = yaml.safe_load((ROOT / "_data" / "moods.yml").read_text(encoding="utf-8")) or {}
        e = m.get(mood)
        if e and e.get("color"):
            return e["color"], (e.get("label") or mood or "neutral").upper()
    except Exception:  # noqa: BLE001
        pass
    return fb.get(mood, ("#00e5ff", (mood or "neutral").upper()))


def _parse_tape(fm):
    """Pull tape rows (label/value/chg/dir/spark) out of front-matter text."""
    rows = []
    block = re.search(r"^tape:\s*\n(.*?)(?=^\w|\Z)", fm + "\n", re.DOTALL | re.MULTILINE)
    scope = block.group(1) if block else fm
    for m in re.finditer(r"-\s*\{([^}]*)\}", scope):
        seg = m.group(1)

        def q(k):  # quote-aware so commas inside "7,384" are safe
            mm = re.search(rf'{k}:\s*"([^"]*)"', seg)
            return mm.group(1).strip() if mm else None
        dm = re.search(r"dir:\s*([A-Za-z]+)", seg)
        sm = re.search(r"spark:\s*\[([^\]]*)\]", seg)
        spark = [float(x) for x in re.findall(r"-?\d+\.?\d*", sm.group(1))] if sm else []
        if q("label"):
            rows.append({"label": q("label"), "value": q("value"), "chg": q("chg"),
                         "dir": dm.group(1) if dm else None, "spark": spark})
    return rows


def _abs_chg(r):
    try:
        return abs(float((r.get("chg") or "0").replace("%", "").replace("+", "")))
    except Exception:  # noqa: BLE001
        return 0.0


FONT_DIR = TOOLS / "fonts"


def _hex_rgb(hx):
    hx = (hx or "#00e5ff").lstrip("#")
    return tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _ai_background(concept, W, H):
    """Optional: an AI-generated background via the OpenAI Images API. Returns a
    PIL RGBA image cropped to WxH, or None if no key / not configured / it fails.
    This is the 'evolve over time' switch: set VEGA_IMAGE_KEY to turn it on."""
    key = os.environ.get("VEGA_IMAGE_KEY") or os.environ.get("OPENAI_IMAGE_KEY")
    if not key or not concept:
        return None
    import base64
    import urllib.request
    from io import BytesIO
    from PIL import Image
    prompt = ("Editorial financial illustration for a market diary cover. Dark, moody, "
              "cinematic fintech aesthetic, abstract, high contrast, no text and no words. "
              "Scene: " + concept)
    payload = json.dumps({"model": "gpt-image-1", "prompt": prompt,
                          "size": "1536x1024", "n": 1}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/images/generations", data=payload,
                                 method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read())
        img = Image.open(BytesIO(base64.b64decode(d["data"][0]["b64_json"]))).convert("RGBA")
        sw, sh = img.size
        scale = max(W / sw, H / sh)
        img = img.resize((int(sw * scale), int(sh * scale)))
        x = (img.size[0] - W) // 2
        y = (img.size[1] - H) // 2
        return img.crop((x, y, x + W, y + H))
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[warn] AI background failed, using designed cover: {e}\n")
        return None


def make_cover(now, slug, fm):
    """Render a bold, clickable PNG cover (YouTube-thumbnail style) from the post's
    own data: big headline, mood art, market context, branding. Raster so it also
    works as the social/OG share image (SVG does not). Optional AI background."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    W, H = 1200, 630
    color = _hex_rgb(_mood_color(field(fm, "mood"))[0])
    mood_label = _mood_color(field(fm, "mood"))[1]
    title = field(fm, "title") or "Market Diary"
    session = (field(fm, "session") or "adhoc").upper()
    concept = field(fm, "image_concept") or ""
    rows = _parse_tape(fm)
    ink, dim, paper = (233, 237, 246), (140, 150, 175), (6, 7, 14)

    def font(name, size):
        return ImageFont.truetype(str(FONT_DIR / name), size)

    # Deterministic per-post fingerprint: small variations so similar days differ.
    h = hashlib.md5((slug + now.strftime("%Y%m%d")).encode()).digest()
    tint = 0.10 + (h[0] % 8) / 100.0        # how strongly the mood tints the bg
    grid_gap = 42 + h[1] % 16

    img = Image.new("RGBA", (W, H), paper + (255,))

    ai = _ai_background(concept, W, H)
    if ai is not None:
        img.alpha_composite(ai)
        scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scrim)
        for y in range(H):                  # darken left + bottom for text legibility
            a = int(205 * (1 - y / H) ** 0.6) if y < H else 0
            sd.line([(0, y), (W, y)], fill=(4, 6, 12, max(70, a)))
        sd.rectangle([0, 0, int(W * 0.62), H], fill=(4, 6, 12, 120))
        img.alpha_composite(scrim)
    else:
        # Designed background: vertical mood-tinted gradient + faint grid + dots.
        top = _mix(paper, color, tint)
        d0 = ImageDraw.Draw(img)
        for y in range(H):
            d0.line([(0, y), (W, y)], fill=_mix(top, paper, y / H) + (255,))
        grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grid)
        for x in range(0, W, grid_gap):
            gd.line([(x, 0), (x, H)], fill=color + (16,))
        for y in range(0, H, grid_gap):
            gd.line([(0, y), (W, y)], fill=color + (16,))
        img.alpha_composite(grid)
        dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dots)
        for k in range(18):
            b1, b2, b3 = h[(k * 3) % 16], h[(k * 3 + 1) % 16], h[(k * 3 + 2) % 16]
            cx, cy, rr = 560 + b1 * 600 // 255, 30 + b2 * 250 // 255, 1 + b3 % 3
            dd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color + (40 + b3 % 60,))
        img.alpha_composite(dots)

    # Chart = the biggest mover's series, drawn low across the lower third.
    sparked = sorted([r for r in rows if len(r.get("spark") or []) >= 2],
                     key=_abs_chg, reverse=True)
    series = sparked[0]["spark"] if sparked else [1, 1.12, 1.05, 1.22, 1.16, 1.4, 1.28, 1.55]
    chart_label = sparked[0]["label"] if sparked else "markets"
    # Color the line by the series' OWN direction (green up / red down), not by the
    # post mood: a rising line must never render red just because the day was risk-off.
    chart_color = (27, 240, 168) if series[-1] >= series[0] else (255, 59, 107)
    cy_top, cy_bot = 372, 568
    mn, mx = min(series), max(series)
    rng = (mx - mn) or 1
    pts = [(i * W / (len(series) - 1), cy_bot - (v - mn) / rng * (cy_bot - cy_top))
           for i, v in enumerate(series)]
    chart = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chart)
    cd.polygon(pts + [(W, H), (0, H)], fill=chart_color + (40,))
    cd.line(pts, fill=chart_color + (180,), width=5, joint="curve")
    chart = chart.filter(ImageFilter.GaussianBlur(0.6))
    img.alpha_composite(chart)

    draw = ImageDraw.Draw(img)

    def glow(xy, text, fnt, fill, gcol, rad=10, anchor=None):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(xy, text, font=fnt, fill=gcol + (180,), anchor=anchor)
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(rad)))
        draw.text(xy, text, font=fnt, fill=fill, anchor=anchor)

    def spaced(xy, text, fnt, fill, gap=6):
        x, y = xy
        for ch in text:
            draw.text((x, y), ch, font=fnt, fill=fill)
            x += draw.textlength(ch, font=fnt) + gap

    # Eyebrow: VEGA'S BELL / SESSION / DATE
    f_eye = font("SpaceMono-Bold.ttf", 21)
    spaced((64, 52), f"VEGA'S BELL  /  {session}  /  {now.strftime('%b %d, %Y').upper()}",
           f_eye, (0, 229, 255), gap=3)

    # Mood badge pill (light text for contrast on the mood-tinted pill)
    f_mood = font("SpaceMono-Bold.ttf", 26)
    mw = draw.textlength(mood_label, font=f_mood)
    draw.rounded_rectangle([64, 96, 64 + mw + 40, 142], radius=10,
                           fill=color + (48,), outline=color + (230,), width=2)
    draw.text((84, 104), mood_label, font=f_mood, fill=(245, 248, 255))

    # Headline: shrink font until it fits <= 3 lines within the width.
    max_w = 1010
    for size in (96, 86, 76, 66, 58):
        f_h = font("Arvo-Bold.ttf", size)
        words, lines, cur = title.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if draw.textlength(t, font=f_h) <= max_w:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= 3:
            break
    lh = int(size * 1.12)
    y = 178
    for ln in lines[:3]:
        glow((64, y), ln, f_h, (244, 248, 255), color, rad=12)
        y += lh

    # Optional hook line (from the writer's image_concept), kept short.
    if concept:
        hook = concept if len(concept) <= 66 else concept[:63].rstrip() + "..."
        draw.text((66, y + 6), hook, font=font("SpaceMono-Regular.ttf", 22), fill=color)

    # Stat strip along the bottom: up to 3 tape rows, green/red by direction.
    f_lab = font("SpaceMono-Bold.ttf", 16)
    f_val = font("SpaceMono-Bold.ttf", 27)
    f_chg = font("SpaceMono-Bold.ttf", 18)
    for i, r in enumerate(rows[:3]):
        x = 64 + i * 372
        up = r.get("dir") == "up"
        c = (27, 240, 168) if up else ((255, 59, 107) if r.get("dir") == "down" else dim)
        spaced((x, 556), str(r.get("label") or "").upper()[:18], f_lab, dim, gap=1)
        val = str(r.get("value") or "")
        draw.text((x, 580), val, font=f_val, fill=ink)
        draw.text((x + draw.textlength(val, font=f_val) + 12, 588),
                  str(r.get("chg") or ""), font=f_chg, fill=c)

    # Branding mark (the neon V) top-right.
    try:
        logo = Image.open(ROOT / "assets" / "img" / "logo.png").convert("RGBA")
        logo = logo.resize((58, 58))
        img.alpha_composite(logo, (W - 58 - 56, 44))
    except Exception:  # noqa: BLE001
        pass

    journal = ROOT / "assets" / "journal"
    journal.mkdir(parents=True, exist_ok=True)
    fname = f"{now.strftime('%Y-%m-%d')}-{slug}.png"
    img.convert("RGB").save(journal / fname, "PNG", optimize=True)
    return f"/assets/journal/{fname}"


SVG_FENCE_RE = re.compile(r"```(?:svg|xml|html)?\s*\n?\s*(<svg\b.*?</svg>)\s*\n?```",
                          re.DOTALL | re.IGNORECASE)
SVG_RAW_RE = re.compile(r"<svg\b.*?</svg>", re.DOTALL | re.IGNORECASE)


def extract_svg(body):
    """Pull Vega's hand-drawn cover SVG out of the body. Accepts a fenced ```svg
    block (preferred) or a bare <svg>...</svg>. Returns (svg_or_None, body_without_it)."""
    m = SVG_FENCE_RE.search(body)
    if m:
        svg = m.group(1)
    else:
        m = SVG_RAW_RE.search(body)
        if not m:
            return None, body
        svg = m.group(0)
    cleaned = (body[:m.start()] + body[m.end():]).strip()
    return svg, cleaned


def sanitize_svg(svg):
    """Validate the writer's SVG is a safe, self-contained illustration. Raises
    ValueError if it is unusable; returns the (lightly normalized) markup."""
    s = svg.strip()
    low = s.lower()
    if not low.startswith("<svg") or "</svg>" not in low:
        raise ValueError("not a complete <svg> element")
    # No scripts, no external/remote references, no raster embeds, no foreign HTML.
    for bad in ("<script", "<foreignobject", "javascript:", "<image", "<iframe",
                'href="http', "href='http", "url(http", "<!entity", "<!doctype"):
        if bad in low:
            raise ValueError(f"disallowed content in cover svg: {bad!r}")
    if "—" in s or "–" in s:
        raise ValueError("cover svg contains a forbidden em/en-dash")
    if "xmlns=" not in low:
        s = s.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    if "viewbox" not in low:                       # keep the 1200x630 cover ratio
        s = s.replace("<svg", '<svg viewBox="0 0 1200 630"', 1)
    return s


def save_cover_svg(now, slug, svg):
    """Sanitize and write the cover SVG. Returns its site-relative path."""
    s = sanitize_svg(svg)
    journal = ROOT / "assets" / "journal"
    journal.mkdir(parents=True, exist_ok=True)
    fname = f"{now.strftime('%Y-%m-%d')}-{slug}.svg"
    (journal / fname).write_text(s, encoding="utf-8")
    return f"/assets/journal/{fname}"


def rasterize_svg(svg_abspath, png_abspath, W, H):
    """SVG -> PNG for the social / OG card (SVG is not a valid OG image). Returns the
    site-relative PNG path, or None if no rasterizer is installed (caller falls back
    to the Pillow template so the pipeline never breaks)."""
    try:
        import cairosvg
    except Exception:  # noqa: BLE001 — cairosvg + system Cairo are optional
        return None
    try:
        cairosvg.svg2png(url=str(svg_abspath), write_to=str(png_abspath),
                         output_width=W, output_height=H, background_color="#06070e")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[warn] SVG rasterize failed: {e}\n")
        return None
    return "/" + str(png_abspath.relative_to(ROOT)).replace("\\", "/")


def augment(entry, now, snapshot):
    """Inject sparkline series, then wire up the cover. Vega draws a bespoke SVG
    illustration per entry (like Trinity/Doaia); we save it as the on-page cover and
    rasterize a PNG for social/OG cards. If the writer emits no usable SVG, we fall
    back to the designed Pillow template so a post is never left without a cover."""
    fm, body = split_front_matter(entry)
    if fm is None:
        return entry
    slug = field(fm, "slug") or re.sub(r"[^a-z0-9]+", "-", (field(fm, "title") or "entry").lower()).strip("-")

    # 1) inject sparkline series into each tape row (from the live snapshot)
    def add_spark(m):
        row = m.group(0)
        if "spark:" in row:
            return row
        lab = (re.search(r'label:\s*"([^"]+)"', row) or [None, ""])[1]
        s = match_spark(lab, snapshot)
        return row if not s else row.rstrip()[:-1].rstrip() + f", spark: {s} }}"
    new_fm = re.sub(r"-\s*\{[^}]*\}", add_spark, fm)

    # 2) cover art. Pull Vega's hand-drawn SVG out of the body (it never renders as
    # prose), save it, and try to rasterize a PNG for social cards.
    svg, body = extract_svg(body)
    img_svg = None
    if svg:
        try:
            img_svg = save_cover_svg(now, slug, svg)
        except ValueError as e:
            sys.stderr.write(f"[warn] cover svg rejected, using template: {e}\n")

    try:
        if img_svg:
            if "image:" not in new_fm:
                new_fm = f'image: "{img_svg}"\n' + new_fm
            if "image_alt:" not in new_fm:
                alt = (field(new_fm, "image_concept") or field(new_fm, "title") or
                       "Vega's Bell cover illustration").replace('"', "'")
                new_fm = f'image_alt: "{alt}"\n' + new_fm
            png = ROOT / "assets" / "journal" / f"{now.strftime('%Y-%m-%d')}-{slug}.png"
            og = rasterize_svg(ROOT / img_svg.lstrip("/"), png, 1200, 630)
            if not og:                       # no rasterizer: keep social cards working
                og = make_cover(now, slug, new_fm)
            if og and "og_image:" not in new_fm:
                new_fm = f'og_image: "{og}"\n' + new_fm
        else:
            img = make_cover(now, slug, new_fm)
            if img and "image:" not in new_fm:
                new_fm = f'image: "{img}"\n' + new_fm
            if img and "og_image:" not in new_fm:
                new_fm = f'og_image: "{img}"\n' + new_fm
    except Exception as e:  # noqa: BLE001 — cover is decorative, never block publish
        sys.stderr.write(f"[warn] cover generation failed: {e}\n")

    return f"---\n{new_fm}\n---\n{body}"


def save_and_publish(entry, now, dry_run, no_push):
    fm, _ = split_front_matter(entry)
    slug = field(fm, "slug")
    # Cover artifacts: image is the on-page SVG, og_image the rasterized social PNG.
    covers = [c for c in (field(fm, "image"), field(fm, "og_image")) if c]
    fname = f"{now.strftime('%Y-%m-%d')}-{slug}.md"
    dest = POSTS / fname

    if dry_run:
        print(f"--- DRY RUN: would write {dest} ---\n")
        print(entry)
        # Tidy: drop the cover files this dry run generated so they never linger
        # untracked (and can't be swept into a later real commit).
        if not dest.exists():
            for c in covers:
                cov = ROOT / c.lstrip("/")
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
    for c in covers:
        cov = ROOT / c.lstrip("/")
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
    ap.add_argument("--session", choices=["open", "close", "radar", "adhoc"], default="adhoc")
    ap.add_argument("--topic", default=None,
                    help="for --session radar: the catalyst to cover (auto-picks if omitted)")
    ap.add_argument("--dry-run", action="store_true", help="print the entry, write nothing")
    ap.add_argument("--no-push", action="store_true", help="commit but do not push")
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    now = datetime.now(TZ)
    topic = None
    if args.session == "radar":
        print(f"[*] radar piece — researching: {args.topic or '(auto-pick)'}…")
        brief, topic = fetch_topic_brief(args.topic)
        print(f"[*] topic resolved to: {topic}")
        snapshot_file = TOOLS / "topic_snapshot.json"   # has no market tape; cover uses fallback
    else:
        print(f"[*] {args.session} session — fetching market brief…")
        brief = fetch_brief(args.session)
        snapshot_file = TOOLS / "market_snapshot.json"

    memory = gather_memory()
    if memory:
        print("[*] feeding Vega its recent track record (self-learning)")
    print("[*] asking Vega (Hermes) to write…")
    entry = call_hermes(build_prompt(args.session, now, brief, memory, topic))

    ok, reason = validate(entry, brief)
    if not ok:
        sys.exit(f"[error] generated entry failed validation: {reason}\n\n{entry[:800]}")
    print("[ok] entry validated")

    # Enrich with an auto-generated cover image + sparkline data (best effort).
    # Radar pieces have no market tape, so the cover falls back to a designed look.
    try:
        snapshot = {}
        if args.session != "radar":
            snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
        entry = augment(entry, now, snapshot)
        print("[ok] cover image + sparklines added")
    except Exception as e:  # noqa: BLE001 — enrichment must never block publishing
        sys.stderr.write(f"[warn] enrichment skipped: {e}\n")

    save_and_publish(entry, now, args.dry_run, args.no_push)


if __name__ == "__main__":
    main()
