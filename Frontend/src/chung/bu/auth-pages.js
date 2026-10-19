(function () {
  'use strict';
  const BU = window.BU;
  const register = document.body.dataset.authPage === 'register';
  const form = document.querySelector(register ? '#register-form' : '#login-form');
  const errorBox = document.getElementById('error');
  const submit = form.querySelector('[type="submit"]');
  const submitLabel = submit.querySelector('span');
  const originalLabel = submitLabel.textContent;
  const next = new URLSearchParams(location.search).get('next');
  BU.motion.init(document);
  const existing = BU.session.get();
  if (existing) {
    location.replace(BU.session.next(next, existing.user.role));
    return;
  }
  document.querySelector('.auth-theme').addEventListener('click', function () {
    BU.motion.setTheme(BU.motion.theme() === 'dark' ? 'light' : 'dark');
  });
  const video = document.querySelector('.auth-bg video');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function videoState() {
    if (document.hidden || reduced.matches) video.pause();
    else video.play().catch(function () {});
  }
  document.addEventListener('visibilitychange', videoState);
  reduced.addEventListener('change', videoState);
  videoState();
  document.querySelectorAll('[data-password]').forEach(function (button) {
    button.addEventListener('click', function () {
      const input = document.getElementById(button.dataset.password);
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      input.toggleAttribute('data-visible', show);
      button.textContent = show ? 'Ẩn' : 'Hiện';
      button.setAttribute('aria-pressed', String(show));
      button.setAttribute('aria-label', (show ? 'Ẩn ' : 'Hiện ') + (input.id === 'confirm_password' ? 'mật khẩu nhập lại' : 'mật khẩu'));
    });
  });
  function clearErrors() {
    errorBox.hidden = true;
    form.querySelectorAll('[aria-invalid]').forEach(function (input) { input.removeAttribute('aria-invalid'); });
    form.querySelectorAll('.auth-field-error').forEach(function (error) { error.hidden = true; });
  }
  function fieldError(name, message) {
    const input = form.elements.namedItem(name);
    const error = document.getElementById(name + '-error');
    if (!input || !error) return false;
    input.setAttribute('aria-invalid', 'true');
    error.textContent = message;
    error.hidden = false;
    input.focus();
    return true;
  }
  document.querySelectorAll('[data-demo-email]').forEach(function (button) {
    button.addEventListener('click', function () {
      form.elements.email.value = button.dataset.demoEmail;
      form.elements.password.value = 'BuoyUp@2026';
      clearErrors();
      submit.focus();
    });
  });
  if (register) {
    const password = form.elements.password;
    password.addEventListener('input', function () {
      const value = password.value;
      const score = Number(value.length >= 8) + Number(/[a-zA-Z]/.test(value) && /[0-9]/.test(value)) + Number(/[^a-zA-Z0-9]/.test(value)) + Number(value.length >= 12);
      document.getElementById('password-strength').value = value ? score : 0;
      document.getElementById('password-hint').textContent = !value ? 'Dùng ít nhất tám ký tự, có chữ và số.' : score < 2 ? 'Cần mạnh hơn · dùng ít nhất tám ký tự, có chữ và số.' : score < 4 ? 'Khá tốt · thêm ký tự đặc biệt và độ dài để tăng bảo mật.' : 'Mật khẩu mạnh.';
    });
    document.getElementById('open-terms').addEventListener('click', function () { document.getElementById('terms-dialog').showModal(); });
  }
  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
    errorBox.focus();
  }
  // A finished face scan stays valid on the server for a few minutes, so a retried submit reuses it.
  let faceEnrollId = null;
  // Sign-up without a face (no camera, camera refused, no face model, failed scan, or the person chose it):
  // the phone number verified with an SMS OTP instead (otp-sms.js; checked in the browser for now).
  let otpProof = null;
  const FACE_OTP_REASONS = { FACE_UNAVAILABLE: 'Máy chủ chưa sẵn sàng nhận diện khuôn mặt, nên bạn xác thực số điện thoại bằng mã OTP để tạo tài khoản.' };
  async function signupOtp(reason) {
    const phone = form.elements.phone;
    const proof = await BU.otp.verify({ phone: phone.value.trim(), editable: true, reason: reason || '',
      sub: 'Nhận mã 6 chữ số qua SMS để xác nhận số điện thoại và hoàn tất tạo tài khoản.' });
    phone.value = proof.phone;
    return proof;
  }
  function passwordInstead(message) {
    showError(message);
    (form.elements.email.value ? form.elements.password : form.elements.email).focus();
  }
  const faceLogin = document.getElementById('face-login');
  if (faceLogin && BU.face) {
    faceLogin.addEventListener('click', async function () {
      clearErrors();
      const email = form.elements.email;
      email.value = email.value.trim();
      if (email.value && !email.validity.valid) { fieldError('email', 'Email chưa hợp lệ. Để trống để nhận diện khuôn mặt trên mọi tài khoản.'); return; }
      try {
        const result = await BU.face.login(email.value);
        BU.session.set(result);
        location.assign(BU.session.next(next, result.user.role));
      } catch (error) {
        // No passwordless OTP login: without a real SMS provider it would let anyone in. A face that cannot be
        // checked sends the person back to the email and password form instead.
        if (error.code === 'USE_PASSWORD') passwordInstead('Không xác thực được bằng khuôn mặt. Vui lòng đăng nhập bằng email và mật khẩu.');
        else if (error.code !== 'CANCELLED') passwordInstead('Không xác thực được bằng khuôn mặt. Vui lòng đăng nhập bằng email và mật khẩu.');
      }
    });
  }
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    if (submit.disabled) return;
    clearErrors();
    const email = form.elements.email;
    email.value = email.value.trim();
    if (register && !form.elements.display_name.value.trim()) { fieldError('display_name', 'Vui lòng nhập họ và tên.'); return; }
    if (!email.value || !email.validity.valid) { fieldError('email', 'Vui lòng nhập địa chỉ email hợp lệ.'); return; }
    const password = form.elements.password.value;
    if (!password) { fieldError('password', 'Vui lòng nhập mật khẩu.'); return; }
    if (register) {
      if (password.length < 8 || !/[a-zA-Z]/.test(password) || !/[0-9]/.test(password)) { fieldError('password', 'Mật khẩu cần ít nhất tám ký tự, có chữ và số.'); return; }
      if (password !== form.elements.confirm_password.value) { fieldError('confirm_password', 'Mật khẩu nhập lại chưa khớp.'); return; }
      if (!form.elements.accept_terms.checked) { fieldError('accept_terms', 'Vui lòng đồng ý với điều khoản sử dụng.'); return; }
      // A number changed after the OTP needs a new code.
      if (otpProof && BU.otp && BU.otp.normalize(form.elements.phone.value) !== otpProof.phone) otpProof = null;
      if (BU.face && !faceEnrollId && !otpProof) {
        try { faceEnrollId = await BU.face.enroll(); } catch (error) {
          if (error.code === 'CANCELLED' || !BU.otp) {
            // No face model on the server (and no OTP box on the page): it does not require a scan, so sign-up goes on.
            if (error.code !== 'FACE_UNAVAILABLE') {
              showError('Cần quét khuôn mặt hoặc xác thực bằng mã OTP để hoàn tất tạo tài khoản. Bấm “Tạo tài khoản” để làm lại.');
              return;
            }
          } else {
            try { otpProof = await signupOtp(FACE_OTP_REASONS[error.code] || ''); } catch (_) {
              showError('Cần quét khuôn mặt hoặc xác thực bằng mã OTP để hoàn tất tạo tài khoản. Bấm “Tạo tài khoản” để làm lại.');
              return;
            }
            const note = document.querySelector('.auth-face-note span:last-child');
            if (note) note.textContent = 'Đã xác thực số điện thoại ' + otpProof.phone_masked + ' bằng mã OTP.';
          }
        }
      }
    }
    submit.disabled = true;
    form.setAttribute('aria-busy', 'true');
    submitLabel.textContent = register ? 'Đang tạo tài khoản…' : 'Đang đăng nhập…';
    try {
      const payload = { email: email.value, password: password };
      if (register) {
        payload.display_name = form.elements.display_name.value.trim();
        payload.accept_terms = true;
        if (form.elements.phone.value.trim()) payload.phone = form.elements.phone.value.trim();
        if (faceEnrollId) payload.face_enroll_id = faceEnrollId;
        else if (otpProof) { payload.otp_verified = true; payload.phone = form.elements.phone.value.trim(); }
      }
      const result = await BU.api.auth[register ? 'register' : 'login'](payload);
      BU.session.set(result);
      location.assign(register ? 'workspace.html' : BU.session.next(next, result.user.role));
    } catch (error) {
      const messages = {
        INVALID_CREDENTIALS: 'Email hoặc mật khẩu chưa đúng. Vui lòng kiểm tra và thử lại.',
        RATE_LIMITED: 'Bạn đã thử đăng nhập nhiều lần. Vui lòng chờ một lúc rồi thử lại.',
        CONFLICT: 'Email này đã có tài khoản. Hãy đăng nhập hoặc dùng email khác.',
        NETWORK: 'Chưa kết nối được với BuoyUp. Kiểm tra kết nối rồi thử lại.'
      };
      const message = messages[error.code] || error.message || messages.NETWORK;
      const field = error.details && error.details.field;
      // An expired or already-registered face scan must be redone on the next submit.
      if (field === 'face_enroll_id' || error.code === 'FACE_ALREADY_REGISTERED') faceEnrollId = null;
      if (field === 'phone') otpProof = null;
      if (!fieldError(field || (error.code === 'CONFLICT' ? 'email' : ''), message)) showError(message);
    } finally {
      submit.disabled = false;
      form.removeAttribute('aria-busy');
      submitLabel.textContent = originalLabel;
    }
  });
})();
