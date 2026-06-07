/* "Next bell" countdown. Shows time until the next US market bell:
   opening bell 9:30 ET, closing bell 16:00 ET, weekdays. During market hours it
   counts down to the close; otherwise to the next open. Holidays are ignored. */
(function () {
  var el = document.getElementById('next-bell-text');
  var box = document.getElementById('next-bell');
  if (!el) return;

  var OPEN = 9 * 3600 + 30 * 60;   // 09:30 ET in seconds-of-day
  var CLOSE = 16 * 3600;           // 16:00 ET
  var DAY = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

  function etParts() {
    var p = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', weekday: 'short',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    }).formatToParts(new Date());
    var o = {}; p.forEach(function (x) { o[x.type] = x.value; });
    return o;
  }

  function compute() {
    var o = etParts();
    var h = parseInt(o.hour, 10) % 24;   // some engines emit '24' at midnight
    var sec = h * 3600 + parseInt(o.minute, 10) * 60 + parseInt(o.second, 10);
    var d = DAY[o.weekday];
    var weekday = d >= 1 && d <= 5;
    if (weekday && sec < OPEN) return { label: 'opening bell', delta: OPEN - sec };
    if (weekday && sec < CLOSE) return { label: 'closing bell', delta: CLOSE - sec };
    // otherwise: next trading day's open
    var add = 1, nd = (d + 1) % 7;
    while (nd === 0 || nd === 6) { add++; nd = (d + add) % 7; }
    return { label: 'opening bell', delta: (86400 - sec) + (add - 1) * 86400 + OPEN };
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function fmt(s) {
    var hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
    return hh > 0 ? hh + 'h ' + pad(mm) + 'm' : mm + 'm ' + pad(ss) + 's';
  }

  function tick() {
    var c = compute();
    el.textContent = c.label + ' in ' + fmt(c.delta);
    if (box) box.setAttribute('title', 'Next ' + c.label + ' in ' + fmt(c.delta) + ' (US market, ET)');
  }
  tick();
  setInterval(tick, 1000);
})();
