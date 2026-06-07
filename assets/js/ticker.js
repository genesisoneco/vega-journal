/* Live market ticker. Pulls /api/ticker (cached server-side) and renders a
   seamless marquee that scrolls left, refreshing the data every 30s.
   The scroll is driven by requestAnimationFrame (not CSS) so it always moves,
   even when the OS "reduce motion" setting would disable CSS animations. */
(function () {
  var BASE = window.VEGA_API;
  var track = document.getElementById('ticker-track');
  var bar = track && track.parentElement;
  if (!track || !BASE) return;

  var SPEED = 45;            // pixels per second
  var offset = 0, half = 0, paused = false, last = 0;

  function fmt(p) {
    if (p == null) return '';
    if (p >= 1000) return p.toLocaleString(undefined, { maximumFractionDigits: 0 });
    if (p >= 1) return p.toFixed(2);
    return p.toFixed(4);
  }
  function item(it) {
    var up = it.chg == null ? true : it.chg >= 0;
    var chg = it.chg == null ? '' : (up ? '+' : '') + it.chg.toFixed(2) + '%';
    return '<span class="tk ' + (up ? 'tk--up' : 'tk--down') + '"><b>' + it.label +
      '</b> ' + fmt(it.price) + ' <i>' + chg + '</i></span>';
  }
  function measure() { half = track.scrollWidth / 2; }

  function render(items) {
    var html = items.map(item).join('');
    track.innerHTML = html + html;   // duplicate => seamless loop at -half
    measure();
  }

  function step(ts) {
    if (!last) last = ts;
    var dt = (ts - last) / 1000; last = ts;
    if (!paused && half > 0) {
      offset -= SPEED * dt;
      if (-offset >= half) offset += half;   // wrap without a visible jump
      track.style.transform = 'translateX(' + offset.toFixed(2) + 'px)';
    }
    requestAnimationFrame(step);
  }

  function load() {
    fetch(BASE + '/api/ticker')
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d.items && d.items.length) render(d.items); })
      .catch(function () {});
  }

  if (bar) {
    bar.addEventListener('mouseenter', function () { paused = true; });
    bar.addEventListener('mouseleave', function () { paused = false; });
  }
  window.addEventListener('resize', measure);

  load();
  setInterval(load, 30000);
  requestAnimationFrame(step);
})();
