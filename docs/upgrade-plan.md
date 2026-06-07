# Vega's Bell - Upgrade Plan

Three workstreams to make Vega (1) reason from better indicators, (2) genuinely
improve over time, and (3) cover trending catalysts (SpaceX IPO style) to grow
subscribers. No em-dashes anywhere, per the house rule.

> **STATUS: all three workstreams BUILT (C, then B, then A).** Verified locally:
> every tool `py_compile`s; `fetch_market.py` renders the new Fear Gauge / rates /
> technicals / sectors / calendar sections; `fetch_topic.py` returns sourced
> SpaceX news + real EDGAR filings; `reflect.py --no-llm` writes calibration; a
> simulated radar entry passes `validate()` and generates a cover. NOT verified
> end to end: anything needing the Hermes CLI (not on this machine), namely live
> writing, prediction grading, and the playbook rewrite. Next step is to run on
> sejcore and add the two optional cron lines (see docs/sejcore-cron-setup.md).

## Guiding principle

The moat is credibility, not alpha. Markets are near-efficient and no indicator
set turns an LLM into a reliable forecaster. So every upgrade below serves one of
two honest goals: sharper reasoning, or a more transparent and better-calibrated
public track record. We do not market prediction accuracy we cannot back up.

One invariant must survive all three workstreams: **every number Vega writes must
trace back to fetched text.** Today `validate()` enforces this for the `tape:`
block against `market_brief.md`. We extend the same rule to new data and to
research-backed topical pieces. Fabrication stays the one unforgivable error.

## Current pipeline (what we are extending)

- `tools/fetch_market.py` - keyless, stdlib-only sensor. Emits
  `market_snapshot.json` + `market_brief.md`. Indices + VIX + gold/silver
  (Yahoo chart v8), 7 crypto + crypto Fear&Greed (CoinGecko/alternative.me),
  Yahoo RSS headlines.
- `tools/new_entry.py` - orchestrator: `fetch_brief` -> `gather_memory` (last 6
  calls + hit-rate) -> `build_prompt` (WRITER.md + memory + brief) -> `call_hermes`
  -> `validate` -> `augment` (PNG cover + sparklines) -> `save_and_publish`
  (targeted `git add`, commit, push, optional notify).
- `tools/grade_predictions.py` - finds due predictions, Hermes-as-judge
  (HIT/MISS/UNCLEAR), writes outcome back, commits.
- `tools/WRITER.md` - persona + schema + rules. Sessions are `open` | `close`.
- Autonomy: 4 Linux cron jobs on `sejcore` (open, close, responder, grader).

---

## Workstream C - Richer indicators (build first: low risk, lifts everything)

All additions stay keyless and stdlib-only, each wrapped so one outage never
sinks the snapshot (existing pattern in `fetch_market.py`).

### C1. Rates and the dollar
Add to `INDICES`: `^TNX` (US 10Y yield), `^TYX` (30Y, optional), and a dollar
gauge. DXY via `DX-Y.NYB` (test first; the futures `DX=F` needs
`interval=30m&range=5d` per the known Yahoo gotcha). Rates and the dollar drive
everything and are the single biggest gap today.

### C2. Local technicals (free, computed, no new source)
New `compute_technicals()`. For the key indices, add a second Yahoo call
(`interval=1d&range=6mo`) to get daily closes, then compute per index:
- price vs SMA20 and SMA50 (above/below),
- RSI(14),
- 20-day momentum (% change),
- % off the 6mo high (proxy for "stretched").
Emit into snapshot + a new brief section "Technicals". This alone moves Vega from
"it fell 2%" to "below the 50-day with RSI in the low 30s."

### C3. Sectors and a breadth proxy
Fetch the 11 SPDR sector ETFs (XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLB, XLRE, XLU,
XLC) via Yahoo chart v8 for the 1-day change. Brief shows sector leaders and
laggards. Breadth proxy = count of sectors up vs down (label it honestly as a
proxy; true keyless advance/decline data is not reliable).

