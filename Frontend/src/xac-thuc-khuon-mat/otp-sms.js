/* BuoyUp SMS OTP: the way in when the face cannot be checked (no camera, camera refused, insecure page,
 * no face model on the server, face not recognised / liveness failed / timed out, or "Dùng mã OTP thay thế").
 *
 * BU.otp.verify(options) opens the dialog and resolves with {method:'otp', phone, phone_masked, verified_at}
 * once the right 6-digit code is typed; it rejects with code CANCELLED (Hủy, Esc).
 *   options.phone     the number on the account (user.phone); asked for when missing or not a VN/CN mobile
 *   options.editable  let the person change the number (sign-up)
 *   options.sub       the line under the title; options.reason a note on why the face was not used
 *
 * TODO(SMS): no SMS provider is connected yet. The code is generated and checked here in the browser and
 * shown in the dialog as the incoming text message, so the server only receives "otp_verified": true.
 * With a provider, move both halves to the server: POST /v4/otp/send {phone, purpose} → {otp_id, expires_in}
 * and POST /v4/otp/verify {otp_id, code} → a single-use proof sent instead of otp_verified
 * (BackEnd/API_config/API_CONTRACT_V4.md §1b), and drop the in-dialog message. */
(function (global) {
  'use strict';
  var BU = global.BU = global.BU || {};
  var LENGTH = 6, RESEND_SECONDS = 60, TTL_MS = 5 * 60 * 1000, MAX_WRONG = 5;
  var MAX_SENDS = 5, SEND_WINDOW_MS = 15 * 60 * 1000;
  var PHONE_KEY = 'bu_otp_phone';
  var sends = [];  // send times on this page, across dialogs
  var ui = null;

  /* Mirrors normalize_phone() in BackEnd/src/app/api/auth.py. */
  function normalize(phone) {
    var raw = String(phone || '').trim();
    if (!/^\+?[\d\s().-]{8,24}$/.test(raw)) return null;
    var digits = raw.replace(/\D/g, ''), international = raw.charAt(0) === '+';
    if (!international && digits.slice(0, 2) === '00') { digits = digits.slice(2); international = true; }
    var vn = /^(?:84|0|840)([35789]\d{8})$/.exec(digits), cn = /^(?:86)?(1[3-9]\d{9})$/.exec(digits);
    if (vn && (digits.slice(0, 2) === '84' || !international)) return '+84' + vn[1];
    if (cn && (digits.slice(0, 2) === '86' || !international)) return '+86' + cn[1];
    return null;
  }
  function mask(phone) {
    var digits = String(phone || '').replace(/\D/g, '');
    return digits.length >= 3 ? '•••• ' + digits.slice(-3) : '';
  }
  function remembered() { try { return global.sessionStorage.getItem(PHONE_KEY) || ''; } catch (_) { return ''; } }
  function remember(phone) { try { global.sessionStorage.setItem(PHONE_KEY, phone); } catch (_) { /* optional */ } }
  function newCode() {
    var c = global.crypto;
    if (c && c.getRandomValues) {
      var buf = new Uint32Array(1), limit = 4294000000;  // a multiple of 10^6: no modulo bias
      do { c.getRandomValues(buf); } while (buf[0] >= limit);
      return String(buf[0] % 1000000).padStart(LENGTH, '0');
    }
    return String(Math.floor(Math.random() * 1000000)).padStart(LENGTH, '0');
  }

  function build() {
    var dialog = document.createElement('dialog');
    dialog.className = 'otp-dialog';
    dialog.setAttribute('aria-labelledby', 'otp-title');
    dialog.setAttribute('aria-describedby', 'otp-sub');
    dialog.innerHTML =
      '<div class="otp-kicker">XÁC THỰC QUA SMS</div><h2 id="otp-title">Xác thực bằng mã OTP</h2>' +
      '<p class="otp-sub" id="otp-sub"></p><p class="otp-reason" hidden></p>' +
      '<form class="otp-form" novalidate>' +
      '<div class="otp-phone"><span class="otp-label">Số điện thoại nhận mã</span>' +
      '<div class="otp-phone-fixed"><strong></strong><button type="button" class="otp-link otp-change">Đổi số</button></div>' +
      '<label class="otp-phone-edit"><span class="otp-visually-hidden">Số điện thoại nhận mã</span>' +
      '<input type="tel" name="otp_phone" autocomplete="tel" inputmode="tel" maxlength="24" placeholder="0912 345 678 hoặc +86 138 0000 0000" aria-describedby="otp-phone-error"></label>' +
      '<p class="otp-error" id="otp-phone-error" hidden></p></div>' +
      '<div class="otp-sms" role="status" aria-live="polite" hidden><div class="otp-sms-head"><span class="otp-sms-icon" aria-hidden="true">✉</span>' +
      '<strong>Tin nhắn</strong><span class="otp-sms-from">BuoyUp</span><span class="otp-sms-time">vừa xong</span></div><p class="otp-sms-body"></p></div>' +
      '<div class="otp-entry" hidden><p class="otp-sent" role="status" aria-live="polite"></p>' +
      '<label class="otp-label" for="otp-code">Nhập mã 6 chữ số</label>' +
      '<input id="otp-code" class="otp-code" name="otp_code" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" spellcheck="false" aria-describedby="otp-code-hint otp-code-error">' +
      '<p class="otp-hint" id="otp-code-hint">Mã có hiệu lực trong 5 phút.</p><p class="otp-error" id="otp-code-error" role="alert" hidden></p>' +
      '<button type="button" class="otp-link otp-resend" disabled></button></div>' +
      '<div class="otp-actions"><button type="button" class="otp-cancel">Hủy</button>' +
      '<button type="submit" class="otp-primary"><span>Gửi mã</span><span aria-hidden="true">↗</span></button></div></form>' +
      '<p class="otp-privacy">BuoyUp không bao giờ hỏi mã OTP qua điện thoại hay tin nhắn. Không chia sẻ mã này cho bất kỳ ai.</p>';
    document.body.appendChild(dialog);
    var q = function (sel) { return dialog.querySelector(sel); };
    return { dialog: dialog, form: q('.otp-form'), sub: q('.otp-sub'), reason: q('.otp-reason'),
      fixed: q('.otp-phone-fixed'), fixedText: q('.otp-phone-fixed strong'), change: q('.otp-change'),
      edit: q('.otp-phone-edit'), phone: q('.otp-phone-edit input'), phoneError: q('#otp-phone-error'),
      sms: q('.otp-sms'), smsBody: q('.otp-sms-body'), entry: q('.otp-entry'), sent: q('.otp-sent'),
      code: q('.otp-code'), codeError: q('#otp-code-error'), resend: q('.otp-resend'),
      cancel: q('.otp-cancel'), primary: q('.otp-primary'), primaryLabel: q('.otp-primary span') };
  }

  function show(el, on) { el.hidden = !on; }
  function error(el, text) { el.textContent = text || ''; el.hidden = !text; }
  function focusables() {
    return Array.prototype.filter.call(ui.dialog.querySelectorAll('button, input'), function (el) {
      return !el.disabled && !el.closest('[hidden]') && el.offsetParent !== null;
    });
  }

  function verify(options) {
    options = options || {};
    ui = ui || build();
    if (ui.current) ui.current.abort();
    var state = { phone: normalize(options.phone) || normalize(remembered()), editing: false, code: null,
      issued: 0, wrong: 0, locked: false, timer: null, resendAt: 0, done: false };
    state.editing = !state.phone || !!options.editable && !normalize(options.phone);
    ui.sub.textContent = options.sub || 'BuoyUp gửi mã 6 chữ số qua SMS tới số điện thoại của bạn.';
    ui.reason.textContent = options.reason || '';
    show(ui.reason, !!options.reason);

    return new Promise(function (resolve, reject) {
      var me = { abort: function () { finish(cancelled()); } };
      ui.current = me;
      function cancelled() { var e = new Error('Đã hủy xác thực bằng mã OTP.'); e.code = 'CANCELLED'; return e; }
      function finish(err, value) {
        if (state.done) return;
        state.done = true;
        clearInterval(state.timer);
        ui.form.removeEventListener('submit', onSubmit);
        ui.cancel.removeEventListener('click', onCancel);
        ui.dialog.removeEventListener('cancel', onCancel);
        ui.dialog.removeEventListener('keydown', onKey);
        ui.change.removeEventListener('click', onChange);
        ui.resend.removeEventListener('click', onResend);
        ui.code.removeEventListener('input', onInput);
        ui.code.removeEventListener('paste', onPaste);
        if (ui.current === me) { ui.current = null; if (ui.dialog.open) ui.dialog.close(); }
        if (err) reject(err); else resolve(value);
      }
      function render() {
        var sent = !!state.code;
        show(ui.fixed, !state.editing);
        show(ui.edit, state.editing);
        ui.fixedText.textContent = state.phone ? mask(state.phone) : '';
        show(ui.change, !!options.editable || !normalize(options.phone));
        show(ui.entry, sent && !state.editing);
        show(ui.sms, sent && !state.editing);
        ui.primaryLabel.textContent = sent && !state.editing ? 'Xác nhận mã' : 'Gửi mã';
        ui.primary.disabled = sent && !state.editing && state.locked;
        ui.code.disabled = state.locked;
        tick();
      }
      function tick() {
        var left = Math.max(0, Math.ceil((state.resendAt - Date.now()) / 1000));
        ui.resend.disabled = left > 0;
        ui.resend.textContent = left > 0 ? 'Gửi lại mã (' + left + ' giây)' : 'Gửi lại mã';
        if (!left) clearInterval(state.timer);
      }
      function send() {
        if (state.editing) {
          var phone = normalize(ui.phone.value);
          if (!phone) {
            ui.phone.setAttribute('aria-invalid', 'true');
            error(ui.phoneError, 'Số điện thoại chưa hợp lệ. Nhập số di động Việt Nam (vd. 0912 345 678) hoặc Trung Quốc (vd. +86 138 0000 0000).');
            ui.phone.focus();
            return;
          }
          ui.phone.removeAttribute('aria-invalid');
          error(ui.phoneError, '');
          state.phone = phone;
        }
        var now = Date.now();
        sends = sends.filter(function (t) { return now - t < SEND_WINDOW_MS; });
        if (sends.length >= MAX_SENDS) {
          error(state.code ? ui.codeError : ui.phoneError, 'Bạn đã yêu cầu nhiều mã liên tiếp. Vui lòng chờ 15 phút rồi gửi lại.');
          return;
        }
        sends.push(now);
        remember(state.phone);
        state.editing = false;
        state.code = newCode();
        state.issued = now;
        state.wrong = 0;
        state.locked = false;
        state.resendAt = now + RESEND_SECONDS * 1000;
        clearInterval(state.timer);
        state.timer = setInterval(tick, 1000);
        ui.sent.textContent = 'Đã gửi mã tới ' + mask(state.phone);
        ui.smsBody.textContent = 'BuoyUp: Mã xác thực của bạn là ' + state.code + '. Không chia sẻ mã này.';
        ui.code.value = '';
        ui.code.removeAttribute('aria-invalid');
        error(ui.codeError, '');
        ui.sms.classList.remove('is-new');
        void ui.sms.offsetWidth;  // restart the arrival animation on a resend
        ui.sms.classList.add('is-new');
        render();
        ui.code.focus();
      }
      function check() {
        var value = ui.code.value.replace(/\D/g, '');
        if (state.locked) return;
        if (value.length !== LENGTH) {
          ui.code.setAttribute('aria-invalid', 'true');
          error(ui.codeError, 'Nhập đủ 6 chữ số của mã.');
          ui.code.focus();
          return;
        }
        if (Date.now() - state.issued > TTL_MS) {
          state.locked = true;
          error(ui.codeError, 'Mã đã hết hạn. Vui lòng gửi lại mã mới.');
          render(); ui.resend.focus();
          return;
        }
        if (value !== state.code) {
          state.wrong++;
          ui.code.setAttribute('aria-invalid', 'true');
          if (state.wrong >= MAX_WRONG) {
            state.locked = true;
            error(ui.codeError, 'Bạn đã nhập sai 5 lần. Vui lòng gửi lại mã mới.');
            render();
            (ui.resend.disabled ? ui.cancel : ui.resend).focus();
          } else {
            error(ui.codeError, 'Mã chưa đúng. Bạn còn ' + (MAX_WRONG - state.wrong) + ' lần nhập.');
            ui.code.select();
          }
          return;
        }
        ui.code.removeAttribute('aria-invalid');
        error(ui.codeError, '');
        ui.sent.textContent = 'Đã xác thực số điện thoại.';
        ui.dialog.classList.add('is-ok');
        ui.primary.disabled = true;
        var proof = { method: 'otp', phone: state.phone, phone_masked: mask(state.phone), verified_at: new Date().toISOString() };
        clearInterval(state.timer);
        setTimeout(function () { ui.dialog.classList.remove('is-ok'); finish(null, proof); }, 450);
      }
      function onSubmit(event) {
        event.preventDefault();
        if (state.done) return;
        if (state.code && !state.editing) check(); else send();
      }
      function onCancel(event) { if (event) event.preventDefault(); finish(cancelled()); }
      function onChange() {
        state.editing = true; state.code = null; clearInterval(state.timer); state.resendAt = 0;
        ui.phone.value = state.phone ? state.phone : (options.phone || '');
        render(); ui.phone.focus();
      }
      function onResend() { if (!ui.resend.disabled) send(); }
      function onInput() {
        var digits = ui.code.value.replace(/\D/g, '').slice(0, LENGTH);
        if (digits !== ui.code.value) ui.code.value = digits;
        if (ui.codeError.textContent && !state.locked) { error(ui.codeError, ''); ui.code.removeAttribute('aria-invalid'); }
        if (digits.length === LENGTH) check();
      }
      function onPaste(event) {
        var text = (event.clipboardData || global.clipboardData);
        text = text && text.getData ? text.getData('text') : '';
        var digits = String(text || '').replace(/\D/g, '').slice(0, LENGTH);
        if (!digits) return;
        event.preventDefault();
        ui.code.value = digits;
        onInput();
      }
      // Native <dialog> keeps the page inert; this keeps Tab cycling inside the box as well.
      function onKey(event) {
        if (event.key !== 'Tab') return;
        var list = focusables();
        if (!list.length) return;
        var first = list[0], last = list[list.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
      ui.form.addEventListener('submit', onSubmit);
      ui.cancel.addEventListener('click', onCancel);
      ui.dialog.addEventListener('cancel', onCancel);
      ui.dialog.addEventListener('keydown', onKey);
      ui.change.addEventListener('click', onChange);
      ui.resend.addEventListener('click', onResend);
      ui.code.addEventListener('input', onInput);
      ui.code.addEventListener('paste', onPaste);
      ui.phone.value = state.editing ? (options.phone || remembered() || '') : '';
      ui.phone.removeAttribute('aria-invalid');
      error(ui.phoneError, ''); error(ui.codeError, '');
      ui.dialog.classList.remove('is-ok');
      ui.primary.disabled = false;
      render();
      if (!ui.dialog.open) ui.dialog.showModal();
      (state.editing ? ui.phone : ui.primary).focus();
    });
  }

  BU.otp = { verify: verify, normalize: normalize, mask: mask };
})(window);
