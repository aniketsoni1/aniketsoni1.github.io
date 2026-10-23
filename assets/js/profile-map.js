/* ════════════════════════════════════════════════════════════════════
   profile-map.js - "Around the World" map on /profile/ (#map)
   Progressive enhancement: without JS the section shows a country list.
   Data:  #pf-map-data, rendered from the `geo:` tags in _data/profile.yml.
   Shape: assets/img/world-map.svg (scripts/build_world_map.mjs), fetched
          the first time the section is on screen.
   One pin per country; each pin carries one colored dot per category.
   ════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var sec = document.getElementById('map');
  var dataEl = document.getElementById('pf-map-data');
  if (!sec || !dataEl || !window.fetch || !window.DOMParser) return;
  var D;
  try { D = JSON.parse(dataEl.textContent); } catch (e) { return; }
  // `geo: XX` arrives as a string, `geo: [XX, YY]` as an array.
  D.items.forEach(function (it) { it.c = [].concat(it.c); });

  var NS = 'http://www.w3.org/2000/svg';
  var wrap = sec.querySelector('.pf-map');
  var canvas = sec.querySelector('.pf-map-canvas');
  var panel = sec.querySelector('.pf-map-panel');
  var tip = sec.querySelector('.pm-tip');
  var bar = sec.querySelector('.pf-map-filter');
  var ORDER = D.groups.map(function (g) { return g.k; });
  var LABEL = {};
  D.groups.forEach(function (g) { LABEL[g.k] = g.l; });

  var state = { k: 'all', sel: null };
  var svg = null, pins = null, scale = 1, started = false;

  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function plural(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }
  function cname(c) { return (D.geo[c] || [c])[0]; }

  // Items under the current filter, grouped by country code.
  function byCountry() {
    var out = {};
    D.items.forEach(function (it) {
      if (state.k !== 'all' && it.k !== state.k) return;
      it.c.forEach(function (c) { (out[c] = out[c] || []).push(it); });
    });
    return out;
  }
  // [[category, count], ...] in the configured category order.
  function cats(list) {
    var n = {};
    list.forEach(function (it) { n[it.k] = (n[it.k] || 0) + 1; });
    return ORDER.filter(function (k) { return n[k]; }).map(function (k) { return [k, n[k]]; });
  }
  // Countries by record count (most first), worldwide / online last.
  function ranked(groups) {
    return Object.keys(groups).sort(function (a, b) {
      if (a === 'WW') return 1;
      if (b === 'WW') return -1;
      return groups[b].length - groups[a].length || cname(a).localeCompare(cname(b));
    });
  }
  function dots(list) {
    return '<span class="pm-dots">' + cats(list).map(function (x) {
      return '<i class="m-' + x[0] + '" title="' + esc(LABEL[x[0]]) + ': ' + x[1] + '"></i>';
    }).join('') + '</span>';
  }

  // ── Pins ───────────────────────────────────────────────────────────
  var STEP = 9.2, R = 3.8, PAD = 4.4;
  function pinScale() {
    var w = canvas.clientWidth || 960;
    return Math.max(1, Math.min(1.7, 0.6 * 960 / w));
  }
  function el(name, attrs) {
    var n = document.createElementNS(NS, name);
    for (var a in attrs) n.setAttribute(a, attrs[a]);
    return n;
  }
  function drawPins() {
    if (!svg) return;
    var groups = byCountry();
    Array.prototype.forEach.call(svg.querySelectorAll('path[data-c]'), function (p) {
      var c = p.getAttribute('data-c');
      p.classList.toggle('has', !!groups[c]);
      p.classList.toggle('sel', c === state.sel);
    });
    pins.textContent = '';
    // Larger clusters first so smaller neighbours stay clickable on top.
    ranked(groups).forEach(function (c) {
      var g = D.geo[c];
      if (c === 'WW' || !g) return;
      var list = groups[c], cs = cats(list), n = cs.length;
      var cols = n > 4 ? Math.ceil(n / 2) : n, rows = Math.ceil(n / cols);
      var w = cols * STEP + PAD, h = rows * STEP + PAD;
      var pin = el('g', {
        'class': 'pm-pin' + (c === state.sel ? ' is-sel' : ''), 'data-c': c, tabindex: '0', role: 'button',
        'aria-label': g[0] + ': ' + plural(list.length, 'record') + '. ' + cs.map(function (x) { return LABEL[x[0]] + ' ' + x[1]; }).join(', '),
        transform: 'translate(' + g[1] + ' ' + g[2] + ') scale(' + scale + ')'
      });
      pin.appendChild(el('rect', { 'class': 'pm-pill', x: -w / 2, y: -h / 2, width: w, height: h, rx: Math.min(h / 2, 7) }));
      cs.forEach(function (x, i) {
        var col = i % cols, row = Math.floor(i / cols);
        var inRow = row === rows - 1 ? n - row * cols : cols;  // centre a short last row
        pin.appendChild(el('circle', {
          'class': 'm-' + x[0], r: R,
          cx: (col - (inRow - 1) / 2) * STEP, cy: (row - (rows - 1) / 2) * STEP
        }));
      });
      pins.insertBefore(pin, pins.firstChild);
    });
  }
  function rescale() {
    var s = pinScale();
    if (Math.abs(s - scale) < 0.02) return;
    scale = s;
    Array.prototype.forEach.call(pins ? pins.querySelectorAll('.pm-pin') : [], function (p) {
      p.setAttribute('transform', p.getAttribute('transform').replace(/scale\([^)]*\)/, 'scale(' + s + ')'));
    });
  }

  // ── Tooltip ────────────────────────────────────────────────────────
  function showTip(c, target) {
    var list = byCountry()[c];
    if (!list) return hideTip();
    var html = '<div class="pm-tip-h">' + esc(cname(c)) + ' <b>' + list.length + '</b></div><ul>';
    cats(list).forEach(function (x) {
      html += '<li><i class="m-' + x[0] + '"></i>' + esc(LABEL[x[0]]) + '<b>' + x[1] + '</b></li>';
    });
    tip.innerHTML = html + '</ul><div class="pm-tip-f">' + (c === state.sel ? 'Selected' : 'Click for details') + '</div>';
    tip.hidden = false;
    var cr = canvas.getBoundingClientRect(), r = target.getBoundingClientRect();
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(Math.max(r.left - cr.left + r.width / 2 - w / 2, 6), cr.width - w - 6);
    var top = r.top - cr.top - h - 8;
    if (top < 4) top = r.bottom - cr.top + 8;
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }
  function hideTip() { tip.hidden = true; }

  // ── Side panel ─────────────────────────────────────────────────────
  function link(it) {
    var ext = /^https?:/.test(it.u);
    return '<a href="' + esc(it.u) + '"' + (ext ? ' target="_blank" rel="noopener"' : '') + '>' + esc(it.t) + (ext ? ' ↗' : '') + '</a>';
  }
  function renderPanel() {
    var groups = byCountry();
    var keys = ranked(groups);
    var nC = keys.filter(function (c) { return c !== 'WW'; }).length;
    var total = 0, seen = [];
    keys.forEach(function (c) { groups[c].forEach(function (it) { if (seen.indexOf(it) < 0) { seen.push(it); total++; } }); });
    var scope = state.k === 'all' ? 'All categories' : LABEL[state.k];

    if (!state.sel || !groups[state.sel]) {
      state.sel = null;
      var html = '<div class="pm-head"><span class="pm-eyebrow">' + esc(scope) + '</span>' +
        '<strong>' + nC + (nC === 1 ? ' country' : ' countries') + ' · ' + plural(total, 'record') + '</strong>' +
        '<span class="pm-hint">Select a pin or a country for details.</span></div><ol class="pm-rank">';
      keys.forEach(function (c) {
        html += '<li><button type="button" data-c="' + c + '"' + (c === 'WW' ? ' class="is-ww"' : '') + '>' +
          '<span class="pm-rn">' + esc(cname(c)) + '</span>' + dots(groups[c]) + '<b>' + groups[c].length + '</b></button></li>';
      });
      panel.innerHTML = html + '</ol>';
      return;
    }
    var c = state.sel, list = groups[c];
    var out = '<button type="button" class="pm-back">← All countries</button>' +
      '<div class="pm-head"><span class="pm-eyebrow">' + esc(scope) + '</span><strong>' + esc(cname(c)) + '</strong>' +
      '<span class="pm-hint">' + plural(list.length, 'record') + (c === 'WW' ? ' · online and worldwide programs, not pinned' : '') + '</span></div>';
    cats(list).forEach(function (x) {
      out += '<h3 class="pm-cat"><i class="m-' + x[0] + '"></i>' + esc(LABEL[x[0]]) + '<b>' + x[1] + '</b></h3><ul class="pm-items">';
      list.forEach(function (it) {
        if (it.k !== x[0]) return;
        out += '<li>' + link(it) + (it.o ? '<span>' + esc(it.o) + '</span>' : '') + (it.d ? '<small>' + esc(it.d) + '</small>' : '') + '</li>';
      });
      out += '</ul>';
    });
    panel.innerHTML = out;
  }

  function select(c, focusPanel) {
    state.sel = c;
    hideTip();
    drawPins();
    renderPanel();
    if (focusPanel) {
      var f = panel.querySelector('.pm-back, button');
      if (f) f.focus({ preventScroll: true });
    }
    if (c && window.matchMedia('(max-width: 900px)').matches) {
      panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }
  function setFilter(k) {
    state.k = k;
    Array.prototype.forEach.call(bar.querySelectorAll('button'), function (b) {
      var on = b.getAttribute('data-k') === k;
      b.classList.toggle('is-on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    drawPins();
    renderPanel();
  }

  // ── Wiring ─────────────────────────────────────────────────────────
  function onPin(e) {
    var t = e.target.closest ? e.target.closest('.pm-pin, path.has') : null;
    return t ? t.getAttribute('data-c') : null;
  }
  function wire() {
    svg.addEventListener('click', function (e) {
      var c = onPin(e);
      if (c) select(c === state.sel ? null : c, false);
    });
    svg.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var c = onPin(e);
      if (c) { e.preventDefault(); select(c, true); }
    });
    svg.addEventListener('mouseover', function (e) {
      var c = onPin(e);
      if (c) showTip(c, svg.querySelector('.pm-pin[data-c="' + c + '"]') || e.target);
    });
    svg.addEventListener('mouseout', function (e) {
      if (!e.relatedTarget || !svg.contains(e.relatedTarget) || !onPin({ target: e.relatedTarget })) hideTip();
    });
    svg.addEventListener('focusin', function (e) {
      var c = onPin(e);
      if (c) showTip(c, e.target);
    });
    svg.addEventListener('focusout', hideTip);
    panel.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      if (b.classList.contains('pm-back')) {
        var prev = state.sel;
        select(null, false);
        var again = panel.querySelector('button[data-c="' + prev + '"]');
        if (again) again.focus({ preventScroll: true });
      } else if (b.hasAttribute('data-c')) {
        select(b.getAttribute('data-c'), true);
      }
    });
    bar.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (b) setFilter(b.getAttribute('data-k'));
    });
    sec.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && state.sel) select(null, false);
    });
    if (window.ResizeObserver) new ResizeObserver(rescale).observe(canvas);
    else window.addEventListener('resize', rescale);
  }

  function fail() {
    sec.classList.remove('pm-js');
    wrap.hidden = true;
    bar.hidden = true;
  }
  function start() {
    if (started) return;
    started = true;
    fetch(wrap.getAttribute('data-src'))
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (text) {
        var doc = new DOMParser().parseFromString(text, 'image/svg+xml');
        var root = doc.documentElement;
        if (!root || root.nodeName.toLowerCase() !== 'svg') throw new Error('bad svg');
        svg = document.importNode(root, true);
        svg.setAttribute('class', 'pm-svg');
        svg.setAttribute('viewBox', wrap.getAttribute('data-vb') || svg.getAttribute('viewBox'));
        svg.setAttribute('role', 'group');
        svg.setAttribute('aria-label', 'World map. Each pin is a country; colored dots show the categories recorded there.');
        svg.removeAttribute('fill'); svg.removeAttribute('fill-opacity');
        pins = el('g', { 'class': 'pm-pins' });
        svg.appendChild(pins);
        canvas.insertBefore(svg, tip);
        scale = pinScale();
        drawPins();
        wire();
        sec.classList.add('pm-ready');
      })
      .catch(fail);
  }

  // Show the interactive view; the server-rendered list stays for print.
  sec.classList.add('pm-js');
  wrap.hidden = false;
  bar.hidden = false;
  renderPanel();
  if (window.IntersectionObserver) {
    var io = new IntersectionObserver(function (es) {
      if (es.some(function (x) { return x.isIntersecting; })) { io.disconnect(); start(); }
    }, { rootMargin: '300px' });
    io.observe(wrap);
  } else {
    start();
  }
})();
