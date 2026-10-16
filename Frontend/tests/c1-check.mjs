/* Run with node frontend/tests/c1-check.mjs. No packages, server, or build required.
 * Optional C1_API_EVIDENCE=/tmp/c1-api-evidence.json replays isolated backend responses.
 * These checks exercise the application scripts; they do not replace browser layout QA. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const evidence = process.env.C1_API_EVIDENCE ? JSON.parse(fs.readFileSync(process.env.C1_API_EVIDENCE, 'utf8')) : null;
const results = [];
const check = async (name, fn) => { await fn(); results.push(name); console.log('PASS ' + name); };
const store = () => {
  const values = new Map();
  return { getItem: k => values.get(k) ?? null, setItem: (k, v) => values.set(k, String(v)), removeItem: k => values.delete(k) };
};
class Element {
  constructor(text = '') {
    this.textContent = text; this.value = ''; this.hidden = false; this.disabled = false;
    this.dataset = {}; this.children = []; this.attrs = {}; this.events = {}; this.checked = false;
    this.validity = { valid: true }; this.style = { removeProperty() {}, setProperty() {} };
    const classes = new Set();
    this.classList = { add: v => classes.add(v), remove: v => classes.delete(v), contains: v => classes.has(v), toggle: (v, on) => on ? classes.add(v) : classes.delete(v) };
  }
  get innerHTML() { return this.textContent.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'); }
  set innerHTML(value) { this.markup = value; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  toggleAttribute(k, on) { if (on) this.setAttribute(k, ''); else this.removeAttribute(k); }
  hasAttribute(k) { return k in this.attrs; }
  addEventListener(k, fn) { (this.events[k] ||= []).push(fn); }
  async trigger(k, event = {}) { for (const fn of this.events[k] || []) await fn({ currentTarget: this, target: this, preventDefault() {}, ...event }); }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.append(item); }
  replaceChildren(...items) { this.children = [...items]; this.textContent = ''; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  matches() { return false; }
  closest() { return null; }
  focus() { this.focused = true; }
  remove() { this.removed = true; }
  pause() { this.paused = true; }
  play() { this.paused = false; return Promise.resolve(); }
}
function env(page = 'login.html') {
  const elements = new Map();
  const doc = new Element(); doc.documentElement = new Element(); doc.body = new Element();
  doc.createElement = () => new Element(); doc.getElementById = id => elements.get(id) || null;
  doc.querySelector = selector => elements.get(selector) || null;
  doc.querySelectorAll = () => [];
  doc.dispatchEvent = () => {};
  const navigations = [], timers = new Map(), events = {}, frames = new Map(); let id = 0;
  const media = { matches: true, addEventListener() {} };
  const ctx = vm.createContext({ console, URL, URLSearchParams, Intl, Date, Error, AbortController,
    localStorage: store(), sessionStorage: store(), document: doc,
    location: { href: 'http://localhost:8000/app/' + page, origin: 'http://localhost:8000', pathname: '/app/' + page, search: '', hash: '', replace: v => navigations.push(v), assign: v => navigations.push(v) },
    setTimeout: fn => { timers.set(++id, fn); return id; }, clearTimeout: id => timers.delete(id),
    requestAnimationFrame: fn => { frames.set(++id, fn); return id; }, cancelAnimationFrame: id => frames.delete(id),
    matchMedia: query => query.includes('reduced-motion') ? media : { matches: false, addEventListener() {} },
    addEventListener: (name, fn) => { (events[name] ||= []).push(fn); },
    MutationObserver: class { observe() {} }, CustomEvent: class { constructor(name, options) { this.type = name; this.detail = options?.detail; } },
    fetch: async () => { throw new TypeError('offline'); }, innerWidth: 360,
  });
  ctx.window = ctx;
  return { ctx, doc, elements, navigations, timers, media, frames, events };
}
const SRC = {"main.js": "trang-chu/main.js", "workspace-v4.js": "nguoi-ban/workspace-v4.js", "admin-v4.js": "quan-tri/admin-v4.js", "officer-labels.js": "quan-tri/officer-labels.js", "bu/bank.js": "ngan-hang/bank.js", "bu/api.js": "chung/bu/api.js", "bu/session.js": "chung/bu/session.js", "bu/motion.js": "chung/bu/motion.js", "bu/shell.js": "chung/bu/shell.js", "bu/auth-pages.js": "chung/bu/auth-pages.js"};
const load = (e, filename) => vm.runInContext(fs.readFileSync(path.join(root, 'src', SRC[filename]), 'utf8'), e.ctx, { filename });
const sessionFor = role => ({ token: 'test-token', expires_at: new Date(Date.now() + 3600000).toISOString(), user: { id: 'test', email: role + '@example.com', display_name: 'Người dùng kiểm thử', role, bank_code: role === 'bank' ? 'WEBANK' : null } });
const response = (status, body) => ({ ok: status >= 200 && status < 300, status, text: async () => body == null ? '' : JSON.stringify(body) });
const plain = value => JSON.parse(JSON.stringify(value));
const settle = async () => { for (let n = 0; n < 50; n++) await Promise.resolve(); };

await check('role homes, bank isolation, wrong-role guard', () => {
  const e = env('workspace.html'); load(e, 'bu/session.js');
  for (const [role, home] of Object.entries({ seller: 'workspace.html', officer: 'admin.html', admin: 'admin.html', bank: 'bank.html' })) {
    e.ctx.BU.session.set(sessionFor(role));
    assert.equal(e.ctx.BU.session.home(role), home);
    assert.equal(e.ctx.BU.requireRole([role]).user.role, role);
    assert.equal(e.ctx.BU.requireRole([role === 'bank' ? 'seller' : 'bank']), null);
    assert.equal(e.navigations.at(-1), home);
  }
});
await check('missing/expired sessions and safe next destinations', () => {
  const e = env('bank.html'); load(e, 'bu/session.js');
  assert.equal(e.ctx.BU.requireRole(['bank']), null); assert.match(e.navigations.at(-1), /login\.html\?next=/);
  e.ctx.BU.session.set(sessionFor('bank')); e.ctx.localStorage.setItem('bu_expires_at', new Date(0).toISOString());
  assert.equal(e.ctx.BU.session.get(), null); assert.equal(e.ctx.localStorage.getItem('bu_token'), null);
  for (const next of ['https://other.test/', '//other.test/', 'javascript:alert(1)', '/app/giaodien/admin.html']) assert.equal(e.ctx.BU.session.next(next, 'seller'), 'workspace.html');
  assert.equal(e.ctx.BU.session.next('/app/giaodien/workspace.html?tab=loans#loan', 'seller'), '/app/giaodien/workspace.html?tab=loans#loan');
});
await check('Bearer header, public isolation, contract errors, 401 redirects, network', async () => {
  const e = env('workspace.html'); load(e, 'bu/api.js'); load(e, 'bu/session.js'); e.ctx.BU.session.set(sessionFor('seller'));
  let seen;
  e.ctx.fetch = async (url, init) => { seen = { url, init }; return response(200, { user: sessionFor('seller').user }); };
  await e.ctx.BU.api.auth.me(); assert.equal(seen.url, '/v4/auth/me'); assert.equal(seen.init.headers.Authorization, 'Bearer test-token');
  await e.ctx.BU.api.public.overview(); assert.equal(seen.init.headers.Authorization, undefined);
  await assert.rejects(e.ctx.BU.api.request('https://other.test/v4/auth/me'), err => err.code === 'INVALID_ENDPOINT');
  e.ctx.fetch = async () => response(400, { error: { code: 'VALIDATION_ERROR', message: 'Tên không hợp lệ', details: { field: 'display_name' } } });
  await assert.rejects(e.ctx.BU.api.auth.register({}), err => err.code === 'VALIDATION_ERROR' && err.status === 400 && err.details.field === 'display_name');
  e.ctx.fetch = async () => response(401, { error: { code: 'INVALID_CREDENTIALS', message: 'Sai', details: {} } });
  await assert.rejects(e.ctx.BU.api.auth.login({}), err => err.code === 'INVALID_CREDENTIALS');
  assert.equal(e.navigations.length, 0); assert(e.ctx.BU.session.get());
  await assert.rejects(e.ctx.BU.api.auth.me(), err => err.status === 401);
  assert.equal(e.ctx.BU.session.get(), null); assert.match(e.navigations.at(-1), /login\.html\?next=/);
  e.ctx.fetch = async () => { throw new TypeError('offline'); };
  await assert.rejects(e.ctx.BU.api.auth.login({}), err => err.code === 'NETWORK' && err.status === 0);
});
function authEnv(register = false) {
  const e = env(register ? 'register.html' : 'login.html');
  e.doc.body.dataset.authPage = register ? 'register' : 'login';
  const form = new Element(), submit = new Element(), label = new Element('Đăng nhập');
  submit.querySelector = () => label; form.querySelector = () => submit;
  const fields = { namedItem: name => fields[name] || null };
  for (const name of ['email', 'password', 'display_name', 'phone', 'confirm_password', 'accept_terms']) {
    fields[name] = new Element(); e.elements.set(name, fields[name]); e.elements.set(name + '-error', new Element());
  }
  form.elements = fields;
  form.querySelectorAll = selector => selector === '[aria-invalid]' ? Object.values(fields).filter(v => v instanceof Element && v.hasAttribute('aria-invalid')) : [...e.elements.entries()].filter(([k]) => k.endsWith('-error')).map(([,v]) => v);
  e.elements.set(register ? '#register-form' : '#login-form', form);
  for (const key of ['error', '.auth-theme', '.auth-bg video', 'password-strength', 'password-hint', 'open-terms', 'terms-dialog']) e.elements.set(key, new Element());
  e.elements.get('error').hidden = true;
  load(e, 'bu/api.js'); load(e, 'bu/session.js');
  e.ctx.BU.motion = { init() {}, theme: () => 'light', setTheme() {} };
  load(e, 'bu/auth-pages.js');
  return { ...e, form, submit, label, fields };
}
await check('login as all demo roles chooses the matching page and legacy bridge', async () => {
  const demos = evidence?.demos || ['seller','officer','admin','bank'].map(role => ({ login: { body: sessionFor(role) } }));
  for (const demo of demos) {
    const e = authEnv(); const data = demo.login.body;
    e.fields.email.value = data.user.email; e.fields.password.value = 'BuoyUp@2026';
    e.ctx.fetch = async () => response(200, data);
    await e.form.trigger('submit');
    assert.equal(e.navigations.at(-1), e.ctx.BU.session.home(data.user.role));
    assert.equal(e.ctx.BU.session.get().user.role, data.user.role);
    assert.equal(e.submit.disabled, false);
  }
});
await check('register payload, success, password confirmation, terms and field errors', async () => {
  const e = authEnv(true);
  e.fields.email.value = 'test@example.com'; e.fields.display_name.value = 'Kiểm thử'; e.fields.password.value = 'BuoyUp@2026';
  e.fields.confirm_password.value = 'different'; e.fields.accept_terms.checked = true;
  await e.form.trigger('submit'); assert.equal(e.fields.confirm_password.attrs['aria-invalid'], 'true'); assert.equal(e.navigations.length, 0);
  e.fields.confirm_password.value = 'BuoyUp@2026'; e.fields.accept_terms.checked = false;
  await e.form.trigger('submit'); assert.equal(e.fields.accept_terms.attrs['aria-invalid'], 'true');
  e.fields.accept_terms.checked = true;
  e.ctx.fetch = async () => response(400, { error: { code: 'VALIDATION_ERROR', message: 'Tên chưa phù hợp', details: { field: 'display_name' } } });
  await e.form.trigger('submit'); assert.equal(e.fields.display_name.attrs['aria-invalid'], 'true'); assert.equal(e.elements.get('display_name-error').textContent, 'Tên chưa phù hợp');
  let payload;
  e.ctx.fetch = async (_, init) => { payload = JSON.parse(init.body); return response(201, evidence?.registration.body || sessionFor('seller')); };
  await e.form.trigger('submit'); assert.equal(payload.accept_terms, true); assert.equal(payload.phone, undefined); assert.equal(payload.confirm_password, undefined);
  assert.equal(e.navigations.at(-1), 'workspace.html'); assert.equal(e.submit.disabled, false);
});
await check('credentials, rate-limit and network errors stay inline without navigation', async () => {
  const e = authEnv(); e.fields.email.value = 'test@example.com'; e.fields.password.value = 'wrong';
  for (const [status, code] of [[401,'INVALID_CREDENTIALS'],[429,'RATE_LIMITED']]) {
    e.ctx.fetch = async () => response(status, { error: { code, message: 'Error', details: {} } });
    await e.form.trigger('submit'); assert.equal(e.elements.get('error').hidden, false); assert.equal(e.submit.disabled, false); assert.equal(e.navigations.length, 0);
  }
  e.ctx.fetch = async () => { throw new TypeError('offline'); }; await e.form.trigger('submit');
  assert.match(e.elements.get('error').textContent, /kết nối/); assert.equal(e.submit.disabled, false);
});
await check('reduced motion: Vietnamese numbers, no frames, static reveals and paused videos', () => {
  const e = env('index.html'), video = new Element(), reveal = new Element();
  e.doc.querySelectorAll = selector => selector.includes('video') ? [video] : selector === '[data-reveal]' ? [reveal] : [];
  load(e, 'bu/motion.js'); e.ctx.BU.motion.init(e.doc, { marketing: true });
  const number = new Element(); e.ctx.BU.motion.countUp(number, 123456, { suffix: ' đ' });
  assert.equal(number.textContent, '123.456 đ'); assert.equal(e.frames.size, 0); assert.equal(video.paused, true); assert(reveal.classList.contains('is-in'));
  e.ctx.BU.motion.setTheme('dark'); assert.equal(e.doc.documentElement.dataset.theme, 'dark'); assert.equal(e.ctx.localStorage.getItem('bu_theme'), 'dark');
  e.media.matches = false; e.doc.hidden = true; e.ctx.BU.motion.init(e.doc);
  assert.equal(e.frames.size, 0); assert.equal(video.paused, true);
});
await check('homepage uses API stats/banks, simulation labels, unavailable retry', async () => {
  const e = env('index.html');
  for (const key of ['.marketing-theme','.burger','mobile-menu','[data-menu-overlay]','.bg-video','public-banks','public-stats','overview-status','overview-retry','simulation-badge','bank-simulation-badge']) e.elements.set(key, new Element());
  e.elements.get('mobile-menu').querySelector = () => new Element();
  load(e, 'bu/api.js'); load(e, 'bu/session.js');
  e.ctx.BU.motion = { init() {}, reduced: () => true };
  const overview = evidence?.public.overview.body || { stats: { sellers: 123, banks: 2 }, banks: [{name:'Test bank'}], simulated: true };
  e.ctx.fetch = async () => response(200, overview); load(e, 'main.js'); await settle();
  assert.equal(e.elements.get('public-banks').children.length, overview.banks.length);
  assert.equal(e.elements.get('public-banks').children[0].textContent, overview.banks[0].name);
  assert.equal(e.elements.get('public-stats').children[0].children[0].textContent, new Intl.NumberFormat('vi-VN').format(overview.stats.sellers));
  assert.equal(e.elements.get('simulation-badge').hidden, false); assert.equal(e.elements.get('bank-simulation-badge').hidden, false);
  e.ctx.fetch = async () => response(404, { error: {code:'NOT_FOUND',message:'Unavailable'} });
  await e.elements.get('overview-retry').trigger('click');
  assert.equal(e.elements.get('overview-retry').hidden, false); assert.equal(e.elements.get('public-stats').children.length, 1);
  assert.match(e.elements.get('public-stats').children[0].textContent, /kết nối/); assert.equal(e.elements.get('simulation-badge').hidden, true);
});
await check('shell mounts role navigation, escapes identity, mobile menu and logout', async () => {
  const e = env('bank.html'); load(e, 'bu/api.js'); load(e, 'bu/session.js');
  const data = sessionFor('bank'); data.user.display_name = '<script>unsafe</script>'; e.ctx.BU.session.set(data);
  e.ctx.BU.motion = { init() {} };
  const host = new Element(), main = new Element(), slots = new Map();
  for (const name of ['.bu-sidebar','.bu-shell-menu','.bu-sidebar-backdrop','.bu-user-menu','.bu-logout','.bu-logout-error']) slots.set(name, new Element());
  slots.set('#app-content', main); host.querySelector = name => slots.get(name);
  slots.get('.bu-sidebar').querySelector = () => new Element(); e.elements.set('#shell', host);
  load(e, 'bu/shell.js'); assert.equal(e.ctx.BU.shell.mount('#shell'), main);
  assert.match(host.markup, /Cổng ngân hàng/); assert.match(host.markup, /data-notifications-slot/);
  assert.match(host.markup, /&lt;script&gt;unsafe/); assert(!host.markup.includes('<script>unsafe'));
  await slots.get('.bu-shell-menu').trigger('click'); assert.equal(slots.get('.bu-shell-menu').attrs['aria-expanded'], 'true');
  await host.trigger('keydown', { key: 'Escape' }); assert.equal(slots.get('.bu-sidebar-backdrop').hidden, true);
  await slots.get('.bu-logout').trigger('click'); assert.equal(slots.get('.bu-logout-error').hidden, false); assert(e.ctx.BU.session.get());
  e.ctx.fetch = async () => response(204, null); await slots.get('.bu-logout').trigger('click');
  assert.equal(e.ctx.BU.session.get(), null); assert.equal(e.navigations.at(-1), 'login.html');
});
await check('bank portal validates identity, uses authorized figures, and shows its syndicate rounds', async () => {
  const e = env('bank.html'); load(e, 'bu/api.js'); load(e, 'bu/session.js');
  const data = sessionFor('bank'); e.ctx.BU.session.set(data); e.ctx.bankSession = e.ctx.BU.requireRole(['bank']);
  const main = new Element(); const requested = [];
  const bank = {code:'WEBANK',name:'WeBank',currency:'CNY',limit_total:5000000,limit_used:55960,limit_remaining:4944040,policy:{min_grade:'C',tiers:[1,2],min_amount:10000,max_amount:2000000,max_rate:.15,min_share:.3},public_key:'test-key',contract_id:'CONTRACT'};
  e.ctx.BU.shell = { mount: () => main }; e.ctx.BU.motion = { init() {} };
  e.ctx.fetch = async url => {
    requested.push(url);
    if (url === '/v4/auth/me') return response(200, {user:data.user});
    if (url === '/v4/bank/portfolio') return response(200, {bank,totals:{loans:1,active:1,amount:55960,repaid:0,outstanding:58198},shares:[{loan_id:'loan_test',pct:.4,amount:55960,repaid:0,outstanding:58198,status:'active',contract_id:'CONTRACT'}],simulated:true});
    if (url === '/v4/bank/withdrawals') return response(200, {items:[{id:'WD-test',summary:{text:'<script>unsafe</script>'},my_piece:{pct:.4,amount:55960,contract_id:'CONTRACT'},fingerprint_ok:true}]});
    if (url === '/v4/bank/syndicate') return response(200, {bank:'WEBANK',items:[
      {application:'APP-<img src=x onerror=alert(1)>',status:'offered',grade:'B',borrower_type:'individual_business',province:'HN',industry:'quần áo',rounds:[{amount:200000,bank:'WEBANK',decision:'approve',ms:1500,reason:'<b>policy ok</b>'}],result:'approved',limit:200000,share:{bank:'WEBANK',pct:.4,amount:80000}},
      {application:'APP-lead',status:'disbursed',grade:'A',borrower_type:'company',rounds:[],result:'approved',limit:100000,share:{bank:'WEBANK',pct:.3,amount:30000}}]});
    return response(404, {error:{code:'NOT_FOUND',message:'Unavailable'}});
  };
  load(e, 'bu/bank.js'); await settle();
  assert.match(main.markup, /Mỗi ngân hàng chỉ thấy phần của mình/);
  assert.match(main.markup, /55\.960 tệ/); assert.match(main.markup, /4\.944\.040 tệ/);
  assert.match(main.markup, /Mô phỏng/); assert(!main.markup.includes('Phê duyệt ngân hàng'));
  assert(!main.markup.includes('<script>unsafe</script>')); assert.match(main.markup, /&lt;script&gt;unsafe/);
  assert.match(main.markup, /Duyệt song song/); assert.match(main.markup, /Đồng ý/); assert.match(main.markup, /1,5 giây/);
  assert.match(main.markup, /Ngân hàng dẫn đầu/); assert.match(main.markup, /Doanh nghiệp/); assert.match(main.markup, /40%/);
  assert(!main.markup.includes('<img src=x')); assert(!main.markup.includes('<b>policy ok</b>')); assert.match(main.markup, /&lt;b&gt;policy ok/);
  assert.deepEqual(requested, ['/v4/auth/me','/v4/bank/portfolio','/v4/bank/withdrawals','/v4/bank/syndicate']);
  const missing = env('bank.html'); load(missing, 'bu/api.js'); load(missing, 'bu/session.js');
  load(missing, 'bu/bank.js'); assert.equal(missing.navigations.length, 0);
});
await check('v4 namespaces preserve quote, plan, select/contract/sign, loan, bank, chain, and feature payloads', async () => {
  const e=env('workspace.html'); load(e,'bu/api.js'); e.ctx.localStorage.setItem('bu_token','namespace-token');
  let seen;
  e.ctx.fetch=async(url,init)=>{seen={url,method:init.method,body:init.body?JSON.parse(init.body):undefined,authorization:init.headers.Authorization};return response(200,{});};
  await e.ctx.BU.api.applications.quote('case/1',{amount:120000});
  assert.deepEqual(seen,{url:'/v4/applications/case%2F1/quote',method:'POST',body:{amount:120000},authorization:'Bearer namespace-token'});
  await e.ctx.BU.api.applications.plan('case',{qty:5000,price:80}); assert.equal(seen.method,'PUT');
  await e.ctx.BU.api.applications.consentRevoke('case'); assert.equal(seen.url,'/v4/applications/case/consent/revoke');
  assert.equal(e.ctx.BU.api.applications.accept,undefined); assert.equal(e.ctx.BU.api.applications.acceptSmaller,undefined);
  await e.ctx.BU.api.applications.select('case',{amount:150000,tenor_m:6,method:'revenue',due_day:28});
  assert.deepEqual(seen,{url:'/v4/applications/case/select',method:'POST',body:{amount:150000,tenor_m:6,method:'revenue',due_day:28},authorization:'Bearer namespace-token'});
  await e.ctx.BU.api.applications.contract('case'); assert.deepEqual([seen.url,seen.method],['/v4/applications/case/contract','GET']);
  await e.ctx.BU.api.applications.sign('case',{read_ack:true,method:'otp'}); assert.deepEqual([seen.url,seen.body],['/v4/applications/case/sign',{read_ack:true,method:'otp'}]);
  await e.ctx.BU.api.loans.simulateAdvance('l/1','2026-12-12'); assert.deepEqual([seen.url,seen.body],['/v4/loans/l%2F1/simulate-advance',{to:'2026-12-12'}]);
  await e.ctx.BU.api.loans.prepay('l'); assert.deepEqual([seen.url,seen.method,seen.body],['/v4/loans/l/prepay','POST',{}]);
  await e.ctx.BU.api.loans.receivingAccount('l',{bank:'CMB',number:'622200'}); assert.equal(seen.method,'PUT');
  await e.ctx.BU.api.bank.syndicate(); assert.equal(seen.url,'/v4/bank/syndicate');
  await e.ctx.BU.api.chain.decrypt('WD-test',{private_key_hex:'a'.repeat(64)}); assert.equal(seen.body.private_key_hex,'a'.repeat(64));
  await e.ctx.BU.api.banks.rotateKey('WEBANK',{public_key:'key'}); assert.equal(seen.method,'PUT');
  await e.ctx.BU.api.admin.updateUser('user',{active:false}); assert.equal(seen.method,'PATCH');
  await e.ctx.BU.api.withdrawals.manual({requestId:'uuid'}); assert.equal(seen.body.requestId,'uuid');
});
await check('motion loops finish counters and disable marketing smoothing in hidden tabs', async () => {
  const e = env('index.html'); e.media.matches = false;
  let created = 0, destroyed = 0;
  e.ctx.Lenis = class { constructor() { created++; } raf() {} on() {} destroy() { destroyed++; } };
  load(e, 'bu/motion.js'); e.ctx.BU.motion.init(e.doc); assert.equal(created, 0);
  const value = new Element(); e.ctx.BU.motion.countUp(value, 42, { duration: 100 });
  for (const time of [0, 100]) { const callbacks = [...e.frames.values()]; e.frames.clear(); callbacks.forEach(fn => fn(time)); }
  assert.equal(value.textContent, '42'); assert.equal(e.frames.size, 0);
  e.ctx.BU.motion.init(e.doc, { marketing: true }); assert.equal(created, 1); assert.equal(e.frames.size, 1);
  e.doc.hidden = true; await e.doc.trigger('visibilitychange'); assert.equal(destroyed, 1); assert.equal(e.frames.size, 0);
  e.doc.hidden = false; await e.doc.trigger('visibilitychange'); assert.equal(created, 2);
  e.media.matches = true; e.ctx.BU.motion.init(e.doc); assert.equal(destroyed, 2); assert.equal(e.frames.size, 0);
});


for (const remote of [true,false]) {
 await check('bank chain terms, mixed withdrawals and policy payload ('+(remote?'remote':'local')+')',async()=>{
 const e=env('bank.html');load(e,'bu/api.js');load(e,'bu/session.js');
 const data=sessionFor('bank');e.ctx.BU.session.set(data);e.ctx.bankSession=data;
 const main=new Element();e.ctx.BU.shell={mount:()=>main};e.ctx.BU.motion={init(){}};
 const policy={min_grade:'C',tiers:[1],min_amount:500,max_amount:500000,min_share:.3,min_rate:.08,max_rate:.15,max_share:1,max_share_amount:500000,min_share_amount:500,max_tenor_days:180,min_store_age_months:12,min_store_rating:4,fee_pct:.001};
 if(remote)policy.chain={version:2,hash:'0x123456789abcdef',summary:'<img onerror=bad>',risk_appetite:'moderate',red_flags:['<script>bad</script>'],escalate_when:['review'],deal_breakers:['stop'],contract:{no:'C1',status:'active',reimbursement_terms:'terms',fee_terms:'fees'}};
 let submitted;
 e.ctx.fetch=async(url,init)=>{
 if(url==='/v4/auth/me')return response(200,{user:data.user});
 if(url==='/v4/bank/portfolio')return response(200,{bank:{code:'WEBANK',name:'Bank',currency:'CNY',limit_total:5000000,policy},simulated:true});
 if(url==='/v4/bank/withdrawals')return response(200,{items:[{id:'real',simulated:false,explorer_url:'https://chain.test/explorer/?a=1&b=2'},{id:'unsafe',simulated:false,explorer_url:'javascript:alert(1)'},{id:'old',simulated:true}]});
 if(url==='/v4/banks/WEBANK/policy'){submitted=JSON.parse(init.body);return response(200,{});}
 return response(404,{});
 };
 load(e,'bu/bank.js');await settle();
 assert(main.markup.includes('Chuỗi thật'));assert(main.markup.includes('Mô phỏng'));
 assert(main.markup.includes('rel="noopener noreferrer"'));assert(!main.markup.includes('javascript:'));
 assert.equal(main.markup.includes('Điều khoản trên chuỗi'),remote);
 assert.equal(main.markup.includes('name="max_rate"'),!remote);
 if(remote){assert(main.markup.includes('Tiền trả nợ mô phỏng'));assert(main.markup.includes('&lt;img onerror=bad&gt;'));assert(main.markup.includes('0,1'));}
 const button=new Element(),form=new Element();form.id='bank-policy';form.querySelector=()=>button;
 const vals={min_grade:'C',tiers:['1'],excluded_groups:[],min_amount:'500',max_amount:'500000',min_share:'.3',max_rate:'.15',exclude_industries:['điện tử'],borrower_types:['individual_business'],max_tenor_m:'12',max_late_days:'30'};
 e.ctx.FormData=class{get(k){return vals[k]}getAll(k){return vals[k]}};
 await main.trigger('submit',{target:form});
 assert.equal('max_rate' in submitted,!remote);
 assert.deepEqual([submitted.borrower_types,submitted.exclude_industries,submitted.max_tenor_m,submitted.max_late_days,submitted.tiers],[['individual_business'],['điện tử'],12,30,[1]]);
 submitted=undefined;vals.borrower_types=[];await main.trigger('submit',{target:form});
 assert.equal(submitted,undefined);


 });
}

console.log(`${results.length} groups passed${evidence ? '; replayed real API responses for seven demo accounts and registration' : ''}. Browser layout/console QA remains separate.`);
