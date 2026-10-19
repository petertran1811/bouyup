/* BuoyUp face capture: camera, guided head circle at sign-up, face login with a turn challenge.
 * Frames go one at a time to /v4/face (BackEnd/src/Reid, InsightFace buffalo_l); the server
 * decides what is captured. BU.face.enroll() resolves with an enroll_id for /auth/register,
 * BU.face.login(email?) with a session like /auth/login, BU.face.verify() (signed in: 1:1 re-check against
 * the registered face) with a verify_id. They reject with code CANCELLED; enroll() and verify() also with
 * FACE_UNAVAILABLE / FACE_NOT_ENROLLED when the server cannot check a face.
 * The box always offers a way out instead of the face: "Dùng mã OTP thay thế" (enroll, verify; rejects with
 * code USE_OTP, the caller then opens BU.otp.verify from otp-sms.js) or "Đăng nhập bằng mật khẩu" (login;
 * code USE_PASSWORD). After a camera error, no face model, a failed or timed-out scan it is suggested. */
(function (global) {
  'use strict';
  var BU = global.BU = global.BU || {};
  var SEGMENTS = 8, FRAME_WIDTH = 640, FRAME_GAP_MS = 120;
  var LOGIN_SEGMENT = { left: 4, right: 0 };
  var ui = null;

  var MODES = {
    enroll: { start: '/v4/face/enroll', id: 'enroll_id', title: 'Quét khuôn mặt của bạn',
      sub: 'Nhìn thẳng vào camera, rồi xoay đầu chậm thành một vòng tròn cho tới khi cả vòng sáng lên.', ok: 'Đã ghi nhận khuôn mặt.' },
    login: { start: '/v4/face/login', id: 'login_id', challenge: true, title: 'Đăng nhập bằng khuôn mặt',
      sub: 'Nhìn thẳng vào camera, sau đó quay mặt chậm theo hướng dẫn.', ok: 'Xác thực thành công. Đang đăng nhập…' },
    // Signed in: the bearer token goes along; failures are 403 so the session is kept.
    verify: { start: '/v4/face/verify', id: 'verify_id', challenge: true, auth: true, title: 'Xác minh lại khuôn mặt',
      sub: 'So khớp với khuôn mặt bạn đã đăng ký. Nhìn thẳng vào camera, sau đó quay mặt chậm theo hướng dẫn.', ok: 'Khuôn mặt khớp với tài khoản.' }
  };
  function post(path, body, auth) { return BU.api.request(path, { method: 'POST', body: body || {}, auth: !!auth, timeout: 20000 }); }
  function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

  function arc(i) {
    // Segment i points at i*45 degrees, counter-clockwise from screen right (the video is mirrored).
    var r = 92, mid = i * 360 / SEGMENTS, a1 = (mid - 19) * Math.PI / 180, a2 = (mid + 19) * Math.PI / 180;
    var p = function (a) { return (100 + r * Math.cos(a)).toFixed(2) + ' ' + (100 - r * Math.sin(a)).toFixed(2); };
    return '<path class="face-seg" data-i="' + i + '" d="M ' + p(a1) + ' A ' + r + ' ' + r + ' 0 0 0 ' + p(a2) + '"/>';
  }

  function build() {
    var dialog = document.createElement('dialog');
    dialog.className = 'auth-dialog face-dialog';
    dialog.setAttribute('aria-labelledby', 'face-title');
    var segs = '';
    for (var i = 0; i < SEGMENTS; i++) segs += arc(i);
    dialog.innerHTML =
      '<div class="face-kicker">XÁC THỰC KHUÔN MẶT</div><h2 id="face-title"></h2><p class="face-sub"></p>' +
      '<div class="face-stage"><video class="face-video" playsinline muted autoplay></video>' +
      '<svg class="face-ring" viewBox="0 0 200 200" aria-hidden="true">' + segs + '</svg></div>' +
      '<p class="face-hint" role="status" aria-live="polite"></p>' +
      '<div class="face-progress" aria-hidden="true"><span></span></div>' +
      '<div class="face-actions"><button type="button" class="face-cancel">Hủy</button>' +
      '<button type="button" class="face-retry auth-submit" hidden><span>Thử lại</span><span aria-hidden="true">↻</span></button></div>' +
      '<p class="face-alt-note" hidden></p><button type="button" class="face-alt" hidden></button>' +
      '<p class="face-privacy">Khung hình được gửi tới máy chủ BuoyUp để nhận diện. BuoyUp lưu đặc trưng ArcFace và ảnh khuôn mặt đã căn chỉnh của bạn để đăng nhập; video không được ghi lại.</p>';
    document.body.appendChild(dialog);
    var q = function (sel) { return dialog.querySelector(sel); };
    return { dialog: dialog, title: q('#face-title'), sub: q('.face-sub'), video: q('.face-video'), stage: q('.face-stage'),
      hint: q('.face-hint'), bar: q('.face-progress span'), cancel: q('.face-cancel'), retry: q('.face-retry'), alt: q('.face-alt'), altNote: q('.face-alt-note'),
      segs: Array.prototype.slice.call(dialog.querySelectorAll('.face-seg')), canvas: document.createElement('canvas') };
  }

  function paint(done, next) {
    ui.segs.forEach(function (seg, i) {
      seg.classList.toggle('is-done', !!(done && done[i]));
      seg.classList.toggle('is-next', next === i);
    });
  }

  function say(text, tone) {
    ui.hint.textContent = text || '';
    ui.hint.dataset.tone = tone || '';
  }

  function grab() {
    var video = ui.video;
    if (!video.videoWidth) return null;
    var scale = Math.min(1, FRAME_WIDTH / video.videoWidth);
    ui.canvas.width = Math.round(video.videoWidth * scale);
    ui.canvas.height = Math.round(video.videoHeight * scale);
    ui.canvas.getContext('2d').drawImage(video, 0, 0, ui.canvas.width, ui.canvas.height);  // raw, not mirrored
    return ui.canvas.toDataURL('image/jpeg', 0.82);
  }

  async function openCamera() {
    if (!global.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      var insecure = new Error('Camera chỉ hoạt động qua HTTPS hoặc http://localhost.');
      insecure.code = 'CAMERA'; throw insecure;
    }
    try {
      return await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } } });
    } catch (cause) {
      var error = new Error(cause && cause.name === 'NotAllowedError' ? 'Bạn cần cho phép BuoyUp dùng camera để xác thực khuôn mặt.' : 'Không mở được camera. Kiểm tra camera rồi thử lại.');
      error.code = 'CAMERA'; throw error;
    }
  }

  function unavailable(message) {
    var error = new Error(message || 'Xác thực khuôn mặt chưa sẵn sàng.'); error.code = 'FACE_UNAVAILABLE';
    return error;
  }

  // The way out of the face box: an SMS OTP (sign-up, re-checks) or the password form (login).
  var ALT = {
    otp: { code: 'USE_OTP', label: 'Dùng mã OTP thay thế', note: 'Không quét được khuôn mặt? Bạn có thể xác thực bằng mã OTP gửi qua SMS.' },
    password: { code: 'USE_PASSWORD', label: 'Đăng nhập bằng mật khẩu', note: 'Không nhận diện được? Bạn có thể đăng nhập bằng email và mật khẩu.' }
  };
  function altFor(mode) { return mode === 'login' ? ALT.password : BU.otp ? ALT.otp : null; }

  function run(mode, email) {
    ui = ui || build();
    var conf = MODES[mode], login = !!conf.challenge, alt = altFor(mode);
    // One state per run; an older run that is still awaiting never touches the dialog again.
    var state = { stopped: false, stream: null, busy: false };
    ui.current = state;
    function live() { return !state.stopped && ui.current === state; }
    ui.title.textContent = conf.title;
    ui.sub.textContent = conf.sub;
    ui.dialog.classList.toggle('is-login', login);
    ui.alt.hidden = !alt;
    ui.alt.textContent = alt ? alt.label : '';
    ui.alt.classList.remove('is-suggested');
    ui.altNote.hidden = true;
    ui.altNote.textContent = alt ? alt.note : '';

    return new Promise(function (resolve, reject) {
      function stop() {
        state.stopped = true;
        if (state.stream) state.stream.getTracks().forEach(function (track) { track.stop(); });
        state.stream = null;
        if (ui.current === state) ui.video.srcObject = null;
      }
      function finish(error, value) {
        stop(); cleanup();
        if (ui.dialog.open && ui.current === state) ui.dialog.close();
        if (error) reject(error); else resolve(value);
      }
      function cancel(event) {
        if (event) event.preventDefault();
        var cancelled = new Error('Đã hủy xác thực khuôn mặt.'); cancelled.code = 'CANCELLED';
        finish(cancelled);
      }
      function retry() { attempt(); }
      function other() {
        var instead = new Error(alt.label); instead.code = alt.code;
        finish(instead);
      }
      function cleanup() {
        ui.cancel.removeEventListener('click', cancel);
        ui.dialog.removeEventListener('cancel', cancel);
        ui.retry.removeEventListener('click', retry);
        ui.alt.removeEventListener('click', other);
      }
      ui.cancel.addEventListener('click', cancel);
      ui.dialog.addEventListener('cancel', cancel);
      ui.retry.addEventListener('click', retry);
      if (alt) ui.alt.addEventListener('click', other);

      async function attempt() {
        if (state.busy || !live()) return;
        state.busy = true;
        ui.retry.hidden = true;
        ui.alt.classList.remove('is-suggested');
        ui.altNote.hidden = true;
        ui.stage.classList.remove('is-ok', 'is-error');
        paint(null, null); ui.bar.style.width = '0%';
        say('Đang mở camera…');
        try {
          // Server first: no camera prompt when it cannot check a face for this account.
          var start = await post(conf.start, mode === 'login' ? { email: email || '' } : {}, conf.auth);
          if (!live()) return;
          if (!state.stream) {
            var stream = await openCamera();
            if (!live()) { stream.getTracks().forEach(function (track) { track.stop(); }); return; }
            state.stream = stream;
            ui.video.srcObject = stream;
            await ui.video.play().catch(function () {});
          }
          var path = conf.start + '/' + encodeURIComponent(start[conf.id]) + '/frame';
          say(start.message || 'Nhìn thẳng vào camera.');
          while (live()) {
            var image = grab();
            if (!image) { await wait(100); continue; }
            var out = await post(path, { image: image }, conf.auth);
            if (!live()) return;
            ui.stage.classList.toggle('has-face', !!out.face);
            if (login) {
              paint(null, out.challenge ? LOGIN_SEGMENT[out.challenge] : null);
              ui.bar.style.width = out.done ? '100%' : out.stage === 'turn' ? '66%' : '33%';
            } else {
              paint(out.segments, out.next_segment);
              ui.bar.style.width = Math.round((out.progress || 0) * 100) + '%';
            }
            say(out.message, out.hint === 'OK' ? '' : 'warn');
            if (out.done) {
              stop(); cleanup();  // past this point Cancel can no longer throw the result away
              ui.stage.classList.add('is-ok');
              if (!login) paint(new Array(SEGMENTS).fill(true), null);
              say(conf.ok, 'ok');
              await wait(700);
              finish(null, mode === 'login' ? out : start[conf.id]);
              return;
            }
            await wait(FRAME_GAP_MS);
          }
        } catch (error) {
          if (!live()) return;
          // Sign-up goes on without a face when the server has no face model (it then does not require one);
          // the identity step falls back the same way, and for accounts that never registered a face.
          if (mode !== 'login' && (error.code === 'FACE_UNAVAILABLE' || error.code === 'FACE_NOT_ENROLLED')) { finish(error); return; }
          ui.stage.classList.add('is-error');
          say(error.message || 'Không thể xác thực khuôn mặt. Vui lòng thử lại.', 'error');
          ui.retry.hidden = false;
          if (alt) {
            // No camera, camera refused, no face model, not recognised, liveness failed, timed out: suggest the other way.
            ui.alt.classList.add('is-suggested');
            ui.altNote.hidden = false;
          }
          // Without a camera (or with no model on the server) another scan cannot work: focus the other way.
          if (alt && (error.code === 'CAMERA' || error.code === 'FACE_UNAVAILABLE')) ui.alt.focus(); else ui.retry.focus();
        } finally { state.busy = false; }
      }
      if (!ui.dialog.open) ui.dialog.showModal();
      attempt();
    });
  }

  BU.face = {
    enroll: async function () {
      var status = await BU.api.request('/v4/face/status', { auth: false }).catch(function () { return null; });
      if (status && !status.available) throw unavailable();  // no camera prompt when the server cannot scan
      return run('enroll');
    },
    login: function (email) { return run('login', email); },
    verify: function () { return run('verify'); }
  };
})(window);
