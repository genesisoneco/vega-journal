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
    ("GC=F", "Gold"),
    ("SI=F", "Silver"),
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
# Rates + the dollar: the macro backdrop that drives equities and crypto.
# ^TNX is the US 10Y yield (quoted as the percent, e.g. 4.25). DX-Y.NYB is the
# ICE US Dollar Index. Both work from Yahoo chart v8 like any index.
RATES = [
    ("^TNX", "US 10Y Yield"),
    ("^TYX", "US 30Y Yield"),
    ("DX-Y.NYB", "US Dollar Index"),
]
# SPDR sector ETFs -> sector name. Used for sector leaders/laggards and as a
# keyless breadth proxy (how many sectors are green).
SECTORS = [
    ("XLK", "Technology"),
    ("XLF", "Financials"),
    ("XLY", "Consumer Disc."),
    ("XLP", "Consumer Staples"),
    ("XLE", "Energy"),
    ("XLV", "Health Care"),
    ("XLI", "Industrials"),
    ("XLB", "Materials"),
    ("XLRE", "Real Estate"),
    ("XLU", "Utilities"),
    ("XLC", "Communications"),
]
# Symbols we compute daily technicals for (needs a longer daily history).
TECH_SYMBOLS = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq Composite"),
    ("^DJI", "Dow Jones"),
    ("^RUT", "Russell 2000"),
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
def _downsample(series, target=24):
    """Trim a numeric series to ~target points, dropping Nones, rounded."""
    clean = [round(v, 2) for v in series if v is not None]
    if len(clean) <= target:
        return clean
    step = len(clean) / target
    return [clean[int(i * step)] for i in range(target)]


def fetch_quotes(pairs, spark=True):
    """Fetch price/change (and optionally a sparkline) for a list of
    (symbol, name) pairs via Yahoo chart v8. Each row degrades on its own."""
    out = []
    for sym, name in pairs:
        q = urllib.parse.quote(sym)
        # 60m/5d gives a richer series for the sparkline; meta still has price/prev.
        data = _get_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?interval=60m&range=5d"
        )
        row = {"symbol": sym, "name": name, "price": None, "change_pct": None,
               "spark": [], "available": False}
        try:
            res = data["chart"]["result"][0]
            meta = res["meta"]
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            if spark:
                try:
                    closes = res["indicators"]["quote"][0]["close"]
                    row["spark"] = _downsample(closes)
                except Exception:  # noqa: BLE001
                    pass
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


def fetch_indices():
    return fetch_quotes(INDICES)


def fetch_rates():
    return fetch_quotes(RATES)


def fetch_sectors():
    """Sector ETFs with 1-day change. No sparkline (we only need the move).
    Returns rows sorted strongest-first plus a breadth proxy."""
    rows = fetch_quotes(SECTORS, spark=False)
    avail = [r for r in rows if r["available"] and r["change_pct"] is not None]
    avail.sort(key=lambda r: r["change_pct"], reverse=True)
    up = sum(1 for r in avail if r["change_pct"] > 0)
    down = sum(1 for r in avail if r["change_pct"] < 0)
    return {
        "rows": avail,
        "leaders": avail[:3],
        "laggards": avail[-3:][::-1] if len(avail) >= 3 else [],
        "breadth_up": up,
        "breadth_down": down,
        "breadth_total": len(avail),
        "available": bool(avail),
    }


