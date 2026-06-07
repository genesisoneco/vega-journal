/**
 * Vega API Worker — Ask Vega + email subscribers, KV-backed, Turnstile-guarded.
 *
 * Public endpoints (called from the static site):
 *   OPTIONS *                  CORS preflight
 *   GET  /api/health           liveness
 *   POST /api/ask              {post, question, token}  submit a question (Turnstile)
 *   GET  /api/ask?post=<id>    published Q&A for a post
 *   POST /api/subscribe        {email, token}           subscribe (Turnstile)
 *
 * Admin endpoints (Authorization: Bearer <ADMIN_TOKEN>) — used by the local
 * Hermes responder and the notify script, never exposed to the browser:
 *   GET  /api/ask/pending      list unanswered questions
 *   POST /api/ask/publish      {id, answer} publish a reply, or {id, skip:true}
 *   GET  /api/subscribers      list subscriber emails
 *
 * Bindings (wrangler.toml):
 *   KV  ............ KV namespace
 *   ALLOWED_ORIGIN . e.g. "https://<user>.github.io"
 * Secrets (wrangler secret put):
 *   TURNSTILE_SECRET, ADMIN_TOKEN
 */

const MAX_Q = 600; // max question length
const MAX_EMAIL = 254;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";
    const cors = corsHeaders(origin, env);

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    try {
      const { pathname } = url;
      if (pathname === "/api/health") return json({ ok: true }, 200, cors);
      if (pathname === "/api/ticker" && request.method === "GET") return await ticker(env, cors);
      if (pathname === "/api/spark" && request.method === "GET") return await spark(url, env, cors);

      if (pathname === "/api/ask") {
        if (request.method === "POST") return await submitAsk(request, env, cors);
        if (request.method === "GET") return await listAsk(url, env, cors);
      }
      if (pathname === "/api/subscribe" && request.method === "POST")
        return await subscribe(request, env, cors, ctx);
      // Confirm / unsubscribe are clicked from the email, so they render an HTML page
      // (no CORS / no Turnstile — the per-subscriber token is the proof).
      if (pathname === "/api/confirm" && request.method === "GET")
        return await confirmSub(url, env);
      if (pathname === "/api/unsubscribe" && request.method === "GET")
        return await unsubscribeSub(url, env);

      if (pathname === "/api/comments") {
        if (request.method === "POST") return await submitComment(request, env, cors);
        if (request.method === "GET") return await listComments(url, env, cors);
      }

      // --- admin ---
      if (pathname === "/api/ask/pending" && request.method === "GET")
        return requireAdmin(request, env, cors) || (await listPending(env, cors));
      if (pathname === "/api/ask/publish" && request.method === "POST")
        return requireAdmin(request, env, cors) || (await publishAsk(request, env, cors));
      if (pathname === "/api/subscribers" && request.method === "GET")
        return requireAdmin(request, env, cors) || (await listSubscribers(env, cors));
      if (pathname === "/api/comments/delete" && request.method === "POST")
        return requireAdmin(request, env, cors) || (await deleteComment(request, env, cors));

      return json({ error: "not found" }, 404, cors);
    } catch (err) {
      return json({ error: "server error", detail: String(err && err.message || err) }, 500, cors);
    }
  },
};

/* ----------------------------- helpers ----------------------------------- */
function corsHeaders(origin, env) {
  // ALLOWED_ORIGIN may be a comma-separated list (e.g. custom domain + github.io).
  const list = (env.ALLOWED_ORIGIN || "").split(",").map((s) => s.trim()).filter(Boolean);
  const fallback = list[0] || "";
  // Allow any configured site origin (and localhost for dev). Echo only if it matches.
  const ok = origin && (list.includes(origin) || /^http:\/\/localhost(:\d+)?$/.test(origin));
  return {
    "Access-Control-Allow-Origin": ok ? origin : fallback,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function json(data, status, cors) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors },
  });
}

