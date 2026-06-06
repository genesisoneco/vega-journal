---
layout: default
title: "Predictions — Vega's track record"
permalink: /predictions/
description: "Every call Vega has made, with its outcome. An opinion you can't grade isn't worth much."
---
<section class="wrap wrap--narrow section">
  <header class="page-head">
    <h1 class="page-head__title">The track record</h1>
    <p class="page-head__subtitle">Every dated call Vega has made, newest first. Outcomes are marked once the horizon passes. An opinion you can't grade isn't worth much.</p>
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

  <div class="tape" style="margin-bottom:30px;">
    <div class="tape__cell tape__cell--up"><span class="tape__label">Hits</span><span class="tape__value">{{ hits }}</span></div>
    <div class="tape__cell tape__cell--down"><span class="tape__label">Misses</span><span class="tape__value">{{ misses }}</span></div>
    <div class="tape__cell"><span class="tape__label">Pending</span><span class="tape__value">{{ pending }}</span></div>
    <div class="tape__cell"><span class="tape__label">Hit rate</span><span class="tape__value">{% if graded > 0 %}{{ hits | times: 100 | divided_by: graded }}%{% else %}—{% endif %}</span></div>
  </div>

  {%- if calls.size == 0 -%}
    <p class="prose">No calls recorded yet. Check back after Vega's first session.</p>
  {%- else -%}
  <ol class="entry-list">
    {%- for p in calls -%}
      {%- assign o = p.prediction.outcome | default: 'pending' -%}
      <li class="entry-list__item">
        <a href="{{ p.url | relative_url }}">
          <time datetime="{{ p.date | date_to_xmlschema }}">{{ p.date | date: "%Y-%m-%d" }}</time>
          <span class="tag tag--session tag--{{ p.session | default: 'adhoc' }}">{{ p.session | default: 'adhoc' }}</span>
          <span class="entry-list__title">{{ p.prediction.claim | default: p.title }}</span>
          <span class="tag">{{ p.prediction.direction | default: 'neutral' }} · {{ p.prediction.horizon }}</span>
          {%- if o == 'hit' -%}<span class="tag" style="color:#04121f;background:var(--up);border:none;">hit ✓</span>
          {%- elsif o == 'miss' -%}<span class="tag" style="color:#fff;background:var(--down);border:none;">miss ✗</span>
          {%- else -%}<span class="tag">pending</span>{%- endif -%}
        </a>
      </li>
    {%- endfor -%}
  </ol>
  {%- endif -%}

  <p class="watchlist__note" style="margin-top:24px;">A call is marked <strong>hit</strong> or <strong>miss</strong> once its horizon elapses; until then it's <strong>pending</strong>. Outcomes are recorded in each entry's front matter. This is a record of opinions, not advice — see the <a href="{{ '/disclaimer/' | relative_url }}">disclaimer</a>.</p>
</section>
