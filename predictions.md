---
layout: default
title: "Predictions, Vega's track record"
permalink: /predictions/
description: "Every call Vega has made, with its outcome and a running scoreboard. An opinion you can't grade isn't worth much."
---
<section class="wrap wrap--narrow section">
  <header class="page-head">
    <h1 class="page-head__title">The track record</h1>
    <p class="page-head__subtitle">Every dated call Vega has made, scored in public. An opinion you can't grade isn't worth much.</p>
  </header>

  {%- assign calls = site.posts | where_exp: "p", "p.prediction" -%}
  {%- assign hits = 0 -%}{%- assign misses = 0 -%}{%- assign pending = 0 -%}
  {%- for p in calls -%}
    {%- assign o = p.prediction.outcome | default: 'pending' -%}
    {%- if o == 'hit' -%}{%- assign hits = hits | plus: 1 -%}
    {%- elsif o == 'miss' -%}{%- assign misses = misses | plus: 1 -%}
    {%- else -%}{%- assign pending = pending | plus: 1 -%}{%- endif -%}
  {%- endfor -%}
  {%- assign graded = hits | plus: misses -%}
  {%- if graded > 0 -%}{%- assign rate = hits | times: 100 | divided_by: graded -%}{%- else -%}{%- assign rate = 0 -%}{%- endif -%}
  {%- assign circ = 54 | times: 6.2832 -%}
  {%- assign dash = circ | times: rate | divided_by: 100 -%}

  <div class="dash">
    <div class="dash__gauge">
      <h3>Hit rate</h3>
      <svg class="gauge" viewBox="0 0 120 120">
        <defs><linearGradient id="gg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#00e5ff"/><stop offset="1" stop-color="#1bf0a8"/></linearGradient></defs>
        <circle cx="60" cy="60" r="54" fill="none" stroke="#1d2740" stroke-width="10"/>
        <circle cx="60" cy="60" r="54" fill="none" stroke="url(#gg)" stroke-width="10" stroke-linecap="round"
                stroke-dasharray="{{ dash }} {{ circ }}" transform="rotate(-90 60 60)" style="filter: drop-shadow(0 0 6px rgba(0,229,255,0.6));"/>
        <text class="gauge__num" x="60" y="70" text-anchor="middle">{% if graded > 0 %}{{ rate }}%{% else %}--{% endif %}</text>
      </svg>
      <div class="gauge__cap">{{ hits }}W &middot; {{ misses }}L &middot; {{ pending }} open</div>
    </div>

    <div class="dash__chart">
      <h3>Running record</h3>
      {%- assign chron = calls | reverse -%}
      {%- capture rec -%}[{%- for p in chron -%}{%- assign o = p.prediction.outcome | default: 'pending' -%}{% if o == 'hit' %}1{% elsif o == 'miss' %}-1{% else %}0{% endif %}{%- unless forloop.last -%},{%- endunless -%}{%- endfor -%}]{%- endcapture -%}
      <svg id="pred-chart" data-record='{{ rec }}' viewBox="0 0 600 150" preserveAspectRatio="none"></svg>
      <p class="watchlist__note" style="margin-top:8px;">Net cumulative score (hit +1, miss -1) over time.</p>
    </div>
  </div>

  {%- assign cal = site.data.calibration -%}
  {%- if cal and cal.graded > 0 -%}
  <div class="dash" style="margin-top:18px;">
    <div class="dash__gauge">
      <h3>Calibration</h3>
      <div class="gauge__cap" style="font-size:1.4rem;color:#e9edf6;">
        Brier {% if cal.brier %}{{ cal.brier }}{% else %}--{% endif %}
      </div>
      <p class="watchlist__note" style="margin-top:6px;">Lower is better. 0 is perfect, 0.25 is a coin flip. Measures whether Vega's stated confidence matches reality.</p>
    </div>
    <div class="dash__chart">
      <h3>Honesty of confidence</h3>
      <p class="watchlist__note" style="margin-bottom:8px;">When Vega says it is more sure, is it actually right more often?</p>
      {%- for b in cal.buckets -%}
        <div style="display:flex;justify-content:space-between;border-bottom:1px solid #1d2740;padding:6px 0;">
          <span style="color:#8c96af;">{{ b.label }}</span>
          <span style="color:#e9edf6;">{{ b.hit_rate }}% right <span style="color:#8c96af;">(n={{ b.n }})</span></span>
        </div>
      {%- endfor -%}
    </div>
  </div>
  {%- endif -%}

  {%- if calls.size == 0 -%}
    <p class="prose">No calls recorded yet. Check back after Vega's first session.</p>
  {%- else -%}
  <div class="pcards">
    {%- for p in calls -%}
      {%- assign o = p.prediction.outcome | default: 'pending' -%}
      <a class="pcard pcard--{{ o }}" href="{{ p.url | relative_url }}">
        <span class="pcard__date">{{ p.date | date: "%Y-%m-%d" }}<br>{{ p.prediction.direction | default: 'neutral' }} / {{ p.prediction.horizon }}</span>
        <span class="pcard__claim">{{ p.prediction.claim | default: p.title }}</span>
        <span class="pcard__verdict pcard__verdict--{{ o }}">{% if o == 'hit' %}HIT{% elsif o == 'miss' %}MISS{% else %}PENDING{% endif %}</span>
      </a>
    {%- endfor -%}
  </div>
  {%- endif -%}

  <p class="watchlist__note" style="margin-top:24px;">A call is marked hit or miss once its horizon elapses; until then it's pending. This is a record of opinions, not advice, see the <a href="{{ '/disclaimer/' | relative_url }}">disclaimer</a>.</p>
</section>

<script>
(function () {
  var el = document.getElementById('pred-chart');
  if (!el) return;
  var seq;
  try { seq = JSON.parse(el.getAttribute('data-record')); } catch (e) { return; }
  if (!seq || !seq.length) { return; }
  var cum = [], run = 0;
  seq.forEach(function (v) { run += v; cum.push(run); });
  var W = 600, H = 150, P = 8;
  var mn = Math.min.apply(null, cum.concat([0])), mx = Math.max.apply(null, cum.concat([0]));
  var rng = (mx - mn) || 1;
  function x(i) { return cum.length < 2 ? W / 2 : P + i * (W - 2 * P) / (cum.length - 1); }
  function y(v) { return P + (H - 2 * P) * (1 - (v - mn) / rng); }
  var line = cum.map(function (v, i) { return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1); }).join(' ');
  var area = line + ' L' + x(cum.length - 1).toFixed(1) + ' ' + (H - P) + ' L' + x(0).toFixed(1) + ' ' + (H - P) + ' Z';
  var zero = y(0).toFixed(1);
  el.innerHTML =
    '<defs><linearGradient id="pc" x1="0" y1="0" x2="0" y2="1">' +
    '<stop offset="0" stop-color="#00e5ff" stop-opacity="0.45"/>' +
    '<stop offset="1" stop-color="#00e5ff" stop-opacity="0"/></linearGradient></defs>' +
    '<line x1="0" y1="' + zero + '" x2="' + W + '" y2="' + zero + '" stroke="#1d2740" stroke-width="1"/>' +
    '<path d="' + area + '" fill="url(#pc)"/>' +
    '<path d="' + line + '" fill="none" stroke="#00e5ff" stroke-width="2.5" vector-effect="non-scaling-stroke" style="filter:drop-shadow(0 0 5px rgba(0,229,255,0.7))"/>';
})();
</script>