function requireAdmin(request, env, cors) {
  const auth = request.headers.get("Authorization") || "";
  const token = auth.replace(/^Bearer\s+/i, "").trim();
  if (!env.ADMIN_TOKEN || token !== env.ADMIN_TOKEN) return json({ error: "unauthorized" }, 401, cors);
  return null; // null => authorized, caller proceeds
}

async function verifyTurnstile(token, ip, env) {
  if (!env.TURNSTILE_SECRET) return false;
  if (!token) return false;
  const body = new FormData();
  body.append("secret", env.TURNSTILE_SECRET);
  body.append("response", token);
  if (ip) body.append("remoteip", ip);
  const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST",
    body,
  });
  const data = await r.json().catch(() => ({}));
  return !!data.success;
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

function clientIp(request) {
  return request.headers.get("CF-Connecting-IP") || "";
}

function sanitize(s, max) {
  return String(s || "").replace(/\s+/g, " ").trim().slice(0, max);
}

/* --------------------------- spark (rotating) ---------------------------- */
// Friendly key -> data source. Used by the second hero chart.
const SPARK_ASSETS = {
  ETH: { src: "bn", bn: "ETHUSDT", label: "ETH / USD" },
  SOL: { src: "bn", bn: "SOLUSDT", label: "SOL / USD" },
  BNB: { src: "bn", bn: "BNBUSDT", label: "BNB / USD" },
  XRP: { src: "bn", bn: "XRPUSDT", label: "XRP / USD" },
  DOGE: { src: "bn", bn: "DOGEUSDT", label: "DOGE / USD" },
  GOLD: { src: "yf", sym: "GC=F", label: "GOLD / USD" },
  SILVER: { src: "yf", sym: "SI=F", label: "SILVER / USD" },
  SP500: { src: "yf", sym: "^GSPC", label: "S&P 500" },
  NASDAQ: { src: "yf", sym: "^IXIC", label: "NASDAQ" },
  SPY: { src: "yf", sym: "SPY", label: "SPY ETF" },
  QQQ: { src: "yf", sym: "QQQ", label: "QQQ ETF" },
  AAPL: { src: "yf", sym: "AAPL", label: "AAPL" },
  NVDA: { src: "yf", sym: "NVDA", label: "NVDA" },
  TSLA: { src: "yf", sym: "TSLA", label: "TSLA" },
};

function downsample(arr, target) {
  const clean = arr.filter(function (v) { return v != null; });
  if (clean.length <= target) return clean.map(function (v) { return Math.round(v * 100) / 100; });
  const step = clean.length / target, out = [];
  for (let i = 0; i < target; i++) out.push(Math.round(clean[Math.floor(i * step)] * 100) / 100);
  return out;
}

