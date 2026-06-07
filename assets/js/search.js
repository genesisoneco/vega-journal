/* Global client-side search. Loads /search.json (built by Jekyll) on first use,
   filters posts by title/excerpt/body/tags/mood, and shows a live dropdown.
   Press "/" anywhere to focus; Esc to close; Up/Down/Enter to navigate. */
(function () {
  var wrap = document.getElementById('site-search');
  var input = document.getElementById('site-search-input');
  var results = document.getElementById('site-search-results');
  if (!wrap || !input || !results) return;

  var INDEX = null, loading = false, active = -1, items = [];

  function load() {
    if (INDEX || loading) return;
    loading = true;
    fetch(input.getAttribute('data-index') || '/search.json')
      .then(function (r) { return r.json(); })
      .then(function (d) { INDEX = Array.isArray(d) ? d : []; if (input.value) run(); })
      .catch(function () { INDEX = []; });
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function score(p, q) {
    var t = (p.title || '').toLowerCase();
    var hay = (t + ' ' + (p.excerpt || '') + ' ' + (p.body || '') + ' ' +
      (p.tags || []).join(' ') + ' ' + (p.mood || '') + ' ' + (p.session || '')).toLowerCase();
    if (hay.indexOf(q) === -1) return 0;
    return (t.indexOf(q) === 0 ? 100 : 0) + (t.indexOf(q) !== -1 ? 25 : 0) + 1;
  }

  function run() {
    var q = input.value.trim().toLowerCase();
    if (!q || !INDEX) { close(); return; }
    items = INDEX
      .map(function (p) { return { p: p, s: score(p, q) }; })
      .filter(function (x) { return x.s > 0; })
      .sort(function (a, b) { return b.s - a.s; })
      .slice(0, 8)
      .map(function (x) { return x.p; });

    if (!items.length) {
      results.innerHTML = '<div class="site-search__empty">No entries match “' + esc(q) + '”</div>';
    } else {
      results.innerHTML = items.map(function (p, i) {
        var meta = [p.session, p.date].filter(Boolean).join(' · ');
        return '<a class="sr" role="option" data-i="' + i + '" href="' + esc(p.url) + '">' +
          '<span class="sr__title">' + esc(p.title) + '</span>' +
          '<span class="sr__meta">' + esc(meta) + '</span>' +
          '<span class="sr__excerpt">' + esc(p.excerpt) + '</span></a>';
      }).join('');
    }
    active = -1;
    results.hidden = false;
    wrap.classList.add('is-open');
  }

  function close() {
    results.hidden = true;
    wrap.classList.remove('is-open');
    active = -1;
  }

  function move(dir) {
    var els = results.querySelectorAll('.sr');
    if (!els.length) return;
    active = (active + dir + els.length) % els.length;
    els.forEach(function (el, i) { el.classList.toggle('is-active', i === active); });
    els[active].scrollIntoView({ block: 'nearest' });
  }

  input.addEventListener('focus', load);
  input.addEventListener('input', run);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
    else if (e.key === 'Enter') {
      var els = results.querySelectorAll('.sr');
      var el = active >= 0 ? els[active] : els[0];
      if (el) { e.preventDefault(); window.location.href = el.getAttribute('href'); }
    } else if (e.key === 'Escape') { close(); input.blur(); }
  });

  document.addEventListener('click', function (e) { if (!wrap.contains(e.target)) close(); });
  document.addEventListener('keydown', function (e) {
    if (e.key === '/' && document.activeElement !== input &&
        !/^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || '')) {
      e.preventDefault(); input.focus();
    }
  });
})();
