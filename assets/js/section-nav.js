/* ════════════════════════════════════════════════════════════════════
   section-nav.js - floating page navigation (bottom-left), every page

   Stack, top to bottom:   ↑ Back to top   ‹ Previous   › Next
   - Back to top appears after scrolling 400px (same as before).
   - Previous / Next adapt to the page:
       homepage     scroll sections (hero, About, The Pipeline, ...)
       /profile/    one category open  -> adjacent categories
                    overview tiles     -> Next opens the first category
                    "View all" (#all)  -> section above / below the scroll
       blog post    previous / next post
       other pages  no Previous / Next (Back to top only)
   - At the first section Previous is hidden; at the last, Next is hidden.
   Labels show on hover and are read by screen readers ("Next: Experience").
   ════════════════════════════════════════════════════════════════════ */
(function () {
  var ICON = {
    top:  '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5,12 12,5 19,12"/></svg>',
    prev: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15,18 9,12 15,6"/></svg>',
    next: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9,18 15,12 9,6"/></svg>'
  };
  var body = document.body;

  // ── Build the stack (reuse an existing #back-to-top so page scripts keep working) ──
  var wrap = document.createElement('nav');
  wrap.className = 'page-nav';
  wrap.setAttribute('aria-label', 'Page navigation');
  var top = document.getElementById('back-to-top');
  if (!top) {
    top = document.createElement('button');
    top.id = 'back-to-top';
    top.type = 'button';
    top.innerHTML = ICON.top;
    top.addEventListener('click', function () { window.scrollTo({ top: 0, behavior: 'smooth' }); });
    window.addEventListener('scroll', function () { top.classList.toggle('visible', window.scrollY > 400); }, { passive: true });
  }
  top.setAttribute('aria-label', 'Back to top');
  top.setAttribute('data-label', 'Back to top');
  top.removeAttribute('title');
  function mk(kind) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'page-nav-btn page-nav-' + kind; b.innerHTML = ICON[kind]; b.hidden = true;
    return b;
  }
  var prev = mk('prev'), next = mk('next');
  wrap.appendChild(top); wrap.appendChild(prev); wrap.appendChild(next);
  body.appendChild(wrap);

  function setBtn(b, word, target) {
    if (!target) { b.hidden = true; b._go = null; return; }
    b.hidden = false; b._go = target.go;
    b.setAttribute('aria-label', word + ': ' + target.label);
    b.setAttribute('data-label', word + ': ' + target.label);
  }
  [prev, next].forEach(function (b) { b.addEventListener('click', function () { if (b._go) b._go(); }); });

  function clean(t) { return (t || '').replace(/\s+/g, ' ').trim(); }
  function scrollTo(el) { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  // index of the section whose top has passed ~35% of the viewport
  function currentIndex(list) {
    var line = window.innerHeight * 0.35, idx = 0;
    list.forEach(function (el, i) { if (el.getBoundingClientRect().top <= line) idx = i; });
    return idx;
  }
  function byScroll(list, name) {
    var i = currentIndex(list);
    var at = function (j) { var el = list[j]; return el ? { label: name(el), go: function () { scrollTo(el); } } : null; };
    return { prev: at(i - 1), next: at(i + 1) };
  }

  // ── Page adapters ──
  var resolve = null;

  // Blog post: previous / next post links rendered by the post layout.
  var pp = document.querySelector('.post-nav-prev'), pn = document.querySelector('.post-nav-next');
  if (pp || pn) {
    var link = function (a) {
      if (!a) return null;
      var t = a.querySelector('.pn-title');
      return { label: clean(t ? t.textContent : a.textContent), go: function () { location.href = a.href; } };
    };
    resolve = function () { return { prev: link(pp), next: link(pn) }; };
  }

  // Profile: category view, overview, or "View all".
  else if (document.querySelector('.pf-section')) {
    var cats = Array.prototype.slice.call(document.querySelectorAll('.pf-section'));
    var title = function (el) { var h = el.querySelector('.pf-h2'); return clean(h ? h.textContent : el.id); };
    var open = function (el) { return { label: title(el), go: function () { location.hash = '#' + el.id; } }; };
    resolve = function () {
      if (body.classList.contains('pf-all') || body.classList.contains('pf-searching')) {
        var vis = cats.filter(function (c) { return c.offsetParent !== null; });
        return byScroll(vis, title);
      }
      var active = cats.filter(function (c) { return c.classList.contains('is-active'); })[0];
      if (!active) return { prev: null, next: open(cats[0]) };       // overview tiles
      var i = cats.indexOf(active);
      return { prev: cats[i - 1] ? open(cats[i - 1]) : null, next: cats[i + 1] ? open(cats[i + 1]) : null };
    };
  }

  // Homepage: top-level scroll sections.
  else {
    var secs = Array.prototype.slice.call(document.querySelectorAll('main section[id], body > section[id]'))
      .filter(function (s) { return !s.closest('footer') && !(s.parentElement && s.parentElement.closest('section')); });
    if (secs.length > 1) {
      var name = function (s) {
        if (s.id === 'hero') return 'Introduction';
        var h = s.querySelector('.sec-title, h2');
        var t = clean(h ? h.textContent : '');
        return t || clean((s.getAttribute('aria-label') || s.id).split(' and ')[0]);
      };
      resolve = function () { return byScroll(secs, name); };
    }
  }

  function update() {
    var r = resolve ? resolve() : { prev: null, next: null };
    setBtn(prev, 'Previous', r.prev);
    setBtn(next, 'Next', r.next);
  }
  var queued = false;
  window.addEventListener('scroll', function () {
    if (queued) return; queued = true;
    requestAnimationFrame(function () { queued = false; update(); });
  }, { passive: true });
  window.addEventListener('hashchange', function () { setTimeout(update, 0); });
  window.addEventListener('resize', update);
  update();
  setTimeout(update, 300);   // after the profile router has applied the hash
})();