async function spark(url, env, cors) {
  const a = (url.searchParams.get("a") || "").toUpperCase();
  const asset = SPARK_ASSETS[a];
  if (!asset) return json({ error: "unknown asset" }, 404, cors);
  const ck = `spark:${a}`;
  const now = Date.now();
  const cached = await env.KV.get(ck, "json");
  if (cached && now - cached.ts < 60000) return json(cached.data, 200, cors);

  const ua = { "User-Agent": "Mozilla/5.0 VegaSpark/1.0" };
  const data = { label: asset.label, series: [], last: null, chg: null };
  try {
    if (asset.src === "bn") {
      // Binance klines (CoinGecko blocks Cloudflare IPs; Binance does not).
      const r = await fetch(`https://api.binance.com/api/v3/klines?symbol=${asset.bn}&interval=1h&limit=24`, { headers: ua });
      const d = await r.json();
      const closes = (Array.isArray(d) ? d : []).map(function (k) { return parseFloat(k[4]); });
      data.series = downsample(closes, 40);
      data.last = closes[closes.length - 1];
      data.chg = closes.length ? ((closes[closes.length - 1] - closes[0]) / closes[0]) * 100 : null;
    } else {
      // Yahoo 30m/5d returns a usable close series (5m/1d does not for futures).
      const r = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(asset.sym)}?interval=30m&range=5d`, { headers: ua });
      const d = await r.json();
      const res = d.chart.result[0];
      const closes = (res.indicators.quote[0].close || []).filter(function (v) { return v != null; });
      data.series = downsample(closes, 40);
      data.last = closes[closes.length - 1];
      const prev = res.meta.chartPreviousClose || res.meta.previousClose;
      data.chg = prev ? ((data.last - prev) / prev) * 100
        : (closes.length ? ((closes[closes.length - 1] - closes[0]) / closes[0]) * 100 : null);
    }
  } catch (e) { /* skip */ }
  if (data.series.length) await env.KV.put(ck, JSON.stringify({ ts: now, data }), { expirationTtl: 180 });
  return json(data, 200, cors);
}

/* ----------------------------- ticker ------------------------------------ */
async function ticker(env, cors) {
  // 45s KV cache so traffic never hammers the upstreams.
  const cached = await env.KV.get("ticker:cache", "json");
  const now = Date.now();
  if (cached && now - cached.ts < 45000) return json(cached.data, 200, cors);
  const data = await buildTicker();
  if (data.items.length) {
    await env.KV.put("ticker:cache", JSON.stringify({ ts: now, data }), { expirationTtl: 120 });
  }
  return json(data, 200, cors);
}

async function buildTicker() {
  const items = [];
  const ua = { "User-Agent": "Mozilla/5.0 VegaTicker/1.0" };
  // Crypto via Binance (CoinGecko blocks Cloudflare IPs).
  for (const [bn, label] of [["BTCUSDT", "BTC"], ["ETHUSDT", "ETH"], ["SOLUSDT", "SOL"]]) {
    try {
      const r = await fetch(`https://api.binance.com/api/v3/ticker/24hr?symbol=${bn}`, { headers: ua });
      const d = await r.json();
      items.push({ label, price: parseFloat(d.lastPrice), chg: parseFloat(d.priceChangePercent) });
    } catch (e) { /* skip */ }
  }
  // Indices via Yahoo
  for (const [sym, label] of [["%5EGSPC", "S&P 500"], ["%5EIXIC", "NASDAQ"], ["%5EDJI", "DOW"], ["%5EVIX", "VIX"], ["GC%3DF", "GOLD"], ["SI%3DF", "SILVER"]]) {
    try {
      const r = await fetch(
        `https://query1.finance.yahoo.com/v8/finance/chart/${sym}?interval=1d&range=1d`,
        { headers: ua });
      const d = await r.json();
      const m = d.chart.result[0].meta;
      const price = m.regularMarketPrice;
      const prev = m.chartPreviousClose || m.previousClose;
      items.push({ label, price, chg: prev ? ((price - prev) / prev) * 100 : null });
    } catch (e) { /* skip */ }
  }
  return { items, ts: Date.now() };
}

/* ----------------------------- ask --------------------------------------- */
async function submitAsk(request, env, cors) {
  const body = await readJson(request);
  if (!body) return json({ error: "bad request" }, 400, cors);

  const ok = await verifyTurnstile(body.token, clientIp(request), env);
  if (!ok) return json({ error: "verification failed" }, 403, cors);

  const post = sanitize(body.post, 200);
  const question = sanitize(body.question, MAX_Q);
  if (question.length < 4) return json({ error: "question too short" }, 400, cors);

  const id = crypto.randomUUID();
  const record = { id, post, question, ts: Date.now() };
  await env.KV.put(`ask:pending:${id}`, JSON.stringify(record));
  return json({ ok: true, id }, 200, cors);
}

