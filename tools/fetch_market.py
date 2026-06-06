#!/usr/bin/env python3
"""fetch_market.py — Vega's market sensor.

Pulls a snapshot of global markets from FREE, no-API-key sources and emits:
  - market_snapshot.json  (structured data, for tooling)
  - market_brief.md       (human/LLM-readable digest, fed to the writer)
and prints the brief to stdout.

Stdlib only (urllib/json/xml) so it runs anywhere Python 3.8+ is installed,
no `pip install` required. Every source is wrapped so one outage never sinks
the whole snapshot — missing pieces are marked "unavailable" and the rest
still renders.

Usage:
    python fetch_market.py [--session open|close] [--out DIR]

Sources (all keyless):
  Stock indices + VIX  Yahoo Finance chart v8
  Crypto prices/24h    CoinGecko simple/price
  Crypto market cap    CoinGecko global
  Crypto Fear & Greed  alternative.me
  Headlines            Yahoo Finance RSS
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

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VegaMarketDiary/1.0"

# --- What Vega watches ------------------------------------------------------
# Yahoo symbols for indices / volatility (^ = index).
INDICES = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq Composite"),
    ("^DJI", "Dow Jones"),
    ("^RUT", "Russell 2000"),
    ("^VIX", "VIX (volatility)"),
    ("^N225", "Nikkei 225"),
    ("^FTSE", "FTSE 100"),
]
# CoinGecko ids -> display symbol.
CRYPTO = [
    ("bitcoin", "BTC"),
    ("ethereum", "ETH"),
    ("solana", "SOL"),
    ("binancecoin", "BNB"),
    ("ripple", "XRP"),
    ("dogecoin", "DOGE"),
    ("cardano", "ADA"),
]
NEWS_RSS = "https://finance.yahoo.com/news/rssindex"
MAX_HEADLINES = 8


def _get(url, timeout=15, retries=2):
    """GET a URL with a browser UA. Returns raw bytes, or None on failure."""
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 429:  # rate limited — back off and retry
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        except Exception as e:  # noqa: BLE001 — any network hiccup
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


def _pct(now, prev):
    if not prev:
        return None
    return round((now - prev) / prev * 100, 2)


# --- Stocks / indices via Yahoo chart v8 ------------------------------------
def fetch_indices():
    out = []
    for sym, name in INDICES:
        q = urllib.parse.quote(sym)
        data = _get_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?interval=1d&range=5d"
        )
        row = {"symbol": sym, "name": name, "price": None, "change_pct": None, "available": False}
        try:
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            row.update(
                price=price,
                prev_close=prev,
                change_pct=_pct(price, prev),
                currency=meta.get("currency"),
                available=price is not None,
            )
        except Exception:  # noqa: BLE001 — leave row marked unavailable
            pass
        out.append(row)
        time.sleep(0.2)  # be polite
    return out


# --- Crypto via CoinGecko ---------------------------------------------------
def fetch_crypto():
    ids = ",".join(c[0] for c in CRYPTO)
    data = _get_json(
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true"
    )
    out = []
    for cid, sym in CRYPTO:
        row = {"id": cid, "symbol": sym, "price": None, "change_pct": None, "available": False}
        if data and cid in data:
            d = data[cid]
            row.update(
                price=d.get("usd"),
                change_pct=round(d.get("usd_24h_change"), 2) if d.get("usd_24h_change") is not None else None,
                market_cap=d.get("usd_market_cap"),
                available=d.get("usd") is not None,
            )
        out.append(row)
    return out


def fetch_crypto_global():
    data = _get_json("https://api.coingecko.com/api/v3/global")
    if not data or "data" not in data:
        return {"available": False}
    d = data["data"]
    return {
        "available": True,
        "total_market_cap_usd": d.get("total_market_cap", {}).get("usd"),
        "market_cap_change_24h_pct": round(d.get("market_cap_change_percentage_24h_usd"), 2)
        if d.get("market_cap_change_percentage_24h_usd") is not None else None,
        "btc_dominance": round(d.get("market_cap_percentage", {}).get("btc"), 1)
        if d.get("market_cap_percentage", {}).get("btc") is not None else None,
        "eth_dominance": round(d.get("market_cap_percentage", {}).get("eth"), 1)
        if d.get("market_cap_percentage", {}).get("eth") is not None else None,
    }


def fetch_crypto_fng():
    data = _get_json("https://api.alternative.me/fng/?limit=1")
    try:
        d = data["data"][0]
        return {"available": True, "value": int(d["value"]), "label": d["value_classification"]}
    except Exception:  # noqa: BLE001
        return {"available": False}


# --- News via Yahoo Finance RSS ---------------------------------------------
def fetch_headlines():
    raw = _get(NEWS_RSS)
    if raw is None:
        return []
    try:
        root = ET.fromstring(raw)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title")
            if title:
                items.append(title.strip())
            if len(items) >= MAX_HEADLINES:
                break
        return items
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[warn] rss parse failed: {e}\n")
        return []


# --- Assemble ---------------------------------------------------------------
def build_snapshot(session):
    now = datetime.now(timezone.utc)
    return {
        "generated_utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "session": session,
        "indices": fetch_indices(),
        "crypto": fetch_crypto(),
        "crypto_global": fetch_crypto_global(),
        "crypto_fear_greed": fetch_crypto_fng(),
        "headlines": fetch_headlines(),
    }


def _fmt_price(v):
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 1:
        return f"{v:,.2f}"
    return f"{v:.4f}"


def _arrow(pct):
    if pct is None:
        return ""
    return "▲" if pct > 0 else ("▼" if pct < 0 else "▬")


def render_brief(snap):
    L = []
    L.append(f"# Market Brief — {snap['session']} session")
    L.append(f"_Generated {snap['generated_utc']}_\n")

    L.append("## Equity indices")
    for r in snap["indices"]:
        if r["available"]:
            L.append(f"- **{r['name']}** ({r['symbol']}): {_fmt_price(r['price'])} "
                     f"{_arrow(r['change_pct'])} {r['change_pct']:+.2f}%"
                     if r["change_pct"] is not None
                     else f"- **{r['name']}** ({r['symbol']}): {_fmt_price(r['price'])}")
        else:
            L.append(f"- **{r['name']}** ({r['symbol']}): unavailable")

    L.append("\n## Crypto")
    g = snap["crypto_global"]
    if g.get("available"):
        tmc = g["total_market_cap_usd"]
        L.append(f"- Total market cap: ${tmc/1e12:.2f}T "
                 f"({g['market_cap_change_24h_pct']:+.2f}% 24h)" if g.get("market_cap_change_24h_pct") is not None
                 else f"- Total market cap: ${tmc/1e12:.2f}T")
        L.append(f"- BTC dominance: {g['btc_dominance']}%  |  ETH dominance: {g['eth_dominance']}%")
    fng = snap["crypto_fear_greed"]
    if fng.get("available"):
        L.append(f"- Fear & Greed: **{fng['value']}/100 — {fng['label']}**")
    for r in snap["crypto"]:
        if r["available"]:
            L.append(f"- **{r['symbol']}**: ${_fmt_price(r['price'])} "
                     f"{_arrow(r['change_pct'])} {r['change_pct']:+.2f}% (24h)"
                     if r["change_pct"] is not None
                     else f"- **{r['symbol']}**: ${_fmt_price(r['price'])}")
        else:
            L.append(f"- **{r['symbol']}**: unavailable")

    L.append("\n## Headlines")
    if snap["headlines"]:
        for h in snap["headlines"]:
            L.append(f"- {h}")
    else:
        L.append("- (no headlines retrieved)")

    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Fetch a keyless market snapshot for Vega.")
    ap.add_argument("--session", choices=["open", "close", "adhoc"], default="adhoc")
    ap.add_argument("--out", default=".", help="directory to write snapshot files into")
    args = ap.parse_args()

    # Windows consoles default to a legacy codepage (e.g. cp949) that can't
    # encode the em-dashes/arrows in the brief. Force UTF-8 so stdout never
    # crashes the run and Task Scheduler sees a clean exit code.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001 — older Python / already-utf8
            pass

    snap = build_snapshot(args.session)
    brief = render_brief(snap)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "market_snapshot.json").write_text(json.dumps(snap, indent=2), encoding="utf-8")
    (outdir / "market_brief.md").write_text(brief, encoding="utf-8")

    sys.stdout.write(brief)


if __name__ == "__main__":
    main()