# --- Local technicals (computed, no extra source needed) --------------------
def _rsi(closes, period=14):
    """Wilder's RSI over a list of closes. None if not enough data."""
    if len(closes) < period + 1:
        return None
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def fetch_technicals():
    """Daily-bar technicals (SMA20/50, RSI14, 20d momentum, % off 6mo high) for
    the key indices. One extra Yahoo call each (interval=1d&range=6mo)."""
    out = []
    for sym, name in TECH_SYMBOLS:
        q = urllib.parse.quote(sym)
        data = _get_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?interval=1d&range=6mo"
        )
        row = {"symbol": sym, "name": name, "available": False}
        try:
            res = data["chart"]["result"][0]
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
            if len(closes) >= 50:
                price = closes[-1]
                sma20 = sum(closes[-20:]) / 20
                sma50 = sum(closes[-50:]) / 50
                hi = max(closes)
                mom20 = _pct(price, closes[-21]) if len(closes) >= 21 else None
                row.update(
                    available=True,
                    price=round(price, 2),
                    vs_sma20="above" if price >= sma20 else "below",
                    vs_sma50="above" if price >= sma50 else "below",
                    rsi14=_rsi(closes),
                    mom20_pct=mom20,
                    pct_off_high=round((price / hi - 1) * 100, 1) if hi else None,
                )
        except Exception:  # noqa: BLE001
            pass
        out.append(row)
        time.sleep(0.2)
    return out


def fetch_crypto_spark(symbol):
    """Short hourly close series for a coin via Binance klines (keyless)."""
    data = _get_json(
        f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=1h&limit=48"
    )
    if not data:
        return []
    try:
        return _downsample([float(k[4]) for k in data])  # index 4 = close
    except Exception:  # noqa: BLE001
        return []


# --- Crypto via CoinGecko ---------------------------------------------------
def fetch_crypto():
    ids = ",".join(c[0] for c in CRYPTO)
    data = _get_json(
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true"
    )
    out = []
    for cid, sym in CRYPTO:
        row = {"id": cid, "symbol": sym, "price": None, "change_pct": None,
               "spark": [], "available": False}
        if data and cid in data:
            d = data[cid]
            row.update(
                price=d.get("usd"),
                change_pct=round(d.get("usd_24h_change"), 2) if d.get("usd_24h_change") is not None else None,
                market_cap=d.get("usd_market_cap"),
                available=d.get("usd") is not None,
            )
            row["spark"] = fetch_crypto_spark(sym)
            time.sleep(0.15)
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


# --- Curated calendar -------------------------------------------------------
# tools/calendar.txt is a hand-kept list of known macro events, one per line:
#   2026-06-18 | FOMC rate decision
# We surface only events within the next ~12 days. Keyless, stdlib-only; this is
# the honest stopgap for the one area where free real-time calendar data is thin.
def read_calendar(window_days=12):
    path = Path(__file__).resolve().parent / "calendar.txt"
    if not path.exists():
        return []
    today = datetime.now(timezone.utc).date()
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        ds, _, label = line.partition("|")
        try:
            d = datetime.strptime(ds.strip(), "%Y-%m-%d").date()
        except ValueError:
            continue
        delta = (d - today).days
        if 0 <= delta <= window_days:
            out.append({"date": ds.strip(), "in_days": delta, "event": label.strip()})
    out.sort(key=lambda e: e["in_days"])
    return out


# --- Vega Fear Gauge --------------------------------------------------------
# A transparent 0-100 risk-sentiment composite. 0 = extreme fear, 100 = extreme
# greed. Formula is published on the site (the point is reproducibility, not a
# black box). Each component is averaged only if available.
def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def vega_fear_gauge(snap):
    parts = {}
    # VIX: ~12 calm (greed) -> ~35 stressed (fear), inverted and clamped.
    for r in snap["indices"]:
        if r["symbol"] == "^VIX" and r.get("price") is not None:
            parts["vix"] = round(_clamp(100 * (35 - r["price"]) / (35 - 12)), 1)
            break
    # Breadth: share of sectors green.
    sec = snap.get("sectors", {})
    if sec.get("breadth_total"):
        parts["breadth"] = round(100 * sec["breadth_up"] / sec["breadth_total"], 1)
    # Momentum: S&P 20-day momentum, +5% -> greedy, -5% -> fearful.
    for t in snap.get("technicals", []):
        if t["symbol"] == "^GSPC" and t.get("mom20_pct") is not None:
            parts["momentum"] = round(_clamp(50 + t["mom20_pct"] * 5), 1)
            break
    # Crypto Fear & Greed is already a 0-100 greed index.
    fng = snap.get("crypto_fear_greed", {})
    if fng.get("available"):
        parts["crypto"] = float(fng["value"])
    if not parts:
        return {"available": False}
    score = round(sum(parts.values()) / len(parts))
    if score < 25:
        label = "Extreme Fear"
    elif score < 45:
        label = "Fear"
    elif score < 55:
        label = "Neutral"
    elif score < 75:
        label = "Greed"
    else:
        label = "Extreme Greed"
    return {"available": True, "score": score, "label": label, "components": parts}