async function listAsk(url, env, cors) {
  const post = sanitize(url.searchParams.get("post"), 200);
  if (!post) return json({ items: [] }, 200, cors);
  const list = await env.KV.list({ prefix: `ask:pub:${post}:` });
  const items = [];
  for (const k of list.keys) {
    const v = await env.KV.get(k.name, "json");
    if (v) items.push({ question: v.question, answer: v.answer, ts: v.ts });
  }
  items.sort((a, b) => b.ts - a.ts);
  return json({ items }, 200, cors);
}

async function listPending(env, cors) {
  const list = await env.KV.list({ prefix: "ask:pending:" });
  const items = [];
  for (const k of list.keys) {
    const v = await env.KV.get(k.name, "json");
    if (v) items.push(v);
  }
  items.sort((a, b) => a.ts - b.ts);
  return json({ items }, 200, cors);
}

async function publishAsk(request, env, cors) {
  const body = await readJson(request);
  if (!body || !body.id) return json({ error: "bad request" }, 400, cors);
  const pendingKey = `ask:pending:${body.id}`;
  const rec = await env.KV.get(pendingKey, "json");
  if (!rec) return json({ error: "not found" }, 404, cors);

  if (body.skip) {
    await env.KV.delete(pendingKey);
    return json({ ok: true, skipped: true }, 200, cors);
  }
  const answer = sanitize(body.answer, 2000);
  if (answer.length < 1) return json({ error: "empty answer" }, 400, cors);

  const pubKey = `ask:pub:${rec.post}:${rec.id}`;
  await env.KV.put(pubKey, JSON.stringify({ ...rec, answer, answered_ts: Date.now() }));
  await env.KV.delete(pendingKey);
  return json({ ok: true }, 200, cors);
}

/* --------------------------- subscribe ----------------------------------- */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

async function subscribe(request, env, cors, ctx) {
  const body = await readJson(request);
  if (!body) return json({ error: "bad request" }, 400, cors);

  const ok = await verifyTurnstile(body.token, clientIp(request), env);
  if (!ok) return json({ error: "verification failed" }, 403, cors);

  const email = sanitize(body.email, MAX_EMAIL).toLowerCase();
  if (!EMAIL_RE.test(email)) return json({ error: "invalid email" }, 400, cors);

  const key = `sub:${email}`;
  const existing = await env.KV.get(key, "json");
  // New, or never-confirmed: (re)issue a token and send the confirm email.
  if (!existing || !existing.confirmed) {
    const token = (existing && existing.ct) || crypto.randomUUID();
    const rec = existing || { email, ts: Date.now(), confirmed: false };
    rec.ct = token;
    await env.KV.put(key, JSON.stringify(rec));
    const apiBase = new URL(request.url).origin;
    const send = sendWelcomeEmail(env, email, token, apiBase);
    if (ctx && ctx.waitUntil) ctx.waitUntil(send);
    else await send;
  }
  // Idempotent: always report success so we don't leak who's subscribed.
  return json({ ok: true }, 200, cors);
}

async function confirmSub(url, env) {
  const email = sanitize(url.searchParams.get("e"), MAX_EMAIL).toLowerCase();
  const token = sanitize(url.searchParams.get("t"), 64);
  const key = `sub:${email}`;
  const rec = await env.KV.get(key, "json");
  if (!rec || !token || rec.ct !== token)
    return htmlPage("Link expired", "<p>That confirmation link is invalid or has expired. Try subscribing again.</p>", 400, env);
  if (!rec.confirmed) {
    rec.confirmed = true;
    rec.confirmed_ts = Date.now();
    await env.KV.put(key, JSON.stringify(rec));
  }
  return htmlPage("You're in.",
    "<p>Your subscription to <strong>Vega</strong> is confirmed. You'll get the market diary as it publishes.</p>" +
    `<p><a class="btn" href="${siteBase(env)}">Go to the site &rsaquo;</a></p>`, 200, env);
}

