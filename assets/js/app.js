/* Vega motion + polish: scroll reveal, count-up numbers, reading progress,
   live hero sparkline. Vanilla, defer-loaded, respects reduced-motion. */
(function () {
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* --- Scroll reveal --- */
  var targets = document.querySelectorAll('.card, .tape, .prediction, .ask, .comments, .support-card, .pcard, .dash__gauge, .dash__chart, .watchlist, .section__head');
  if ('IntersectionObserver' in window && !reduce) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('is-visible'); io.unobserve(e.target); }
      });
    }, { threshold: 0.08 });
    targets.forEach(function (t) { t.classList.add('reveal'); io.observe(t); });
  }

  /* --- Count-up on plain-integer tape values --- */
  function countUp(el) {
    var clean = el.textContent.replace(/,/g, '');
    if (!/^\d+$/.test(clean)) return;
    var target = parseInt(clean, 10), dur = 900, t0 = null;
    function step(ts) {
      if (!t0) t0 = ts;
      var k = Math.min((ts - t0) / dur, 1);
      el.textContent = Math.round(target * (1 - Math.pow(1 - k, 3))).toLocaleString();
      if (k < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  if (!reduce) {
    var nums = document.querySelectorAll('.tape__value');
    if ('IntersectionObserver' in window) {
      var io2 = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) { if (e.isIntersecting) { countUp(e.target); io2.unobserve(e.target); } });
      }, { threshold: 0.5 });
      nums.forEach(function (n) { io2.observe(n); });
    }
  }

  /* --- Reading progress bar --- */
  var bar = document.querySelector('#read-progress > span');
  if (bar) {
    var onScroll = function () {
      var h = document.documentElement;
      var max = h.scrollHeight - h.clientHeight;
      bar.style.width = (max > 0 ? (h.scrollTop / max) * 100 : 0) + '%';
    };
    document.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* --- Live hero sparkline (BTC, last 24h via CoinGecko) --- */
  var host = document.getElementById('hero-spark');
  if (host) {
    fetch('https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=1')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var prices = (d.prices || []).map(function (p) { return p[1]; });
        if (prices.length < 2) return;
        var W = 420, H = 56, P = 2;
        var mn = Math.min.apply(null, prices), mx = Math.max.apply(null, prices), rng = (mx - mn) || 1;
        var up = prices[prices.length - 1] >= prices[0];
        var color = up ? '#1bf0a8' : '#ff3b6b';
        var pts = prices.map(function (v, i) {
          return (P + i * (W - 2 * P) / (prices.length - 1)).toFixed(1) + ' ' +
                 (P + (H - 2 * P) * (1 - (v - mn) / rng)).toFixed(1);
        });
        var line = pts.map(function (p, i) { return (i ? 'L' : 'M') + p; }).join(' ');
        var area = line + ' L' + (W - P) + ' ' + (H - P) + ' L' + P + ' ' + (H - P) + ' Z';
        var last = prices[prices.length - 1];
        host.innerHTML =
          '<span class="hero__spark-label">BTC / USD &middot; 24h &middot; ' +
          last.toLocaleString(undefined, { maximumFractionDigits: 0 }) + '</span>' +
          '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' +
          '<defs><linearGradient id="hs" x1="0" y1="0" x2="0" y2="1">' +
          '<stop offset="0" stop-color="' + color + '" stop-opacity="0.5"/>' +
          '<stop offset="1" stop-color="' + color + '" stop-opacity="0"/></linearGradient></defs>' +
          '<path d="' + area + '" fill="url(#hs)"/>' +
          '<path d="' + line + '" fill="none" stroke="' + color + '" stroke-width="2" vector-effect="non-scaling-stroke"/>' +
          '</svg>';
      })
      .catch(function () {});
  }
})();
