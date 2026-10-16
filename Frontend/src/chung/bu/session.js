/* Persistent v4 session and the legacy console bridge. Backend enforces permissions. */
(function (global) {
  'use strict';
  var BU = global.BU = global.BU || {};
  var homes = { seller: 'workspace.html', officer: 'admin.html', admin: 'admin.html', bank: 'bank.html' };
  var expiryTimer = null;
  var storageTimer = null;
  var guardedRoles = null;

  function home(role) { return homes[role] || 'login.html'; }
  function clear() {
    clearTimeout(expiryTimer);
    try {
      ['bu_token', 'bu_user', 'bu_expires_at'].forEach(function (key) { localStorage.removeItem(key); });
      sessionStorage.removeItem('sg_session');
    } catch (_) { /* optional storage */ }
  }
  function bridge(user) {
    if (user.role === 'bank') { sessionStorage.removeItem('sg_session'); return; }
    var previous;
    try { previous = JSON.parse(sessionStorage.getItem('sg_session')); } catch (_) { /* optional */ }
    var legacy = {
      username: user.email,
      role: user.role === 'seller' ? 'seller' : 'admin',
      label: user.display_name,
      sellerId: previous && previous.username === user.email && previous.sellerId || 'seller_demo_001',
      at: new Date().toISOString()
    };
    sessionStorage.setItem('sg_session', JSON.stringify(legacy));
    return legacy;
  }
  function get() {
    try {
      var token = localStorage.getItem('bu_token');
      var user = JSON.parse(localStorage.getItem('bu_user'));
      var expiry = localStorage.getItem('bu_expires_at');
      if (!token || !user || !homes[user.role] || !expiry || !Number.isFinite(Date.parse(expiry)) || Date.parse(expiry) <= Date.now()) {
        clear(); return null;
      }
      bridge(user);
      return { token: token, user: user, expires_at: expiry };
    } catch (_) { clear(); return null; }
  }
  function set(data) {
    if (!data || !data.token || !data.user || !homes[data.user.role] || !data.expires_at || Date.parse(data.expires_at) <= Date.now() || !Number.isFinite(Date.parse(data.expires_at))) {
      throw new Error('Phiên đăng nhập không hợp lệ. Vui lòng thử lại.');
    }
    try {
      localStorage.setItem('bu_token', data.token);
      localStorage.setItem('bu_user', JSON.stringify(data.user));
      localStorage.setItem('bu_expires_at', data.expires_at);
      bridge(data.user);
    } catch (_) {
      clear(); throw new Error('Trình duyệt đang chặn lưu phiên. Hãy cho phép lưu trữ để đăng nhập.');
    }
    return data;
  }
  function login() {
    location.replace('login.html?next=' + encodeURIComponent(location.pathname + location.search + location.hash));
  }
  // Only known app destinations may be restored; reject external URLs and other roles.
  function next(value, role) {
    if (!value) return home(role);
    try {
      var url = new URL(value, location.href);
      var allowed = ['/app/giaodien/' + home(role), '/app/giaodien/index.html'];
      if (url.origin === location.origin && allowed.indexOf(url.pathname) !== -1) return url.pathname + url.search + url.hash;
    } catch (_) { /* invalid next */ }
    return home(role);
  }
  BU.session = { get: get, set: set, clear: clear, bridge: bridge, home: home, next: next };
  BU.requireRole = function (roles) {
    guardedRoles = roles;
    var session = get();
    if (!session) { login(); return null; }
    if (roles.indexOf(session.user.role) === -1) { location.replace(home(session.user.role)); return null; }
    clearTimeout(expiryTimer);
    expiryTimer = setTimeout(function () { BU.requireRole(roles); }, Math.min(Date.parse(session.expires_at) - Date.now() + 50, 2147483647));
    return session;
  };
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && guardedRoles) BU.requireRole(guardedRoles);
  });
  // Another tab can revoke or replace the session without leaving this page stale.
  global.addEventListener('storage', function (event) {
    if (!/^bu_(token|user|expires_at)$/.test(event.key || '')) return;
    if (!/\/(workspace|admin|bank)\.html$/.test(location.pathname)) return;
    // set()/clear() update several keys; observe the completed transaction in another tab.
    clearTimeout(storageTimer);
    storageTimer = setTimeout(function () {
      var session = get();
      if (!session) login();
      else if (location.pathname !== '/app/giaodien/' + home(session.user.role)) location.replace(home(session.user.role));
      else if (guardedRoles) BU.requireRole(guardedRoles);
    }, 50);
  });
})(window);
