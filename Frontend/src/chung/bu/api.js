/* BuoyUp v4 transport. Same origin; financial values belong to the API. */
(function (global) {
  'use strict';
  var BU = global.BU = global.BU || {};

  function clearSession() {
    if (BU.session) { BU.session.clear(); return; }
    try {
      ['bu_token', 'bu_user', 'bu_expires_at'].forEach(function (key) { localStorage.removeItem(key); });
      sessionStorage.removeItem('sg_session');
    } catch (_) { /* Storage may be disabled. */ }
  }

  async function request(path, options) {
    var opts = options || {};
    var endpoint = new URL(path, location.href);
    if (endpoint.origin !== location.origin || !endpoint.pathname.startsWith('/v4/')) {
      var unsafe = new Error('Địa chỉ API không hợp lệ.');
      unsafe.code = 'INVALID_ENDPOINT'; unsafe.status = 0; unsafe.details = {};
      throw unsafe;
    }
    var headers = { Accept: 'application/json' };
    var token;
    try { token = localStorage.getItem('bu_token'); } catch (_) { /* optional storage */ }
    if (token && opts.auth !== false) headers.Authorization = 'Bearer ' + token;
    var init = { method: opts.method || 'GET', headers: headers, credentials: 'same-origin' };
    if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.body);
    }
    var controller = new AbortController();
    init.signal = controller.signal;
    var timer = setTimeout(function () { controller.abort(); }, opts.timeout || 15000);
    try {
      var response = await fetch(path, init);
      var raw = await response.text();
      var data = null;
      try { data = raw ? JSON.parse(raw) : null; } catch (_) { /* Error pages may be HTML. */ }
      if (!response.ok) {
        var envelope = data && data.error || {};
        var error = new Error(envelope.message || 'Không thể thực hiện yêu cầu. Vui lòng thử lại.');
        error.code = envelope.code || 'HTTP_ERROR';
        error.status = response.status;
        error.details = envelope.details || {};
        // Invalid credentials are a form error, not an expired authenticated session.
        if (response.status === 401 && opts.auth !== false) {
          clearSession();
          var next = location.pathname + location.search + location.hash;
          location.replace('login.html?next=' + encodeURIComponent(next));
        }
        throw error;
      }
      if (raw && data === null) {
        var invalid = new Error('Phản hồi không hợp lệ. Vui lòng thử lại.');
        invalid.code = 'INVALID_RESPONSE'; invalid.status = response.status; invalid.details = {};
        throw invalid;
      }
      return data;
    } catch (error) {
      if (error.code) throw error;
      var network = new Error(error.name === 'AbortError' ? 'Kết nối quá lâu. Vui lòng thử lại.' : 'Không kết nối được máy chủ. Vui lòng thử lại.');
      network.code = 'NETWORK'; network.status = 0; network.details = {}; network.cause = error;
      throw network;
    } finally { clearTimeout(timer); }
  }

  BU.api = {
    request: request,
    auth: {
      login: function (body) { return request('/v4/auth/login', { method: 'POST', body: body, auth: false }); },
      register: function (body) { return request('/v4/auth/register', { method: 'POST', body: body, auth: false }); },
      me: function () { return request('/v4/auth/me'); },
      logout: function () { return request('/v4/auth/logout', { method: 'POST' }); }
    },
    public: {
      overview: function () { return request('/v4/public/overview', { auth: false }); },
      demoStores: function () { return request('/v4/public/demo-stores', { auth: false }); }
    }
  };

  // Keep every console on the authenticated, same-origin v4 transport.
  var id = encodeURIComponent;
  var get = function (path) { return request(path); };
  var write = function (path, body, method) { return request(path, { method: method || 'POST', body: body === undefined ? {} : body }); };
  BU.api.applications = {
    list: function (status) { return get('/v4/applications' + (status ? '?status=' + id(status) : '')); },
    create: function (body) { return write('/v4/applications', body); },
    get: function (key) { return get('/v4/applications/' + id(key)); },
    offer: function (key) { return get('/v4/applications/' + id(key) + '/offer'); },
    trace: function (key) { return get('/v4/applications/' + id(key) + '/trace'); },
    messages: function (key) { return get('/v4/applications/' + id(key) + '/messages'); },
    contract: function (key) { return get('/v4/applications/' + id(key) + '/contract'); },
    action: function (key, action, body) { return write('/v4/applications/' + id(key) + '/' + action, body, action === 'plan' ? 'PUT' : 'POST'); }
  };
  ['identity', 'consent', 'plan', 'verify', 'answers', 'quote', 'what-if', 'select', 'sign', 'manual-channel', 'request-human', 'consent/draft', 'consent/revoke'].forEach(function (action) {
    BU.api.applications[action.replace(/[-/](\w)/g, function (_, c) { return c.toUpperCase(); })] = function (key, body) { return BU.api.applications.action(key, action, body); };
  });
  BU.api.loans = {
    list: function () { return get('/v4/loans'); }, get: function (key) { return get('/v4/loans/' + id(key)); },
    simulateInflow: function (key, amount) { return write('/v4/loans/' + id(key) + '/simulate-inflow', { amount: amount }); },
    simulateTransfer: function (key, body) { return write('/v4/loans/' + id(key) + '/simulate-transfer', body); },
    simulateAdvance: function (key, to) { return write('/v4/loans/' + id(key) + '/simulate-advance', { to: to }); },
    minimum: function (key) { return write('/v4/loans/' + id(key) + '/minimum'); },
    prepay: function (key) { return write('/v4/loans/' + id(key) + '/prepay'); },
    receivingAccount: function (key, body) { return write('/v4/loans/' + id(key) + '/receiving-account', body, 'PUT'); }
  };
  BU.api.officer = { queue: function () { return get('/v4/officer/queue'); }, decision: function (key, body) { return write('/v4/officer/applications/' + id(key) + '/decision', body); } };
  BU.api.portfolio = function () { return get('/v4/portfolio'); };
  BU.api.monitoring = { tick: function (body) { return write('/v4/monitoring/tick', body); }, alerts: function () { return get('/v4/alerts'); }, ack: function (key) { return write('/v4/alerts/' + id(key) + '/ack'); } };
  BU.api.banks = {
    list: function (region) { return get('/v4/banks' + (region ? '?region=' + id(region) : '')); }, get: function (code) { return get('/v4/banks/' + id(code)); },
    policy: function (code, body) { return write('/v4/banks/' + id(code) + '/policy', body, 'PUT'); },
    rotateKey: function (code, body) { return write('/v4/banks/' + id(code) + '/public-key', body, 'PUT'); }
  };
  BU.api.bank = {
    portfolio: function () { return get('/v4/bank/portfolio'); }, withdrawals: function () { return get('/v4/bank/withdrawals'); },
    syndicate: function () { return get('/v4/bank/syndicate'); }
  };
  BU.api.chain = {
    status: function () { return get('/v4/chain/status'); }, blocks: function () { return get('/v4/chain/blocks?limit=20'); },
    withdrawals: function () { return get('/v4/chain/withdrawals'); }, withdrawal: function (key) { return get('/v4/chain/withdrawals/' + id(key)); },
    decrypt: function (key, body) { return write('/v4/chain/withdrawals/' + id(key) + '/decrypt', body); }, keys: function () { return get('/v4/chain/keys'); },
    verify: function () { return get('/v4/chain/verify'); }, verifyCase: function (key) { return get('/v4/chain/cases/' + id(key) + '/verify'); }
  };
  BU.api.postaudit = {
    run: function () { return write('/v4/postaudit/run'); }, reports: function () { return get('/v4/postaudit/reports'); }, proposals: function () { return get('/v4/postaudit/proposals'); },
    decision: function (key, body) { return write('/v4/postaudit/proposals/' + id(key) + '/decision', body); }, params: function () { return get('/v4/params'); }
  };
  BU.api.admin = {
    users: function () { return get('/v4/admin/users'); }, createUser: function (body) { return write('/v4/admin/users', body); }, updateUser: function (key, body) { return write('/v4/admin/users/' + id(key), body, 'PATCH'); },
    audit: function () { return get('/v4/admin/audit'); }, autoApproval: function (group, body) { return write('/v4/admin/auto-approval/' + id(group), body, 'PUT'); }
  };
  BU.api.withdrawals = { list: function () { return get('/v4/withdrawals'); }, manual: function (body) { return write('/v4/withdrawals/manual', body); }, verify: function (key) { return get('/v4/withdrawals/' + id(key) + '/verify'); } };
  BU.api.regions = function () { return get('/v4/regions'); };
})(window);
