/* BuoyUp public homepage: API-backed figures, progressive motion, accessible menu. */
(function () {
  'use strict';
  const BU = window.BU;
  const motion = BU && BU.motion;
  if (motion) motion.init(document, { marketing: true });

  const session = BU && BU.session && BU.session.get();
  if (session) {
    document.body.classList.add('is-authenticated');
    document.querySelectorAll('[data-login-link]').forEach(function (link) {
      link.textContent = 'Vào ứng dụng';
      link.href = BU.session.home(session.user.role);
    });
    document.querySelectorAll('[data-register-link]').forEach(function (link) { link.hidden = true; });
  }
  document.querySelector('.marketing-theme').addEventListener('click', function () {
    if (motion) motion.setTheme(motion.theme() === 'dark' ? 'light' : 'dark');
  });

  const burger = document.querySelector('.burger');
  const menu = document.getElementById('mobile-menu');
  const overlay = document.querySelector('[data-menu-overlay]');
  function setMenu(open, returnFocus) {
    burger.setAttribute('aria-expanded', String(open));
    burger.setAttribute('aria-label', open ? 'Đóng trình đơn' : 'Mở trình đơn');
    menu.hidden = overlay.hidden = !open;
    document.body.classList.toggle('menu-open', open);
    if (open) menu.querySelector('a').focus();
    else if (returnFocus) burger.focus();
  }
  burger.addEventListener('click', function () { setMenu(menu.hidden, true); });
  overlay.addEventListener('click', function () { setMenu(false, true); });
  menu.addEventListener('click', function (event) { if (event.target.closest('a')) setMenu(false, false); });
  document.addEventListener('keydown', function (event) {
    if (menu.hidden) return;
    if (event.key === 'Escape') setMenu(false, true);
    if (event.key === 'Tab') {
      const items = [burger].concat(Array.from(menu.querySelectorAll('a:not([hidden])')));
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  window.addEventListener('resize', function () { if (innerWidth > 720 && !menu.hidden) setMenu(false, false); });

  const video = document.querySelector('.bg-video');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function syncVideo() {
    document.body.classList.toggle('is-hidden', document.hidden);
    if (document.hidden || reduced.matches) video.pause();
    else { const playing = video.play(); if (playing) playing.catch(function () {}); }
  }
  reduced.addEventListener('change', syncVideo);
  document.addEventListener('visibilitychange', syncVideo);
  syncVideo();

  const bankList = document.getElementById('public-banks');
  const statsList = document.getElementById('public-stats');
  const status = document.getElementById('overview-status');
  const retry = document.getElementById('overview-retry');
  const badge = document.getElementById('simulation-badge');
  const bankBadge = document.getElementById('bank-simulation-badge');
  const fields = [
    ['sellers', 'Người bán'], ['applications', 'Hồ sơ'],
    ['loans_active', 'Khoản vay đang hoạt động'], ['disbursed_total', 'Tổng giải ngân · CNY'],
    ['banks', 'Ngân hàng'], ['chain_blocks', 'Khối nhật ký'], ['agents', 'AI agent']
  ];
  let loading = false;
  async function loadOverview() {
    if (loading) return;
    loading = true;
    retry.hidden = true;
    status.textContent = 'Đang kết nối hệ thống…';
    statsList.setAttribute('aria-busy', 'true');
    bankList.setAttribute('aria-busy', 'true');
    try {
      const overview = await BU.api.public.overview();
      if (!overview || !overview.stats || !Array.isArray(overview.banks)) throw new Error('Invalid overview');
      bankList.replaceChildren();
      overview.banks.forEach(function (bank) {
        const node = document.createElement('span');
        node.className = 'bank-node'; node.textContent = bank.name || bank.code;
        bankList.appendChild(node);
      });
      if (!overview.banks.length) bankList.textContent = 'Chưa có ngân hàng trong danh sách.';
      statsList.replaceChildren();
      fields.forEach(function (field) {
        const value = overview.stats[field[0]];
        if (typeof value !== 'number' || !Number.isFinite(value)) return;
        const card = document.createElement('div'); card.className = 'live-stat';
        const number = document.createElement('strong');
        const label = document.createElement('span'); label.textContent = field[1];
        card.append(number, label); statsList.appendChild(card);
        number.textContent = new Intl.NumberFormat('vi-VN').format(value);
        if (motion && !motion.reduced() && 'IntersectionObserver' in window) {
          const observer = new IntersectionObserver(function (entries) {
            if (entries.some(function (entry) { return entry.isIntersecting; })) {
              motion.countUp(number, value); observer.disconnect();
            }
          }, { threshold: 0.4 });
          observer.observe(number);
        }
      });
      if (!statsList.children.length) statsList.textContent = 'Hệ thống chưa có số liệu tổng quan.';
      badge.hidden = overview.simulated !== true;
      bankBadge.hidden = overview.simulated !== true;
      status.textContent = overview.simulated ? 'Dữ liệu mô phỏng từ hệ thống · Không phải giao dịch tiền thật.' : 'Đã cập nhật từ hệ thống.';
    } catch (error) {
      badge.hidden = bankBadge.hidden = true;
      status.textContent = 'Chưa tải được tổng quan. Bạn vẫn có thể khám phá hoặc tạo tài khoản.';
      bankList.replaceChildren();
      const bankPlaceholder = document.createElement('span');
      bankPlaceholder.className = 'data-skeleton'; bankPlaceholder.textContent = 'Danh sách ngân hàng đang chờ kết nối';
      bankList.appendChild(bankPlaceholder);
      statsList.replaceChildren();
      const statsPlaceholder = document.createElement('div');
      statsPlaceholder.className = 'data-skeleton'; statsPlaceholder.textContent = 'Số liệu sẽ xuất hiện khi kết nối lại';
      statsList.appendChild(statsPlaceholder);
      retry.hidden = false;
    } finally {
      loading = false;
      statsList.setAttribute('aria-busy', 'false'); bankList.setAttribute('aria-busy', 'false');
      if (window.ScrollTrigger) window.ScrollTrigger.refresh();
    }
  }
  retry.addEventListener('click', loadOverview);
  loadOverview();
})();