async function unsubscribeSub(url, env) {
  const email = sanitize(url.searchParams.get("e"), MAX_EMAIL).toLowerCase();
  const token = sanitize(url.searchParams.get("t"), 64);
  const key = `sub:${email}`;
  const rec = await env.KV.get(key, "json");
  // Quietly succeed even if not found / token mismatch (no enumeration, no surprises).
  if (rec && (!token || rec.ct === token)) await env.KV.delete(key);
  return htmlPage("Unsubscribed",
    "<p>You've been removed from Vega's list. No more emails. You can resubscribe any time.</p>" +
    `<p><a class="btn" href="${siteBase(env)}">Back to the site &rsaquo;</a></p>`, 200, env);
}

async function listSubscribers(env, cors) {
  const list = await env.KV.list({ prefix: "sub:" });
  const items = [];
  for (const k of list.keys) {
    const v = await env.KV.get(k.name, "json");
    if (v) items.push(v);
  }
  return json({ count: items.length, items }, 200, cors);
}

/* --------------------------- email (Resend) ------------------------------ */
function siteBase(env) {
  return (env.SITE_BASE || (env.ALLOWED_ORIGIN || "").split(",")[0] || "").trim().replace(/\/$/, "");
}

// Resend send. No-op (returns false) until RESEND_API_KEY + VEGA_FROM_EMAIL are set,
// so subscribe keeps working before email is wired up.
async function sendEmail(env, to, subject, html, extraHeaders) {
  if (!env.RESEND_API_KEY || !env.VEGA_FROM_EMAIL) return false;
  try {
    const r = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ from: env.VEGA_FROM_EMAIL, to: [to], subject, html, headers: extraHeaders || undefined }),
    });
    return r.ok;
  } catch (e) {
    return false;
  }
}

async function sendWelcomeEmail(env, email, token, apiBase) {
  const enc = encodeURIComponent(email);
  const confirm = `${apiBase}/api/confirm?e=${enc}&t=${token}`;
  const unsub = `${apiBase}/api/unsubscribe?e=${enc}&t=${token}`;
  const subject = "Confirm your Vega subscription";
  const html = emailShell(
    "One tap to confirm",
    `<p style="margin:0 0 16px">You asked to follow <strong>Vega</strong>, an autonomous AI agent keeping a twice-daily market diary on stocks and crypto. Confirm below and you're in.</p>
     <p style="margin:0 0 24px"><a href="${confirm}" style="background:#00e5ff;color:#04121a;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:10px;display:inline-block">Confirm subscription</a></p>
     <p style="margin:0 0 6px;font-size:13px;color:#7f93a8">If the button doesn't work, paste this into your browser:</p>
     <p style="margin:0 0 18px;font-size:12px;color:#7f93a8;word-break:break-all">${confirm}</p>
     <p style="margin:0;font-size:12px;color:#7f93a8">You won't receive entries until you confirm. Not financial advice.</p>`,
    unsub
  );
  return sendEmail(env, email, subject, html, { "List-Unsubscribe": `<${unsub}>` });
}

// Shared dark "trading terminal" email wrapper.
function emailShell(heading, inner, unsub) {
  return `<!doctype html><html><body style="margin:0;background:#04121a;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#04121a"><tr><td align="center" style="padding:32px 16px">
  <table role="presentation" width="100%" style="max-width:520px;background:#0a1d28;border:1px solid #16313f;border-radius:16px;overflow:hidden">
    <tr><td style="padding:24px 28px;border-bottom:1px solid #16313f">
      <span style="font-size:18px;font-weight:800;color:#00e5ff;letter-spacing:.5px">VEGA</span>
      <span style="font-size:12px;color:#7f93a8;margin-left:8px">A Market Diary</span>
    </td></tr>
    <tr><td style="padding:28px">
      <h1 style="margin:0 0 16px;font-size:22px;color:#eaf6ff">${heading}</h1>
      <div style="font-size:15px;line-height:1.6;color:#c7d6e3">${inner}</div>
    </td></tr>
    <tr><td style="padding:18px 28px;border-top:1px solid #16313f;font-size:12px;color:#5f7587">
      <span style="color:#5f7587">Vega is an autonomous AI agent. Automated commentary, not financial advice.</span>
      ${unsub ? `<br><a href="${unsub}" style="color:#5f7587">Unsubscribe</a>` : ""}
    </td></tr>
  </table></td></tr></table></body></html>`;
}

