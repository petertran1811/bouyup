/* BuoyUp staff hub: a home view with one tile per function, each function on its own view.
   Hash routes (#/queue, #/complaints, ...) so back/forward, reload and deep links work.
   Only shows and hides the sections admin-v4.js already renders; it calls no API and changes
   no permission: admin-only tiles and sections keep the data-admin attribute that admin-v4.js
   toggles, and the server still checks every request. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const main = $('board-main');
  if (!main) return;

  // Vietnamese source text; i18n.js translates it once it is on the page.
  const ROUTES = {
    queue: ['Hàng đợi phê duyệt', 'Hồ sơ đang chờ cán bộ quyết định'],
    complaints: ['Khiếu nại', 'Trả lời có lý do trong 5 ngày làm việc'],
    cases: ['Hồ sơ', 'Tra cứu mọi hồ sơ theo người bán'],
    portfolio: ['Danh mục', 'Dư nợ theo ngân hàng, hạng rủi ro và sự kiện'],
    loans: ['Giám sát khoản vay', 'Agent 4 theo dõi dòng tiền và cảnh báo sớm'],
    banks: ['Ngân hàng', 'Chính sách cho vay và khóa của từng ngân hàng'],
    law: ['Tra cứu luật', 'Điều luật Việt Nam, Trung Quốc kèm hiệu lực'],
    chain: ['Chuỗi & sổ cái', 'Khối, đồng thuận và lệnh rút tiền niêm phong'],
    payouts: ['Lệnh chi thủ công', 'Tạo và theo dõi lệnh chi chia theo ngân hàng'],
    postaudit: ['Hậu kiểm', 'Agent 5 rà soát, đề xuất và phiên bản tham số'],
    users: ['Người dùng', 'Tạo, kích hoạt hoặc vô hiệu hóa tài khoản'],
    audit: ['Nhật ký quản trị', 'Mọi thao tác của cán bộ và quản trị viên']
  };
  const ADMIN_ONLY = new Set(['users', 'audit']);
  // The old one-page anchors keep working as deep links.
  const LEGACY = {
    'queue-section': 'queue', 'complaints-section': 'complaints', 'credit-section': 'cases', portfolio: 'portfolio',
    'credit-loans-section': 'loans', 'banks-section': 'banks', 'law-section': 'law', 'chain-section': 'chain',
    'manual-section': 'payouts', 'postaudit-section': 'postaudit', 'users-section': 'users', 'audit-section': 'audit'
  };
  const views = Array.from(main.querySelectorAll('[data-view]'));
  const subhead = $('hub-subhead');
  let current = null, cameFromHome = false;

  // admin-v4.js shows or hides [data-admin] from the session and again after /auth/me.
  const isAdmin = () => { const el = $('users-section'); return !!el && !el.hidden; };

  function parse(hash) {
    const h = String(hash || '').replace(/^#/, '');
    if (!h || h === '/') return 'home';
    if (h.charAt(0) === '/') { const r = h.slice(1).split(/[/?]/)[0]; return ROUTES[r] ? r : 'home'; }
    if (LEGACY[h]) return LEGACY[h];
    return null; // in-page anchors (e.g. #flow-B3 inside the case drawer) are not routes
  }
  function allowed(route) { return route === 'home' || (ROUTES[route] && (!ADMIN_ONLY.has(route) || isAdmin())); }
  function setHash(route) {
    const target = route === 'home' ? '#/' : '#/' + route;
    if (location.hash !== target) history.replaceState(history.state, '', location.pathname + location.search + target);
  }

  function render(route, opts) {
    opts = opts || {};
    if (!allowed(route)) { route = 'home'; setHash('home'); }
    const changed = route !== current;
    current = route;
    main.dataset.view = route;
    document.body.classList.toggle('hub-is-home', route === 'home');
    views.forEach(el => el.classList.toggle('hub-view-on', el.dataset.view === route));
    subhead.hidden = route === 'home';
    if (route !== 'home') {
      const [title, desc] = ROUTES[route];
      $('hub-page-title').textContent = title;
      $('hub-crumb').textContent = title;
      $('hub-page-desc').textContent = desc;
      const svg = main.querySelector('[data-hub-tile="' + route + '"] svg');
      $('hub-page-icon').innerHTML = svg ? svg.outerHTML : '';
    }
    mirrorCount();
    // Moving between functions closes the case drawer, so it never sits over the wrong view.
    if (changed && opts.user) {
      const drawer = $('drawer');
      if (drawer && !drawer.hidden) $('drawer-close').click();
    }
    if (changed && !opts.initial) {
      window.scrollTo(0, 0);
      const heading = route === 'home' ? $('hub-title') : $('hub-page-title');
      if (heading && opts.user) heading.focus({ preventScroll: true });
    }
  }

  function onHash(initial) {
    const route = parse(location.hash);
    if (route === null) { if (initial) { setHash('home'); render('home', { initial: true }); } return; }
    setHash(route); // legacy anchors and unknown routes become #/route
    const prev = current;
    render(route, { initial, user: !initial });
    if (!initial) cameFromHome = prev === 'home' && route !== 'home';
  }

  $('hub-back').addEventListener('click', () => {
    // Step back in history when the person came here from the hub; otherwise go to the hub.
    if (cameFromHome) history.back(); else location.hash = '#/';
  });
  window.addEventListener('hashchange', () => onHash(false));

  // Role-specific greeting: "officer text|admin text".
  function roleTexts() {
    const admin = isAdmin();
    main.querySelectorAll('[data-hub-role-text]').forEach(el => {
      const parts = el.dataset.hubRoleText.split('|'), text = admin ? parts[1] : parts[0];
      if (el.dataset.hubRoleShown !== text) { el.textContent = text; el.dataset.hubRoleShown = text; }
    });
    document.body.classList.toggle('hub-role-admin', admin);
  }

  // Live counts on the tiles, read from what admin-v4.js has already rendered (no extra requests).
  const COUNTS = [
    ['queue', 'queue-count', 'text', '{x} hồ sơ chờ', true],
    ['complaints', 'complaints-count', 'text', '{x} chưa trả lời', true],
    ['cases', 'credit-count', 'text', '{x} hồ sơ'],
    ['loans', 'credit-loans', 'rows', '{x} khoản vay'],
    ['banks', 'banks', 'rows', '{x} ngân hàng'],
    ['payouts', 'manual-list', 'rows', '{x} lệnh chi'],
    ['users', 'users', 'rows', '{x} tài khoản'],
    ['audit', 'audit', 'rows', '{x} sự kiện gần nhất']
  ];
  function readCount(source, kind) {
    if (kind === 'text') { const t = source.textContent.trim(); return /^\d+$/.test(t) ? Number(t) : null; }
    if (source.querySelector('table')) return source.querySelectorAll('tbody tr').length;
    return source.querySelector('.empty') ? 0 : null;
  }
  function updateCount(route, source, kind, template, attention) {
    const badge = main.querySelector('[data-hub-count="' + route + '"]');
    if (!badge) return;
    const n = readCount(source, kind);
    badge.hidden = n === null;
    if (n === null) return;
    const text = template.replace('{x}', new Intl.NumberFormat('vi-VN').format(n));
    if (badge.dataset.hubShown !== text) { badge.textContent = text; badge.dataset.hubShown = text; }
    badge.classList.toggle('is-attention', !!attention && n > 0);
    if (route === current) mirrorCount();
  }
  // The open function's count also sits in its page header.
  function mirrorCount() {
    const out = $('hub-page-count'), badge = current && current !== 'home' && main.querySelector('[data-hub-count="' + current + '"]');
    const text = badge && !badge.hidden ? badge.dataset.hubShown : '';
    out.hidden = !text;
    if (text && out.dataset.hubShown !== text) { out.textContent = text; out.dataset.hubShown = text; }
    out.classList.toggle('is-attention', !!badge && badge.classList.contains('is-attention'));
  }
  COUNTS.forEach(([route, id, kind, template, attention]) => {
    const source = $(id);
    if (!source) return;
    const update = () => updateCount(route, source, kind, template, attention);
    new MutationObserver(update).observe(source, { childList: true, characterData: kind === 'text', subtree: kind === 'text' });
    update();
  });

  const adminProbe = $('users-section');
  if (adminProbe) new MutationObserver(() => { roleTexts(); if (current && !allowed(current)) { setHash('home'); render('home'); } }).observe(adminProbe, { attributes: true, attributeFilter: ['hidden'] });
  roleTexts();
  document.documentElement.classList.add('hub-ready');
  onHash(true);
})();
