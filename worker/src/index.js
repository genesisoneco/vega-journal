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
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";
    const cors = corsHeaders(origin, env);

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    try {
      const { pathname } = url;
      if (pathname === "/api/health") return json({ ok: true }, 200, cors);

      if (pathname === "/api/ask") {
        if (request.method === "POST") return await submitAsk(request, env, cors);
        if (request.method === "GET") return await listAsk(url, env, cors);
      }
      if (pathname === "/api/subscribe" && request.method === "POST")
        return await subscribe(request, env, cors);

      // --- admin ---
      if (pathname === "/api/ask/pending" && request.method === "GET")
        return requireAdmin(request, env, cors) || (await listPending(env, cors));
      if (pathname === "/api/ask/publish" && request.method === "POST")
        return requireAdmin(request, env, cors) || (await publishAsk(request, env, cors));
      if (pathname === "/api/subscribers" && request.method === "GET")
        return requireAdmin(request, env, cors) || (await listSubscribers(env, cors));

      return json({ error: "not found" }, 404, cors);
    } catch (err) {
      return json({ error: "server error", detail: String(err && err.message || err) }, 500, cors);
    }
  },
};

/* ----------------------------- helpers ----------------------------------- */
function corsHeaders(origin, env) {
  const allowed = env.ALLOWED_ORIGIN || "";
  // Allow the configured site origin (and localhost for dev). Echo only if it matches.
  const ok = origin && (origin === allowed || /^http:\/\/localhost(:\d+)?$/.test(origin));
  return {
    "Access-Control-Allow-Origin": ok ? origin : allowed,
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

async function subscribe(request, env, cors) {
  const body = await readJson(request);
  if (!body) return json({ error: "bad request" }, 400, cors);

  const ok = await verifyTurnstile(body.token, clientIp(request), env);
  if (!ok) return json({ error: "verification failed" }, 403, cors);

  const email = sanitize(body.email, MAX_EMAIL).toLowerCase();
  if (!EMAIL_RE.test(email)) return json({ error: "invalid email" }, 400, cors);

  const key = `sub:${email}`;
  const existing = await env.KV.get(key);
  if (!existing) {
    await env.KV.put(key, JSON.stringify({ email, ts: Date.now(), confirmed: false }));
  }
  // Idempotent: always report success so we don't leak who's subscribed.
  return json({ ok: true }, 200, cors);
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
