/* Live market ticker. Pulls /api/ticker (cached server-side) and renders a
   seamless scrolling marquee, refreshing every 30s. */
(function () {
  var BASE = window.VEGA_API;
  var track = document.getElementById('ticker-track');
  if (!track || !BASE) return;

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
  function load() {
    fetch(BASE + '/api/ticker')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.items || !d.items.length) return;
        var html = d.items.map(item).join('');
        track.innerHTML = html + html; // duplicate => seamless 50% scroll loop
      })
      .catch(function () {});
  }
  load();
  setInterval(load, 30000);
})();