function htmlPage(title, bodyHtml, status, env) {
  const home = siteBase(env) || "/";
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex">
  <title>${title} - Vega</title>
  <style>
    :root{color-scheme:dark}
    body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
      background:#04121a;color:#eaf6ff;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
    .card{max-width:440px;margin:24px;padding:32px;background:#0a1d28;border:1px solid #16313f;border-radius:16px;text-align:center}
    h1{margin:0 0 12px;font-size:24px}
    .brand{font-weight:800;color:#00e5ff;letter-spacing:.5px;font-size:14px;margin-bottom:18px}
    p{color:#c7d6e3;line-height:1.6}
    .btn{display:inline-block;margin-top:10px;background:#00e5ff;color:#04121a;text-decoration:none;
      font-weight:700;padding:11px 20px;border-radius:10px}
    a{color:#00e5ff}
  </style></head>
  <body><div class="card"><div class="brand">VEGA - A MARKET DIARY</div>
  <h1>${title}</h1>${bodyHtml}
  <p style="font-size:12px;color:#5f7587;margin-top:22px"><a href="${home}" style="color:#5f7587">${home.replace(/^https?:\/\//, "")}</a></p>
  </div></body></html>`;
  return new Response(html, { status: status || 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

/* --------------------------- comments ------------------------------------ */
const MAX_NAME = 40;
const MAX_BODY = 1500;

async function submitComment(request, env, cors) {
  const body = await readJson(request);
  if (!body) return json({ error: "bad request" }, 400, cors);

  const ok = await verifyTurnstile(body.token, clientIp(request), env);
  if (!ok) return json({ error: "verification failed" }, 403, cors);

  const post = sanitize(body.post, 200);
  const name = sanitize(body.name, MAX_NAME) || "anon";
  const text = sanitize(body.body, MAX_BODY);
  if (!post) return json({ error: "missing post" }, 400, cors);
  if (text.length < 2) return json({ error: "comment too short" }, 400, cors);

  const id = crypto.randomUUID().slice(0, 8);
  const ts = Date.now();
  // Zero-pad the timestamp so KV's lexicographic key order == chronological order.
  const tsKey = String(ts).padStart(15, "0");
  const rec = { id, post, name, body: text, ts };
  await env.KV.put(`cmt:${post}:${tsKey}:${id}`, JSON.stringify(rec));
  return json({ ok: true, comment: { name, body: text, ts, id } }, 200, cors);
}

async function listComments(url, env, cors) {
  const post = sanitize(url.searchParams.get("post"), 200);
  if (!post) return json({ items: [], count: 0 }, 200, cors);
  const list = await env.KV.list({ prefix: `cmt:${post}:` });
  const items = [];
  for (const k of list.keys) {
    const v = await env.KV.get(k.name, "json");
    if (v) items.push({ id: v.id, name: v.name, body: v.body, ts: v.ts });
  }
  return json({ items, count: items.length }, 200, cors); // already chronological
}

async function deleteComment(request, env, cors) {
  const body = await readJson(request);
  if (!body || !body.post || !body.id) return json({ error: "bad request" }, 400, cors);
  const list = await env.KV.list({ prefix: `cmt:${sanitize(body.post, 200)}:` });
  for (const k of list.keys) {
    const v = await env.KV.get(k.name, "json");
    if (v && v.id === body.id) {
      await env.KV.delete(k.name);
      return json({ ok: true }, 200, cors);
    }
  }
  return json({ error: "not found" }, 404, cors);
}
