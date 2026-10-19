/* BuoyUp i18n: Vietnamese is the source language; English and Simplified Chinese are
   rendered in place from a phrase dictionary (i18n-dict.js) plus a few number patterns.
   Classic script, load in <head> right after i18n-dict.js so the first paint is translated.
   - Text nodes and placeholder/aria-label/title/alt (and value of input buttons) are
     translated when they match a dictionary phrase exactly (after trim), a phrase with
     its numbers replaced by {x}, a {x} template, or " · "-separated parts.
   - The Vietnamese source of every node is kept in a WeakMap, so switching back and
     forth never needs a reload. A MutationObserver covers content rendered later by JS.
   - Never touches what people type (input/textarea values, contenteditable) nor chat
     message bodies the seller wrote (the assistant answers in the chosen language; its
     template lines, e.g. Agent 3's reasons, still match the dictionary); <option> without
     value keeps its Vietnamese value for the API. */
(function (global) {
  'use strict';
  var BU = global.BU = global.BU || {};
  var doc = global.document, root = doc.documentElement;
  var STORE = 'bu_lang';
  var LANGS = [['vi', 'VI', 'Tiếng Việt'], ['en', 'EN', 'English'], ['zh', '中文', '简体中文']];
  var IDX = { en: 0, zh: 1 };
  var ATTRS = ['placeholder', 'aria-label', 'title', 'alt'];
  var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, NOSCRIPT: 1, CODE: 1, PRE: 1 };
  var NO_WALK = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1 };
  var SKIP_SEL = '[data-i18n-skip],[contenteditable=""],[contenteditable="true"],.chat-msg.from-me .chat-content';
  var NUM = /\d+(?:[.,]\d+)*/g;
  var VI_CHARS = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i;
  var AFFIX = /^([\s↗↘↙↖←→↓↑↶↻⇄·•✓✔✕×✧◇◈◎◐▦⌕⌘☰…:\-–—+*#(\[“"]*)([\s\S]*?)([\s↗↘↙↖←→↓↑·•✓…:;,.!?)\]”"\-–—*]*)$/;

  var dict = null, templates = null, reverse = null, cache = { en: new Map(), zh: new Map() };
  var textMeta = new WeakMap(), attrMeta = new WeakMap();
  var lang = 'vi', touched = false, observer = null;

  function loadDict() {
    if (dict) return dict;
    dict = Object.create(null);
    var src = BU.i18nDict || {};
    Object.keys(src).forEach(function (k) { dict[norm(k)] = src[k]; });
    return dict;
  }
  function norm(s) { return String(s).replace(/[\s ]+/g, ' ').trim(); }
  function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function buildTemplates() {
    if (templates) return templates;
    templates = [];
    var d = loadDict();
    Object.keys(d).forEach(function (key) {
      if (key.indexOf('{x}') < 0) return;
      var parts = key.split('{x}');
      if (!parts.join('').replace(/[\s·:,.()\-–—/]/g, '')) return; // nothing literal to anchor on
      var body = parts.map(function (p) { return escapeRe(p).replace(/ /g, '\\s*'); }).join('(.*?)');
      var letters = (parts.join('').match(/[A-Za-zÀ-ỹĐđ]/g) || []).length;
      templates.push({ prefix: parts[0].trim(), re: new RegExp('^\\s*' + body + '\\s*$'), key: key, n: parts.length - 1, weight: parts.join('').length, letters: letters });
    });
    templates.sort(function (a, b) { return b.weight - a.weight; });
    return templates;
  }
  function buildReverse() {
    if (reverse) return reverse;
    reverse = new Map();
    var d = loadDict();
    Object.keys(d).forEach(function (key) {
      if (key.indexOf('{x}') >= 0) return;
      d[key].forEach(function (v) { if (v && v.length >= 4 && v !== key && !reverse.has(v)) reverse.set(v, key); });
    });
    return reverse;
  }
  /* Vietnamese number formatting (1.234,5) to English/Chinese (1,234.5). */
  function nums(s) {
    return String(s).replace(/\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+(?![.,]?\d)/g, function (m) {
      return m.replace(/[.,]/g, function (c) { return c === '.' ? ',' : '.'; });
    });
  }
  function fill(out, values) {
    var i = 0;
    return out.replace(/\{(x|\d+)\}/g, function (_, k) {
      var v = k === 'x' ? values[i++] : values[Number(k) - 1];
      return v == null ? '' : v;
    });
  }
  function pick(entry, l) { var v = entry && entry[IDX[l]]; return typeof v === 'string' ? v : null; }

  /* Translate one trimmed Vietnamese string; null when unknown. */
  function tr(src, l, depth) {
    if (!src || l === 'vi') return null;
    var c = cache[l];
    if (c.has(src)) return c.get(src);
    var out = lookup(src, l, depth || 0);
    if (c.size > 6000) c.clear();
    c.set(src, out);
    return out;
  }
  function lookup(src, l, depth) {
    var d = loadDict(), key = norm(src), hit = d[key];
    if (hit) return pick(hit, l);
    if (!/[A-Za-zÀ-ỹĐđ]/.test(key)) { var bare = nums(key); return bare !== key ? bare : null; } // Vietnamese-formatted numbers
    // Numbers replaced by {x}: "Bước 3/9" -> "Bước {x}/{x}".
    var found = key.match(NUM);
    if (found) {
      hit = d[key.replace(NUM, '{x}')];
      if (hit && pick(hit, l) != null) return fill(pick(hit, l), found.map(nums));
    }
    // Strip decorative prefixes/suffixes: "← Quay lại", "Mật khẩu mẫu:", "Tiếp tục ↗".
    var m = AFFIX.exec(key);
    if (m && /\)/.test(m[3]) && m[2].indexOf('(') >= 0) m = null; // keep balanced brackets for templates
    if (m && (m[1] || m[3]) && m[2] && m[2] !== key) {
      var core = tr(m[2], l, depth + 1);
      if (core != null) {
        var tail = m[3];
        if (l === 'zh') tail = tail.replace(/^:\s*$/, '：').replace(/^\.$/, '。');
        return m[1] + core + tail;
      }
    }
    if (depth > 3) return null;
    // " · "-separated labels: translate every part that is known, keep the others.
    if (key.indexOf(' · ') > 0) {
      var any = false;
      var parts = key.split(' · ').map(function (p) {
        var t = tr(p, l, depth + 1); if (t != null) { any = true; return t; } return p;
      });
      if (any) return parts.join(' · ');
    }
    // "Label: value" / "A — B": only when every Vietnamese part resolves.
    var sep = key.indexOf(': ') > 0 ? ': ' : key.indexOf(' — ') > 0 ? ' — ' : null;
    if (sep) {
      var ok = true;
      var pieces = key.split(sep).map(function (p, i, all) {
        var t = tr(p, l, depth + 1); if (t != null) return t;
        // A short leading name ("Váy liền: Doanh thu …") may stay as data.
        if (/[A-Za-zÀ-ỹĐđ]{2}/.test(p) && !(i === 0 && all.length === 2 && p.length <= 32)) ok = false;
        return p;
      });
      if (pieces.length === 2 && pieces[1] === key.split(sep)[1]) ok = false;
      if (ok) return pieces.join(l === 'zh' && sep === ': ' ? '：' : sep);
    }
    // Known label followed by an amount: "Doanh thu 150.000 tệ", "Lãi suất 12,5%".
    var tailNum = /^(.*?[^\d\s.,])\s+((?:[+\-−])?\d[\d.,]*\s*(?:tệ|đồng|%|tháng|ngày|năm|kỳ|giờ|phút|giây|khoản|lần)?)$/.exec(key);
    if (tailNum) {
      var head = tr(tailNum[1], l, depth + 1);
      if (head != null) return head + ' ' + (tr(tailNum[2], l, depth + 1) || nums(tailNum[2]));
    }
    if (!VI_CHARS.test(key)) return null;
    var list = buildTemplates();
    for (var i = 0; i < list.length; i++) {
      var t = list[i];
      if (t.prefix && key.lastIndexOf(t.prefix, 0) !== 0) continue;
      var mm = t.re.exec(key);
      if (!mm || mm[0] === '') continue;
      var target = pick(d[t.key], l);
      if (target == null) continue;
      var loose = false;
      var vals = mm.slice(1).map(function (v) {
        v = v.trim(); if (!v) return v;
        var x = tr(v, l, depth + 1);
        if (x != null) return x;
        if (/[A-Za-zÀ-ỹĐđ]{2}/.test(v)) loose = true; // a name, or a phrase this template should not swallow
        return nums(v);
      });
      // Short templates such as "{x} tháng" must not wrap an untranslated Vietnamese phrase.
      if (loose && t.letters < 6) continue;
      return fill(target, vals).replace(/\s{2,}/g, ' ').trim();
    }
    return null;
  }
  function translateRaw(raw) {
    var m = /^(\s*)([\s\S]*?)(\s*)$/.exec(raw);
    if (!m[2]) return raw;
    var out = tr(m[2], lang);
    return out == null ? raw : m[1] + out + m[3];
  }
  /* The Vietnamese source of a value: what we last wrote maps back to its source;
     anything else is new content from the page (possibly a translated string it read back). */
  function sourceOf(meta, current) {
    if (meta && (current === meta.out || current === meta.src)) return meta.src;
    if (touched) {
      var t = norm(current), back = t && buildReverse().get(t);
      if (back) return current.replace(t, back);
    }
    return current;
  }

  function skipped(el) {
    for (var n = el; n && n.nodeType === 1; n = n.parentNode) if (SKIP_TAGS[n.nodeName]) return true;
    return !!(el && el.closest && el.closest(SKIP_SEL));
  }
  function doText(node) {
    var parent = node.parentNode;
    if (!parent || parent.nodeType !== 1 || skipped(parent)) return;
    var meta = textMeta.get(node), src = sourceOf(meta, node.data);
    if (!meta && lang === 'vi' && src === node.data) return;
    if (parent.nodeName === 'OPTION' && !parent.hasAttribute('value')) parent.setAttribute('value', norm(src));
    var out = lang === 'vi' ? src : translateRaw(src);
    textMeta.set(node, { src: src, out: out });
    if (node.data !== out) node.data = out;
  }
  function doAttrs(el) {
    if (NO_WALK[el.nodeName] || el.hasAttribute('data-i18n-skip')) return;
    var names = ATTRS;
    if (el.nodeName === 'INPUT' && /^(button|submit|reset)$/i.test(el.type)) names = ATTRS.concat('value');
    var metas = attrMeta.get(el);
    for (var i = 0; i < names.length; i++) {
      var name = names[i], cur = el.getAttribute(name);
      if (cur == null || !cur.trim()) continue;
      var meta = metas && metas[name];
      if (!meta && lang === 'vi') continue;
      var src = sourceOf(meta, cur), out = lang === 'vi' ? src : translateRaw(src);
      if (!metas) { metas = {}; attrMeta.set(el, metas); }
      metas[name] = { src: src, out: out };
      if (cur !== out) el.setAttribute(name, out);
    }
  }
  function walk(node) {
    if (!node) return;
    if (node.nodeType === 3) { doText(node); return; }
    if (node.nodeType !== 1 && node.nodeType !== 9 && node.nodeType !== 11) return;
    if (node.nodeType === 1) { if (NO_WALK[node.nodeName] || node.closest('[data-i18n-skip]')) return; if (!node.closest(SKIP_SEL)) doAttrs(node); }
    var w = doc.createTreeWalker(node, 5 /* SHOW_ELEMENT | SHOW_TEXT */, {
      acceptNode: function (n) {
        if (n.nodeType === 1) return NO_WALK[n.nodeName] || n.hasAttribute('data-i18n-skip') ? 2 : 1; // reject the whole subtree
        return 1;
      }
    });
    var n, texts = [], els = [];
    while ((n = w.nextNode())) (n.nodeType === 3 ? texts : els).push(n);
    els.forEach(function (el) { if (!el.closest(SKIP_SEL)) doAttrs(el); });
    texts.forEach(doText);
  }
  function handle(records) {
    if (lang === 'vi' && !touched) return;
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r.type === 'childList') for (var j = 0; j < r.addedNodes.length; j++) walk(r.addedNodes[j]);
      else if (r.type === 'characterData') doText(r.target);
      else if (r.type === 'attributes' && r.target.nodeType === 1 && !r.target.closest(SKIP_SEL)) doAttrs(r.target);
    }
  }
  function observe() {
    if (observer || !global.MutationObserver) return;
    observer = new MutationObserver(function (records) {
      handle(records); mountSwitchers();
      observer.takeRecords(); // our own writes are already settled
    });
    observer.observe(root, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS.concat('value') });
  }
  function flush() { if (observer) { handle(observer.takeRecords()); } }

  var fontLoaded = false;
  function ensureFont() {
    if (fontLoaded || lang !== 'zh' || !doc.head) return;
    fontLoaded = true;
    var link = doc.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap';
    doc.head.appendChild(link);
  }
  function setLang(next, opts) {
    if (next !== 'en' && next !== 'zh') next = 'vi';
    if (next !== lang) touched = true;
    lang = next;
    root.lang = next === 'zh' ? 'zh-CN' : next;
    root.setAttribute('data-lang', next);
    if (!opts || opts.persist !== false) { try { localStorage.setItem(STORE, next); } catch (_) { /* storage may be blocked */ } }
    ensureFont();
    if (doc.body || (opts && opts.force)) walk(root);
    syncSwitchers();
    try { doc.dispatchEvent(new CustomEvent('bu:lang', { detail: next })); } catch (_) {}
  }

  /* ---- Language switcher: a compact menu placed right after each theme toggle. ---- */
  var switchers = [];
  var UI_LABEL = { vi: 'Ngôn ngữ', en: 'Language', zh: '语言' };
  function makeSwitcher(className) {
    var wrap = doc.createElement('div');
    wrap.className = 'bu-lang';
    wrap.setAttribute('data-i18n-skip', '');
    var btn = doc.createElement('button');
    btn.type = 'button';
    btn.className = (className || '') + ' bu-lang-btn';
    btn.setAttribute('aria-haspopup', 'true');
    btn.setAttribute('aria-expanded', 'false');
    btn.innerHTML = '<svg class="bu-lang-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.6 3.9 5.6 3.9 9s-1.3 6.4-3.9 9c-2.6-2.6-3.9-5.6-3.9-9S9.4 5.6 12 3z"/></svg><span class="bu-lang-code"></span>';
    var menu = doc.createElement('div');
    menu.className = 'bu-lang-menu';
    menu.setAttribute('role', 'menu');
    menu.hidden = true;
    LANGS.forEach(function (item) {
      var opt = doc.createElement('button');
      opt.type = 'button';
      opt.setAttribute('role', 'menuitemradio');
      opt.setAttribute('lang', item[0] === 'zh' ? 'zh-CN' : item[0]);
      opt.dataset.lang = item[0];
      opt.innerHTML = '<span class="bu-lang-opt-code">' + item[1] + '</span><span>' + item[2] + '</span>';
      opt.addEventListener('click', function () { close(wrap, true); setLang(item[0]); });
      menu.appendChild(opt);
    });
    btn.addEventListener('click', function () { if (menu.hidden) open(wrap); else close(wrap, false); });
    wrap.addEventListener('keydown', function (event) {
      var items = Array.prototype.slice.call(menu.querySelectorAll('button'));
      var at = items.indexOf(doc.activeElement);
      if (event.key === 'Escape' && !menu.hidden) { event.stopPropagation(); close(wrap, true); }
      else if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && !menu.hidden) {
        event.preventDefault();
        var next = at < 0 ? 0 : (at + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
        items[next].focus();
      }
    });
    wrap.appendChild(btn); wrap.appendChild(menu);
    switchers.push(wrap);
    syncOne(wrap);
    return wrap;
  }
  function open(wrap) {
    switchers.forEach(function (w) { if (w !== wrap) close(w, false); });
    var btn = wrap.firstChild, menu = wrap.lastChild;
    var rect = btn.getBoundingClientRect();
    wrap.classList.toggle('is-up', rect.bottom > global.innerHeight - 170);
    wrap.classList.toggle('is-left', rect.left < 150);
    menu.hidden = false; btn.setAttribute('aria-expanded', 'true');
    var current = menu.querySelector('[aria-checked="true"]') || menu.firstChild;
    current.focus();
  }
  function close(wrap, focus) {
    var btn = wrap.firstChild, menu = wrap.lastChild;
    if (menu.hidden) return;
    menu.hidden = true; btn.setAttribute('aria-expanded', 'false');
    if (focus) btn.focus();
  }
  function syncOne(wrap) {
    var btn = wrap.firstChild;
    var item = LANGS.filter(function (x) { return x[0] === lang; })[0];
    btn.querySelector('.bu-lang-code').textContent = item[1];
    btn.setAttribute('aria-label', UI_LABEL[lang] + ': ' + item[2]);
    btn.title = UI_LABEL[lang];
    wrap.lastChild.setAttribute('aria-label', UI_LABEL[lang]);
    Array.prototype.forEach.call(wrap.lastChild.children, function (opt) {
      opt.setAttribute('aria-checked', String(opt.dataset.lang === lang));
    });
  }
  function syncSwitchers() { switchers.forEach(syncOne); }
  var TOGGLES = '.marketing-theme,.auth-theme,[data-theme-toggle],[data-lang-switch]';
  function mountSwitchers() {
    if (!doc.body) return;
    var hosts = doc.querySelectorAll(TOGGLES);
    for (var i = 0; i < hosts.length; i++) {
      var host = hosts[i];
      if (host.__buLang && host.__buLang.isConnected) continue;
      var sw;
      if (host.hasAttribute('data-lang-switch')) { sw = makeSwitcher(host.getAttribute('data-lang-class') || 'bu-lang-pill'); host.appendChild(sw); }
      else {
        var cls = host.className.replace(/\b(is-[\w-]+|marketing-theme|auth-theme)\b/g, '').trim();
        if (host.classList.contains('marketing-theme')) cls = 'bu-lang-foot';
        if (host.classList.contains('auth-theme')) cls = 'bu-lang-auth';
        sw = makeSwitcher(cls);
        host.insertAdjacentElement('afterend', sw);
      }
      host.__buLang = sw;
    }
  }
  function mountFloating() {
    if (doc.querySelector('.bu-lang')) return;
    var holder = doc.createElement('div');
    holder.className = 'bu-lang-float';
    holder.appendChild(makeSwitcher('bu-lang-pill'));
    doc.body.appendChild(holder);
  }
  doc.addEventListener('click', function (event) {
    switchers.forEach(function (w) { if (!w.contains(event.target)) close(w, false); });
  });

  // Boot: language from storage, then translate as the parser streams the page in.
  var saved = 'vi';
  try { saved = localStorage.getItem(STORE) || 'vi'; } catch (_) { /* storage may be blocked */ }
  if (saved !== 'en' && saved !== 'zh') saved = 'vi';
  lang = saved; touched = saved !== 'vi';
  root.lang = saved === 'zh' ? 'zh-CN' : saved;
  root.setAttribute('data-lang', saved);
  ensureFont();
  observe();
  if (touched && doc.body) walk(root);
  function ready() {
    mountSwitchers(); mountFloating();
    if (touched) walk(root);
    if (observer) observer.takeRecords();
  }
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', ready); else ready();

  BU.i18n = {
    lang: function () { return lang; },
    set: function (next) { setLang(next); },
    /** Translate a Vietnamese UI string for the current language (returns the source when unknown). */
    t: function (text) { if (lang === 'vi') return text; var out = tr(norm(text), lang); return out == null ? text : out; },
    /** Apply pending translations synchronously (use after innerHTML when code reads text back). */
    flush: flush,
    /** The Vietnamese source of a rendered text node or element's text. */
    source: function (node) {
      if (!node) return '';
      if (node.nodeType === 3) { var m = textMeta.get(node); return m && node.data === m.out ? m.src : node.data; }
      var out = '', w = doc.createTreeWalker(node, 4), n;
      while ((n = w.nextNode())) { var mm = textMeta.get(n); out += mm && n.data === mm.out ? mm.src : n.data; }
      return out;
    },
    languages: LANGS.map(function (x) { return x[0]; })
  };
})(window);
