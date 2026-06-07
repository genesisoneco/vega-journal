/* Gradient sparklines for the market tape. Reads a JSON number array from each
   .tape__cell[data-spark] and renders a gradient-filled SVG area chart, colored
   green/red by the cell's direction. No dependencies. */
(function () {
  function draw(cell) {
    var raw = cell.getAttribute('data-spark');
    if (!raw) return;
    var data;
    try { data = JSON.parse(raw); } catch (e) { return; }
    if (!data || data.length < 2) return;

    var up = cell.classList.contains('tape__cell--up');
    var down = cell.classList.contains('tape__cell--down');
    var color = up ? '#30a46c' : (down ? '#e5484d' : '#4ea1ff');

    var W = 120, H = 34, P = 2;
    var min = Math.min.apply(null, data), max = Math.max.apply(null, data);
    var range = (max - min) || 1;
    var pts = data.map(function (v, i) {
      var x = P + i * (W - 2 * P) / (data.length - 1);
      var y = P + (H - 2 * P) * (1 - (v - min) / range);
      return x.toFixed(1) + ' ' + y.toFixed(1);
    });
    var line = pts.map(function (p, i) { return (i ? 'L' : 'M') + p; }).join(' ');
    var area = line + ' L' + (W - P) + ' ' + (H - P) + ' L' + P + ' ' + (H - P) + ' Z';
    var id = 'sg' + Math.random().toString(36).slice(2, 8);

    var svg =
      '<svg class="spark" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">' +
      '<defs><linearGradient id="' + id + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="' + color + '" stop-opacity="0.5"/>' +
      '<stop offset="1" stop-color="' + color + '" stop-opacity="0"/></linearGradient></defs>' +
      '<path d="' + area + '" fill="url(#' + id + ')"/>' +
      '<path d="' + line + '" fill="none" stroke="' + color + '" stroke-width="1.5" vector-effect="non-scaling-stroke"/>' +
      '</svg>';

    var holder = document.createElement('div');
    holder.className = 'tape__spark';
    holder.innerHTML = svg;
    cell.appendChild(holder);
  }
  var cells = document.querySelectorAll('.tape__cell[data-spark]');
  for (var i = 0; i < cells.length; i++) draw(cells[i]);
})();
