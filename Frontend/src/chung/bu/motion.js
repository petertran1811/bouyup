/* BuoyUp motion. Classic script; load GSAP/ScrollTrigger first, Lenis on marketing only. */
(function (global) {
  'use strict';
  const BU = global.BU = global.BU || {};
  const doc = global.document, root = doc.documentElement;
  const preference = global.matchMedia('(prefers-reduced-motion: reduce)');
  const darkPreference = global.matchMedia('(prefers-color-scheme: dark)');
  const seen = new WeakSet(), tilts = new Set(), counters = new Map(), tweens = new Set(), pausedTweens = new Set();
  let lenis = null, frame = 0, marketing = false;
  const reduced = () => preference.matches || root.dataset.motion === 'reduce';
  function theme() { return root.dataset.theme || (darkPreference.matches ? 'dark' : 'light'); }
  function setTheme(value) {
    if (value !== 'light' && value !== 'dark') return;
    root.dataset.theme = value;
    try { localStorage.setItem('bu_theme', value); } catch (_) { /* Private browser storage may be unavailable. */ }
    const meta = doc.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = value === 'dark' ? '#0c090b' : '#f8f4f7';
    doc.dispatchEvent(new CustomEvent('bu:theme', { detail: value }));
  }
  try { const saved = localStorage.getItem('bu_theme'); if (saved === 'dark' || saved === 'light') root.dataset.theme = saved; } catch (_) {}
  function nodes(scope, selector) {
    return [...(scope.matches && scope.matches(selector) ? [scope] : []), ...scope.querySelectorAll(selector)];
  }
  function tick(time) {
    frame = 0;
    if (doc.hidden || reduced()) return;
    if (lenis) lenis.raf(time);
    counters.forEach((state, el) => {
      if (state.start === null) state.start = time;
      const progress = Math.min((time - state.start) / state.duration, 1);
      state.render(state.from + (state.target - state.from) * (1 - Math.pow(1 - progress, 3)));
      if (progress === 1) counters.delete(el);
    });
    if (lenis || counters.size) frame = global.requestAnimationFrame(tick);
  }
  function schedule() { if (!frame && !doc.hidden && !reduced() && (lenis || counters.size)) frame = global.requestAnimationFrame(tick); }
  /** target must come from API data. duration: milliseconds; decimals, prefix, suffix, from. */
  function countUp(el, target, options = {}) {
    if (!el || !Number.isFinite(Number(target)) || target === null || target === '') return;
    target = Number(target);
    const formatter = new Intl.NumberFormat('vi-VN', { minimumFractionDigits: options.decimals || 0, maximumFractionDigits: options.decimals || 0 });
    const format = value => `${options.prefix || ''}${formatter.format(value)}${options.suffix || ''}`;
    const render = value => { el.textContent = format(value); };
    el.setAttribute('aria-label', format(target));
    el.setAttribute('aria-live', 'off');
    counters.delete(el);
    if (reduced() || doc.hidden || options.duration === 0) { render(target); return; }
    render(options.from || 0);
    counters.set(el, { target, from: options.from || 0, duration: Math.max(1, options.duration || 1200), start: null, render });
    schedule();
  }
  function reveal(scope = doc) {
    nodes(scope, '[data-reveal]').forEach((el, index) => {
      if (seen.has(el)) return;
      seen.add(el);
      if (reduced() || !global.gsap || !global.ScrollTrigger) { el.classList.add('is-in'); return; }
      global.gsap.registerPlugin(global.ScrollTrigger);
      const tween = global.gsap.fromTo(el, { opacity: 0, y: 26 }, {
        opacity: 1, y: 0, duration: .6, delay: Math.min(index % 5 * .055, .22), ease: 'power3.out',
        clearProps: 'opacity,transform', scrollTrigger: { trigger: el, start: 'top 94%', once: true },
        onComplete() { el.classList.add('is-in'); tweens.delete(tween); }
      });
      tweens.add(tween);
    });
  }
  function tilt(scope) {
    nodes(scope, '[data-tilt]').forEach(el => {
      if (tilts.has(el)) return;
      tilts.add(el);
      let pending = 0;
      const reset = () => { cancelAnimationFrame(pending); pending = 0; el.style.removeProperty('transform'); el.style.removeProperty('--bu-mx'); el.style.removeProperty('--bu-my'); };
      el._buResetTilt = reset;
      el.addEventListener('pointermove', event => {
        if (reduced() || doc.hidden || event.pointerType !== 'mouse' || el.matches(':focus-within')) return;
        const bounds = el.getBoundingClientRect();
        const x = (event.clientX - bounds.left) / bounds.width, y = (event.clientY - bounds.top) / bounds.height;
        cancelAnimationFrame(pending);
        pending = requestAnimationFrame(() => {
          const max = Math.min(Number(el.dataset.tiltMax) || 3, 6);
          el.style.transform = `perspective(1100px) rotateX(${(0.5-y)*max}deg) rotateY(${(x-0.5)*max}deg)`;
          el.style.setProperty('--bu-mx', `${x*100}%`); el.style.setProperty('--bu-my', `${y*100}%`);
        });
      }, { passive: true });
      el.addEventListener('pointerleave', reset); el.addEventListener('focusin', reset);
    });
  }
  function sync() {
    const pause = doc.hidden || reduced();
    root.toggleAttribute('data-bu-paused', pause);
    if (pause) {
      cancelAnimationFrame(frame); frame = 0;
      tilts.forEach(el => el._buResetTilt());
      counters.forEach(state => state.render(state.target)); counters.clear();
      tweens.forEach(tween => {
        if (reduced()) { tween.progress(1); if (tween.scrollTrigger) tween.scrollTrigger.kill(); }
        else if (tween.isActive()) { tween.pause(); pausedTweens.add(tween); }
      });
      if (reduced()) { tweens.clear(); pausedTweens.clear(); }
    } else { pausedTweens.forEach(tween => tween.resume()); pausedTweens.clear(); }
    if (lenis && pause) { lenis.destroy(); lenis = null; }
    if (!pause && marketing && !lenis && global.Lenis) {
      lenis = new global.Lenis({ autoRaf: false, lerp: .1, smoothWheel: true, anchors: true });
      if (global.ScrollTrigger) lenis.on('scroll', global.ScrollTrigger.update);
    }
    doc.querySelectorAll('video[autoplay],video[data-bu-video]').forEach(video => {
      if (pause) video.pause(); else { const promise = video.play(); if (promise) promise.catch(() => {}); }
    });
    schedule();
  }
  function toast(message, options = {}) {
    let host = doc.querySelector('.bu-toast-host');
    if (!host) { host = doc.createElement('div'); host.className = 'bu-toast-host'; host.setAttribute('role', 'status'); host.setAttribute('aria-live', 'polite'); doc.body.append(host); }
    const el = doc.createElement('div'); el.className = 'bu-toast';
    const text = doc.createElement('span'); text.textContent = message;
    const close = doc.createElement('button'); close.type = 'button'; close.textContent = '×'; close.setAttribute('aria-label', 'Đóng thông báo');
    close.addEventListener('click', () => el.remove()); el.append(text, close); host.append(el);
    setTimeout(() => el.remove(), options.duration || 6000); return el;
  }
  function init(scope = doc, options = {}) { marketing = marketing || !!options.marketing; reveal(scope); tilt(scope); sync(); }
  doc.addEventListener('visibilitychange', sync);
  preference.addEventListener('change', sync);
  new MutationObserver(sync).observe(root, { attributes: true, attributeFilter: ['data-motion'] });
  doc.addEventListener('click', event => { const target = event.target.closest('[data-theme-toggle]'); if (target) setTheme(theme() === 'dark' ? 'light' : 'dark'); });
  BU.motion = { init, reveal, countUp, reduced, theme, setTheme, toast };
})(window);