# --- Assemble ---------------------------------------------------------------
def build_snapshot(session):
    now = datetime.now(timezone.utc)
    snap = {
        "generated_utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "session": session,
        "indices": fetch_indices(),
        "rates": fetch_rates(),
        "sectors": fetch_sectors(),
        "technicals": fetch_technicals(),
        "crypto": fetch_crypto(),
        "crypto_global": fetch_crypto_global(),
        "crypto_fear_greed": fetch_crypto_fng(),
        "calendar": read_calendar(),
        "headlines": fetch_headlines(),
    }
    snap["fear_gauge"] = vega_fear_gauge(snap)
    return snap


def _fmt_price(v):
    if v is None:
        return "n/a"
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

    fg = snap.get("fear_gauge", {})
    if fg.get("available"):
        comp = ", ".join(f"{k} {int(v)}" for k, v in fg["components"].items())
        L.append(f"\n## Vega Fear Gauge: **{fg['score']}/100 — {fg['label']}**")
        L.append(f"_(composite of {comp}; 0 = extreme fear, 100 = extreme greed)_")

    rates = snap.get("rates", [])
    if any(r["available"] for r in rates):
        L.append("\n## Rates and the dollar")
        for r in rates:
            if r["available"]:
                L.append(f"- **{r['name']}** ({r['symbol']}): {_fmt_price(r['price'])} "
                         f"{_arrow(r['change_pct'])} {r['change_pct']:+.2f}%"
                         if r["change_pct"] is not None
                         else f"- **{r['name']}** ({r['symbol']}): {_fmt_price(r['price'])}")
            else:
                L.append(f"- **{r['name']}** ({r['symbol']}): unavailable")

    techs = [t for t in snap.get("technicals", []) if t.get("available")]
    if techs:
        L.append("\n## Technicals (daily)")
        for t in techs:
            bits = [f"vs 20d MA: {t['vs_sma20']}", f"vs 50d MA: {t['vs_sma50']}"]
            if t.get("rsi14") is not None:
                bits.append(f"RSI14 {t['rsi14']}")
            if t.get("mom20_pct") is not None:
                bits.append(f"20d mom {t['mom20_pct']:+.1f}%")
            if t.get("pct_off_high") is not None:
                bits.append(f"{t['pct_off_high']:+.1f}% off 6mo high")
            L.append(f"- **{t['name']}**: " + ", ".join(bits))

    sec = snap.get("sectors", {})
    if sec.get("available"):
        L.append("\n## Sectors")
        L.append(f"- Breadth: {sec['breadth_up']}/{sec['breadth_total']} sectors green "
                 f"(proxy for market breadth)")
        if sec.get("leaders"):
            lead = ", ".join(f"{r['name']} {r['change_pct']:+.2f}%" for r in sec["leaders"])
            L.append(f"- Leaders: {lead}")
        if sec.get("laggards"):
            lag = ", ".join(f"{r['name']} {r['change_pct']:+.2f}%" for r in sec["laggards"])
            L.append(f"- Laggards: {lag}")

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

    cal = snap.get("calendar", [])
    if cal:
        L.append("\n## On the calendar")
        for e in cal:
            when = "today" if e["in_days"] == 0 else (
                "tomorrow" if e["in_days"] == 1 else f"in {e['in_days']} days")
            L.append(f"- {e['date']} ({when}): {e['event']}")

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