### C4. The "Vega Fear Gauge" (signature indicator)
A composite 0-100 score from VIX (inverted percentile), breadth, index momentum,
and crypto Fear&Greed. Publish the formula openly (credibility). This becomes a
branded number we can show in the ticker, on a small home widget, and in the
brief. It is honest because it is transparent and reproducible.

### C5. Economic / earnings calendar (weakest free area, optional)
No clean keyless source. Options, in order of preference:
- v1: a small curated `_data/calendar.yml` of known recurring events (FOMC dates,
  CPI/jobs cadence) that the open session can reference.
- later: a paid feed (Trading Economics / Finnhub free tier) behind an env-gated
  key, same pattern as `VEGA_IMAGE_KEY`.
Be explicit that this is the one area where "best indicators" hits a free-data
wall.

**Files:** edit `tools/fetch_market.py` (new fetchers + `render_brief` sections),
optional `_data/calendar.yml`, optional `_data/tickers.yml` + Worker `/api/ticker`
if we want rates/sectors scrolling too. No change to validation invariant: new
numbers all land in the brief, so anti-fabrication keeps working.

**Risk:** more HTTP calls per run (~30 symbols). Keep the polite `time.sleep`,
stay within `VEGA_TIMEOUT_SEC`. Each fetch independently degrades.

---

## Workstream B - Genuine self-improvement (build second: depends on named signals)

Today the loop is shallow: `gather_memory()` shows only the last 6 calls and the
writer is told to calibrate. It never accumulates wisdom or changes what it
watches. We add three durable mechanisms.

### B1. Persistent playbook
New `method/playbook.md`, a growing list of durable lessons Vega maintains about
itself ("too bullish into Fed weeks", "crypto calls beat equity calls"). Unlike
the last-6 memory, the full playbook is fed into **every** `build_prompt`. This is
the difference between forgetting after 6 posts and compounding judgment.

### B2. Signal attribution
- WRITER.md gains a required front-matter field `signals: [vix, breadth,
  btc-dominance, ...]`: the indicators Vega leaned on for this call.
- When `grade_predictions.py` resolves a call HIT/MISS, it records each cited
  signal's outcome into `method/signal_stats.json`.
- `build_prompt` feeds back the best and worst signals: "Signals that have
  preceded your correct calls: X, Y. Signals that have not: Z." Over months Vega
  leans on what has actually worked. This is the real, honest version of
  "constantly using the best indicators."

### B3. Reflection job + public meta-review
New `tools/reflect.py` (weekly or monthly cron):
- reads the full graded history + `signal_stats.json`,
- asks Hermes to write 3-5 durable lessons and to prune/add playbook entries,
- updates `method/playbook.md`, commits.
Optionally emits a public "How I'm doing" post (hit-rate, best/worst calls, what I
am changing). Great content and real accountability.

Also: compute a Brier score (confidence vs outcome) over graded predictions and
surface a calibration line on `predictions.md`. Calibration, shown publicly, is
the brand.

**Files:** new `method/playbook.md`, `method/signal_stats.json`,
`tools/reflect.py`; edit `tools/WRITER.md` (emit `signals:`, consult playbook),
`tools/new_entry.py` (`build_prompt` injects playbook + signal feedback),
`tools/grade_predictions.py` (write signal outcomes; also tighten its `git add -A`
to a targeted add for consistency with the house rule), `predictions.md`
(calibration). Add 1 cron line on sejcore.

**Risk:** low. All additive. Reflection is gated and rare; if it fails the daily
pipeline is untouched.

---

## Workstream A - Topical "On the Radar" pieces (biggest growth lever)

A third content type beyond open/close: opinionated thesis pieces on the
catalysts readers are already searching (SpaceX IPO, a Fed decision, a megacap
earnings print, a crypto ETF). Evergreen, SEO-rich, highly shareable, top of the
subscriber funnel. Depends on a real research feed because of the anti-fabrication
rule (see the SpaceX note below).

### A1. New session type `radar`
Add `radar` to the argparse choices in `new_entry.py` and `fetch_market.py`. A
radar run takes an optional `--topic "SpaceX IPO"`.

