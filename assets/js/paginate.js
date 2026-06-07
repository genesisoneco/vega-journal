/* Client-side pagination for plain lists (GitHub Pages has no list paginator).
   Mark a container with data-paginate="N"; its element children become the items,
   shown N per page with a numbered pager. No JS -> every item just stays visible. */
(function () {
  function build(container) {
    var per = parseInt(container.getAttribute('data-paginate'), 10);
    if (!per || per < 1) return;
    var items = Array.prototype.filter.call(container.children, function (el) {
      return el.nodeType === 1;
    });
    if (items.length <= per) return;                 // nothing to paginate
    var pages = Math.ceil(items.length / per);
    var current = 0;

    var nav = document.createElement('nav');
    nav.className = 'pager';
    nav.setAttribute('aria-label', 'Pagination');
    container.parentNode.insertBefore(nav, container.nextSibling);

    function go(page, scroll) {
      current = Math.max(0, Math.min(pages - 1, page));
      var start = current * per, end = start + per;
      for (var i = 0; i < items.length; i++) {
        items[i].style.display = (i >= start && i < end) ? '' : 'none';
      }
      render();
      if (scroll) {
        var top = container.getBoundingClientRect().top + window.pageYOffset - 80;
        window.scrollTo({ top: top < 0 ? 0 : top, behavior: 'smooth' });
      }
    }

    function btn(label, page, opts) {
      opts = opts || {};
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'pager__btn' + (opts.active ? ' is-active' : '');
      b.textContent = label;
      if (opts.active) b.setAttribute('aria-current', 'page');
      if (opts.disabled) b.disabled = true;
      else b.addEventListener('click', function () { go(page, true); });
      return b;
    }

    function gap() {
      var s = document.createElement('span');
      s.className = 'pager__gap';
      s.textContent = '…';
      return s;
    }

    function windowed() {
      // always show first, last, and current +/-1; ellipses fill the rest.
      var set = {};
      set[0] = set[pages - 1] = 1;
      for (var d = -1; d <= 1; d++) {
        var p = current + d;
        if (p >= 0 && p < pages) set[p] = 1;
      }
      return Object.keys(set).map(Number).sort(function (a, b) { return a - b; });
    }

    function render() {
      nav.innerHTML = '';
      nav.appendChild(btn('Prev', current - 1, { disabled: current === 0 }));
      var ps = windowed(), prev = -1;
      ps.forEach(function (p) {
        if (p - prev > 1) nav.appendChild(gap());
        nav.appendChild(btn(String(p + 1), p, { active: p === current }));
        prev = p;
      });
      nav.appendChild(btn('Next', current + 1, { disabled: current === pages - 1 }));
    }

    go(0, false);
  }

  var containers = document.querySelectorAll('[data-paginate]');
  for (var i = 0; i < containers.length; i++) build(containers[i]);
})();
