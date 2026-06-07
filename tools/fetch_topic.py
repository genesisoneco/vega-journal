#!/usr/bin/env python3
"""fetch_topic.py — Vega's research sensor for topical "On the Radar" pieces.

Given a topic (for example "SpaceX IPO"), pull a focused, SOURCED bundle so Vega
writes from facts, not memory. This matters because the house anti-fabrication
rule forbids inventing numbers: every figure Vega cites in a radar piece must
appear in this bundle. Emits:
  - topic_snapshot.json  (structured)
  - topic_brief.md       (fed to the radar writer; the source of allowed numbers)

All sources are keyless and stdlib-only:
  News      Google News RSS search
  Filings   SEC EDGAR full-text search (best effort)
  Trending  Yahoo trending tickers (used to auto-pick a topic if none given)

Usage:
    python fetch_topic.py --topic "SpaceX IPO" [--out DIR]
    python fetch_topic.py                     # auto-pick from trending tickers
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# SEC requires a descriptive UA with contact; reuse a real-looking browser UA
# for the others. (vega@vegabell.com is the project contact.)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VegaMarketDiary/1.0 (vega@vegabell.com)"
MAX_NEWS = 14
MAX_FILINGS = 6


def _get(url, timeout=15, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(0.8 * (attempt + 1))
    sys.stderr.write(f"[warn] fetch failed: {url} ({last})\n")
    return None


def _get_json(url, **kw):
    raw = _get(url, **kw)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[warn] bad json from {url}: {e}\n")
        return None


# --- News via Google News RSS search ----------------------------------------
def search_news(topic):
    q = urllib.parse.quote(topic)
    raw = _get(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
    if raw is None:
        return []
    out = []
    try:
        root = ET.fromstring(raw)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            src_el = item.find("source")
            source = (src_el.text.strip() if src_el is not None and src_el.text else "")
            pub = (item.findtext("pubDate") or "").strip()
            out.append({"title": title, "source": source, "date": pub[:16]})
            if len(out) >= MAX_NEWS:
                break
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[warn] news parse failed: {e}\n")
    return out


# --- Filings via SEC EDGAR full-text search (best effort) -------------------
def search_filings(topic):
    q = urllib.parse.quote(f'"{topic}"')
    data = _get_json(f"https://efts.sec.gov/LATEST/search-index?q={q}")
    out = []
    try:
        for h in (data.get("hits", {}).get("hits", []) or [])[:MAX_FILINGS]:
            s = h.get("_source", {})
            forms = s.get("file_type") or (s.get("forms") or [""])[0]
            disp = (s.get("display_names") or [""])[0]
            date = s.get("file_date") or s.get("filed", "")
            out.append({"form": forms, "filer": disp, "date": date})
    except Exception:  # noqa: BLE001
        pass
    return out


# --- Trending (to auto-pick a topic) ----------------------------------------
def trending_symbols():
    data = _get_json("https://query1.finance.yahoo.com/v1/finance/trending/US?count=10")
    try:
        quotes = data["finance"]["result"][0]["quotes"]
        return [q.get("symbol") for q in quotes if q.get("symbol")]
    except Exception:  # noqa: BLE001
        return []


def build(topic):
    now = datetime.now(timezone.utc)
    return {
        "generated_utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "topic": topic,
        "news": search_news(topic),
        "filings": search_filings(topic),
    }


def render_brief(snap):
    L = [f"# Research Brief: {snap['topic']}",
         f"_Generated {snap['generated_utc']}_",
         "",
         "Use ONLY facts and figures that appear below. If a number you want is not",
         "here, do not state it. Attribute claims to their source when you can.",
         "",
         "## Recent news"]
    if snap["news"]:
        for n in snap["news"]:
            src = f" ({n['source']})" if n["source"] else ""
            when = f" - {n['date']}" if n["date"] else ""
            L.append(f"- {n['title']}{src}{when}")
    else:
        L.append("- (no news retrieved)")
    if snap["filings"]:
        L.append("\n## SEC filings (full-text search)")
        for f in snap["filings"]:
            L.append(f"- {f.get('form', '')} - {f.get('filer', '')} ({f.get('date', '')})")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Fetch a sourced research bundle for a topic.")
    ap.add_argument("--topic", default=None, help="topic to research; auto-picks if omitted")
    ap.add_argument("--out", default=".", help="directory to write output into")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    topic = args.topic
    if not topic:
        syms = trending_symbols()
        topic = f"{syms[0]} stock" if syms else "stock market today"
        sys.stderr.write(f"[info] no topic given; auto-picked: {topic}\n")

    snap = build(topic)
    brief = render_brief(snap)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "topic_snapshot.json").write_text(json.dumps(snap, indent=2), encoding="utf-8")
    (outdir / "topic_brief.md").write_text(brief, encoding="utf-8")
    sys.stdout.write(brief)


if __name__ == "__main__":
    main()
