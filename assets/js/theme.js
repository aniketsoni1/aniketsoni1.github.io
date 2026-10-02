/* ════════════════════════════════════════════════════════════════════
   theme.js - site-wide theme picker (loaded by every layout)

   The round #theme-toggle button opens a small menu: Light / Dark plus three
   accent swatches for the current mode. Choices persist in localStorage:
     theme          "light" | "dark"        (site default: light)
     accent-light   teal | indigo | terracotta
     accent-dark    teal | violet | amber
   The inline snippet in each layout's <head> applies the saved choice before
   first paint; this file only builds the menu and handles changes.
   ════════════════════════════════════════════════════════════════════ */
(function () {
  var PALETTES = {
    light: [
      { key: 'teal',       label: 'Teal',       color: '#007272' },
      { key: 'indigo',     label: 'Indigo',     color: '#3b4ccf' },
      { key: 'terracotta', label: 'Terracotta', color: '#b4532a' }
    ],
    dark: [
      { key: 'teal',   label: 'Teal',   color: '#009e9e' },
      { key: 'violet', label: 'Violet', color: '#a78bfa' },
      { key: 'amber',  label: 'Amber',  color: '#f5b041' }
    ]
  };
  var BG = { light: '#f5f4f1', dark: '#050505' };
  var root = document.documentElement;

  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function mode() { return root.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; }
  function accentFor(m) {
    var a = read('accent-' + m);
    return PALETTES[m].some(function (p) { return p.key === a; }) ? a : 'teal';
  }

  function apply(m, accent) {
    if (m === 'light') root.setAttribute('data-theme', 'light'); else root.removeAttribute('data-theme');
    root.setAttribute('data-accent', accent || accentFor(m));
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (t) { t.setAttribute('content', BG[m]); });
    store('theme', m);
    render();
  }

  // ── Menu ──
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.setAttribute('aria-haspopup', 'true');
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-label', 'Theme: mode and color');
  btn.setAttribute('title', 'Theme');

  var menu = document.createElement('div');
  menu.className = 'theme-menu';
  menu.id = 'theme-menu';
  menu.setAttribute('role', 'dialog');
  menu.setAttribute('aria-label', 'Theme settings');
  menu.innerHTML =
    '<p class="theme-menu-label">Mode</p>' +
    '<div class="theme-modes"><button type="button" data-mode="light">Light</button><button type="button" data-mode="dark">Dark</button></div>' +
    '<p class="theme-menu-label">Color</p>' +
    '<div class="theme-swatches"></div>';
  document.body.appendChild(menu);
  btn.setAttribute('aria-controls', 'theme-menu');

  function render() {
    var m = mode(), a = root.getAttribute('data-accent') || 'teal';
    menu.querySelectorAll('[data-mode]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-mode') === m)); });
    var sw = menu.querySelector('.theme-swatches');
    sw.innerHTML = PALETTES[m].map(function (p) {
      return '<button type="button" data-accent="' + p.key + '" aria-pressed="' + (p.key === a) + '" style="--sw:' + p.color + '">' +
             '<i aria-hidden="true"></i>' + p.label + '</button>';
    }).join('');
  }

  function open(show) {
    menu.classList.toggle('open', show);
    btn.setAttribute('aria-expanded', String(show));
    if (show) { var f = menu.querySelector('[aria-pressed="true"]'); if (f) f.focus({ preventScroll: true }); }
  }

  btn.addEventListener('click', function (e) { e.stopPropagation(); open(!menu.classList.contains('open')); });
  menu.addEventListener('click', function (e) {
    e.stopPropagation();
    var b = e.target.closest('button'); if (!b) return;
    if (b.hasAttribute('data-mode')) apply(b.getAttribute('data-mode'));
    else if (b.hasAttribute('data-accent')) { var k = b.getAttribute('data-accent'); store('accent-' + mode(), k); apply(mode(), k); }
  });
  document.addEventListener('click', function () { open(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && menu.classList.contains('open')) { open(false); btn.focus(); } });

  // Normalise state set by the <head> snippet (also covers first visits).
  apply(mode(), accentFor(mode()));
})();