### A2. Research feed (keyless)
New `tools/fetch_topic.py` (or a mode of `fetch_market.py`): for a given topic,
pull a focused, sourced bundle so Vega writes from facts, not memory:
- Google News RSS search (keyless):
  `https://news.google.com/rss/search?q=<topic>&hl=en-US` -> recent headlines,
  snippets, sources, dates.
- SEC EDGAR full-text/filings search (keyless) for IPO/S-1 signals when relevant.
- Yahoo trending tickers (keyless): `/v1/finance/trending/US` to auto-surface
  what is hot when no topic is passed.
The bundle is rendered as `topic_brief.md` and passed in place of (or alongside)
the market brief. Crucially, any figure Vega cites (a valuation, a revenue
number) must appear in this bundle, so `validate()` extends to check radar numbers
against `topic_brief.md`. Same invariant, new source.

### A3. Topic selection
- Manual: `--topic "..."` (you steer the hot take).
- Auto fallback: a picker reads trending tickers + aggregated headlines and
  chooses the strongest catalyst (heuristic first; Hermes-assisted later).

### A4. Radar writer spec
New `tools/WRITER_RADAR.md`: longer form (600-1000 words), structure = what is
happening, what it means, Vega's committed view, and a falsifiable, dated
prediction tied to the catalyst. Same hard rules (no buy/sell calls, sourced
numbers only, no em-dash). Cover reuses `make_cover` with a "RADAR" eyebrow and
the fallback chart when there is no `tape:`.

### A5. Surfacing
Tag `radar` (auto via `ensure_tag_pages.py`), a nav link "On the Radar", and an
optional home strip. Feeds the same email broadcast and SEO/JSON-LD path.

### The SpaceX IPO case (concrete)
SpaceX is private, so an IPO is speculative and its financials are estimates. The
no-fabrication rule means Vega cannot invent a valuation. The research feed (A2)
supplies sourced figures (for example a reported tender valuation, Starlink
revenue estimates) which Vega then cites and reasons over: what an eventual IPO
would mean for retail demand, eventual index inclusion, read-through to other
space and defense names, and Starship funding. The falsifiable call is
conditional and dated, for example "no SpaceX S-1 on file before [date], 70%" or
"if it prices above $X, the first-week read-through lifts [peer]." This is exactly
the appealing, opinionated content that converts readers, done without breaking
the credibility rule.

**Files:** new `tools/fetch_topic.py`, `tools/WRITER_RADAR.md`; edit
`new_entry.py` (radar branch, topic plumbing, validation against topic brief),
`navigation.yml`, optional home include. Add 1 cron line on sejcore (for example
two radar pieces a week, plus on-demand runs you trigger).

**Risk:** medium. Research quality varies; keep the sourced-numbers-only rule
strict. Google News RSS and EDGAR are keyless but can rate-limit; wrap and cache.

---

## Recommended sequence

1. **C (indicators)** - low risk, immediately sharpens every entry, and produces
   the named signals B needs.
2. **B (self-improvement)** - builds on C's signals; deepens the track-record
   story that is already the differentiator.
3. **A (topical)** - the growth lever; can be fast-tracked in parallel since the
   research feed is largely independent of C and B. If subscriber growth is the
   priority, we can start A immediately and backfill C/B.

Each workstream is shippable on its own and none disrupts the autonomous cron on
sejcore (we only add new cron lines and document them in
`docs/sejcore-cron-setup.md`).

## Cross-cutting guardrails

- Anti-fabrication invariant extended to every new data source and to radar pieces.
- Keyless + stdlib-only where possible; anything needing a key is env-gated and
  optional (same pattern as `VEGA_IMAGE_KEY`).
- No em-dash or en-dash anywhere rendered or served; `validate()` already rejects.
- Every new fetch degrades independently; one outage never sinks a run.
- New cron jobs documented for sejcore; `verify_cron.py` updated to expect them.
- Honesty in labeling: the breadth proxy is called a proxy, the fear gauge formula
  is published, the calendar's free-data limits are stated.
