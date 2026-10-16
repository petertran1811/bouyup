/* Authenticated shell. Mount on new pages without disturbing legacy consoles. */
(function (global) {
  'use strict';
  var BU = global.BU = global.BU || {};
  var labels = { seller: 'Người bán', officer: 'Cán bộ tín dụng', bank: 'Ngân hàng đối tác', admin: 'Quản trị viên' };
  var nav = {
    seller: [['Gian hàng của tôi', 'workspace.html', '◈']],
    officer: [['Hàng đợi & danh mục', 'admin.html', '▦']],
    admin: [['Quản trị liên minh', 'admin.html', '▦']],
    bank: [['Cổng ngân hàng', 'bank.html', '◈']]
  };
  function escape(text) {
    var node = document.createElement('span'); node.textContent = text || ''; return node.innerHTML;
  }
  BU.shell = {
    mount: function (target, options) {
      var session = BU.session.get();
      if (!session) return null;
      var host = typeof target === 'string' ? document.querySelector(target) : target;
      if (!host) return null;
      var user = session.user;
      host.className = 'bu-shell';
      var links = nav[user.role].map(function (item) {
        return '<a class="bu-nav-link' + (location.pathname.endsWith('/' + item[1]) ? ' is-active' : '') + '" href="' + item[1] + '"' + (location.pathname.endsWith('/' + item[1]) ? ' aria-current="page"' : '') + '><span aria-hidden="true">' + item[2] + '</span>' + item[0] + '</a>';
      }).join('');
      host.innerHTML = '<a class="bu-skip-link" href="#app-content">Đến nội dung chính</a>' +
        '<aside class="bu-sidebar" id="app-sidebar" aria-label="Điều hướng ứng dụng"><a class="bu-brand" href="index.html"><img src="../src/chung/assets/logo.webp" width="40" height="40" alt="">BuoyUp<span class="bu-brand-dot" aria-hidden="true"></span></a>' +
        '<p class="bu-eyebrow">' + escape(labels[user.role]) + '</p><nav class="bu-shell-nav">' + links + '<a class="bu-nav-link" href="index.html">↗ Trang chủ</a></nav><div class="bu-sidebar-foot"><span class="bu-status-dot" aria-hidden="true"></span> Mỗi quyết định có căn cứ.</div></aside>' +
        '<div class="bu-shell-body"><header class="bu-topbar"><button class="bu-btn bu-btn--ghost bu-shell-menu" type="button" aria-label="Mở điều hướng" aria-controls="app-sidebar" aria-expanded="false">☰</button><span class="bu-topbar-title">' + escape(options && options.title || 'Không gian làm việc') + '</span><div class="bu-topbar-actions"><div class="bu-notifications" data-notifications-slot aria-label="Thông báo"></div><button class="bu-btn bu-btn--ghost" data-theme-toggle type="button" aria-label="Đổi giao diện sáng tối">◐</button><details class="bu-user-menu"><summary><span class="bu-avatar" aria-hidden="true">' + escape((user.display_name || user.email).slice(0, 1).toUpperCase()) + '</span><span class="bu-user-name">' + escape(user.display_name) + '</span><span aria-hidden="true">⌄</span></summary><div class="bu-user-dropdown"><strong>' + escape(user.display_name) + '</strong><span>' + escape(user.email) + '</span><span class="bu-badge">' + escape(labels[user.role]) + '</span><button class="bu-btn bu-btn--ghost bu-logout" type="button">Đăng xuất</button><p class="bu-logout-error" role="alert" hidden></p></div></details></div></header><main class="bu-shell-main" id="app-content" tabindex="-1"></main></div><button class="bu-sidebar-backdrop" aria-label="Đóng điều hướng" hidden></button>';
      var sidebar = host.querySelector('.bu-sidebar');
      var menu = host.querySelector('.bu-shell-menu');
      var backdrop = host.querySelector('.bu-sidebar-backdrop');
      function closeMenu() {
        sidebar.classList.remove('is-open'); menu.setAttribute('aria-expanded', 'false'); backdrop.hidden = true;
      }
      menu.addEventListener('click', function () {
        var open = !sidebar.classList.contains('is-open');
        sidebar.classList.toggle('is-open', open); menu.setAttribute('aria-expanded', String(open)); backdrop.hidden = !open;
        if (open) sidebar.querySelector('a').focus();
      });
      backdrop.addEventListener('click', function () { closeMenu(); menu.focus(); });
      sidebar.addEventListener('click', function (event) { if (event.target.closest('a')) closeMenu(); });
      host.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') { closeMenu(); host.querySelector('.bu-user-menu').open = false; menu.focus(); }
        if (event.key === 'Tab' && sidebar.classList.contains('is-open')) {
          var links = Array.from(sidebar.querySelectorAll('a'));
          var first = links[0], last = links[links.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      });
      document.addEventListener('click', function (event) { if (!event.target.closest('.bu-user-menu')) host.querySelector('.bu-user-menu').open = false; });
      host.querySelector('.bu-logout').addEventListener('click', async function (event) {
        var button = event.currentTarget; button.disabled = true; button.textContent = 'Đang đăng xuất…';
        try {
          await BU.api.auth.logout();
          BU.session.clear(); location.replace('login.html');
        } catch (error) {
          if (error.status === 401) return;
          var notice = host.querySelector('.bu-logout-error');
          notice.hidden = false; notice.textContent = 'Chưa thể thu hồi phiên. Vui lòng thử lại.';
          button.disabled = false; button.textContent = 'Đăng xuất';
        }
      });
      if (BU.motion) BU.motion.init(host);
      return host.querySelector('#app-content');
    }
  };
})(window);
