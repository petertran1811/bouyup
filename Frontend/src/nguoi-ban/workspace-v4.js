/* Seller onboarding: the API owns workflow state and every financial figure. */
(function () {
  'use strict';
  const session = BU.requireRole(['seller']);
  if (!session) return;
  const $ = id => document.getElementById(id);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = value => value == null ? '—' : new Intl.NumberFormat('vi-VN').format(value);
  const money = (value, currency) => `${num(value)} ${currency === 'CNY' ? 'tệ' : currency === 'VND' ? 'đồng' : esc(currency || '')}`;
  const pct = value => value == null ? '—' : new Intl.NumberFormat('vi-VN', {style:'percent',maximumFractionDigits:2}).format(value);
  const day = value => { const v=String(value || ''), m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(v); if(m) return `${m[3]}/${m[2]}/${m[1]}`; const t=v?new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(v)?v:v+'Z'):null; return t&&!isNaN(t) ? t.toLocaleDateString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',day:'2-digit',month:'2-digit',year:'numeric'}) : value ? esc(v.slice(0, 10)) : 'Chưa có thông tin'; };
  // API explanation prose may contain staff terminology. Never surface it to sellers.
  const sellerText = value => String(value || '').replace(/(?:sha256:|0x)[a-f\d]+/gi, '')
    .replace(/\b(?:RISK|LAW|AML|POL|EVENT)[-_][A-Z\d_-]+(?:#[\d]+)?/gi, '')
    .replace(/\b(?:Agent\s*\d|Pha\s*[012]|FATE|VERIFIED|OUT_OF_SCOPE|ESCALATED)\b/gi, '')
    .replace(/\b[a-z][a-z\d_]*_[a-z\d_]+(?:\([^)]*\))?/gi, '')
    .replace(/\bB\d+\b/g, '').replace(/\s{2,}/g, ' ').trim();
  const copy = value => esc(sellerText(value));
  const statusNames = {draft:'Đang lập hồ sơ',identified:'Đang lập hồ sơ',consented:'Đang lập hồ sơ',verifying:'Đang xác minh',verified:'Đã xác minh',needs_answer:'Cần bạn làm rõ',offered:'Ngân hàng đã duyệt hạn mức',in_control:'Đang kiểm tra',selected:'Chờ ký hợp đồng',signed:'Đang giải ngân',expired:'Hạn mức hết hiệu lực',escalated:'Đang kiểm tra thêm',rejected:'Chưa được duyệt',out_of_scope:'Chưa đủ điều kiện',disbursed:'Đã giải ngân',repaying:'Đang trả nợ',closed:'Đã tất toán',active:'Đang trả nợ',overdue:'Cần trả nợ'};
  const groups = ['quần áo','thực phẩm đóng gói','thực phẩm rời','thực phẩm chức năng','dược','thiết bị y tế I','thiết bị y tế II','thiết bị y tế III','thuốc lá điện tử','dịch thuốc lá điện tử','điện tử','khác'];
  // Loan circle, Stage 1: three separate boxes, none pre-ticked, each linked to its own text.
  const scopes = [
    {key:'credit_inquiry',label:'Ủy quyền tra cứu tín dụng cho WeBank và các ngân hàng hợp tác',covers:'Báo cáo tín dụng; điểm liên ngân hàng',doc:'van-ban/tra-cuu-tin-dung.html'},
    {key:'share_partners',label:'Đồng ý chuyển hồ sơ vay cho các ngân hàng hợp tác trong danh sách đính kèm',covers:'Hồ sơ vay và kết quả thẩm định',doc:'van-ban/ngan-hang-hop-tac.html'},
    {key:'data_processing',label:'Đồng ý xử lý thông tin khuôn mặt và dữ liệu tài chính để xác thực và thẩm định',covers:'Khuôn mặt (xác thực, ký); dữ liệu thuế; ảnh doanh thu bạn tự nộp',doc:'van-ban/xu-ly-du-lieu.html'}
  ];
  // Review 17/10/2026: personal sellers too; the tenor is set by BuoyUp, so it is not shown as a choice here.
  const borrowerTypes=[['individual','Cá nhân','Bán hàng online, chưa đăng ký kinh doanh · vay tối đa 50.000 tệ'],['individual_business','Hộ kinh doanh','Có đăng ký hộ kinh doanh · vay tối đa 200.000 tệ'],['company','Doanh nghiệp','Có đăng ký doanh nghiệp · cần bảo lãnh của người đại diện']];
  const DECLARE_IMAGES='Tôi cam đoan số doanh thu và ảnh chụp tôi tải lên là của cửa hàng tôi, lấy từ trang quản lý cửa hàng và không bị chỉnh sửa.';
  const DECLARE_ALL='Tôi cam đoan toàn bộ thông tin trong kế hoạch vay là đúng sự thật và do tôi tự kê khai. Tôi hiểu rằng kê khai gian dối có thể bị từ chối, bị thu hồi khoản vay trước hạn và chịu trách nhiệm theo pháp luật.';
  const field = (key, label, value='', type='text', extra='') => `<label class="v4-field">${label}<input name="${key}" type="${type}" value="${esc(value)}" ${extra}></label>`;
  const select = (key, label, values, value) => `<label class="v4-field">${label}<select name="${key}">${values.map(v => `<option ${v === value ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
  const button = (action, text, primary=false, extra='') => `<button type="button" class="btn ${primary ? 'btn-primary' : ''}" data-action="${action}" ${extra}>${text}</button>`;
  const submit = (text, extra='') => `<div class="wizard-actions"><button type="submit" class="btn btn-primary" ${extra}>${text}</button></div>`;
  const facts = entries => `<dl class="v4-facts">${entries.map(([label,value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join('')}</dl>`;
  const details = (label, html, extra='') => `<details ${extra} class="wizard-details"><summary>${label}</summary>${html}</details>`;
  const api = (path, method='GET', body) => BU.api.request(path, {method,body,timeout:60000});
  const appPath = (tail='') => `/v4/applications/${encodeURIComponent(state.app.id)}${tail}`;
  let state = {app:null,items:[],stores:[],demo:false,platforms:[],profile:null,loan:null,selected:null,quotePending:false,complaints:[],complaintChannel:'',features:{cccd_ocr:false},notices:{items:[],unread:0,loaded:false}};
  // Agent 5's reports to the seller (SELLER_SERVICES_PLAN §6.5): list, the open report, a cache of opened ones.
  let reportsData={items:[],loaded:false},reportId=null,reportCache={},reportsAt=0;
  let complaintOpen=false, view='home', complaintPrefill=null;
  let loanDrawer=(()=>{try{return localStorage.getItem('bu_loan_drawer')==='1';}catch(_){return false;}})();
  const complaintStatus={acknowledged:'Đã tiếp nhận',in_review:'Cán bộ đang xem',escalated:'Đã chuyển trưởng nhóm',answered:'Đã trả lời'};
  const complaintCategories=[['rejection','Bị từ chối'],['limit','Hạn mức bị giảm'],['fees','Lãi và phí'],['debit','Trích nợ'],['data','Dữ liệu cá nhân'],['other','Khác']];
  let local, busy=false, modalOpen=false, returnFocus=null, consentDraft=null, consentBody=null, consentDraftAttempt=false;
  let chatVisible=false;
  const chatEl=document.getElementById('wizard-chat');
  const chat={appId:null,items:[],sending:false,loaded:false,error:''};
  let chatFollow=true, chatScrollTop=0, chatUnread=false, chatRendered='';
  let homeLoanAppId=null, homeLoanExpanded=null;
  const loanChainCache=new Map();
  const CHAT_SUGGEST=['Vì sao hạn mức của tôi là số này?','Doanh thu 12 tháng của tôi thế nào?','Lịch trả góp của tôi thế nào?','Ngân hàng nào cho tôi vay?'];
  let loading='', verifyReview=false, verifyAttempt='', quoteTimer, quoteSerial=0, navigationSerial=0, pollTimer;
  const key = () => state.app?.next_action?.key || 'none';
  const storageKey = () => `bu_seller_wizard:${session.user.id || session.user.email}:${state.app?.id || 'new'}`;
  const canFace=()=>!!window.BU?.face&&session.user?.face_enrolled===true;
  const signMethods=()=>canFace()?['face','otp']:['otp'];
  const signMethod=()=>signMethods().includes(local.signMethod)?local.signMethod:signMethods()[0];
  const personLabel=()=>local.identity?.otp?'Đã xác thực bằng mã OTP':canFace()?'Quét khuôn mặt':'Xác thực bằng mã OTP';
  function freshLocal() { return {key:key(),start:'welcome',tier:2,borrower_type:'individual_business',urls:[state.profile?.store_url || ''],reg_no:'',fallback:false,connect:null,notConnected:'',confirmed:false,confirmIndex:0,identity:{cccd:false,face:false},cccd:{},consentStep:0,boxes:{},signMethod:'face',planStep:0,plan:null,statements:[],answer:null,choice:null}; }
  function restore() {
    local=freshLocal();
    try { const saved=JSON.parse(sessionStorage.getItem(storageKey())); if(saved) local={...local,...saved}; } catch (_) { /* Storage is optional. */ }
    if(local.key!==key()) { local.consentStep=0;local.planStep=0;local.answer=null; }
    local.key=key();
    if(state.app) {
      local.identity={cccd:!!state.app.identity?.cccd,face:!!state.app.identity?.face,...local.identity};
      if(state.app.cccd_scans)local.cccd={...(local.cccd || {}),...state.app.cccd_scans};
      if(!local.plan) local.plan={...(state.app.plan?.submitted ? state.app.plan : state.app.plan?.suggested || {})};
    }
  }
  function save() { local.key=key();try { sessionStorage.setItem(storageKey(),JSON.stringify(local)); } catch (_) { /* Keep progress in memory. */ } }
  function capture() {
    const form=$('wizard-screen').querySelector('form');if(!form)return;
    const fd=new FormData(form),data=Object.fromEntries(fd);
    if(form.dataset.form==='welcome'){local.tier=Number(data.tier || local.tier);local.borrower_type=data.borrower_type || local.borrower_type;}
    if(form.dataset.form==='stores'){local.urls=fd.getAll('store_url');local.reg_no=data.reg_no || '';}
    if(form.dataset.form==='consent-boxes'){local.boxes=Object.fromEntries(scopes.map(x=>[x.key,fd.has(x.key)]));local.signMethod=data.method || local.signMethod;}
    if(form.dataset.form==='statements')local.statements=readStatements(fd);
    if(form.dataset.form==='choice')local.choice=readChoice(fd);
    if(form.dataset.form==='plan-step')local.plan={...local.plan,...data};
    if(form.dataset.form==='answer')local.answer=data;
    if(form.dataset.form==='whatif')local.whatif=data;
    save();
  }
  function notice(message='',error=false) {
    const target=modalOpen ? $('wizard-notice') : $('notice');
    target.hidden=!message;target.textContent=sellerText(message);target.classList.toggle('error',error);
    target.setAttribute('role',error?'alert':'status');
  }
  function title(text, guidance, content) { return `<h1 id="wizard-title" tabindex="-1">${text}</h1><p class="wizard-guidance">${guidance}</p><div class="wizard-content">${content}</div>`; }
  function readStatements(fd) { return fd.getAll('st_month').map((month,i)=>({month,revenue:fd.getAll('st_revenue')[i]})).filter(r=>r.month&&r.revenue!==''); }
  // BuoyUp sets the tenor (the longest of the borrower type) and the method (equal instalments).
  function readChoice(fd) { return {amount:Number(fd.get('amount')),due_day:Number(fd.get('due_day') || 10)}; }
  function welcome() {
    return title('Chào mừng',`Chào ${copy(session.user.display_name)}, cùng xem bạn vay được bao nhiêu.`, `<form data-form="welcome"><p><strong>Bạn vay với tư cách</strong></p><div class="wizard-choices">${borrowerTypes.map(([k,label,caption])=>`<label class="wizard-choice"><input type="radio" name="borrower_type" value="${k}" ${local.borrower_type===k?'checked':''}><span><strong>${label}</strong><small>${caption}</small></span></label>`).join('')}</div><input type="hidden" name="tier" value="2">${submit('Bắt đầu')}</form>`);
  }
  // Step 2 · Kết nối cửa hàng (HANDOVER 16.7). A pasted link proves nothing, so the seller proves the store is theirs:
  // the platform's own sign-in (OAuth, only platforms BuoyUp has an app on), or a code sent to the phone number
  // registered for the store. The code is generated and checked on the server. Never the platform's password.
  const PLATFORM_NAMES={douyin:'Douyin',taobao:'Taobao',tmall:'Tmall',jd:'JD',pinduoduo:'Pinduoduo',kuaishou:'Kuaishou'};
  const platformName=p=>PLATFORM_NAMES[p] || p || '';
  const VERIFIED_LABEL={otp_registered_phone:'Đã xác minh quyền sở hữu qua số điện thoại đăng ký cửa hàng',oauth:'Đã xác minh quyền sở hữu qua đăng nhập sàn'};
  function stores() {
    const oauth=(state.platforms || []).filter(p=>p.oauth);
    const sample=state.demo?button('demo-picker','Dùng gian hàng mẫu'):'';
    const blocked=local.notConnected?`<div class="shop-blocked" role="alert"><p>${copy(local.notConnected)}</p>${sample}</div>`:'';
    return title('Kết nối cửa hàng',local.fallback?'Không đọc được link; bạn có thể nhập số đăng ký kinh doanh của cửa hàng.':'BuoyUp chỉ lập hồ sơ cho cửa hàng bạn chứng minh được là của mình.', `${oauth.length?`<div class="shop-oauth">${oauth.map(p=>button('oauth','Kết nối qua '+esc(p.name || platformName(p.platform)),false,`data-platform="${esc(p.platform)}"`)).join('')}</div><p class="v4-muted">Bạn đăng nhập trên trang của sàn; BuoyUp không bao giờ hỏi mật khẩu tài khoản sàn.</p>`:''}${blocked}<form data-form="stores"><div id="store-links">${field('store_url','Dán link cửa hàng của bạn',local.urls[0] || '','url',`${!local.fallback?'required':''} maxlength="500" placeholder="https://…"`)}</div><div class="wizard-link-actions">${local.notConnected?'':sample}</div><div id="registration-fallback" ${local.fallback?'':'hidden'}>${field('reg_no','Số đăng ký kinh doanh',local.reg_no,'text',`${local.fallback?'required':''} maxlength="40"`)}</div>${submit('Tiếp tục')}</form>`);
  }
  function ownerScreen() {
    const c=local.connect,sh=c.shop || {},sent=!!c.connect_id;
    const preview=`<section class="wizard-store"><h2>${esc(sh.shop_name)}</h2>${facts([['Nền tảng',esc(c.platform_name || platformName(c.platform))],['Chủ thể',esc(sh.subject_masked || 'Chưa có thông tin')],['Đăng ký kinh doanh',esc(sh.reg_no_masked || 'Chưa có thông tin')]])}</section>`;
    if(!sent)return title('Xác nhận bạn là chủ cửa hàng','BuoyUp gửi mã 6 chữ số tới số điện thoại đăng ký của cửa hàng trên sàn. Chỉ chủ cửa hàng nhận được mã này.',`${preview}<div class="wizard-actions">${button('shop-send','Gửi mã tới số đăng ký của cửa hàng '+esc(c.phone_masked),true)}</div>${button('shop-cancel','Không phải cửa hàng của tôi')}`);
    const sms=c.dev_code?`<div class="otp-sms is-new" role="status" aria-live="polite"><div class="otp-sms-head"><span class="otp-sms-icon" aria-hidden="true">✉</span><strong>Tin nhắn</strong><span class="otp-sms-from">BuoyUp</span><span class="otp-sms-time">vừa xong</span></div><p class="otp-sms-body">BuoyUp: Mã xác nhận chủ cửa hàng của bạn là ${esc(c.dev_code)}. Không chia sẻ mã này.</p></div>`:'';
    return title('Xác nhận bạn là chủ cửa hàng','Nhập mã 6 chữ số vừa gửi tới số điện thoại đăng ký của cửa hàng.',`${preview}<p class="shop-sent" role="status">Mã đã gửi tới số điện thoại đăng ký của cửa hàng ${esc(c.phone_masked)}. Nếu đó không phải số của bạn, bạn không phải chủ cửa hàng này.</p>${sms}<form data-form="shop-code">${field('code','Nhập mã 6 chữ số','','text','required pattern="[0-9]{6}" maxlength="6" inputmode="numeric" autocomplete="one-time-code"')}<p class="v4-muted">Mã có hiệu lực trong 5 phút.</p>${submit('Xác nhận mã')}</form><div class="wizard-link-actions">${button('shop-send','Gửi lại mã')}${button('shop-cancel','Không phải cửa hàng của tôi')}</div>`);
  }
  // Demo: an open loan from an earlier sample blocks the next one (one loan at a time); the reset settles it
  // through the same prepay path and leaves an on-chain record (POST /v4/demo/reset-my-loans).
  let demoReset=null;
  function demoPicker() {
    if(demoReset===null){demoReset={needed:false};api('/v4/demo/reset-my-loans').then(r=>{demoReset=r||{needed:false};if(local.picker)renderWizard(false);}).catch(()=>{});}
    const reset=demoReset?.needed?`<div class="demo-reset"><p>Bạn đang có khoản vay mở từ một gian hàng mẫu, nên hồ sơ mẫu mới sẽ bị từ chối (mỗi người một khoản vay).</p>${button('demo-reset','Làm mới khoản vay mẫu',true)}<p class="v4-muted">Tất toán các khoản vay mở từ gian hàng mẫu để chọn gian hàng khác.</p></div>`:'';
    return title('Gian hàng mẫu','Chọn một tình huống để tạo hồ sơ.',`${reset}<div class="wizard-demo-picker">${state.stores.map((s,i)=>button('demo',copy(s.label)+(s.borrower_type_label?`<small class="demo-type">${copy(s.borrower_type_label)}</small>`:''),false,`data-index="${i}"`)).join('')}</div>`);
  }
  function confirmation() {
    const stores=state.app.stores || [],s=stores[local.confirmIndex] || stores[0] || {};
    const proof=VERIFIED_LABEL[s.verified_via || state.app.shop_connection?.verified_via];
    return title('Đây có phải cửa hàng của bạn?','Kiểm tra thông tin trước khi tiếp tục.', `${stores.length>1?`<small>Gian hàng ${local.confirmIndex+1}/${stores.length}</small>`:''}<section class="wizard-store"><h2>${copy(s.entity)}</h2>${proof?`<p class="shop-verified"><span aria-hidden="true">✓</span> ${proof}</p>`:''}${facts([...(s.shop_name?[['Cửa hàng',esc(s.shop_name)]]:[]),['Nền tảng',copy(platformName(s.platform))],['Điểm gian hàng',num(s.rating)],['Đăng ký kinh doanh',copy(s.reg_no)],['Hoạt động từ',day(s.registry?.registered)]])}</section><div class="wizard-actions">${button('confirm-store','Đúng, tiếp tục',true)}</div>${button('wrong-store','Không phải')}`);
  }
  function cccdSide(side,label) {
    const r=local.cccd?.[side],f=r?.fields || {};
    const shown=side==='front'?[['Họ tên',f.name?.value],['Số CCCD',f.id_number?.value?f.id_number.value.slice(0,6)+'••••••••'+f.id_number.value.slice(-4):''],['Ngày sinh',f.birth_date?.value?day(f.birth_date.value):'']]:[['Cơ quan cấp',f.issuing_authority?.value],['Hiệu lực',f.validity_period?.value]];
    return `<div class="cccd-side" data-done="${!!r}"><label class="v4-field">${label}<input type="file" accept="image/jpeg,image/png" data-cccd="${side}" id="cccd-${side}"></label>${r?facts(shown.map(([l,v])=>[l,esc(v || 'Chưa đọc được')]))+(r.warnings?.length?`<p class="v4-muted cccd-warn">Hệ thống sẽ kiểm tra thêm thông tin này.</p>`:''):''}</div>`;
  }
  function identity() {
    // CCCD OCR is switched off (CCCD_OCR_REQUIRED=false): the earlier simulated CCCD tile.
    if(!state.features.cccd_ocr)return title('Xác thực danh tính',canFace()?'Chạm vào từng mục. Quét khuôn mặt mở camera để so với khuôn mặt bạn đã đăng ký.':'Chạm vào từng mục. Bạn xác thực bằng mã OTP gửi qua SMS tới số điện thoại của mình.', `<div class="wizard-tiles">${[['cccd','Chụp CCCD'],['face',personLabel()]].map(([k,label])=>`<button type="button" class="btn wizard-tile" data-action="identity-tile" data-key="${k}" data-done="${!!local.identity[k]}" aria-pressed="${!!local.identity[k]}"><span aria-hidden="true">${local.identity[k]?'✓':'◎'}</span><strong>${label}</strong></button>`).join('')}</div><div class="wizard-actions">${button('identity','Tiếp tục',true,local.identity.cccd&&local.identity.face?'':'disabled')}</div>`);
    const demoCards=state.demo?`<p class="v4-muted">Ảnh CCCD mẫu: <a href="mau-cccd/mat-truoc.png" target="_blank" rel="noopener">mặt trước</a> · <a href="mau-cccd/mat-sau.png" target="_blank" rel="noopener">mặt sau</a>.</p>`:'';
    local.identity.cccd=!!local.cccd?.front;
    return title('Xác thực danh tính',canFace()?'Chụp hai mặt CCCD để BuoyUp đọc thông tin, rồi quét khuôn mặt để xác nhận đúng là bạn. Ảnh CCCD chỉ được đọc, không được lưu lại.':'Chụp hai mặt CCCD để BuoyUp đọc thông tin, rồi xác thực bằng mã OTP gửi qua SMS để xác nhận đúng là bạn. Ảnh CCCD chỉ được đọc, không được lưu lại.', `<div class="cccd-grid">${cccdSide('front','Mặt trước CCCD')}${cccdSide('back','Mặt sau CCCD')}</div>${demoCards}<div class="wizard-tiles">${[['face',personLabel()]].map(([k,label])=>`<button type="button" class="btn wizard-tile" data-action="identity-tile" data-key="${k}" data-done="${!!local.identity[k]}" aria-pressed="${!!local.identity[k]}"><span aria-hidden="true">${local.identity[k]?'✓':'◎'}</span><strong>${label}</strong></button>`).join('')}</div><div class="wizard-actions">${button('identity','Tiếp tục',true,local.cccd?.front&&local.cccd?.back&&local.identity.face?'':'disabled')}</div>`);
  }
  function consent() {
    if(local.consentStep<2) return title('Cho phép BuoyUp kiểm tra hồ sơ','Để xét hạn mức, BuoyUp cần bạn cho phép tra cứu tín dụng, chia sẻ hồ sơ với ngân hàng cho vay và xử lý dữ liệu xác thực. Đọc từng văn bản rồi đánh dấu đồng ý.', `<form data-form="consent-boxes"><div class="wizard-consent-boxes">${scopes.map(x=>`<label class="v4-check"><input type="checkbox" name="${x.key}" ${local.boxes?.[x.key]?'checked':''} required><span><strong>${x.label}</strong><br><small>${x.covers} · <a href="${x.doc}" target="_blank" rel="noopener">Đọc văn bản</a></small></span></label>`).join('')}</div><p><strong>Ký bằng</strong></p><div class="wizard-choices">${signMethods().map(k=>[k,{face:'Khuôn mặt',otp:'Mã OTP gửi về điện thoại'}[k]]).map(([k,l])=>`<label class="wizard-choice"><input type="radio" name="method" value="${k}" ${signMethod()===k?'checked':''}><span>${l}</span></label>`).join('')}</div>${submit('Tiếp tục')}</form>`);
    const d=consentDraft?.document;
    return title('Ký ủy quyền','Kiểm tra và ký bằng '+(signMethod()==='otp'?'mã OTP':'khuôn mặt')+'.', `<ul class="wizard-scope-list">${scopes.map(x=>`<li>${x.label}</li>`).join('')}</ul>${details('Xem chi tiết',`<p>Thời điểm ký: ${esc(d?.signed_at || 'Chưa có thông tin')}<br>Hết hạn: ${esc(d?.expires_at || 'Chưa có thông tin')}</p>`)}${consentDraft?`<form data-form="sign-consent"><label class="v4-check"><input type="checkbox" name="confirm" required><span>Tôi đồng ý cho BuoyUp thực hiện các nội dung trên.</span></label>${submit('Ký')}</form>`:`<div class="wizard-actions">${button('consent-draft','Lấy bản ủy quyền',true)}</div>`}`);
  }
  function plan() {
    const p=local.plan || {},currency=esc(state.app.currency || 'CNY'),unit=currency==='CNY'?'tệ':currency==='VND'?'đồng':currency;
    const screens=[
      ['Bạn nhập hàng cho dịp nào?','Gợi ý đã có sẵn; hãy sửa theo dự định của bạn.',`${field('event','Dịp bán hàng',p.event,'text','required maxlength="40"')}${field('item','Mặt hàng',p.item,'text','required maxlength="120"')}${select('group','Nhóm hàng',groups,p.group)}<div id="group-other" ${p.group==='khác'?'':'hidden'}>${field('group_other','Mô tả mặt hàng khác',p.group_other || '','text','maxlength="120" placeholder="Ví dụ: đồ gia dụng nhà bếp"')}</div>`],
      ['Nhập bao nhiêu?','Điền số lượng và giá nhập dự kiến.',`${field('qty','Số lượng',p.qty,'number','required min="1" max="10000000" step="1"')}${field('price',`Giá nhập mỗi sản phẩm (${unit})`,p.price,'number','required min="0.01" max="1000000" step="0.01"')}`],
      ['Bạn đã có sẵn bao nhiêu?','Điền số tiền theo tình hình hiện tại.',`${field('own_capital',`Vốn tự có (${unit})`,p.own_capital,'number','required min="0" max="1000000000" step="1"')}${field('inventory',`Giá trị tồn kho (${unit})`,p.inventory,'number','required min="0" max="1000000000" step="1"')}${field('other_loans',`Các khoản vay khác (${unit})`,p.other_loans,'number','required min="0" max="1000000000" step="1"')}`]
    ];
    if(local.planStep===3){
      const rows=[...(local.statements || [])];while(rows.length<3)rows.push({month:'',revenue:''});
      const imgs=state.app.statement_images || [];
      return title('Doanh thu và ảnh chụp (tùy chọn)','Nhập doanh thu tối đa 6 tháng gần nhất và tải ảnh chụp trang quản lý cửa hàng. Số khớp với thuế và hiện trên ảnh thì hạn mức có thể cao hơn; bỏ trống cũng được.',`<form data-form="statements">${rows.map(r=>`<div class="v4-grid">${field('st_month','Tháng',r.month,'month','')}${field('st_revenue',`Doanh thu (${unit})`,r.revenue,'number','min="0" max="1000000000" step="1"')}</div>`).join('')}${button('statement-add','+ thêm tháng',false,rows.length>=6?'disabled':'')}
        <div class="statement-images"><label class="v4-field">Ảnh chụp doanh thu (JPEG/PNG, tối đa 6 ảnh)<input type="file" accept="image/jpeg,image/png" multiple data-statement-images id="statement-images" ${imgs.length>=6?'disabled':''}></label>${imgs.length?`<ul class="statement-image-list">${imgs.map((im,i)=>`<li>Ảnh ${i+1}${im.month?' · '+esc(im.month):''} ${button('statement-image-remove','Bỏ',false,`data-id="${esc(im.id)}"`)}</li>`).join('')}</ul>`:''}</div>
        <label class="v4-check"><input type="checkbox" name="declare_images" ${imgs.length||local.statements?.length?'required':''}><span>${DECLARE_IMAGES}</span></label>
        <label class="v4-check declaration"><input type="checkbox" name="declaration" required><span><strong>${DECLARE_ALL}</strong></span></label>${submit('Gửi kế hoạch')}</form>`);
    }
    const screen=screens[local.planStep];return title(screen[0],screen[1],`<form data-form="plan-step">${screen[2]}${submit('Tiếp tục')}</form>`);
  }
  function checklist() {
    const steps=state.app.verification?.steps || [];
    const items=[['Gian hàng',['link']],['Đăng ký kinh doanh',['registry']],['Danh tính',['identity']],['Doanh thu theo thuế',['revenue']],['Tín dụng và điểm liên ngân hàng',['sources']],...(state.app.tier===2?[['Kế hoạch',['plan']]]:[])];
    return title(verifyReview?'Đã xác minh xong':'Đang xác minh',verifyReview?'Đã nhận kết quả; cùng xem bước tiếp theo.':'BuoyUp đang kiểm tra thông tin bạn đã đồng ý.', `<ol class="wizard-checklist">${items.map(([label,keys])=>{const found=steps.filter(s=>keys.includes(s.key));const status=found.some(s=>s.status==='fail')?'fail':found.some(s=>s.status==='warn')?'warn':found.length&&found.every(s=>['ok','skip'].includes(s.status))?'ok':'pending';return `<li data-status="${status}">${label}<small>${status==='ok'?'Đã kiểm tra':status==='pending'?'Đang chờ':'Cần xem xét'}</small></li>`;}).join('')}</ol><div class="wizard-actions">${verifyReview?button('wizard-next','Tiếp tục',true):button('verify','Thử lại',true,busy||!verifyAttempt?'disabled':'')}</div>`);
  }
  function needs(q,choice) { return choice?.needs || (['other_bank','add_store','fix'].includes(choice?.key)?q.needs || []:[]); }
  function answer() {
    const q=state.app.verification?.questions?.[0];
    if(!q) return title('Cần bạn làm rõ','Làm mới để nhận câu hỏi tiếp theo.',`<div class="wizard-actions">${button('refresh','Làm mới',true)}</div>`);
    const saved=local.answer || {},chosen=q.choices.find(c=>c.key===saved.choice),extra=needs(q,chosen);
    return title('Cần bạn làm rõ',copy(q.text), `<form data-form="answer"><div class="wizard-choices">${q.choices.map(c=>`<label class="wizard-choice"><input type="radio" name="choice" value="${esc(c.key)}" ${saved.choice===c.key?'checked':''} required><span>${copy(c.label)}</span></label>`).join('')}</div><div id="answer-extra">${extra.includes('account')?field('bank','Ngân hàng',saved.bank,'text','required maxlength="60"')+field('tail','4 số cuối tài khoản',saved.tail,'text','required pattern="[0-9]{4}" maxlength="4" inputmode="numeric"'):''}${extra.includes('inventory')?field('inventory','Giá trị tồn kho cập nhật',saved.inventory,'number','required min="0" max="1000000000" step="1"'):''}${extra.includes('store_url')?field('store_url','Link gian hàng bổ sung',saved.store_url,'url','required maxlength="500"'):''}</div>${submit('Gửi câu trả lời')}</form>`);
  }
  function costFacts(c,currency) {
    return facts([['Số tiền vay',money(c.amount,currency)],['Lãi suất năm (toàn bộ chi phí)',pct(c.rate)],['Phí',money(0,currency)],['Kỳ hạn',`${num(c.tenor_m)} tháng`],['Hình thức',esc(c.method_label)],['Kỳ trả đầu',`${day(c.first_due_date)} · ${money(c.first_payment,currency)}`],['Tổng lãi dự kiến',money(c.total_interest,currency)],['Tổng phải trả dự kiến',money(c.total_due,currency)],['Tiền vay về',copy(c.payee)]].concat(c.revenue_rate?[['Tỷ lệ doanh thu mỗi tháng',pct(c.revenue_rate)]]:[]));
  }
  function scheduleTable(rows,currency) {
    return `<table class="v4-schedule"><thead><tr><th>Kỳ</th><th>Ngày</th><th>Gốc</th><th>Lãi</th><th>Phải trả</th></tr></thead><tbody>${(rows || []).map(r=>`<tr><td>${num(r.k)}</td><td>${day(r.due_date)}</td><td>${num(r.principal)}</td><td>${num(r.interest ?? r.interest_est)}</td><td>${num(r.payment ?? r.payment_est)}</td></tr>`).join('')}</tbody></table><p class="v4-muted">Số tiền ${currency==='CNY'?'tệ':esc(currency)}; lãi tính theo số ngày thực tế, có thể lệch vài đồng khi giải ngân.</p>`;
  }
  function choose() {
    const o=state.app.offer;if(!o)return title('Đang chuẩn bị','BuoyUp đang hoàn tất hạn mức.',`<div class="wizard-actions">${button('refresh','Làm mới',true)}</div>`);
    const syn=state.app.syndicate || {},ch=local.choice || {amount:o.suggested || o.limit,due_day:10};
    local.choice=ch;
    const q=state.selected,currency=o.currency;
    const banks=(syn.split || []).map(b=>`${esc(b.name)} ${Math.round(b.pct*100)}%`).join(' · ');
    const why=sellerText(o.explanation).split(/(?<=[.!?])\s/)[0] || '';
    // Agent 3's reasons when the limit is smaller than proposed (or the banks changed it): list + buttons.
    const dec=state.app.decision || {},exp=dec.explanation;
    const showExp=dec.kind==='smaller_offer'||(dec.kind==='approve'&&(exp?.because || []).length>0);
    return title('Ngân hàng đã duyệt hạn mức',`Bạn chọn số tiền và ngày trả trong hạn mức này; không cần duyệt lại. Kỳ hạn và hình thức trả do BuoyUp xác định.`,
      `<p class="wizard-amount">Tối đa ${money(o.limit,currency)}</p>${facts([['Ngân hàng cùng cho vay',banks || '—'],['Hạn mức hiệu lực đến',day(o.expires_at)],['Gợi ý vay vừa đủ',money(o.suggested,currency)],['Kỳ hạn',`${num(o.tenor_max)} tháng`],['Hình thức trả','Trả góp hằng tháng (gốc chia đều + lãi)'],['Tiền vay về','Tài khoản WeBank của bạn']])}<p class="wizard-explanation">${esc(why)}</p>${showExp?explainBlock(state.app):''}
      <form data-form="choice"><label class="v4-field">Số tiền muốn vay<input name="amount" id="choice-amount" type="range" min="${esc(o.slider?.min ?? 0)}" max="${esc(o.slider?.max ?? o.limit)}" step="${esc(o.slider?.step ?? 100)}" value="${esc(ch.amount)}"></label><p id="choice-amount-label" class="wizard-amount">${money(ch.amount,currency)}</p>
      ${field('due_day','Ngày trả hằng tháng (1–28)',ch.due_day,'number','required min="1" max="28" step="1"')}
      <div id="choice-quote" role="status">${q?costFacts(q,currency)+details('Lịch trả dự kiến',scheduleTable(q.schedule,currency)):'<p class="v4-muted">Đang tính chi phí…</p>'}</div>
      ${submit('Chọn khoản vay này',state.quotePending||!q?'disabled':'')}</form>${button('human','Tôi muốn gặp cán bộ')}`);
  }
  function contractScreen() {
    const k=state.contract,currency=state.app.currency;
    if(!k)return title('Bảng chi phí và hợp đồng','Đang mở văn bản…','<p role="status">Vui lòng đợi…</p>');
    const left=Math.max(0,Math.ceil(k.read_seconds-(Date.now()-state.contractOpenedAt)/1000));
    return title('Đọc bảng chi phí và hợp đồng',`Vui lòng đọc ít nhất ${num(k.read_seconds)} giây trước khi ký.`,
      `${costFacts({...k,payee:k.payee?.to_supplier?`${num(k.payee.to_account)} vào tài khoản kinh doanh WeBank · ${num(k.payee.to_supplier)} trả thẳng ${k.payee.supplier}`:'Tài khoản kinh doanh WeBank của bạn',first_payment:k.schedule?.[0]?.payment},currency)}
      ${facts([['Lãi phạt khi quá hạn',pct(k.penalty_rate)+' / năm'],['Các ngân hàng',(k.banks || []).map(b=>`${esc(b.name)} ${money(b.amount,currency)}`).join(' · ')],['Khiếu nại',esc(k.complaint_channel)]])}
      <ul class="v4-terms">${(k.terms || []).map(t=>`<li>${esc(t)}</li>`).join('')}</ul>${details('Lịch trả dự kiến',scheduleTable(k.schedule,currency),'open')}
      <form data-form="sign">${field('webank_account','Số tài khoản kinh doanh WeBank (nhận tiền vay và tiền hàng)','','text','required pattern="[0-9]{6,20}" inputmode="numeric"')}
      ${k.needs?.supplier_account?field('supplier_account',`Tài khoản của nhà cung cấp ${copy(k.payee?.supplier)} (phần trả thẳng)`,'','text','required maxlength="40"'):''}
      <label class="v4-check"><input type="checkbox" name="use_of_funds_commitment" required><span>Tôi cam kết dùng vốn cho kinh doanh, không mua chứng khoán, bất động sản hay cho vay lại.</span></label>
      ${k.needs?.guarantee?'<label class="v4-check"><input type="checkbox" name="guarantee" required><span>Người đại diện theo pháp luật bảo lãnh cá nhân cho khoản vay.</span></label>':''}
      <label class="v4-check"><input type="checkbox" name="read_ack" required><span>Tôi đã đọc bảng chi phí và hợp đồng.</span></label>
      <div class="wizard-choices">${signMethods().map(v=>[v,{face:'Ký bằng khuôn mặt',otp:'Ký bằng mã OTP'}[v]]).map(([v,l],i)=>`<label class="wizard-choice"><input type="radio" name="method" value="${v}" ${i?'':'checked'}><span>${l}</span></label>`).join('')}</div>
      <p id="read-timer" class="v4-muted" role="status">${left?`Còn ${left} giây đọc`:'Bạn có thể ký'}</p>${submit('Ký hợp đồng',left?'disabled id="sign-submit"':'id="sign-submit"')}</form>${button('rechoose','Chọn lại khoản vay')}`);
  }
  // SELLER_SERVICES_PLAN §4: what Agent 3 told the seller about the decision: reasons as a list, what she
  // can do as buttons (upload → the assistant with a prepared message; chat; loan).
  const EXPLAIN_DRAFT={invoice:'Tôi muốn bổ sung chứng từ: hóa đơn mua vào hoặc báo giá của xưởng cho lô hàng này.',inventory:'Tôi muốn bổ sung chứng từ: ảnh kho hoặc phiếu nhập cho số tồn kho.'};
  function explainAction(i) {
    const v=i.action?.view,dt=i.action?.data_type;
    if(dt)return button('explain-ask','Bổ sung chứng từ',false,`data-text="${esc(EXPLAIN_DRAFT[dt] || 'Tôi muốn bổ sung chứng từ cho hồ sơ.')}"`);
    if(v==='chat')return button('explain-ask','Hỏi trợ lý',false,`data-text="${esc('Tôi muốn xét lại mức đầy đủ cho hồ sơ này.')}"`);
    if(v==='loan')return button('explain-go','Xem khoản vay',false,'data-view="loan"');
    return '';
  }
  function explainBlock(a,skip='') {
    const e=a?.decision?.explanation,because=(e?.because || []).filter(b=>b.text&&b.text!==skip),improve=e?.improve || [];
    if(!e||(!because.length&&!improve.length))return '';
    return `<section class="decision-explain" aria-label="Vì sao có kết quả này"><h2>${copy(e.headline)}</h2>${because.length?`<p class="explain-label">Vì sao</p><ul class="explain-because">${because.map(b=>`<li>${copy(b.text)}</li>`).join('')}</ul>`:''}${improve.length?`<p class="explain-label">Bạn có thể</p><ul class="explain-improve">${improve.map(i=>{const act=explainAction(i);return `<li class="${act?'has-action':''}"><span>${copy(i.text)}</span>${act}</li>`;}).join('')}</ul>`:''}</section>`;
  }
  function outcome() {
    const a=state.app,k=key(),l=state.loan,currency=l?.currency || a.offer?.currency || a.currency;
    if(k==='view_loan') {
      const payee=l?.payee || a.payee || {};
      const destination=payee.to_supplier?`${num(payee.to_account)} đã vào tài khoản kinh doanh WeBank; ${num(payee.to_supplier)} trả thẳng nhà cung cấp ${copy(payee.supplier)}.`:'Tiền đã vào tài khoản kinh doanh WeBank của bạn.';
      return title('Đã giải ngân!',destination,`<p class="wizard-amount">${money(l?.amount,currency)}</p>${facts([['Kỳ trả đầu tiên',`${day(l?.first_due_date)} · ${money(l?.schedule?.[0]?.payment_est,currency)}`]])}<div class="wizard-actions">${button('view-loan','Xem khoản vay',true)}</div>`);
    }
    if(k==='reapply')return title('Hạn mức đã hết hiệu lực','Hạn mức chỉ có hiệu lực 7 ngày. Bạn có thể nộp hồ sơ mới với dữ liệu cập nhật.',`<div class="wizard-actions">${button('new','Nộp hồ sơ mới',true)}</div>`);
    if(k==='wait_officer')return title('Chờ chút nhé','BuoyUp đang kiểm tra thêm hồ sơ của bạn và sẽ báo ngay khi có kết quả.',`<p>${a.expected_review_at?`Dự kiến có kết quả trước ${day(a.expected_review_at)}.`:'Bạn có thể đóng cửa sổ này; hồ sơ vẫn được lưu.'}</p>${explainBlock(a)}<div class="wizard-actions">${button('complaint-open','Gửi khiếu nại')}${button('refresh','Kiểm tra kết quả',true)}</div>`);
    if(['wait_banks','wait_payout'].includes(k))return title(k==='wait_payout'?'Đang giải ngân':'Các ngân hàng đang duyệt','Bạn có thể đóng và quay lại; hồ sơ vẫn được lưu.',`<p role="status">Đang chờ xác nhận kết quả…</p><div class="wizard-actions">${button('refresh','Kiểm tra kết quả',true)}</div>`);
    const reason=a.decision?.reason || a.verification?.reason,exp=a.decision?.explanation;
    return title(statusNames[a.status] || 'Kết quả hồ sơ',reason?copy(reason.factor):'Hồ sơ cần cán bộ xem.',`${reason?.fix&&!exp?.improve?.length?`<p>${copy(reason.fix)}</p>`:''}${explainBlock(a,reason?.factor)}${a.verification?.eligible_from?`<p>Có thể đủ điều kiện từ ${day(a.verification.eligible_from)}.</p>`:''}${a.status==='rejected'&&state.complaintChannel?`<p class="v4-muted">Không đồng ý với kết quả? Bạn có thể gửi khiếu nại ngay tại đây hoặc qua ${copy(state.complaintChannel)}.</p>`:''}<div class="wizard-actions">${a.status==='rejected'?button('complaint-open','Gửi khiếu nại'):''}${button('wizard-close','Về gian hàng',true)}</div>`);
  }
  function screen() {
    if(loading==='stores')return title('Đang đọc gian hàng','BuoyUp đang lấy thông tin cửa hàng của bạn.','<p role="status">Vui lòng đợi một chút…</p>');
    if(loading==='control')return title('Đang ký và giải ngân','Các ngân hàng chuyển vốn vào tài khoản trung gian tại WeBank, rồi giải ngân cho bạn.','<p role="status">Vui lòng đợi một chút…</p>');
    if(!state.app)return local.start==='welcome'?welcome():local.picker&&state.demo?demoPicker():local.connect?ownerScreen():stores();
    if(key()==='identity'&&!local.confirmed)return confirmation();
    if(verifyReview)return checklist();
    return ({identity,consent,plan,verify:checklist,answer,select:choose,sign:contractScreen})[key()]?.() || outcome();
  }
  function renderWizard(focus=true) {
    if(!modalOpen)return;
    const active=document.activeElement,retain=!focus&&$('wizard-screen').contains?.(active);
    const expanded=!focus?[...$('wizard-screen').querySelectorAll('details[open]')].map(d=>d.querySelector('summary')?.textContent):[];
    // One number per stage, never skipped: waiting and outcome screens stay on the stage they belong to.
    const decided=state.app&&(state.app.offer||state.app.decision);
    const current=loading==='stores'?2:loading==='control'?9:!state.app?(local.start==='welcome'?1:2):verifyReview?6
      :({identity:local.confirmed?3:2,consent:4,plan:5,verify:6,answer:6,wait_banks:6,wait_officer:decided?7:6,select:7,reapply:7,sign:8,wait_payout:9,view_loan:9})[key()]
      || (state.app.status==='out_of_scope'||!decided?6:state.app.loan_id?9:7);
    const STAGES=['','Tư cách vay','Kết nối cửa hàng','Danh tính','Cho phép kiểm tra','Kế hoạch','Xác minh','Hạn mức','Hợp đồng','Giải ngân'];
    const sub=key()==='plan'&&!verifyReview&&state.app?` · ${Math.min(local.planStep,3)+1}/4`:'';
    $('wizard-count').textContent=`Bước ${current}/9 · ${STAGES[current]}${sub}`;$('wizard-progress').value=current;
    $('wizard-back').disabled=!!loading || (state.app&&['verify','wait_banks','wait_payout'].includes(key())&&!verifyReview);
    $('wizard-screen').innerHTML=screen();
    syncChat();
    BU.i18n?.flush?.(); // summaries compared below must be in the displayed language
    if(expanded.length)$('wizard-screen').querySelectorAll('details').forEach(d=>{d.open=expanded.includes(d.querySelector('summary')?.textContent);});
    if(busy)$('wizard-screen').querySelectorAll('.btn-primary').forEach(b=>b.disabled=true);
    $('seller-wizard').setAttribute('aria-busy',String(busy));
    if(focus)$('wizard-title')?.focus({preventScroll:true});
    else if(retain){const match=[...$('wizard-screen').querySelectorAll('[id],input,select,button')].find(n=>active.id?n.id===active.id:active.name?n.name===active.name&&(active.type!=='radio'||n.value===active.value):active.dataset.action&&n.dataset.action===active.dataset.action&&n.dataset.key===active.dataset.key);(match || $('wizard-title'))?.focus({preventScroll:true});}
  }
  // Step 7 onward: the offer on one side, Agent 2's chat (backed by the seller's own data) on the other.
  // From the end of verification onward the chat stays available: beside the wizard (split view)
  // while it is open, then on the seller home once it is closed. One panel, moved, never rebuilt.
  function verified() {const st=state.app?.verification?.state;return !!st&&st!=='IN_PROGRESS';}
  function chatOpen() {return !!state.app&&!loading&&verified()&&(verifyReview||!['identity','consent','plan','verify','answer'].includes(key()));}
  function parkChat() {const body=document.querySelector('#seller-wizard .wizard-body');if(chatEl.parentNode!==body)body.appendChild(chatEl);}
  function syncChat() {
    const on=chatOpen(),slot=$('home-chat-slot');
    if(!modalOpen&&on&&slot){if(chatEl.parentNode!==slot)slot.appendChild(chatEl);}else parkChat();
    $('seller-wizard').classList.toggle('split',modalOpen&&on);chatEl.hidden=!on||(!modalOpen&&!slot);
    $('chat-jump').hidden=!on||!modalOpen||chatVisible;
    if(!on)return;
    if(chat.appId!==state.app.id){chat.appId=state.app.id;chat.items=[];chat.loaded=false;chat.sending=false;chat.error='';chatFollow=true;chatScrollTop=0;chatUnread=false;chatRendered='';$('chat-status').textContent='';renderChat();loadChat();}
    else renderChat();
  }
  async function loadChat() {
    const id=chat.appId;
    try {const data=await api(`/v4/applications/${encodeURIComponent(id)}/messages`);if(chat.appId!==id)return;chat.items=data.items || [];}
    catch(error){if(chat.appId!==id)return;chat.error=error.message;}
    chat.loaded=true;renderChat();
  }
  function chatBubble(m) {
    const me=m.from==='seller',staff=m.from==='officer'||m.from==='admin';
    return `<li class="chat-msg ${me?'from-me':staff?'from-staff':'from-bot'}">${me?'':chatAuthor(staff?'Cán bộ tín dụng':'Trợ lý BuoyUp')}<div class="chat-content">${me?esc(m.text).trim():chatMarkdown(m.text)}</div></li>`;
  }
  function chatAuthor(name='Trợ lý BuoyUp') {return `<div class="chat-author"><span class="chat-avatar" aria-hidden="true"><img src="../src/chung/assets/logo.webp" alt="" /></span><strong>${name}</strong></div>`;}
  // Escape first, then allow only **bold** and simple bullet / numbered lists from the model.
  function chatMarkdown(text) {
    const html=String(text || '').split(/\n/).map(line=>esc(sellerText(line))).join('\n').trim().replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
      .replace(/\s+\*\s+(?=<strong>)/g,'\n* ').replace(/:\s+\*\s+/g,':\n* ').replace(/(:|\.)\s+([1-9])\.\s+(?=<strong>|[A-ZĐÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ])/g,'$1\n$2. ');
    const out=[];let list=null;
    for(const line of html.split(/\n+/)){
      const bullet=/^\s*[*•-]\s+(.*)$/.exec(line),num=/^\s*\d+\.\s+(.*)$/.exec(line),kind=bullet?'ul':num?'ol':null;
      if(kind){if(list?.kind!==kind){list={kind,items:[]};out.push(list);}list.items.push((bullet||num)[1]);}
      else if(line.trim()){list=null;out.push(`<p>${line.trim()}</p>`);}
    }
    return out.map(x=>typeof x==='string'?x:`<${x.kind}>${x.items.map(i=>`<li>${i}</li>`).join('')}</${x.kind}>`).join('');
  }
  function followLatest() {
    const scroll=$('chat-scroll');chatFollow=true;chatUnread=false;
    scroll.scrollTop=scroll.scrollHeight;chatScrollTop=scroll.scrollTop || 0;$('chat-latest').hidden=true;
  }
  function resizeChatInput() {const input=$('chat-input');input.style.height='';input.style.height=Math.min(input.scrollHeight || 44,164)+'px';}
  function renderChat(follow=false) {
    const log=$('chat-log');if(!log)return;
    const name=copy(String(session.user.display_name || '').trim().split(/\s+/).pop() || 'bạn');
    const asked=chat.items.some(m=>m.from==='seller');
    const hello=`<li class="chat-msg from-bot ${asked?'':'chat-welcome'}">${chatAuthor()}<div class="chat-content">${asked?`<p>Chào ${name}, em là trợ lý của BuoyUp. Bạn muốn hỏi gì cứ nhắn em nhé.</p>`:`<h2>Chào ${name}, em có thể giúp gì?</h2><p>Em đã xem hồ sơ, dòng tiền và đề xuất của bạn. Cùng xem khoản vay hoặc lên kế hoạch cho mùa bán hàng nhé.</p>`}</div></li>`;
    const turns=chat.items.filter(m=>m.from!=='system').map(chatBubble).join(''); // pipeline status lines are for staff, not the seller
    const errorMarkup=chat.error?`<li class="chat-msg from-bot is-error">${chatAuthor()}<div class="chat-content"><p>${copy(chat.error)}</p></div></li>`:'';
    const messages=turns+errorMarkup;
    if(chatRendered!==messages&&!chatFollow&&!follow)chatUnread=true;
    chatRendered=messages;
    log.innerHTML=hello+turns+(chat.sending?`<li class="chat-msg from-bot chat-typing">${chatAuthor()}<div class="chat-content"><span class="chat-typing-dots" aria-hidden="true"><i></i><i></i><i></i></span><span class="chat-sr">Trợ lý đang xem thông tin của bạn</span></div></li>`:'')+errorMarkup;
    $('chat-suggest').innerHTML=asked||chat.sending||!chat.loaded?'':CHAT_SUGGEST.map(q=>`<button type="button" data-chat-suggest="${esc(q)}">${esc(q)}</button>`).join('');
    $('chat-send').disabled=chat.sending||!chat.loaded;
    $('chat-input').disabled=chat.sending||!chat.loaded;
    resizeChatInput();
    if(follow||chatFollow)followLatest();
    else {$('chat-scroll').scrollTop=chatScrollTop;$('chat-latest').hidden=!chatUnread;}
  }
  async function sendChat(text) {
    text=String(text || '').trim();if(!text||chat.sending||!chat.loaded||!chat.appId)return;
    const id=chat.appId,before=state.app?.status,refocus=document.activeElement===$('chat-input');
    chat.sending=true;chat.error='';chat.items=[...chat.items,{id:'pending',from:'seller',text}];renderChat(true);
    try {
      const data=await api(`/v4/applications/${encodeURIComponent(id)}/messages`,'POST',{text});
      if(chat.appId!==id)return;
      const known=new Set(chat.items.map(m=>m.id));chat.items=[...chat.items.filter(m=>m.id!=='pending'),...(data.items || []).filter(m=>!known.has(m.id))];
      const answer=(data.items || []).find(m=>m.from!=='seller');if(answer)$('chat-status').textContent='Trợ lý trả lời: '+sellerText(answer.text).replace(/\*\*/g,'');
      // A reply can move the case (e.g. the seller asked for an officer): refresh the left side.
      const a=await api(`/v4/applications/${encodeURIComponent(id)}`);
      if(chat.appId===id&&a.status!==before){await applyApp(a);await refreshList();renderHome();$('chat-input').focus({preventScroll:true});}
    } catch(error) {
      if(chat.appId!==id)return;
      chat.items=chat.items.filter(m=>m.id!=='pending');chat.error=error.status===429?'Bạn gửi hơi nhanh, đợi một phút rồi hỏi tiếp nhé.':error.message;
      $('chat-status').textContent=sellerText(chat.error);
      $('chat-input').value=$('chat-input').value || text;
    } finally {
      if(chat.appId===id){chat.sending=false;renderChat();if(refocus&&document.activeElement===document.body)$('chat-input').focus({preventScroll:true});}
    }
  }
  // Agent 4 after disbursement: notices (a yellow one asks the cause), use-of-funds check, reminders.
  const USE_OF_FUNDS={pending:'Chờ hóa đơn mua hàng từ nhà cung cấp',ok:'Đã thấy hóa đơn mua hàng khớp khoản vay',missing:'Chưa thấy hóa đơn mua hàng; hãy gửi hóa đơn cho BuoyUp',not_applicable:''};
  const urgentNotice = n => ['yellow','red'].includes(n.level)&&n.question&&!n.answer;
  function loanNotice(n) {
    const q=n.question&&!n.answer?`<p class="notice-question"><strong>${copy(n.question.text)}</strong></p><div class="notice-choices" role="group" aria-label="${copy(n.question.text)}">${n.question.choices.map(c=>`<button type="button" class="btn btn-sm" data-action="notice-answer" data-notice="${esc(n.id)}" data-choice="${esc(c.key)}">${copy(c.label)}</button>`).join('')}</div>`:'';
    const a=n.answer?`<p class="notice-answer">Bạn đã trả lời: ${copy(n.answer.label)}</p>`:'';
    return `<li class="loan-notice level-${esc(n.level)}"><small>${day(n.at)}</small><p>${copy(n.text)}</p>${q}${a}</li>`;
  }
  function loanNotices(l) {
    const notices=(l.notices || []).filter(n=>!urgentNotice(n)).slice(0,3).map(loanNotice).join('');
    const uof=USE_OF_FUNDS[l.use_of_funds?.status]||'';
    const reminders=(l.reminders || []).slice(-2).map(r=>`<li>${copy(r.text)}</li>`).join('');
    return (notices?`<h3>Thông báo từ BuoyUp</h3><ul class="loan-notices">${notices}</ul>`:'')
      +(uof?`<p class="loan-uof"><strong>Dùng vốn:</strong> ${esc(uof)}</p>`:'')
      +(reminders?`<h3>Nhắc nhở</h3><ul class="loan-reminders">${reminders}</ul>`:'')
      +(l.monitored_at?`<p class="loan-monitored">BuoyUp tự kiểm tra khoản vay lần gần nhất: ${checkedAt(l.monitored_at)}</p>`:'');
  }
  function checkedAt(v) {const d=new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(v)?v:v+'Z');return isNaN(d)?day(v):d.toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit',year:'numeric'});}
  // Agent 4 works in the background: pick up its new notices once a minute, re-rendering only on change.
  // The notification centre (/v4/me/notices) rides the same poll: its unread count is part of the signature.
  const loanSignature=l=>l?JSON.stringify([l.status,l.outstanding,l.monitored_at,l.clock,l.account?.balance,(l.notices||[]).map(n=>[n.id,!!n.answer])]):'';
  const pollSignature=(l,n)=>loanSignature(l)+'|'+(n?.unread ?? '')+'|'+((n?.items || [])[0]?.id || '');
  async function loadNotices(){try{const d=await api('/v4/me/notices');state.notices={items:d.items || [],unread:Number(d.unread || 0),loaded:true};}catch(_){ /* The badge keeps its last value. */ }return state.notices;}
  setInterval(()=>{
    if(document.hidden||modalOpen||busy)return;
    const id=state.loan?.id;
    Promise.all([id?api(`/v4/loans/${encodeURIComponent(id)}`):Promise.resolve(null),api('/v4/me/notices').catch(()=>null)]).then(([l,n])=>{
      if((id&&state.loan?.id!==id)||modalOpen)return;
      const nextLoan=id?l:state.loan,nextNotices=n?{items:n.items || [],unread:Number(n.unread || 0),loaded:true}:state.notices;
      if(pollSignature(nextLoan,nextNotices)===pollSignature(state.loan,state.notices))return;
      // Do not pull the page from under the seller: wait while they type, focus a control or read an open section.
      const main=$('workspace-main'),active=document.activeElement;
      if(active&&active!==main&&(main.contains(active)||active===$('chat-input')))return;
      if(main.querySelector('details[open]'))return;
      state.loan=nextLoan;state.notices=nextNotices;renderHome();
    }).catch(()=>{});
  },60000);
  function loanChainText(record) {
    if(record?.simulated===true)return 'Giải ngân đã ghi sổ';
    if(record?.simulated!==false)return '';
    const parts=['Giải ngân đã ghi trên chuỗi FISCO BCOS'];
    if(record.block!=null)parts.push(`khối ${esc(record.block)}`);
    if(record.remote?.confirmedNodes!=null&&record.remote?.totalNodes!=null)parts.push(`${esc(record.remote.confirmedNodes)}/${esc(record.remote.totalNodes)} nút xác nhận`);
    try {
      const url=new URL(record.explorer_url);
      if(['https:','http:'].includes(url.protocol))parts.push(`<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">Xem ↗</a>`);
    } catch (_) { /* An absent or invalid explorer URL leaves the confirmation readable. */ }
    return parts.join(' · ');
  }
  function loadLoanChain() {
    const l=state.loan;
    if(!l?.id||!l.withdrawal_id||state.app?.loan_id!==l.id||loanChainCache.has(l.id))return;
    const {id,withdrawal_id}=l;
    // Reserve the loan before fetching, so repeated renders and failures never retry.
    loanChainCache.set(id,'');
    api(`/v4/chain/withdrawals/${encodeURIComponent(withdrawal_id)}`).then(record=>{
      const html=loanChainText(record);loanChainCache.set(id,html);
      if(state.loan?.id!==id||state.loan.withdrawal_id!==withdrawal_id||state.app?.loan_id!==id)return;
      const target=$('home-loan-chain');
      if(target){target.innerHTML=html;target.hidden=!html;}
    }).catch(()=>{});
  }
  // After "chỉ trả tối thiểu" the next period shows the minimum (API next_due.minimum_payment), labelled.
  // A signed amount: "+5.000", "−5.000", and plain "0" (never "−-0" / "+0").
  const signed=(v,cur)=>{const n=Number(v)||0;return `${n>0?'+':n<0?'−':''}${money(Math.abs(n),cur)}`;};
  const nextPay=n=>n?.minimum_payment!=null?n.minimum_payment:n?.payment_est;
  const nextIsMin=n=>n?.minimum_payment!=null;
  const ROW_STATUS={upcoming:'Sắp tới',paid:'Đã trả',minimum:'Đã trả tối thiểu',overdue:'Quá hạn',paid_late:'Trả muộn',prepaid:'Đã trả trước'};
  function homeLoan() {
    const l=state.loan;if(!l)return `<p>Khoản vay đang được chuẩn bị. Hãy kiểm tra lại sau.</p>${button('refresh','Làm mới')}`;
    const c=l.currency,n=l.next_due,open=['active','overdue'].includes(l.status);
    const rows=`<table class="v4-schedule"><thead><tr><th>Kỳ</th><th>Ngày</th><th>Dự kiến</th><th>Trạng thái</th></tr></thead><tbody>${(l.schedule || []).map(r=>`<tr><td>${num(r.k)}</td><td>${day(r.due_date)}</td><td>${num(r.amount_due ?? (r.k===n?.k?nextPay(n):r.payment_est))}</td><td>${esc(ROW_STATUS[r.status] || r.status)}${r.choice==='minimum'&&r.status==='upcoming'?' · tối thiểu':''}</td></tr>`).join('')}</tbody></table>`;
    const actions=open?`<div class="wizard-actions loan-actions">${button('repay','Trả nợ',true,`data-id="${esc(l.id)}"`)}${l.minimum?.allowed?button('loan-minimum',`Kỳ tới chỉ trả tối thiểu ${money(l.minimum.quote?.payment,c)}`):''}${button('loan-prepay',`Trả hết hôm nay ${money(l.prepay_quote?.total,c)}`)}</div>${l.minimum&&!l.minimum.allowed&&l.minimum.why?`<p class="v4-muted">${copy(l.minimum.why)}</p>`:''}`:'';
    return `${facts([['Số tiền vay',money(l.amount,c)],['Dư nợ gốc',money(l.principal_outstanding,c)],['Lãi suất năm',pct(l.rate)],['Hình thức',esc(l.method_label)],['Số dư tài khoản kinh doanh',money(l.account?.balance,c)],['Kỳ tới',n?`${day(n.due_date)} · ${nextIsMin(n)?'tối thiểu':'khoảng'} ${money(nextPay(n),c)}`:'—']].concat(l.owed_now?[['Đang quá hạn',`<strong>${money(l.owed_now,c)}</strong> (${num(l.overdue_days)} ngày)`]]:[]))}
      <p id="home-loan-chain" class="home-loan-chain" ${loanChainCache.get(l.id)?'':'hidden'}>${loanChainCache.get(l.id) || ''}</p>${actions}<h3>Lịch trả</h3>${rows}${loanNotices(l)}<h3>Lịch sử trả nợ</h3>${l.repayments?.length?`<ul class="v4-repayments">${l.repayments.map(r=>`<li>${day(r.detail?.as_of || r.at)} · Đã trả ${money(r.amount,c)}${r.detail?` (lãi phạt ${num(r.detail.penalty)}, lãi ${num(r.detail.interest)}, gốc ${num(r.detail.principal)})`:''}</li>`).join('')}</ul>`:'<p>Chưa có lần trả nợ.</p>'}${l.status==='closed'?`<form data-form="receiving">${field('bank','Ngân hàng nhận tiền hàng mới',l.receiving_account?.bank,'text','required maxlength="60"')}${field('number','Số tài khoản',l.receiving_account?.number,'text','required pattern="[0-9]{6,20}"')}${submit('Đổi tài khoản nhận tiền hàng')}</form>`:''}`;
  }
  function homeLoanPanel() {
    const l=state.loan,urgent=(l?.notices || []).filter(urgentNotice);
    const alerts=urgent.length?`<div class="home-loan-alerts"><h3>BuoyUp cần bạn trả lời</h3><ul class="loan-notices">${urgent.map(loanNotice).join('')}</ul></div>`:'';
    return `<section class="home-loan-panel" aria-label="Khoản vay của bạn">${alerts}<details id="home-loan-details" class="home-loan-details" ${homeLoanExpanded?'open':''}><summary><strong>Khoản vay của bạn</strong>${l?`<span class="home-loan-preview">Đã vay ${money(l.amount,l.currency)}<br>Dư nợ gốc ${money(l.principal_outstanding,l.currency)}</span>`:''}</summary><div class="home-loan-content">${homeLoan()}</div></details></section>`;
  }
  // "Ngân hàng của tôi": the WeBank account, card, balance, money in and out, and every loan.
  let bankFilter='all',bankData=null;
  const MOVE_ICON={in:'↓',loan:'↓',out:'↑',repay:'↻'};
  async function renderMyBank(fetch=true) {
    if(fetch||!bankData)await ensureBank(true);
    if(view==='bank')view='history';
    renderHome();
  }
  // Money in: a small bank-style notification when a new movement appears (polled; works on every screen).
  const SEEN_KEY=`bu_seen_moves:${session.user.id || session.user.email}`;
  let seenMoves=null;
  function toast(m,acc) {
    let box=document.getElementById('bank-toasts');
    if(!box){box=document.createElement('div');box.id='bank-toasts';box.className='bank-toasts';box.setAttribute('aria-live','polite');document.body.appendChild(box);}
    const el=document.createElement('div');el.className=`bank-toast k-${m.kind}`;el.setAttribute('role','status');
    el.innerHTML=`<span class="bank-toast-logo" aria-hidden="true">W</span><div><strong>${m.amount>0?'+':'−'}${money(Math.abs(m.amount),acc?.currency || 'CNY')}</strong><span>${esc(m.label)} · TK ${esc(acc?.number_masked || 'WeBank')}</span>${m.balance_after!=null?`<small>Số dư ${money(m.balance_after,acc?.currency || 'CNY')}</small>`:''}</div><button type="button" aria-label="Đóng thông báo">×</button>`;
    el.querySelector('button').addEventListener('click',()=>el.remove());
    box.appendChild(el);setTimeout(()=>{el.classList.add('is-leaving');setTimeout(()=>el.remove(),400);},7000);
  }
  async function pollMoney() {
    if(document.hidden)return;
    try {
      const d=await api('/v4/me/bank'),ids=d.movements.map(m=>m.id).filter(Boolean);
      if(seenMoves===null){try{seenMoves=new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || 'null') || ids);}catch(_){seenMoves=new Set(ids);}}
      const fresh=d.movements.filter(m=>m.id&&!seenMoves.has(m.id)).reverse();
      fresh.slice(-3).forEach(m=>toast(m,d.account));
      ids.forEach(id=>seenMoves.add(id));
      try{localStorage.setItem(SEEN_KEY,JSON.stringify([...seenMoves].slice(-300)));}catch(_){ /* optional */ }
      if(fresh.length){bankData=d;statsData=null;if(['home','history'].includes(view)&&!busy&&!modalOpen&&!document.getElementById('bu-dialog')?.open)renderHome();
        if(state.loan?.id){const l=await api(`/v4/loans/${encodeURIComponent(state.loan.id)}`);if(view==='home'&&!modalOpen&&!$('workspace-main').contains(document.activeElement)){state.loan=l;renderHome();}else state.loan=l;}}
    } catch(_) { /* The next poll tries again. */ }
  }
  setInterval(pollMoney,15000);setTimeout(pollMoney,1500);
  // A small modal for the repay form and confirmations (one element, filled per use).
  function dialog(html) {
    let d=document.getElementById('bu-dialog');
    if(!d){d=document.createElement('dialog');d.id='bu-dialog';d.className='bu-dialog';d.addEventListener('click',e=>{if(e.target===d)d.close();});document.body.appendChild(d);}
    d.innerHTML=html;if(!d.open)d.showModal();d.querySelector('input,button.btn-primary')?.focus();return d;
  }
  const closeDialog=()=>{const d=document.getElementById('bu-dialog');if(d?.open)d.close();};
  let repayLoan=null;
  function repayDialog(l) {
    repayLoan=l;const c=l.currency,bal=Number(l.account?.balance || 0),total=Number(l.prepay_quote?.total || 0),owed=Number(l.owed_now || 0),next=l.next_due;
    const opts=[];
    if(owed>0)opts.push(['overdue','Trả khoản đang quá hạn',owed,`${num(l.overdue_days)} ngày quá hạn, gồm lãi phạt`]);
    else if(next)opts.push(['next','Trả kỳ tới ngay hôm nay',Math.min(Number(next.payment_est || 0),total),`Kỳ ${day(next.due_date)}; lãi chỉ tính đến hôm nay`]);
    opts.push(['all','Trả hết khoản vay',total,'Tất toán, không mất phí trả trước']);
    const first=opts.find(o=>o[2]<=bal)?.[0] || 'custom';
    dialog(`<form data-form="repay" class="repay-form"><header><h2>Trả nợ</h2><button type="button" class="cf-close" data-action="dialog-close" aria-label="Đóng">×</button></header>
      <div class="repay-source"><span>Trừ từ tài khoản WeBank ${esc(l.account?.number?'•••• '+String(l.account.number).slice(-4):'')}</span><strong>Số dư ${money(bal,c)}</strong></div>
      <div class="repay-options">${opts.map(([k,label,amt,sub])=>`<label class="repay-option ${amt>bal?'is-short':''}"><input type="radio" name="option" value="${k}" ${k===first?'checked':''} ${amt>bal?'disabled':''}><span><strong>${label}</strong><small>${sub}</small></span><b>${money(amt,c)}</b></label>`).join('')}
        <label class="repay-option"><input type="radio" name="option" value="custom" ${first==='custom'?'checked':''}><span><strong>Số tiền khác</strong><small>Trả trước một phần gốc, lãi chỉ tính cho số ngày đã dùng</small></span><input class="repay-custom" name="amount" type="number" min="1" max="${Math.min(bal,total)}" step="1" placeholder="Nhập số tiền" inputmode="numeric"></label></div>
      ${total>bal?`<p class="repay-short">Số dư chưa đủ để trả hết (cần ${money(total,c)}). Tiền hàng từ sàn về tài khoản WeBank sẽ được cộng vào số dư; khoản đến hạn được trích tự động.</p>`:''}
      <div class="wizard-actions"><button type="button" class="btn" data-action="dialog-close">Để sau</button><button type="submit" class="btn btn-primary">Trả nợ</button></div></form>`);
  }
  async function openRepay(loanId) {
    const l=state.loan?.id===loanId?state.loan:await api(`/v4/loans/${encodeURIComponent(loanId)}`);
    repayDialog(l);
  }
  // SELLER_SERVICES_PLAN §3.2: no money leaves the account without this box: the amount, interest and
  // principal from the API's quote, a tick, then the face (when the account has one) or the SMS OTP box.
  let pendingPay=null;
  function prepayRows(l,q,amount) {
    const c=l.currency,total=Number(q.total || 0),part=amount!=null&&amount<total;
    if(part)return [['Số tiền trả',money(amount,c)],['Tính vào',Number(q.overdue || 0)>0?'Khoản quá hạn trước (lãi phạt, lãi, gốc), phần còn lại vào lãi rồi gốc':'Lãi cho số ngày đã dùng trước, phần còn lại trừ vào gốc'],['Lãi đến hôm nay',`${money(q.interest,c)} (${num(q.interest_days)} ngày)`],['Phí trả trước',money(q.fee || 0,c)]];
    return [...(Number(q.overdue || 0)>0?[['Khoản đang quá hạn',money(q.overdue,c)]]:[]),['Lãi đến hôm nay',`${money(q.interest,c)} (${num(q.interest_days)} ngày)`],['Gốc còn lại',money(q.principal,c)],['Phí trả trước',money(q.fee || 0,c)],['Tổng trích',`<strong>${money(total,c)}</strong>`]];
  }
  function minimumConfirm(l) {
    const q=l.minimum?.quote,c=l.currency;if(!q)return;
    payConfirm({kind:'minimum',loan:l,title:`Kỳ ${num(q.k)} chỉ trả tối thiểu`,amount:q.payment,body:{},
      rows:[['Ngày trích',day(q.due_date)],['Lãi kỳ này',money(q.interest,c)],['Gốc kỳ này (tối thiểu)',money(q.principal,c)],['Trả đủ kỳ này sẽ là',money(q.full_payment,c)],['Gốc dời sang các kỳ sau',money(q.deferred,c)]],
      ack:`Tôi hiểu kỳ ${num(q.k)} hệ thống trích ${money(q.payment,c)} vào ngày ${day(q.due_date)}; phần gốc ${money(q.deferred,c)} chia cho các kỳ sau và lãi vẫn tính trên dư nợ gốc còn lại.`});
  }
  function payConfirm(p,message='') {
    pendingPay=p;const c=p.loan.currency,face=canFace(); // no registered face → OTP is the default (and only) way
    const ack=p.ack || `Tôi hiểu ${money(p.amount,c)} sẽ được trích ngay từ tài khoản kinh doanh WeBank và không hoàn lại được.`;
    dialog(`<form data-form="pay-confirm" class="repay-form pay-confirm"><header><h2>${esc(p.title)}</h2><button type="button" class="cf-close" data-action="dialog-close" aria-label="Đóng">×</button></header>
      ${message?`<p class="pay-error" role="alert">${esc(message)}</p>`:''}<div class="pay-amount"><span>${p.kind==='minimum'?'Số tiền kỳ tới':'Số tiền trích'}</span><strong>${money(p.amount,c)}</strong></div>
      ${facts(p.rows)}
      <label class="v4-check"><input type="checkbox" name="ack" required><span>${esc(ack)}</span></label>
      <fieldset class="pay-method"><legend>Xác nhận bằng</legend><div class="wizard-choices">${(face?[['face','Khuôn mặt'],['otp','Mã OTP']]:[['otp','Mã OTP']]).map(([k,l2],i)=>`<label class="wizard-choice"><input type="radio" name="method" value="${k}" ${i?'':'checked'}><span>${l2}</span></label>`).join('')}</div>
      <p class="v4-muted">Chọn mã OTP thì BuoyUp gửi mã 6 chữ số qua SMS tới điện thoại của bạn sau khi bạn bấm xác nhận.</p>${face?'<p class="v4-muted">Chọn khuôn mặt thì camera mở để so với khuôn mặt bạn đã đăng ký; không quét được thì bạn dùng mã OTP.</p>':''}</fieldset>
      <div class="wizard-actions"><button type="button" class="btn" data-action="dialog-close">Để sau</button><button type="submit" class="btn btn-primary">${p.kind==='minimum'?'Xác nhận trả tối thiểu':'Xác nhận trả'}</button></div></form>`);
  }
  // Seller home v6 (17/10/2026): a bank-app home page with feature tiles; each feature is its own page.
  const ICONS={
    home:'<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-5h4v5"/>',
    history:'<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v4h4"/><path d="M12 8v4l3 2"/>',
    repay:'<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/><path d="M15 15h3"/>',
    chat:'<path d="M4 5h16v11H9l-5 4z"/><path d="M8 10h8M8 13h5"/>',
    stats:'<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    reports:'<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5"/><path d="M9 17v-3M12 17v-6M15 17v-4"/>',
    loan:'<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5"/><path d="M12.5 11.5c-.5-.6-1.3-.9-2-.8-1 .1-1.6.7-1.6 1.4 0 1.6 3.6.9 3.6 2.6 0 .8-.8 1.4-1.8 1.4-.8 0-1.5-.3-2-.9M10.5 10v1M10.5 16.2v1"/>',
    schedule:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/><path d="M8 14h2M12 14h2M8 17h2"/>',
    apply:'<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M12 8v8M8 12h8"/>',
    notices:'<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    complaints:'<path d="M4 5h16v11H9l-5 4z"/><path d="M12 8v4M12 14.5v.5"/>',
    account:'<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>',
    support:'<path d="M4 13a8 8 0 0 1 16 0"/><rect x="3" y="13" width="4" height="6" rx="1.5"/><rect x="17" y="13" width="4" height="6" rx="1.5"/><path d="M19 19c0 1.5-2 2.5-5 2.5"/>',
    eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    back:'<path d="M15 5l-7 7 7 7"/>'
  };
  const icon=(k,cls='')=>`<svg class="ico ${cls}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ICONS[k] || ''}</svg>`;
  const PAGES={home:'Trang chủ',history:'Lịch sử giao dịch',loan:'Khoản vay của tôi',schedule:'Lịch trả nợ',stats:'Thống kê',reports:'Báo cáo',chat:'Tư vấn',apply:'Hồ sơ vay',notices:'Thông báo',complaints:'Khiếu nại',account:'Tài khoản & ủy quyền'};
  let statsData=null,hideBalance=(()=>{try{return localStorage.getItem('bu_hide_balance')==='1';}catch(_){return false;}})();
  const openLoan=()=>state.loan&&['active','overdue'].includes(state.loan.status)?state.loan:null;
  // Unread items of the notification centre (badge); questions waiting for an answer (banner).
  function urgentCount(){const l=state.loan;return (l?.notices || []).filter(n=>urgentNotice(n)).length;}
  function noticeCount(){return state.notices.loaded?state.notices.unread:urgentCount();}
  function renderNav() {
    const open=state.complaints.filter(c=>c.status!=='answered').length,nc=noticeCount();
    const badge=n=>n?`<span class="nav-count" aria-label="${n} mục mới">${n}</span>`:'';
    const item=(v,extra='')=>`<button type="button" class="nav-item ${view===v?'is-active':''}" data-action="go" data-view="${v}" ${view===v?'aria-current="page"':''}>${icon(v)}<span>${PAGES[v]}</span>${extra}</button>`;
    $('profile-nav').innerHTML='<nav class="seller-nav" aria-label="Điều hướng">'+['home','history','loan','stats','reports','chat','apply'].map(v=>item(v)).join('')+item('notices',badge(nc))+item('complaints',badge(open))+item('account')+'</nav>';
    $('project-list').innerHTML=button('new','+ Hồ sơ vay mới');
    $('application-nav').innerHTML='';
    let bar=document.getElementById('bottom-nav');
    if(!bar&&typeof document.createElement!=='function')return;
    if(!bar){bar=document.createElement('nav');bar.id='bottom-nav';bar.className='bottom-nav';bar.setAttribute('aria-label','Điều hướng nhanh');document.body.appendChild(bar);}
    const tab=(v,label,action='go')=>`<button type="button" class="${view===v?'is-active':''}" data-action="${action}" data-view="${v}">${icon(v)}<span>${label}</span></button>`;
    bar.innerHTML=tab('home','Trang chủ')+tab('history','Giao dịch')+(openLoan()?`<button type="button" class="bottom-pay" data-action="repay" data-id="${esc(openLoan().id)}">${icon('repay')}<span>Trả nợ</span></button>`:tab('apply','Vay vốn'))+tab('chat','Tư vấn')+tab('account','Tài khoản');
  }
  function go(next) {
    view=next==='bank'?'history':next;
    if(next==='complaints')run(async()=>{await loadComplaints();renderHome();});
    else renderHome();
    if(typeof closeSidebar==='function')closeSidebar();
    $('workspace-main').scrollTop=0;if(typeof window!=='undefined')window.scrollTo?.(0,0);
  }
  const pageHead=(title,sub='',actions='')=>`<div class="page-head"><div>${view!=='home'?`<button type="button" class="page-back" data-action="go" data-view="home">${icon('back')}Trang chủ</button>`:''}<h1>${title}</h1>${sub?`<p class="v4-muted">${sub}</p>`:''}</div>${actions}</div>`;
  async function ensureBank(force=false){if(force||!bankData){try{bankData=await api('/v4/me/bank');}catch(_){bankData=bankData || {account:null,loans:[],movements:[],totals:{}};}}return bankData;}
  function moveRows(moves,cur){return moves.map(m=>`<li class="bank-move k-${esc(m.kind)}"><span class="bank-move-icon" aria-hidden="true">${MOVE_ICON[m.kind] || '•'}</span><span class="bank-move-main"><strong>${esc(m.label)}</strong><small>${m.at?checkedAt(m.at):day(m.on)}</small></span><span class="bank-move-amt"><strong>${m.amount>0?'+':'−'}${money(Math.abs(m.amount),cur)}</strong>${m.balance_after!=null?`<small>Số dư ${num(m.balance_after)}</small>`:''}</span></li>`).join('');}
  const masked=v=>hideBalance?'••••••':v;
  // --- pages -------------------------------------------------------------------------------------
  function renderDashboard() {
    const d=bankData,acc=d?.account,cur=acc?.currency || state.loan?.currency || 'CNY',l=openLoan();
    const unfinished=state.items.find(a=>!['disbursed','repaying','closed','rejected','out_of_scope','expired','withdrawn'].includes(a.status));
    const nc=noticeCount(),uc=urgentCount(),openC=state.complaints.filter(c=>c.status!=='answered').length;
    const next=l?.next_due;
    const banners=[l?.owed_now?`<div class="dash-banner is-danger"><span>Khoản vay đang quá hạn <strong>${money(l.owed_now,cur)}</strong> (${num(l.overdue_days)} ngày).</span>${button('repay','Trả ngay',true,`data-id="${esc(l.id)}"`)}</div>`:'',
      uc?`<div class="dash-banner"><span>BuoyUp cần bạn trả lời ${uc} câu hỏi về khoản vay.</span>${button('go','Xem thông báo',false,'data-view="notices"')}</div>`:'',
      unfinished?`<div class="dash-banner"><span>Hồ sơ ${esc(unfinished.code || '')} · ${esc(statusNames[unfinished.status] || '')}: tiếp tục để hoàn tất.</span>${button('open','Tiếp tục hồ sơ',true,`data-id="${esc(unfinished.id)}"`)}</div>`:'',
      d?.open_limit&&!unfinished?`<div class="dash-banner"><span>Hạn mức <strong>${money(d.open_limit.limit,cur)}</strong> đang chờ bạn đến ${day(d.open_limit.expires_at)}.</span>${button('open','Chọn số tiền',true,`data-id="${esc(d.open_limit.application_id)}"`)}</div>`:''].join('');
    const tiles=[['history','Lịch sử giao dịch',`${num((d?.movements || []).length)} giao dịch`],['repay','Trả nợ',l?(next?`Kỳ tới ${day(next.due_date)}`:'Trả trước hạn'):'Chưa có khoản vay'],['chat','Tư vấn','Trợ lý BuoyUp'],['stats','Thống kê','Biến động của bạn'],['reports','Báo cáo',reportsData.items.length?`${num(reportsData.items.length)} báo cáo`:'Tháng, quý, năm'],
      ['loan','Khoản vay',l?money(l.principal_outstanding,cur)+' dư nợ':'Chưa có'],['schedule','Lịch trả nợ',l?`${num((l.schedule || []).filter(r=>r.status==='upcoming').length)} kỳ còn lại`:'—'],['apply','Vay vốn','Hồ sơ và hạn mức'],['notices','Thông báo',nc?`${nc} chưa đọc`:'Đã đọc hết'],
      ['complaints','Khiếu nại',openC?`${openC} đang xử lý`:'Gửi phản ánh'],['account','Tài khoản','Ủy quyền, bảo mật'],['support','Hỗ trợ','Tổng đài, cán bộ']];
    const tileHtml=tiles.map(([k,label,sub])=>{const disabled=k==='repay'&&!l;const action=k==='repay'?`data-action="repay" data-id="${esc(l?.id || '')}"`:k==='support'?'data-action="support"':`data-action="go" data-view="${k}"`;const badge=(k==='notices'&&nc)||(k==='complaints'&&openC)?`<span class="tile-badge">${k==='notices'?nc:openC}</span>`:'';return `<button type="button" class="dash-tile t-${k}" ${action} ${disabled?'disabled':''}><span class="tile-ico">${icon(k)}${badge}</span><strong>${label}</strong><small>${esc(sub)}</small></button>`;}).join('');
    const recent=(d?.movements || []).slice(0,5);
    $('workspace-main').innerHTML=`<div class="v4-wrap dash"><section class="dash-hero"><div class="dash-greet"><p class="v4-muted">Xin chào,</p><h1>${copy(session.user.display_name)}</h1></div>
      <div class="dash-top">${acc?`<section class="bank-card"><div class="bank-card-top"><span>WeBank</span><span>${esc(acc.card?.kind || 'Tài khoản kinh doanh')}</span></div><p class="bank-card-number">${esc(acc.card?.masked || acc.number_masked)}</p><div class="bank-card-balance"><span>Số dư khả dụng <button type="button" class="eye" data-action="toggle-balance" aria-label="${hideBalance?'Hiện':'Ẩn'} số dư" aria-pressed="${hideBalance}">${icon('eye')}</button></span><strong>${masked(money(acc.balance,cur))}</strong></div></section>`
        :`<section class="bank-card is-empty"><div class="bank-card-top"><span>WeBank</span></div><p class="bank-card-number">•••• •••• •••• ••••</p><p class="bank-card-note">Tài khoản kinh doanh WeBank hiện ở đây khi khoản vay đầu tiên được giải ngân.</p></section>`}
      <div class="dash-summary"><div class="dash-stat"><span>Dư nợ gốc</span><strong>${masked(money(d?.totals?.outstanding || 0,cur))}</strong></div><div class="dash-stat"><span>Kỳ trả tới</span><strong>${next?masked(money(nextPay(next),cur)):'—'}</strong>${next?`<small>${day(next.due_date)}${nextIsMin(next)?' · tối thiểu':''}</small>`:''}</div><div class="dash-stat"><span>Tiền hàng về tháng này</span><strong>${masked(money(d?.totals?.month_in || 0,cur))}</strong>${d?.totals?.coverage?.share!=null?`<small class="dash-coverage" title="So với doanh thu ${d.totals.coverage.basis==='tax'?'theo tờ khai thuế':'dự báo trong hồ sơ vay'}">≈ ${Math.round(d.totals.coverage.share*100)} % doanh thu của bạn</small>`:''}</div></div></div></section>
      ${banners?`<div class="dash-banners">${banners}</div>`:''}
      <section class="dash-tiles" aria-label="Chức năng">${tileHtml}</section>
      <section class="v4-panel dash-recent"><div class="panel-head"><h2>Giao dịch gần đây</h2>${recent.length?button('go','Xem tất cả',false,'data-view="history"'):''}</div>${recent.length?`<ul class="bank-moves">${moveRows(recent,cur)}</ul>`:'<p class="v4-muted">Chưa có giao dịch. Tiền vay và tiền hàng về tài khoản WeBank sẽ hiện ở đây.</p>'}</section></div>`;
    if(!d)ensureBank().then(()=>{if(view==='home'&&!modalOpen)renderHome();});
    if(!reportsData.loaded)loadReports().then(()=>{if(view==='home'&&!modalOpen&&reportsData.items.length)renderHome();});
  }
  function renderHistory() {
    const d=bankData,cur=d?.account?.currency || 'CNY';
    const moves=(d?.movements || []).filter(m=>bankFilter==='all'||(bankFilter==='in'?m.amount>0:m.amount<0));
    const groups=[];for(const m of moves){const k=m.on;let g=groups.find(x=>x.k===k);if(!g)groups.push(g={k,items:[]});g.items.push(m);}
    const sum=s=>moves.filter(s).reduce((a,m)=>a+m.amount,0);
    $('workspace-main').innerHTML=`<div class="v4-wrap page-narrow">${pageHead('Lịch sử giao dịch',d?.account?`Tài khoản kinh doanh WeBank ${esc(d.account.number_masked)}`:'',button('my-bank-refresh','Làm mới'))}
      <div class="history-tools"><div class="bank-filters" role="group" aria-label="Lọc giao dịch">${[['all','Tất cả'],['in','Tiền vào'],['out','Tiền ra']].map(([k,l])=>`<button type="button" class="chip ${bankFilter===k?'is-active':''}" data-action="bank-filter" data-filter="${k}" aria-pressed="${bankFilter===k}">${l}</button>`).join('')}</div><div class="history-sum"><span>Vào <strong class="pos">${signed(sum(m=>m.amount>0),cur)}</strong></span><span>Ra <strong>${signed(sum(m=>m.amount<0),cur)}</strong></span></div></div>
      <section class="v4-panel">${groups.length?groups.map(g=>`<h3 class="history-day">${day(g.k)}</h3><ul class="bank-moves">${moveRows(g.items,cur)}</ul>`).join(''):'<p class="v4-muted">Chưa có giao dịch.</p>'}</section></div>`;
    if(!d)ensureBank().then(()=>{if(view==='history')renderHome();});
  }
  function renderLoanPage() {
    const l=state.loan;
    $('workspace-main').innerHTML=`<div class="v4-wrap page-narrow">${pageHead('Khoản vay của tôi',l?`Khoản vay ${money(l.amount,l.currency)} · lãi ${pct(l.rate)}/năm`:'')}
      <section class="v4-panel home-loan-content">${l?homeLoan():`<p>Bạn chưa có khoản vay nào.</p>${button('go','Vay vốn',true,'data-view="apply"')}`}</section></div>`;
    loadLoanChain();
  }
  function renderSchedule() {
    const l=state.loan,c=l?.currency || 'CNY',rows=l?.schedule || [];
    const nextK=rows.find(r=>r.status==='upcoming')?.k;
    const chart=rows.length&&BU.charts?chartSlot('sched',(w,h)=>BU.charts.bars({width:w,height:h,label:'Số tiền mỗi kỳ trả',name:'Phải trả',fmt:v=>money(v,c),bars:rows.map(r=>({label:'Kỳ '+r.k,value:Number(r.amount_due ?? r.payment_est ?? 0),kind:r.k===nextK?'next':r.status==='upcoming'?'todo':'done'}))})):'';
    $('workspace-main').innerHTML=`<div class="v4-wrap page-narrow">${pageHead('Lịch trả nợ',l?`Trả góp hằng tháng vào ngày ${num(l.due_day)}; tiền được trích từ tài khoản WeBank.`:'',openLoan()?button('repay','Trả nợ',true,`data-id="${esc(l.id)}"`):'')}
      ${l?`<section class="v4-panel chart-card"><div class="panel-head"><h2>Số tiền mỗi kỳ</h2><span class="v4-muted chart-legend"><i class="lg-focal"></i>Kỳ tới <i class="lg-done"></i>Đã trả <i class="lg-todo"></i>Sắp tới</span></div>${chart}</section>
      <section class="v4-panel"><table class="v4-schedule"><thead><tr><th>Kỳ</th><th>Ngày</th><th>Gốc</th><th>Lãi dự kiến</th><th>Phải trả</th><th>Trạng thái</th></tr></thead><tbody>${rows.map(r=>`<tr class="${r.k===nextK?'is-next':''}"><td>${num(r.k)}</td><td>${day(r.due_date)}</td><td>${num(r.principal)}</td><td>${num(r.interest_est ?? r.interest)}</td><td><strong>${num(r.amount_due ?? r.payment_est)}</strong></td><td>${esc(ROW_STATUS[r.status] || r.status)}</td></tr>`).join('')}</tbody></table></section>`
        :`<section class="v4-panel"><p>Chưa có lịch trả nợ.</p></section>`}</div>`;
  }
  // Charts render after layout, at each slot's real width, and again when the window is resized.
  const chartFns={};
  function chartSlot(id,fn){chartFns[id]=fn;return `<div class="chart-slot" data-chart="${id}"></div>`;}
  function drawCharts(){
    if(typeof document==='undefined'||!document.querySelectorAll||!window.BU?.charts)return;
    document.querySelectorAll('.chart-slot').forEach(el=>{const f=chartFns[el.dataset.chart];if(f)el.innerHTML=f(el.clientWidth || 640,el.clientHeight || 240);if(window.BU.charts.attach)window.BU.charts.attach(el);});
  }
  let chartTimer=null;
  if(typeof window!=='undefined'&&window.addEventListener)window.addEventListener('resize',()=>{clearTimeout(chartTimer);chartTimer=setTimeout(drawCharts,150);});
  // Thống kê (18/10/2026): the four charts and the KPIs on one frame from /v4/me/stats: the same 12 months
  // (chart 1 revenue, chart 2 goods, chart 4 money in/out) ending with the current month, and the end-of-day
  // balance of one month (chart 3, ‹ › to switch). Money sits on its business day, never on the clock time.
  let statsMonth=null;
  function loadStats(month){statsMonth=month || null;return api('/v4/me/stats'+(month?`?month=${encodeURIComponent(month)}`:'')).then(x=>{statsData=x;if(view==='stats')renderHome();}).catch(e=>notice(e.message,true));}
  function renderStats() {
    const s=statsData,cur=s?.currency || 'CNY';
    if(!s){$('workspace-main').innerHTML=`<div class="v4-wrap">${pageHead('Thống kê')}<p class="v4-muted" role="status">Đang tải số liệu…</p></div>`;
      loadStats(statsMonth);return;}
    const C=BU.charts,rev=s.revenue_12m || [],ml=v=>{const [y,m]=String(v).split('-');return `${m}/${y}`;};
    const dm=v=>{const p=String(v).split('-');return `${p[2]}/${p[1]}`;};
    // Month axis: the month number, the year under the first month and under January ("11 / 2025", "12", "1 / 2026").
    const mx=(list)=>list.map((v,i)=>{const [y,m]=String(v).split('-');return `${Number(m)}`+(i===0||m==='01'?`\n${y}`:'');});
    const narrow=typeof window!=='undefined'&&window.innerWidth<520;
    const wbAll=s.webank_by_month || [],wb=narrow?wbAll.slice(-6):wbAll,goods=s.goods || [],k=s.kpi || {},bd=s.balance_daily,gp=s.goods_period;
    const hasRev=rev.some(r=>r.estimate!=null);
    const signed=(v,sign)=>`${sign}${money(v,cur)}`;
    // Chart 1: revenue by month (tax filing, else the forecast in the loan file) with the sales money that reached WeBank.
    const anyEst=rev.some(r=>r.basis==='forecast'),anyWb=rev.some(r=>r.webank_in!=null);
    const revChart=hasRev&&chartSlot('rev',(w,h)=>C.combo({width:w,height:h,label:'Doanh thu 12 tháng và tiền hàng về WeBank',fmt:v=>money(v,cur),labels:mx(rev.map(r=>r.month)),tips:rev.map(r=>'Tháng '+ml(r.month)),
      bars:{name:'Theo tờ khai thuế',values:rev.map(r=>r.estimate),kinds:rev.map(r=>r.basis==='tax'?'tax':r.basis==='forecast'?'est':'tax'),kindNames:{tax:'Theo tờ khai thuế',est:'Doanh thu ước tính'}},
      line:anyWb?{name:'Tiền hàng về WeBank',values:rev.map(r=>r.webank_in)}:null,
      more:rev.map(r=>[r.share!=null&&r.estimate?{n:'Độ phủ WeBank',t:pct(r.share)}:null])}));
    // Chart 2: revenue per item over the same 12 months.
    const period=gp?`${ml(gp.from)}–${ml(gp.to)}`:'';
    const goodsChart=goods.length&&chartSlot('goods',(w,h)=>C.hbars({width:w,height:h,label:'Doanh thu theo mặt hàng, 12 tháng',name:'Doanh thu ước tính',fmt:v=>money(v,cur),rows:goods.map(g=>({label:g.item,value:g.revenue_est,note:`${C.short(g.revenue_est)} · ${pct(g.share)}`,noteShort:pct(g.share)}))}));
    // Chart 3: end-of-day balance for each day of the month shown.
    const days=bd?.days || [],nDays=bd?.days_in_month || 0,dues=bd?.dues || [];
    const vals=Array.from({length:nDays},(_,i)=>days[i]?.balance ?? null);
    const dueAt=Object.fromEntries(dues.map(d=>[Number(d.date.slice(8)),d]));
    const balChart=bd&&days.some(d=>d.balance!=null)&&chartSlot('bal',(w,h)=>C.line({width:w,height:h,label:'Số dư cuối ngày, tháng '+ml(bd.month),fmt:v=>money(v,cur),
      labels:Array.from({length:nDays},(_,i)=>String(i+1)),xTicks:[0,4,9,14,19,24,29].filter(i=>i<nDays),
      tips:Array.from({length:nDays},(_,i)=>`${String(i+1).padStart(2,'0')}/${bd.month.slice(5)}/${bd.month.slice(0,4)}`),
      series:[{name:'Số dư cuối ngày',values:vals,focal:true}],annotate:null,
      marks:dues.map(d=>({i:Number(d.date.slice(8))-1,label:`Kỳ ${d.k}`})),
      more:Array.from({length:nDays},(_,i)=>{const d=days[i];if(!d)return [];const due=dueAt[i+1];return [d.loan?{n:'Giải ngân',t:signed(d.loan,'+')}:null,d.in?{n:'Tiền hàng về',t:signed(d.in,'+')}:null,d.topup?{n:'Nạp thêm',t:signed(d.topup,'+')}:null,d.out?{n:'Chi kinh doanh',t:signed(d.out,'−')}:null,d.repay?{n:'Trích trả nợ',t:signed(d.repay,'−')}:null,due?{n:`Đến hạn kỳ ${due.k}`,t:money(due.amount,cur)}:null];})}));
    // Chart 4: the same months as chart 1 (the last 6 on a phone): sales money, repayments, business spending.
    const flows=wb.length&&wb.some(w2=>w2.in||w2.repay||w2.out||w2.loan)&&chartSlot('flows',(w,h)=>C.grouped({width:w,height:h,label:'Tiền vào và trả nợ theo tháng',names:['Tiền hàng về','Trả nợ','Chi kinh doanh'],fmt:v=>money(v,cur),
      tips:wb.map(w2=>'Tháng '+ml(w2.month)),groups:(()=>{const l=mx(wb.map(w2=>w2.month));return wb.map((w2,i)=>({label:l[i],values:[w2.in,w2.repay,w2.out]}));})(),more:wb.map(w2=>[w2.loan?{n:'Giải ngân',t:money(w2.loan,cur)}:null])}));
    // KPIs and insights: the same month (the current one) everywhere.
    const kr=k.revenue,kin=k.webank_in,kb=k.balance,top=k.top_item || goods[0],curM=k.month || s.window?.to;
    const revRow=kr?rev.find(r=>r.month===kr.month):null;
    const basisTxt=b=>b==='tax'?'theo tờ khai thuế':b==='forecast'?'ước tính theo dự báo hồ sơ vay':'tiền hàng về WeBank';
    const kpi=(label,value,delta='')=>`<div class="kpi-card"><span>${label}</span><strong>${value}</strong>${delta}</div>`;
    const delta=v=>v==null?'':`<small class="${v>=0?'up':'down'}">${v>=0?'▲':'▼'} ${pct(Math.abs(v))} so tháng trước</small>`;
    const note=t=>`<small class="kpi-note">${t}</small>`;
    const curWb=wbAll.find(w2=>w2.month===curM) || {};
    const card=(title,insight,chart,legend='')=>chart?`<section class="v4-panel chart-card"><div class="chart-head"><h2>${title}</h2>${legend}</div><p class="chart-insight">${insight}</p>${chart}</section>`:'';
    const revIns=kr?`Tháng ${ml(kr.month)}: <strong>${money(kr.amount,cur)}</strong> · ${kr.basis==='forecast'?'ước tính':basisTxt(kr.basis)}`+(revRow?.webank_in!=null?` · về WeBank ${money(revRow.webank_in,cur)}`+(revRow.share!=null?` (${pct(revRow.share)})`:''):''):'';
    const revLegend=`<span class="chart-legend"><i class="lg-todo"></i>Theo tờ khai thuế${anyEst?' <i class="lg-est"></i>Ước tính (chưa có tờ khai)':''}${anyWb?' <i class="lg-line"></i>Tiền hàng về WeBank':''}</span>`;
    const low=days.filter(d=>d.balance!=null).reduce((b,d)=>!b||d.balance<b.balance?d:b,null),lastDay=[...days].reverse().find(d=>d.balance!=null);
    const nextDue=dues.find(d=>d.status!=='paid'&&d.status!=='paid_late') || dues[0];
    const balIns=lastDay?`Cuối ngày ${dm(lastDay.date)}: <strong>${money(lastDay.balance,cur)}</strong>`+(low&&low.date!==lastDay.date?` · thấp nhất ${money(low.balance,cur)} (${dm(low.date)})`:'')+(nextDue?` · kỳ ${nextDue.k} ngày ${dm(nextDue.date)}`:''):'';
    const nav=bd?`<span class="month-nav"><button type="button" class="btn-month" data-action="stats-month" data-month="${esc(bd.prev || '')}" aria-label="Tháng trước" title="Tháng trước" ${bd.prev?'':'disabled'}>‹</button><strong>Tháng ${ml(bd.month)}</strong><button type="button" class="btn-month" data-action="stats-month" data-month="${esc(bd.next || '')}" aria-label="Tháng sau" title="Tháng sau" ${bd.next?'':'disabled'}>›</button></span>`:'';
    const balTools=`<span class="chart-tools">${dues.length?'<span class="chart-legend"><i class="lg-due"></i>Ngày đến hạn</span>':''}${nav}</span>`;
    const flowIns=curWb.month?`Tháng ${ml(curWb.month)}: tiền hàng về <strong>${money(curWb.in || 0,cur)}</strong> · trả nợ ${money(curWb.repay || 0,cur)} · chi ${money(curWb.out || 0,cur)}`:'';
    $('workspace-main').classList.add('has-stats');
    $('workspace-main').innerHTML=`<div class="v4-wrap stats stats-fit">
      <div class="stats-head"><button type="button" class="page-back" data-action="go" data-view="home">${icon('back')}Trang chủ</button><h1>Thống kê</h1><span class="v4-muted">${s.window?`12 tháng ${ml(s.window.from)}–${ml(s.window.to)} · doanh thu, mặt hàng và dòng tiền qua tài khoản WeBank`:'Doanh thu, mặt hàng và dòng tiền qua tài khoản WeBank'}</span><span class="cf-spacer"></span>${button('stats-refresh','Làm mới')}</div>
      <div class="kpi-row">${kpi(kr?`Doanh thu tháng ${ml(kr.month)}`:'Doanh thu tháng',kr?money(kr.amount,cur):'—',kr?(kr.change!=null?delta(kr.change):note(basisTxt(kr.basis))):'')}${kpi('Mặt hàng chủ lực',top?copy(top.item):'—',top?note(`${pct(top.share)} doanh thu 12 tháng`):'')}${kpi(`Tiền hàng về tháng ${ml(curM || '')}`,money(kin?kin.amount:0,cur),revRow&&revRow.month===curM&&revRow.share!=null?note(`${pct(revRow.share)} doanh thu tháng`):'')}${kpi(kb?`Số dư cuối ngày ${dm(kb.on)}`:'Số dư cuối ngày',kb?money(kb.amount,cur):'—')}</div>
      ${!hasRev&&!balChart?'<section class="v4-panel"><p>Chưa có đủ số liệu. Thống kê hiện khi hồ sơ được xác minh và khoản vay có giao dịch.</p></section>':`<div class="chart-grid">${card('Doanh thu 12 tháng',revIns,revChart,revLegend)}
      ${card('Doanh thu theo mặt hàng',top?`<strong>${copy(top.item)}</strong> nhiều nhất · ước tính theo hóa đơn nhập hàng${period?` · ${period}`:''}`:'',goodsChart)}
      ${card('Tiền vào và trả nợ theo tháng',flowIns,flows,'<span class="chart-legend"><i class="lg-focal"></i>Tiền hàng về <i class="lg-todo"></i>Trả nợ <i class="lg-third"></i>Chi kinh doanh</span>')}
      ${bd?`<section class="v4-panel chart-card"><div class="chart-head"><h2>Số dư tài khoản WeBank</h2>${balTools}</div><p class="chart-insight">${balIns || 'Chưa có giao dịch trong tháng này.'}</p>${balChart || '<div class="chart-slot"></div>'}</section>`:''}</div>`}</div>`;
    drawCharts();
  }
  // Agent 5's reports (SELLER_SERVICES_PLAN §6.5): month, quarter, year, closing, registration reminder.
  async function loadReports(){reportsAt=Date.now();try{const d=await api('/v4/me/reports');reportsData={items:d.items || [],loaded:true};}catch(_){reportsData.loaded=true;}return reportsData;}
  const GROUP_SHORT={goods:'Hàng hóa',platform:'Phí sàn',marketing:'Tiếp thị',logistics:'Vận chuyển',staff:'Nhân sự',tax:'Thuế, phí'};
  const REPORT_KIND={month:'Tháng',quarter:'Quý',year:'Năm',closing:'Tất toán',registration:'Nhắc đăng ký'};
  function renderReports() {
    if(reportId)return renderReport(reportId);
    const items=reportsData.items;
    $('workspace-main').innerHTML=`<div class="v4-wrap page-narrow">${pageHead('Báo cáo','Báo cáo kinh doanh BuoyUp lập cho bạn từ tài khoản WeBank: hằng tháng, hằng quý, cuối năm và khi tất toán khoản vay.')}
      <section class="v4-panel">${!reportsData.loaded?'<p class="v4-muted" role="status">Đang tải báo cáo…</p>':items.length?`<ul class="report-list">${items.map(r=>`<li><button type="button" class="report-row ${r.read_at?'':'is-unread'}" data-action="open-report" data-id="${esc(r.id)}"><span class="report-kind k-${esc(r.kind)}">${esc(REPORT_KIND[r.kind] || r.kind)}</span><span class="report-row-main"><strong>${copy(r.title)}</strong><small>${copy(String(r.summary || '').slice(0,160))}</small></span><span class="report-row-date">${day(r.at)}</span></button></li>`).join('')}</ul>`:'<p class="v4-muted">Chưa có báo cáo. Báo cáo tháng đầu tiên có vào ngày 1 tháng sau khi giải ngân.</p>'}</section></div>`;
    // Fresh list on each visit (at most every 20 s): a new report may have been made since.
    if(Date.now()-reportsAt>20000){const before=JSON.stringify(items.map(i=>[i.id,i.read_at]));loadReports().then(d=>{if(view==='reports'&&!reportId&&JSON.stringify(d.items.map(i=>[i.id,i.read_at]))!==before)renderHome();});}
  }
  function reportFigures(r,cur) {
    const d=r.data || {},s=d.sales || {},c=d.cash || {},e=d.expenses || {};
    const card=(label,value,sub='')=>`<div class="kpi-card"><span>${label}</span><strong>${value}</strong>${sub?`<small>${sub}</small>`:''}</div>`;
    if(r.kind==='registration')return card('Doanh thu từ đầu năm',money(d.ytd,cur),d.ytd_basis==='tax'?'theo tờ khai thuế':'ước tính')+card('Ngưỡng phải đăng ký',money(d.threshold,cur),'mỗi năm')+card('Hạn mức sau khi đăng ký',money(d.type_cap?.individual_business,cur),`thay vì ${money(d.type_cap?.individual,cur)}`);
    const sold=s.basis==='tax'?card('Bán được',money(s.estimate,cur),'theo tờ khai thuế'):card('Tiền hàng về WeBank',money(s.webank_in,cur),s.tax_revenue?`tờ khai thuế ${money(s.tax_revenue,cur)}`:'BuoyUp thấy được');
    return sold+card('Chi kinh doanh',money(e.total || 0,cur),e.platform_fee?`gồm phí sàn ước tính ${money(e.platform_fee,cur)}`:'')+card('Còn lại cuối kỳ',money(c.closing || 0,cur),c.lowest_on&&c.lowest<c.closing?`thấp nhất ${money(c.lowest,cur)} (${day(c.lowest_on)})`:'');
  }
  function renderReport(id) {
    const r=reportCache[id];
    if(!r){$('workspace-main').innerHTML=`<div class="v4-wrap page-narrow">${pageHead('Báo cáo')}<p class="v4-muted" role="status">Đang tải báo cáo…</p></div>`;
      api(`/v4/me/reports/${encodeURIComponent(id)}`).then(x=>{reportCache[id]=x;const it=reportsData.items.find(i=>i.id===id);if(it)it.read_at=x.read_at;loadNotices().then(()=>renderNav());if(view==='reports'&&reportId===id)renderHome();}).catch(e=>{reportId=null;notice(e.message,true);if(view==='reports')renderHome();});return;}
    const d=r.data || {},cur=d.currency || 'CNY',C=BU.charts,mm=v=>{const [y,m]=String(v).split('-');return `${Number(m)}/${String(y).slice(2)}`;};
    const groups=((d.expenses || {}).groups || []).slice().sort((a,b)=>b.amount-a.amount);
    const spend=groups.some(g=>g.amount>0)?chartSlot('rep-exp',(w,h)=>C.hbars({width:w,height:h,label:'Chi theo nhóm',name:'Đã chi',fmt:v=>money(v,cur),rows:groups.map(g=>({label:GROUP_SHORT[g.key] || g.label,value:g.amount,note:`${C.short(g.amount)} · ${pct(g.share)}`,noteShort:C.short(g.amount)}))})):'';
    const bm=d.by_month || [];
    const flows=bm.length>1?chartSlot('rep-flow',(w,h)=>C.grouped({width:w,height:h,label:'Tiền vào, trả nợ và chi theo tháng',names:['Tiền vào','Trả nợ','Chi'],fmt:v=>money(v,cur),tips:bm.map(b2=>'Tháng '+mm(b2.month)),groups:bm.map(b2=>({label:mm(b2.month),values:[b2.in+b2.loan_in,b2.repay,b2.out]}))})):'';
    const panel=(title,body,cls='')=>body?`<section class="v4-panel ${cls}"><h2>${title}</h2>${body}</section>`:'';
    const list=xs=>(xs || []).length?`<ul class="report-notes">${xs.map(x=>`<li>${copy(x)}</li>`).join('')}</ul>`:'';
    const ls=d.loan_summary,ba=d.before_after,st=d.store,tr=d.trend?.revenue;
    const facts=rows=>`<dl class="v4-facts">${rows.filter(Boolean).map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl>`;
    const loanBox=ls?facts([['Số vay',money(ls.amount,cur)],['Số ngày vay',ls.days!=null?num(ls.days)+' ngày':'—'],['Tổng lãi thật',money(ls.total_interest,cur)],ls.total_penalty?['Lãi phạt',money(ls.total_penalty,cur)]:null,['Trễ hạn',ls.late_instalments?`${num(ls.late_instalments)} kỳ, lâu nhất ${num(ls.max_overdue_days)} ngày`:'Không trễ kỳ nào']]):'';
    const baBox=ba&&ba.before?facts([['Doanh thu 3 tháng trước giải ngân',ba.before.revenue!=null?money(ba.before.revenue,cur):'chưa có tờ khai'],['Doanh thu 3 tháng sau',ba.after.revenue!=null?money(ba.after.revenue,cur):'chưa có tờ khai'],['Tiền hàng về WeBank 3 tháng sau',money(ba.after.webank_in,cur)]]):'';
    const qBox=r.kind==='quarter'?facts([['Xu hướng doanh thu',tr?.direction?`${tr.direction} ${pct(Math.abs(tr.change || 0))}`:copy(tr?.unavailable || 'Chưa có')],['Tiền đủ chi khoảng',d.runway_months==='∞'?'Không có khoản chi':`${String(d.runway_months).replace('.',',')} tháng`],['Đánh giá cửa hàng',st?.unavailable?copy(st.unavailable):st?.rating?.from!=null?`${st.rating.from} → ${st.rating.to}`:'chưa có'],['Tỷ lệ hoàn hàng',st?.unavailable?'—':st?.returns?.from!=null?`${pct(st.returns.from)} → ${pct(st.returns.to)}`:'chưa có']]):'';
    const cites=r.kind==='registration'&&(d.citations || []).length?`<ul class="report-notes">${(d.citations || []).map(c=>`<li><strong>${esc(c.law)}</strong>: <span lang="zh">${esc(c.quote)}</span></li>`).join('')}</ul>`:'';
    $('workspace-main').classList.add('has-report');
    $('workspace-main').innerHTML=`<div class="v4-wrap page-narrow report-page">${pageHead(copy(r.title),`Lập ngày ${day(r.at)} · số liệu từ tài khoản WeBank`,`<div class="report-actions">${button('report-list','Tất cả báo cáo')}${button('report-print','In',true)}</div>`)}
      ${d.notes?.[0]&&r.kind!=='registration'?`<p class="report-coverage">${copy(d.notes[0])}</p>`:''}
      <div class="kpi-row report-kpis">${reportFigures(r,cur)}</div>
      <section class="v4-panel report-summary"><h2>Tóm tắt</h2><p>${copy(d.summary)}</p>${list(d.flags)}</section>
      ${spend?`<section class="v4-panel chart-card"><div class="chart-head"><h2>Chi theo nhóm</h2></div><p class="chart-insight">Tổng <strong>${money(d.expenses.total,cur)}</strong>${d.expenses.unclassified?` · chưa phân loại ${money(d.expenses.unclassified,cur)}`:''}</p>${spend}</section>`:''}
      ${flows?`<section class="v4-panel chart-card"><div class="chart-head"><h2>Tiền vào, trả nợ, chi theo tháng</h2><span class="v4-muted chart-legend"><i class="lg-focal"></i>Tiền vào <i class="lg-todo"></i>Trả nợ <i class="lg-third"></i>Chi</span></div>${flows}</section>`:''}
      ${panel('Cửa hàng trong quý',qBox)}${panel('Khoản vay',loanBox)}${panel('Trước và sau khi vay',baBox+(ba?.note?`<p class="v4-muted">${copy(ba.note)}</p>`:''))}
      ${d.next_time?.text?panel('Lần vay sau',`<p>${copy(d.next_time.text)}</p>`):''}
      ${panel('Căn cứ pháp lý',cites)}
      ${panel('Ghi chú',list(r.kind==='registration'?d.notes:(d.notes || []).slice(1)))}
      <p class="v4-muted report-foot">${r.chain_tx?'Báo cáo đã được lưu vết trên chuỗi khối BuoyUp; số liệu do hệ thống tính, không do mô hình ngôn ngữ tự đặt.':''}</p></div>`;
  }
  function renderApply() {
    const apps=state.items;
    $('workspace-main').innerHTML=`<div class="v4-wrap page-narrow">${pageHead('Hồ sơ vay','Các hồ sơ vay vốn của bạn với BuoyUp.',button('new','+ Hồ sơ vay mới',true))}
      ${apps.length?`<ul class="apply-list">${apps.map(a=>`<li class="apply-card"><div><strong>${copy(a.store_entity || 'Gian hàng của bạn')}</strong><small>${esc(a.code || '')} · cập nhật ${day(a.updated_at)}</small></div><span class="apply-status s-${esc(a.status)}">${esc(statusNames[a.status] || a.status)}</span><div class="apply-actions">${a.amount_offered?`<span class="v4-muted">Hạn mức ${money(a.amount_offered,'CNY')}</span>`:''}${button('open',['disbursed','repaying','closed'].includes(a.status)?'Xem':'Mở',false,`data-id="${esc(a.id)}"`)}${a.deletable?button('delete-app','Xóa',false,`data-id="${esc(a.id)}"`):''}</div></li>`).join('')}</ul>`
        :`<section class="v4-panel"><h2>Vốn cho mùa bán hàng</h2><p>Cùng xem bạn có thể vay bao nhiêu.</p>${button('new','Bắt đầu',true)}</section>`}</div>`;
  }
  // Notification centre (SELLER_SERVICES_PLAN §3.1): loan notices, case notices and reports in one list.
  const NOTICE_GO={loan:['loan','Xem khoản vay'],chat:['chat','Hỏi trợ lý'],apply:['apply','Xem hồ sơ']};
  function noticeItem(n) {
    const unread=!n.read_at,act=n.action || null;
    const q=n.question&&!n.answer?`<p class="notice-question"><strong>${copy(n.question.text)}</strong></p><div class="notice-choices" role="group" aria-label="${copy(n.question.text)}">${(n.question.choices || []).map(c=>`<button type="button" class="btn btn-sm" data-action="notice-answer" data-loan="${esc(n.loan_id || '')}" data-notice="${esc(n.id)}" data-choice="${esc(c.key)}">${copy(c.label)}</button>`).join('')}</div>`:'';
    const a=n.answer?`<p class="notice-answer">Bạn đã trả lời: ${copy(n.answer.label)}</p>`:'';
    const go=act?.view==='apply'&&act.id?button('open','Mở hồ sơ',false,`data-id="${esc(act.id)}"`):act?.view==='report'&&act.id?button('open-report','Xem báo cáo',false,`data-id="${esc(act.id)}"`):NOTICE_GO[act?.view]?button('go',NOTICE_GO[act.view][1],false,`data-view="${NOTICE_GO[act.view][0]}"`):'';
    return `<li class="loan-notice notice-item level-${esc(n.level)} ${unread?'is-unread':''}">${unread?'<span class="notice-dot" role="img" aria-label="Chưa đọc"></span>':''}<div class="notice-body"><div class="notice-head"><strong>${copy(n.title)}</strong><small>${day(n.at)}</small></div><p>${copy(n.text)}</p>${q}${a}${go?`<div class="notice-actions">${go}</div>`:''}</div></li>`;
  }
  function paintNotices() {
    const items=state.notices.items,rem=state.loan?.reminders || [];
    $('workspace-main').innerHTML=`<div class="v4-wrap page-narrow">${pageHead('Thông báo','Tin từ BuoyUp về hồ sơ, khoản vay, nhắc hạn, báo cáo và câu hỏi cần bạn trả lời.',items.some(n=>!n.read_at)?button('notices-read-all','Đánh dấu đã đọc'):'')}
      <section class="v4-panel">${!state.notices.loaded?'<p class="v4-muted" role="status">Đang tải thông báo…</p>':items.length?`<ul class="loan-notices notice-list">${items.map(noticeItem).join('')}</ul>`:'<p class="v4-muted">Chưa có thông báo.</p>'}</section>
      ${rem.length?`<section class="v4-panel"><h2>Nhắc nhở</h2><ul class="loan-reminders">${rem.slice().reverse().map(r=>`<li><small>${day(r.at)}</small> ${copy(r.text)}</li>`).join('')}</ul></section>`:''}</div>`;
  }
  let noticesOpened=0;
  function renderNotices() {
    paintNotices();
    // Opening the page fetches the latest list, then marks what is shown as read (the dots stay until next visit).
    const serial=++noticesOpened;
    loadNotices().then(async n=>{
      if(serial!==noticesOpened||view!=='notices')return;
      paintNotices();
      const ids=n.items.filter(x=>!x.read_at).map(x=>x.id);
      if(!ids.length)return;
      try{const r=await api('/v4/me/notices/read','POST',{ids});state.notices.unread=Number(r.unread || 0);renderNav();}catch(_){ /* Read marks are retried next visit. */ }
    });
  }
  function renderAccount() {
    const a=state.app,c=a?.consent,u=session.user,acc=bankData?.account;
    const consent=c?`<dl class="v4-facts">${[['Mã ủy quyền',esc(c.id)],['Ký lúc',day(c.signed_at)],['Hết hạn',day(c.expires_at)],['Trạng thái',c.revoked_at?'Đã rút':'Đang hiệu lực']].map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl><ul class="consent-scopes">${(c.scopes || []).map(s=>{const k=typeof s==='string'?s:s?.key,m=scopes.find(x=>x.key===k);return `<li>${copy(m?.label || s?.label || k || '')}</li>`;}).join('')}</ul>${!c.revoked_at?`<p class="v4-muted">Rút ủy quyền thì BuoyUp ngừng tra cứu dữ liệu của bạn; hồ sơ chưa giải ngân sẽ không đi tiếp được.</p>${button('consent-revoke','Rút ủy quyền',false,`data-id="${esc(a.id)}"`)}`:''}`:'<p class="v4-muted">Chưa có ủy quyền nào.</p>';
    $('workspace-main').innerHTML=`<div class="v4-wrap page-narrow">${pageHead('Tài khoản & ủy quyền')}
      <section class="v4-panel"><h2>Thông tin</h2><dl class="v4-facts">${[['Họ tên',copy(u.display_name)],['Email',esc(u.email)],['Điện thoại',esc(u.phone || '—')],['Tài khoản nhận tiền',acc?`WeBank ${esc(acc.number_masked)}`:'—']].map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl></section>
      <section class="v4-panel"><h2>Ủy quyền dữ liệu${a?` · ${esc(a.code || '')}`:''}</h2>${consent}</section>
      <section class="v4-panel"><h2>Bảo mật</h2><p>Đăng nhập bằng mật khẩu hoặc khuôn mặt; xác nhận giao dịch quan trọng bằng khuôn mặt hoặc mã OTP.</p><div class="wizard-actions account-actions">${button('theme','Đổi giao diện sáng / tối')}${button('logout-now','Đăng xuất')}</div></section></div>`;
  }
  function renderChatPage() {
    const a=state.app,on=chatOpen();
    if(!on){$('workspace-main').innerHTML=`<div class="v4-wrap page-narrow">${pageHead('Tư vấn')}<section class="v4-panel"><p>Trợ lý BuoyUp sẵn sàng khi hồ sơ của bạn đã được xác minh. Trợ lý trả lời về hạn mức, doanh thu, lịch trả và các ngân hàng cho vay.</p>${a?button('resume','Tiếp tục hồ sơ',true):button('new','Bắt đầu hồ sơ vay',true)}</section></div>`;return;}
    const l=state.loan,urgent=(l?.notices || []).filter(urgentNotice).length;
    const chip=l?`<span class="cf-chip"><strong>${money(l.principal_outstanding,l.currency)}</strong> dư nợ${l.next_due?` · kỳ tới ${day(l.next_due.due_date)} · ${money(nextPay(l.next_due),l.currency)}${nextIsMin(l.next_due)?' (tối thiểu)':''}`:''}</span>`
      :`<span class="cf-chip"><strong>${esc(statusNames[a.status] || 'Hồ sơ')}</strong> · ${copy(a.stores?.[0]?.entity || '')}</span>`;
    const side=l?`<div class="home-loan-content">${urgent?`<div class="home-loan-alerts"><h3>BuoyUp cần bạn trả lời</h3><ul class="loan-notices">${(l.notices || []).filter(urgentNotice).map(loanNotice).join('')}</ul></div>`:''}${homeLoan()}</div>`
      :`<p>${copy(statusNames[a.status] || '')}</p>${button('resume',key()==='none'?'Xem kết quả':'Tiếp tục hồ sơ',true)}`;
    $('workspace-main').classList.add('has-home-chat');
    $('workspace-main').innerHTML=`<div class="chat-first ${loanDrawer?'drawer-open':''}"><div class="cf-bar"><button type="button" class="page-back" data-action="go" data-view="home">${icon('back')}Trang chủ</button>${chip}${urgent?`<button type="button" class="cf-alert" data-action="loan-drawer">${urgent} việc cần trả lời</button>`:''}<span class="cf-spacer"></span>${openLoan()?button('repay','Trả nợ',true,`data-id="${esc(l.id)}"`):''}${!l?button('resume',key()==='none'?'Xem kết quả':'Mở hồ sơ'):''}<button type="button" class="btn cf-toggle" data-action="loan-drawer" aria-expanded="${loanDrawer}" aria-controls="loan-drawer">${l?'Khoản vay':'Hồ sơ'} ${loanDrawer?'›':'‹'}</button></div><div class="cf-body"><div id="home-chat-slot" class="cf-chat"></div><aside id="loan-drawer" class="cf-drawer" ${loanDrawer?'':'hidden'} aria-label="Khoản vay của bạn"><div class="cf-drawer-head"><h2>${l?'Khoản vay của bạn':'Hồ sơ của bạn'}</h2><button type="button" class="cf-close" data-action="loan-drawer" aria-label="Đóng">×</button></div>${side}</aside></div></div>`;
    loadLoanChain();
  }
  function renderHome() {
    parkChat();
    renderNav();
    $('workspace-main').classList.remove('has-home-chat','has-stats','has-report');
    const pages={home:renderDashboard,history:renderHistory,loan:renderLoanPage,schedule:renderSchedule,stats:renderStats,reports:renderReports,chat:renderChatPage,apply:renderApply,notices:renderNotices,complaints:renderComplaints,account:renderAccount};
    (pages[view] || renderDashboard)();
    drawCharts();
    document.title=`${PAGES[view] || 'Trang chủ'} · BuoyUp`;
    BU.motion.init($('workspace-main'));
    if(!modalOpen)syncChat();
    loadLoanChain(); // the disbursement's chain confirmation, fetched once per loan (shown on the loan page)
  }
  const COMPLAINT_STEPS=[['acknowledged','Đã tiếp nhận'],['in_review','Cán bộ đang xem'],['answered','Đã trả lời']];
  function complaintCard(c) {
    const reached=c.status==='answered'?2:['in_review','escalated'].includes(c.status)?1:0;
    const reason=c.reasons?.reason,codes=c.reasons?.reason_codes || [];
    return `<article class="complaint-card ${c.overdue?'is-overdue':''}"><header><div><strong>${esc(c.id)}</strong> · ${esc(c.category_label)}${c.application_id?` · <span class="v4-muted">${esc((state.items.find(a=>a.id===c.application_id)||{}).store_entity || 'Hồ sơ')}</span>`:''}</div><span class="complaint-status s-${esc(c.status)}">${esc(complaintStatus[c.status] || c.status)}</span></header>
      <ol class="complaint-steps">${COMPLAINT_STEPS.map(([k,l],i)=>`<li class="${i<=reached?'done':''}">${l}</li>`).join('')}</ol>
      <p class="complaint-text">“${esc(c.text)}”</p>
      ${reason?`<div class="complaint-reason"><small>Lý do đã ghi của quyết định</small><p>${copy(reason.factor)}</p>${reason.fix?`<p class="v4-muted">${copy(reason.fix)}</p>`:''}${codes.length?`<ul>${codes.map(r=>`<li>${copy(r.text)}</li>`).join('')}</ul>`:''}</div>`:''}
      ${c.answer?`<div class="complaint-answer"><small>Trả lời của BuoyUp · ${esc(c.outcome_label || '')}</small><p>${esc(c.answer)}</p></div>`
        :`<p class="complaint-due">Trả lời trước <strong>${day(c.answer_due)}</strong>${c.extension_note?` · đã gia hạn: ${copy(c.extension_note)}`:''}${c.overdue?' · <strong>quá hạn, đã chuyển trưởng nhóm</strong>':''}</p>`}
      <footer class="v4-muted">Gửi ${day(c.created_at)} · kênh ${esc({app:'ứng dụng',hotline:'tổng đài',email:'email'}[c.channel] || c.channel)}</footer></article>`;
  }
  function renderComplaints() {
    renderNav();parkChat();
    $('workspace-main').classList.remove('has-home-chat');
    const apps=state.items || [],pre=complaintPrefill || state.app?.id || '';
    const def=(apps.find(a=>a.id===pre)||{}).status==='rejected'?'rejection':state.loan?'debit':'other';
    const list=state.complaints;
    $('workspace-main').innerHTML=`<div class="v4-wrap complaints-page"><div class="page-head"><div><button type="button" class="page-back" data-action="go" data-view="home">${icon('back')}Trang chủ</button><h1>Khiếu nại</h1><p class="v4-muted">Không đồng ý với một quyết định, khoản phí hay lần trích nợ? Gửi cho BuoyUp tại đây. Lý do đã ghi trong hồ sơ được đính kèm tự động; người xem xét là cán bộ khác người đã quyết định.</p></div><ul class="sla-chips"><li><strong>≤ 1 ngày</strong> làm việc · xác nhận</li><li><strong>≤ 5 ngày</strong> làm việc · trả lời có lý do</li>${state.complaintChannel?`<li>${copy(state.complaintChannel)}</li>`:''}</ul></div>
      <div class="complaints-grid"><section class="v4-panel complaint-form"><h2>Gửi khiếu nại mới</h2><form data-form="complaint">
        <label class="v4-field">Về việc<select name="category">${complaintCategories.map(([k,l])=>`<option value="${k}" ${k===def?'selected':''}>${l}</option>`).join('')}</select></label>
        <label class="v4-field">Hồ sơ liên quan<select name="application_id"><option value="">Không gắn hồ sơ</option>${apps.map(a=>`<option value="${esc(a.id)}" ${a.id===pre?'selected':''}>${esc(a.code || a.id)} · ${copy(a.store_entity || '')} · ${esc(statusNames[a.status] || a.status)}</option>`).join('')}</select></label>
        <label class="v4-field">Bạn muốn BuoyUp xem lại điều gì?<textarea name="text" rows="5" required minlength="5" maxlength="2000" placeholder="Mô tả ngắn: chuyện gì xảy ra, bạn mong muốn gì"></textarea></label>
        <div class="wizard-actions"><button class="btn btn-primary" type="submit">Gửi khiếu nại</button></div></form></section>
      <section class="complaint-list-col"><h2>Khiếu nại của bạn ${list.length?`<span class="v4-muted">(${list.length})</span>`:''}</h2>${list.length?list.map(complaintCard).join(''):'<div class="v4-panel empty-note"><p>Bạn chưa gửi khiếu nại nào.</p></div>'}</section></div></div>`;
  }
  function complaintsPanel() {
    if(!state.complaints.length)return '';
    return `<section class="v4-panel complaints-panel"><h2>Khiếu nại của bạn</h2><ul class="complaint-list">${state.complaints.map(c=>`<li><strong>${esc(c.id)} · ${esc(c.category_label)}</strong><span class="bu-badge">${esc(complaintStatus[c.status] || c.status)}</span><p>${c.answer?copy(c.answer):`Trả lời trước ${day(c.answer_due)}${c.extension_note?` (gia hạn: ${copy(c.extension_note)})`:''}`}</p></li>`).join('')}</ul></section>`;
  }
  function showWizard() {
    returnFocus=document.activeElement;closeSidebar();modalOpen=true;notice('');
    if(!$('seller-wizard').open)$('seller-wizard').showModal();renderWizard();pump();
  }
  // Closing the wizard returns to the home page (bank-app home, 17/10/2026).
  function closeWizard() {capture();modalOpen=false;complaintOpen=false;quoteSerial++;state.quotePending=false;clearTimeout(quoteTimer);clearTimeout(pollTimer);$('seller-wizard').close();bankData=null;statsData=null;renderHome();const target=returnFocus?.isConnected?returnFocus:$('workspace-main');target?.focus({preventScroll:true});}
  async function refreshList() {const data=await api('/v4/applications');state.items=data.items || [];await loadComplaints();}
  async function loadComplaints() {try{const c=await api('/v4/complaints');state.complaints=c.items || [];state.complaintChannel=c.channel || '';}catch(_) { /* The list stays as it was. */ }}
  async function applyApp(a,restoreDraft=false) {
    const previous=key();state.app=a;state.quotePending=false;if(previous!==key()||state.selected?.appId!==a.id)state.selected=null;state.contract=null;
    if(restoreDraft)restore();else if(previous!==key()){local.key=key();local.consentStep=0;local.planStep=0;local.answer=null;consentDraft=null;consentBody=null;consentDraftAttempt=false;}
    if(!Object.keys(local.plan || {}).length && a.plan)local.plan={...(a.plan.suggested || a.plan)};
    state.loan=a.loan_id?await api(`/v4/loans/${encodeURIComponent(a.loan_id)}`):null;
    save();renderHome();renderWizard();
  }
  async function open(id,show=true) {
    view='home';
    const serial=++navigationSerial;quoteSerial++;clearTimeout(quoteTimer);clearTimeout(pollTimer);consentDraft=null;consentBody=null;consentDraftAttempt=false;verifyReview=false;verifyAttempt='';
    const a=await api(`/v4/applications/${encodeURIComponent(id)}`);if(serial!==navigationSerial)return;
    await applyApp(a,true);if(show)showWizard();
  }
  // Verification can take long when the model server is slow. If the request times out, or another one for this
  // file is still running (409 VERIFY_IN_PROGRESS / 503 BUSY), wait for the result instead of showing an error.
  async function verifyAndWait() {
    try {await mutate('/verify');return;}
    catch(error) {if(!['NETWORK','VERIFY_IN_PROGRESS','BUSY'].includes(error.code))throw error;}
    notice('BuoyUp vẫn đang xác minh hồ sơ của bạn, vui lòng đợi…');
    for(let i=0;i<60;i++){
      await new Promise(r=>setTimeout(r,3000));
      let a;try{a=await api(appPath());}catch(_){continue;}
      if(!['consented','verifying'].includes(a.status)){await applyApp(a);await refreshList();notice('');renderHome();renderWizard();return;}
    }
    throw new Error('Xác minh đang lâu hơn bình thường. Bạn có thể đóng cửa sổ này; kết quả sẽ có trong mục Thông báo.');
  }
  async function mutate(tail,body={},method='POST') {const a=await api(appPath(tail),method,body);await applyApp(a?.id&&a?.next_action?a:await api(appPath()));await refreshList();renderHome();renderWizard();}
  async function run(fn,control) {
    if(busy)return;busy=true;if(control)control.disabled=true;
    $('workspace-main').setAttribute('aria-busy','true');$('seller-wizard').setAttribute('aria-busy','true');notice('');
    try {await fn();}
    catch(error) {
      if(error.details?.fallback==='reg_no'){local.fallback=true;save();}
      if(error.details?.field==='face_verify_id'&&key()==='identity'){local.identity.face=false;local.identity.otp=null;local.faceVerifyId=null;save();}
      if(error.code==='INVALID_STATE'&&state.app){try{await applyApp(await api(appPath()));}catch(_) { /* Keep the original error. */ }}
      loading='';renderWizard(false);notice(error.message,true);
    } finally {busy=false;loading='';$('workspace-main').removeAttribute('aria-busy');$('seller-wizard').setAttribute('aria-busy','false');if(control?.isConnected)control.disabled=false;renderWizard(false);pump();}
  }
  // Identity step: the camera re-checks the face registered at sign-up (1:1 + turn challenge). An account
  // without a registered face, a server without the face model, no camera, a failed scan or "Dùng mã OTP
  // thay thế" goes through the SMS OTP box instead (otp-sms.js).
  async function identityCheck() {
    if(busy)return;busy=true;notice('');
    try {
      const who=await confirmPerson('identity',canFace()?'face':'otp');
      local.faceVerifyId=who.face_verify_id || null;local.identity.otp=who.method==='otp'?{phone:who.otp_phone}:null;local.identity.face=true;
    } catch(error) {
      if(error.code!=='CANCELLED')notice(error.message,true);
    } finally {busy=false;save();renderWizard(false);}
  }
  // Face or SMS OTP right before the identity step, a consent or a contract signature and a payment.
  // "Khuôn mặt" is offered only to an account with a registered face; a face that cannot be checked falls
  // through to the OTP box. TODO(SMS): the code is checked in the browser until an SMS provider is wired.
  const OTP_TEXT={identity:'Nhận mã 6 chữ số qua SMS để xác nhận đúng là bạn ở bước xác thực danh tính.',consent:'Nhận mã 6 chữ số qua SMS để ký ủy quyền.',sign:'Nhận mã 6 chữ số qua SMS để ký hợp đồng.',payment:'Nhận mã 6 chữ số qua SMS để xác nhận khoản trả.'};
  const FACE_DOWN={FACE_UNAVAILABLE:'Máy chủ chưa sẵn sàng nhận diện khuôn mặt, nên bạn xác thực bằng mã OTP qua SMS.',FACE_NOT_ENROLLED:'Tài khoản chưa đăng ký khuôn mặt, nên bạn xác thực bằng mã OTP qua SMS.'};
  function stopped(){const error=new Error('Bạn đã hủy xác thực. Bạn có thể làm lại khi sẵn sàng.');error.code='CANCELLED';return error;}
  async function confirmPerson(purpose,method) {
    let reason='';
    if(method==='face'&&canFace()){
      try{return {method:'face',face_verify_id:await window.BU.face.verify()};}
      catch(error){
        if(error.code==='CANCELLED')throw stopped();
        if(!['USE_OTP','FACE_UNAVAILABLE','FACE_NOT_ENROLLED'].includes(error.code))throw error;
        reason=FACE_DOWN[error.code] || '';
      }
    }
    if(!window.BU?.otp)throw new Error('Chưa mở được hộp nhập mã OTP. Vui lòng tải lại trang.');
    try{
      const proof=await window.BU.otp.verify({phone:session.user?.phone || '',sub:OTP_TEXT[purpose],reason});
      return {method:'otp',otp_verified:true,otp_phone:proof.phone_masked};
    }catch(error){if(error.code==='CANCELLED')throw stopped();throw error;}
  }
  const proofBody=who=>who.method==='face'?(who.face_verify_id?{face_verify_id:who.face_verify_id}:{}):{otp_verified:true};
  async function draftConsent() {
    consentDraftAttempt=true;
    consentBody={scopes:scopes.map(s=>s.key),method:signMethod()};
    consentDraft=await api(appPath('/consent/draft'),'POST',consentBody);
    if(consentDraft.alg!=='ed25519'||typeof consentDraft.message!=='string'||!consentDraft.document)throw new Error('Bản ủy quyền chưa hợp lệ. Vui lòng thử lại.');
    local.consentStep=2;save();renderWizard();
  }
  // Kết nối cửa hàng: preview (no code yet) → code to the registered phone → verify → application from the connection.
  const OAUTH_ERRORS={DENIED:'Bạn chưa cấp quyền trên trang của sàn, nên cửa hàng chưa được kết nối.',STATE_INVALID:'Phiên kết nối đã hết hạn. Vui lòng kết nối lại cửa hàng.',PLATFORM_ERROR:'Sàn chưa trả thông tin cửa hàng. Vui lòng thử lại sau.'};
  async function lookupShop(body) {
    local.notConnected='';
    try{const p=await api('/v4/shops/connect/lookup','POST',body);local.connect={...p,connect_id:null};local.connectBody=body;local.fallback=false;save();renderWizard();}
    catch(error){if(error.code==='SHOP_NOT_CONNECTED'){local.notConnected=error.message;local.connect=null;save();renderWizard();return;}throw error;}
  }
  async function sendShopCode() {
    const r=await api('/v4/shops/connect/start','POST',local.connectBody || {url:local.urls[0]});local.connect={...r};save();renderWizard();
  }
  async function createFromConnection(id) {
    loading='stores';renderWizard();
    const a=await api('/v4/applications','POST',{tier:local.tier,borrower_type:local.borrower_type || 'individual_business',shop_connection_id:id});
    loading='';local.connect=null;local.notConnected='';local.confirmed=false;local.key=a.next_action.key;await applyApp(a);await refreshList();renderHome();
  }
  function pump() {
    clearTimeout(pollTimer);if(!modalOpen||busy||!state.app)return;
    if(key()==='verify'&&!verifyAttempt){verifyAttempt=state.app.id;run(async()=>{await verifyAndWait();verifyReview=key()!=='verify';renderWizard();});return;}
    if(key()==='consent'&&local.consentStep===2&&!consentDraft&&!consentDraftAttempt){run(draftConsent);return;}
    if(['wait_banks','wait_payout','wait_officer'].includes(key()))pollTimer=setTimeout(()=>run(async()=>{await applyApp(await api(appPath()));}),6000);
    if(key()==='select'&&!state.selected&&!state.quotePending)requestQuote();
    if(key()==='sign'&&!state.contract&&!busy)run(openContract);
  }
  function back() {
    if(busy||loading)return;capture();notice('');
    if(!state.app){if(local.picker)local.picker=false;else if(local.connect)local.connect=null;else if(local.start==='stores')local.start='welcome';else{closeWizard();return;}}
    else if(key()==='identity'&&local.confirmed)local.confirmed=false;
    else if(key()==='identity'&&local.confirmIndex>0)local.confirmIndex--;
    else if(key()==='consent'&&local.consentStep>0){local.consentStep--;consentDraft=null;consentDraftAttempt=false;}
    else if(key()==='plan'&&local.planStep>0)local.planStep--;
    else if(key()==='sign'){run(()=>mutate('/select',local.choice || {}));return;}
    else {closeWizard();return;}
    save();renderWizard();
  }
  document.addEventListener('click',event=>{
    const b=event.target.closest('[data-action]');if(!b)return;const action=b.dataset.action;
    if(action==='wizard-close'){closeWizard();return;}
    if(action==='view-loan'){verifyReview=false;closeWizard();return;}
    if(action==='wizard-back'){back();return;}
    if(busy)return;
    if(action==='resume'){showWizard();return;}
    if(action==='my-bank'){go('bank');return;}
    if(action==='home'){go('home');return;}
    if(action==='complaint-open'||action==='complaint-home'){complaintPrefill=state.app?.id || null;if(modalOpen)closeWizard();go('complaints');return;}
    if(action==='go'){if(b.dataset.view==='reports')reportId=null;go(b.dataset.view);return;}
    if(action==='explain-go'){if(modalOpen)closeWizard();go(b.dataset.view);return;}
    if(action==='explain-ask'){if(modalOpen)closeWizard();go('chat');const input=$('chat-input');if(input){input.value=BU.i18n?BU.i18n.t(b.dataset.text || ''):(b.dataset.text || '');resizeChatInput();if(!input.disabled)input.focus({preventScroll:true});}return;}
    if(action==='dialog-close'){closeDialog();return;}
    if(action==='toggle-balance'){hideBalance=!hideBalance;try{localStorage.setItem('bu_hide_balance',hideBalance?'1':'0');}catch(_){ /* optional */ }renderHome();return;}
    if(action==='theme'){document.querySelector('[data-theme-toggle]')?.click();return;}
    if(action==='logout-now'){$('logout').click();return;}
    if(action==='stats-refresh'){statsData=null;renderHome();return;}
    if(action==='stats-month'){const m=b.dataset.month;if(m&&!b.disabled){b.disabled=true;loadStats(m);}return;}
    if(action==='open-report'){reportId=b.dataset.id || null;go('reports');return;}
    if(action==='report-list'){reportId=null;go('reports');return;}
    if(action==='report-print'){if(typeof window!=='undefined'&&window.print)window.print();return;}
    if(action==='support'){const ch=state.complaintChannel || 'Tổng đài WeBank 95384 · khieunai@buoyup.vn';dialog(`<div class="confirm-box support-box"><h2>Hỗ trợ</h2><p>BuoyUp và WeBank luôn sẵn sàng hỗ trợ bạn.</p><ul class="support-list"><li><strong>Tổng đài và email</strong><span>${copy(ch)}</span></li><li><strong>Trợ lý BuoyUp</strong><span>Hỏi về hạn mức, doanh thu, lịch trả, ngân hàng cho vay.</span></li><li><strong>Khiếu nại</strong><span>Trả lời có lý do trong 5 ngày làm việc.</span></li></ul><div class="wizard-actions"><button type="button" class="btn" data-action="dialog-close">Đóng</button><button type="button" class="btn" data-action="support-go" data-view="complaints">Gửi khiếu nại</button><button type="button" class="btn btn-primary" data-action="support-go" data-view="chat">Hỏi trợ lý</button></div></div>`);return;}
    if(action==='support-go'){closeDialog();go(b.dataset.view);return;}
    if(action==='repay'){run(()=>openRepay(b.dataset.id || state.loan?.id),b);return;}
    if(action==='loan-minimum'&&state.loan){minimumConfirm(state.loan);return;}
    if(action==='loan-prepay'&&state.loan){const l=state.loan,q=l.prepay_quote || {};payConfirm({kind:'prepay',loan:l,title:'Trả hết khoản vay hôm nay',amount:Number(q.total || 0),rows:prepayRows(l,q),body:{}});return;}
    if(action==='delete-app'){const a=state.items.find(x=>x.id===b.dataset.id);dialog(`<div class="confirm-box"><h2>Xóa hồ sơ ${esc(a?.code || '')}?</h2><p>Hồ sơ ${copy(a?.store_entity || '')} sẽ biến khỏi danh sách và không tiếp tục được nữa. Những gì đã ghi trên chuỗi khối vẫn được giữ để kiểm toán.</p><div class="wizard-actions"><button type="button" class="btn" data-action="dialog-close">Giữ lại</button><button type="button" class="btn btn-danger" data-action="delete-app-confirm" data-id="${esc(b.dataset.id)}">Xóa hồ sơ</button></div></div>`);return;}
    if(action==='loan-drawer'){loanDrawer=!loanDrawer;try{localStorage.setItem('bu_loan_drawer',loanDrawer?'1':'0');}catch(_){ /* optional */ }renderHome();return;}
    if(action==='bank-filter'){bankFilter=b.dataset.filter;renderMyBank(false);return;}
    if(action==='complaint-cancel'){complaintOpen=false;renderWizard();return;}
    if(action==='new'){view='home';capture();navigationSerial++;quoteSerial++;clearTimeout(quoteTimer);verifyReview=false;verifyAttempt='';consentDraft=null;consentBody=null;state.app=null;state.loan=null;restore();renderHome();showWizard();return;}
    if(action==='wizard-next') {if(verifyReview){verifyReview=false;}else if(key()==='consent')local.consentStep++;save();renderWizard();pump();return;}
    if(action==='confirm-store'){if(local.confirmIndex<(state.app.stores?.length || 1)-1)local.confirmIndex++;else local.confirmed=true;save();renderWizard();return;}
    if(action==='wrong-store'){const urls=state.app.stores?.map(s=>s.url) || [''];state.app=null;state.loan=null;restore();local.start='stores';local.urls=urls;local.connect=null;save();renderHome();renderWizard();return;}
    if(action==='shop-cancel'){local.connect=null;save();renderWizard();return;}
    if(action==='demo-picker'){if(!state.demo)return;capture();local.picker=!local.picker;local.notConnected='';save();renderWizard();return;}
    if(action==='demo-reset'){run(async()=>{const r=await api('/v4/demo/reset-my-loans','POST',{});demoReset={needed:false};state.loan=null;await refreshList();renderHome();renderWizard(false);notice(`Đã làm mới: tất toán ${r?.settled?.length ?? 0} khoản vay mẫu.`);},b);return;}
    if(action==='demo'){const st=state.stores[Number(b.dataset.index)];local.urls=[st.url];local.reg_no='';local.fallback=false;if(st.borrower_type)local.borrower_type=st.borrower_type;local.picker=false;save();run(()=>lookupShop({url:st.url}),b);return;}
    if(action==='statement-add'){capture();if((local.statements || []).length<6){local.statements=[...(local.statements || []),{month:'',revenue:''}];while(local.statements.length<4)local.statements.push({month:'',revenue:''});}save();renderWizard(false);return;}
    if(action==='identity-tile'&&b.dataset.key==='face'&&(window.BU.face||window.BU.otp)){identityCheck();return;}
    if(action==='identity-tile'){local.identity[b.dataset.key]=true;save();renderWizard(false);return;}
    run(async()=>{
      if(action==='open')await open(b.dataset.id);
      if(action==='my-bank-refresh')await renderMyBank(true);
      if(action==='consent-revoke'){await api(`/v4/applications/${encodeURIComponent(b.dataset.id)}/consent/revoke`,'POST');await applyApp(await api(appPath()));renderHome();notice('Đã rút ủy quyền.');}
      if(action==='delete-app-confirm'){
        const id=b.dataset.id;await api(`/v4/applications/${encodeURIComponent(id)}`,'DELETE');closeDialog();
        if(state.app?.id===id){if(modalOpen)closeWizard();state.app=null;state.loan=null;try{sessionStorage.removeItem(`bu_seller_wizard:${session.user.id || session.user.email}:${id}`);}catch(_){ /* optional */ }restore();}
        await refreshList();renderHome();notice('Đã xóa hồ sơ.');
      }
      if(action==='statement-image-remove'){capture();await applyApp(await api(appPath(`/statement-images/${encodeURIComponent(b.dataset.id)}`),'DELETE'),true);renderWizard(false);}
      if(action==='refresh'){await applyApp(await api(appPath()));await refreshList();renderHome();}
      if(action==='notice-answer'){const lid=b.dataset.loan || state.loan.id,l=await api(`/v4/loans/${encodeURIComponent(lid)}/notices/${encodeURIComponent(b.dataset.notice)}/answer`,'POST',{choice:b.dataset.choice});if(state.loan?.id===lid)state.loan=l;await loadNotices();renderHome();notice('Cảm ơn bạn, BuoyUp đã ghi nhận.');}
      if(action==='identity')await mutate('/identity',local.identity.otp?{cccd:local.identity.cccd,face:false,otp_verified:true,otp_phone:local.identity.otp.phone || ''}:{cccd:local.identity.cccd,face:local.identity.face,...(local.faceVerifyId?{face_verify_id:local.faceVerifyId}:{})});
      if(action==='consent-draft')await draftConsent();
      if(action==='shop-send')await sendShopCode();
      if(action==='oauth'){const r=await api(`/v4/shops/connect/oauth/${encodeURIComponent(b.dataset.platform)}/start?format=json`);save();location.assign(r.authorize_url);}
      if(action==='verify'){verifyAttempt=state.app.id;await verifyAndWait();verifyReview=key()!=='verify';}
      if(action==='human')await mutate('/request-human',{reason:'Người bán muốn cán bộ hỗ trợ xem xét hồ sơ.'});
      if(action==='rechoose'){state.contract=null;await mutate('/select',local.choice);}
      if(action==='notices-read-all'){const r=await api('/v4/me/notices/read','POST',{all:true});state.notices.unread=Number(r.unread || 0);state.notices.items=state.notices.items.map(n=>({...n,read_at:n.read_at || new Date().toISOString()}));renderHome();}
    },b);
  });
  document.addEventListener('submit',event=>{
    const form=event.target.closest('[data-form]');if(!form)return;event.preventDefault();
    const fd=new FormData(form),data=Object.fromEntries(fd);
    if(form.dataset.form==='welcome'){local.tier=Number(data.tier);local.borrower_type=data.borrower_type || local.borrower_type;local.start='stores';save();renderWizard();return;}
    run(async()=>{
      switch(form.dataset.form){
        case 'stores': {
          local.urls=[String(fd.get('store_url') || '').trim()];local.reg_no=data.reg_no?.trim() || '';save();
          if(!local.urls[0]&&!local.reg_no)throw new Error('Dán link cửa hàng của bạn.');
          await lookupShop(local.fallback&&local.reg_no?{reg_no:local.reg_no}:{url:local.urls[0]});break;
        }
        case 'shop-code': {
          const code=String(data.code || '').replace(/\D/g,'');
          if(code.length!==6)throw new Error('Nhập đủ 6 chữ số của mã.');
          const v=await api(`/v4/shops/connect/${encodeURIComponent(local.connect.connect_id)}/verify`,'POST',{code});
          await createFromConnection(v.connection.id);break;
        }
        case 'consent-boxes': {
          local.boxes=Object.fromEntries(scopes.map(x=>[x.key,fd.has(x.key)]));local.signMethod=data.method || signMethod();save();
          if(!scopes.every(x=>local.boxes[x.key]))throw new Error('Cần đánh dấu đủ ba ô đồng ý.');
          await draftConsent();break;
        }
        case 'sign-consent': {
          if(!fd.has('confirm'))throw new Error('Vui lòng xác nhận đồng ý ủy quyền.');
          if(!consentDraft||!consentBody)throw new Error('Vui lòng quay lại để lấy bản ủy quyền.');
          const subtle=window.crypto?.subtle;if(!subtle)throw new Error('Cần HTTPS hoặc localhost để ký ủy quyền.');
          const who=await confirmPerson('consent',consentBody.method);
          let signingKey;try{signingKey=await subtle.generateKey({name:'Ed25519'},false,['sign','verify']);}catch(_){throw new Error('Vui lòng dùng trình duyệt mới có hỗ trợ ký ủy quyền.');}
          const hex=buffer=>Array.from(new Uint8Array(buffer),b=>b.toString(16).padStart(2,'0')).join('');
          const sig=await subtle.sign('Ed25519',signingKey.privateKey,new TextEncoder().encode(consentDraft.message));
          const publicKey=await subtle.exportKey('raw',signingKey.publicKey);
          await mutate('/consent',{...consentBody,method:who.method,...proofBody(who),signature:{alg:'ed25519',public_key:hex(publicKey),sig:hex(sig)}});break;
        }
        case 'plan-step': {
          local.plan={...local.plan,...data};save();
          local.planStep++;save();renderWizard();break;
        }
        case 'statements': {
          local.statements=readStatements(fd);save();
          const p={...local.plan};delete p.suggested;delete p.submitted;delete p.statements;delete p.supplier;delete p.brand;delete p.auth;delete p.declaration;
          if(!fd.has('declaration'))throw new Error('Vui lòng tích ô cam đoan trước khi gửi.');p.declaration=true;if(p.group!=='khác')p.group_other='';
          ['qty','price','inventory','own_capital','other_loans'].forEach(k=>p[k]=Number(p[k]));p.flavor=p.flavor || null;
          if(local.statements.length)p.statements=local.statements.map(r=>({month:r.month,revenue:Number(r.revenue)}));
          await mutate('/plan',p,'PUT');break;
        }
        case 'choice': {
          local.choice=readChoice(fd);save();
          await mutate('/select',local.choice);break;
        }
        case 'sign': {
          const body={read_ack:fd.has('read_ack'),webank_account:String(data.webank_account || '').trim(),use_of_funds_commitment:fd.has('use_of_funds_commitment'),guarantee:fd.has('guarantee'),method:data.method || signMethods()[0]};
          if(data.supplier_account)body.supplier_account=data.supplier_account.trim();
          // Cheap checks first, so the face or the OTP is not asked for a form the server would refuse.
          if(!/^\d{6,20}$/.test(body.webank_account))throw new Error('Số tài khoản kinh doanh WeBank gồm 6–20 chữ số.');
          if(!body.use_of_funds_commitment)throw new Error('Cần cam kết dùng vốn cho kinh doanh.');
          if(!body.read_ack)throw new Error('Vui lòng xác nhận đã đọc bảng chi phí và hợp đồng.');
          const who=await confirmPerson('sign',body.method);Object.assign(body,{method:who.method},proofBody(who));
          loading='control';renderWizard();await mutate('/sign',body);break;
        }
        case 'repay': {
          const l=repayLoan;if(!l)break;
          const opt=data.option,q=l.prepay_quote || {},total=Number(q.total || 0);
          let body={},title='Trả nợ';
          if(opt==='overdue'){body={amount:Number(l.owed_now)};title='Trả khoản đang quá hạn';}
          else if(opt==='next'){body={amount:Math.min(Number(l.next_due?.payment_est || 0),total)};title='Trả kỳ tới ngay hôm nay';}
          else if(opt==='custom'){const amt=Math.floor(Number(data.amount));if(!(amt>0))throw new Error('Nhập số tiền muốn trả.');body={amount:amt};title='Trả trước một phần';}
          else title='Trả hết khoản vay';
          payConfirm({kind:'prepay',loan:l,title,amount:body.amount ?? total,rows:prepayRows(l,q,body.amount),body});
          break;
        }
        case 'pay-confirm': {
          const p=pendingPay;if(!p)break;
          if(!fd.has('ack'))throw new Error('Vui lòng tích ô xác nhận trước khi trả.');
          const method=data.method==='face'&&canFace()?'face':'otp',body={...p.body,confirm:true};
          if(method==='face')closeDialog(); // the camera box; the OTP box opens above this one
          let who;
          try{who=await confirmPerson('payment',method);}
          catch(error){if(error.code==='CANCELLED'){if(method==='face')payConfirm(p);break;}throw error;}
          body.method=who.method;if(who.face_verify_id)body.face_verify_id=who.face_verify_id;
          const lid=p.loan.id,r=await api(`/v4/loans/${encodeURIComponent(lid)}/${p.kind==='minimum'?'minimum':'prepay'}`,'POST',body);
          pendingPay=null;closeDialog();if(state.loan?.id===lid)state.loan=r;bankData=null;statsData=null;
          if(p.kind==='minimum'){renderHome();notice('Kỳ tới bạn chỉ trả mức tối thiểu.');loadNotices();break;}
          if(r.status==='closed'&&state.app){await applyApp(await api(appPath()));await refreshList();}
          if(view==='bank')await renderMyBank(true);else renderHome();
          notice(r.status==='closed'?`Đã trả ${money(r.prepay.paid,r.currency)}. Khoản vay đã tất toán.`:`Đã trả ${money(r.prepay.paid,r.currency)}. Dư nợ gốc còn ${money(r.principal_outstanding,r.currency)}.`);
          pollMoney();loadNotices();break;
        }
        case 'complaint': {
          const body={category:data.category,text:String(data.text || '').trim()};
          if(body.text.length<5)throw new Error('Mô tả ngắn nội dung khiếu nại (ít nhất 5 ký tự).');
          const appId=data.application_id!==undefined?data.application_id:state.app?.id;if(appId)body.application_id=appId;
          const app=state.items.find(a=>a.id===appId);if(state.loan?.id&&(!appId||state.loan.application_id===appId||app?.status==='disbursed'))body.loan_id=state.loan.id;
          const c=await api('/v4/complaints','POST',body);complaintOpen=false;complaintPrefill=null;await loadComplaints();view='complaints';renderComplaints();
          notice(`Đã tiếp nhận khiếu nại ${c.id}. BuoyUp trả lời trước ${day(c.answer_due)}.`);break;
        }
        case 'transfer':state.loan=await api(`/v4/loans/${encodeURIComponent(state.loan.id)}/simulate-transfer`,'POST',{amount:Number(data.amount),kind:data.kind});renderHome();break;
        case 'advance':state.loan=await api(`/v4/loans/${encodeURIComponent(state.loan.id)}/simulate-advance`,'POST',{to:data.to});await applyApp(await api(appPath()));await refreshList();renderHome();break;
        case 'receiving':state.loan=await api(`/v4/loans/${encodeURIComponent(state.loan.id)}/receiving-account`,'PUT',{bank:data.bank,number:data.number});renderHome();notice('Đã đổi tài khoản nhận tiền hàng.');break;
        case 'answer': {
          const q=state.app.verification.questions[0],choice=q.choices.find(c=>c.key===data.choice);
          if(!choice)throw new Error('Vui lòng chọn một câu trả lời.');
          const extra=needs(q,choice),body={flag:q.flag,choice:choice.key};
          if(extra.includes('inventory')){if(data.inventory==null||data.inventory==='')throw new Error('Nhập giá trị tồn kho.');body.inventory=Number(data.inventory);}
          if(extra.includes('store_url')){if(!data.store_url)throw new Error('Nhập link gian hàng.');body.store_url=data.store_url;}
          await mutate('/answers',body);local.answer=null;save();break;
        }
        case 'whatif': {
          local.whatif=data;save();const body={};
          ['own_capital','inventory','qty','supplier'].forEach(k=>{if(data[k]!=null&&data[k]!=='')body[k]=k==='supplier'?data[k]:Number(data[k]);});
          const estimate=await api(appPath('/what-if'),'POST',body);state.estimate={appId:state.app.id,data:estimate};
          $('whatif-result').innerHTML=`<p>Ước tính, cần nộp chứng từ</p>${facts([['Nhu cầu vốn',money(estimate.need,state.app.offer.currency)],['Hạn mức ước tính',money(estimate.limit,state.app.offer.currency)],['Gợi ý vay vừa đủ',money(estimate.suggested,state.app.offer.currency)]])}<p>${copy(estimate.text)}</p>`;break;
        }
        case 'inflow':state.loan=await api(`/v4/loans/${encodeURIComponent(state.loan.id)}/simulate-inflow`,'POST',{amount:Number(data.amount)});await applyApp(await api(appPath()));await refreshList();renderHome();break;
      }
    },form.querySelector('[type="submit"]'));
  });
  const readFile=file=>new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(new Error('Không đọc được ảnh.'));r.readAsDataURL(file);});
  async function scanCccd(input) {
    const file=input.files?.[0],side=input.dataset.cccd;if(!file)return;
    if(file.size>8*1024*1024){notice('Ảnh vượt 8 MB; chụp lại với độ phân giải thấp hơn.',true);return;}
    await run(async()=>{
      notice('Đang đọc CCCD…');
      const r=await api(appPath('/cccd'),'POST',{image:await readFile(file),side});
      local.cccd={...(local.cccd || {}),[r.side]:r};save();notice(r.side===side?'Đã đọc '+(side==='front'?'mặt trước.':'mặt sau.'):'Ảnh là mặt '+(r.side==='front'?'trước':'sau')+'; đã ghi nhận đúng mặt.');
      renderWizard(false);
    },input);
  }
  async function uploadStatementImages(input) {
    const files=[...(input.files || [])].slice(0,6);if(!files.length)return;
    await run(async()=>{
      capture();
      for(const file of files){if(file.size>8*1024*1024)throw new Error('Mỗi ảnh tối đa 8 MB.');await api(appPath('/statement-images'),'POST',{image:await readFile(file)});}
      await applyApp(await api(appPath()),true);notice(`Đã tải ${files.length} ảnh.`);renderWizard(false);
    },input);
  }
  document.addEventListener('change',event=>{
    if(event.target.name==='choice'&&event.target.closest('[data-form="answer"]')){capture();renderWizard(false);[...$('wizard-screen').querySelectorAll('[name="choice"]')].find(input=>input.value===event.target.value)?.focus();}
    if(event.target.matches?.('input[data-cccd]'))scanCccd(event.target);
    if(event.target.matches?.('input[data-statement-images]'))uploadStatementImages(event.target);
    if(event.target.name==='group'&&event.target.closest('[data-form="plan-step"]')){const box=$('group-other');if(box)box.hidden=event.target.value!=='khác';}
  });
  function requestQuote() {
    if(!state.app?.offer)return;
    const ch=local.choice || {amount:state.app.offer.suggested || state.app.offer.limit,due_day:10};
    const serial=++quoteSerial,id=state.app.id;
    clearTimeout(quoteTimer);state.quotePending=true;
    quoteTimer=setTimeout(async()=>{
      try {
        const q=await api(`/v4/applications/${encodeURIComponent(id)}/quote`,'POST',{amount:ch.amount,tenor_m:state.app.offer.tenor_max,method:'installment',due_day:Math.min(28,Math.max(1,ch.due_day || 10))});
        if(serial!==quoteSerial||state.app?.id!==id||!modalOpen||key()!=='select')return;
        state.selected={...q,appId:id};state.quotePending=false;
        const box=$('choice-quote');if(box)box.innerHTML=costFacts(q,state.app.offer.currency)+details('Lịch trả dự kiến',scheduleTable(q.schedule,state.app.offer.currency));
        const sub=$('wizard-screen').querySelector('[data-form="choice"] [type="submit"]');if(sub)sub.disabled=busy;
      } catch(error){if(serial!==quoteSerial||!modalOpen)return;state.quotePending=false;notice(error.message,true);}
    },250);
  }
  async function openContract() {
    state.contract=await api(appPath('/contract'));state.contractOpenedAt=Date.now();renderWizard();
    const tick=()=>{if(!state.contract||key()!=='sign'||!modalOpen)return;const left=Math.max(0,Math.ceil(state.contract.read_seconds-(Date.now()-state.contractOpenedAt)/1000));const t=$('read-timer'),b=$('sign-submit');if(t)t.textContent=left?`Còn ${left} giây đọc`:'Bạn có thể ký';if(b)b.disabled=!!left||busy;if(left)setTimeout(tick,1000);};
    setTimeout(tick,1000);
  }
  document.addEventListener('input',event=>{
    const form=event.target.closest('[data-form="choice"]');
    if(!form){if(event.target.closest('#wizard-screen'))capture();return;}
    local.choice=readChoice(new FormData(form));save();
    const label=$('choice-amount-label');if(label)label.textContent=money(local.choice.amount,state.app.offer.currency);
    const sub=form.querySelector('[type="submit"]');if(sub)sub.disabled=true;
    requestQuote();
  });
  $('chat-form').addEventListener('submit',event=>{event.preventDefault();const input=$('chat-input'),text=input.value;if(!text.trim()||chat.sending||!chat.loaded||!chat.appId)return;input.value='';resizeChatInput();sendChat(text);});
  $('chat-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('chat-form').requestSubmit();}});
  $('chat-input').addEventListener('input',resizeChatInput);
  $('chat-scroll').addEventListener('scroll',()=>{const scroll=$('chat-scroll');chatScrollTop=scroll.scrollTop;chatFollow=scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<=48;if(chatFollow){chatUnread=false;$('chat-latest').hidden=true;}});
  $('chat-latest').addEventListener('click',followLatest);
  matchMedia('(min-width: 1100px)').addEventListener('change',event=>{homeLoanExpanded=event.matches;const loan=$('home-loan-details');if(loan)loan.open=homeLoanExpanded;});
  $('chat-jump').addEventListener('click',()=>{$('wizard-chat').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});$('chat-input').focus({preventScroll:true});});
  // Hide the jump button once the chat panel itself is on screen.
  if('IntersectionObserver' in window)new IntersectionObserver(([entry])=>{chatVisible=entry.isIntersecting;$('chat-jump').hidden=!chatOpen()||chatVisible;},{threshold:0.25}).observe($('wizard-chat'));
  $('chat-suggest').addEventListener('click',event=>{const b=event.target.closest('[data-chat-suggest]');if(b)sendChat(BU.i18n?BU.i18n.t(b.dataset.chatSuggest):b.dataset.chatSuggest);});
  $('seller-wizard').addEventListener('cancel',event=>{event.preventDefault();closeWizard();});
  $('seller-wizard').addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();closeWizard();return;}
    if(event.key!=='Tab')return;
    const nodes=[...$('seller-wizard').querySelectorAll('button,input,select,textarea,summary,a[href]')].filter(n=>!n.disabled&&n.getClientRects().length);
    const first=nodes[0],last=nodes[nodes.length-1];
    if(event.shiftKey&&(document.activeElement===first||document.activeElement===$('wizard-title'))){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  });
  function closeSidebar(){$('workspace-shell').classList.remove('sidebar-open');$('sidebar-backdrop').hidden=true;$('sidebar-toggle').setAttribute('aria-expanded','false');}
  $('sidebar-toggle').addEventListener('click',()=>{const mobile=matchMedia('(max-width:720px)').matches,shell=$('workspace-shell');shell.classList.toggle(mobile?'sidebar-open':'sidebar-collapsed');const expanded=mobile?shell.classList.contains('sidebar-open'):!shell.classList.contains('sidebar-collapsed');$('sidebar-toggle').setAttribute('aria-expanded',String(expanded));$('sidebar-backdrop').hidden=!(mobile&&expanded);if(mobile&&expanded)$('sidebar').querySelector('button')?.focus();});
  $('sidebar-backdrop').addEventListener('click',closeSidebar);
  const media=matchMedia('(max-width:720px)');function syncSidebar(){closeSidebar();$('workspace-shell').classList.remove('sidebar-collapsed');$('sidebar-toggle').setAttribute('aria-expanded',String(!media.matches));}media.addEventListener('change',syncSidebar);syncSidebar();
  document.addEventListener('keydown',event=>{if(modalOpen)return;if(event.key==='Escape'&&$('workspace-shell').classList.contains('sidebar-open')){closeSidebar();$('sidebar-toggle').focus();}if(event.key==='Tab'&&$('workspace-shell').classList.contains('sidebar-open')){const nodes=[...$('sidebar').querySelectorAll('button,a,input')].filter(n=>!n.disabled),first=nodes[0],last=nodes[nodes.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}});
  // Sidebar width: drag the seam between the sidebar and the page (arrow keys when focused, double-click resets).
  (function sidebarResizer(){
    const bar=$('sidebar-resizer'),MIN=200,MAX=420,DEF=280,KEY='bu_sidebar_width';
    if(!bar||!bar.addEventListener)return;
    const apply=w=>{w=Math.round(Math.min(MAX,Math.max(MIN,Number(w) || DEF)));document.body.style.setProperty('--sidebar-width',w+'px');bar.setAttribute('aria-valuenow',String(w));return w;};
    const keep=w=>{try{localStorage.setItem(KEY,String(w));}catch(_){}};
    let width=DEF;try{width=apply(localStorage.getItem(KEY) || DEF);}catch(_){width=apply(DEF);}
    bar.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;event.preventDefault();
      const left=$('sidebar').getBoundingClientRect().left;bar.setPointerCapture?.(event.pointerId);document.body.classList.add('sidebar-resizing');
      const move=e=>{width=apply(e.clientX-left);};
      const up=()=>{bar.removeEventListener('pointermove',move);bar.removeEventListener('pointerup',up);bar.removeEventListener('pointercancel',up);document.body.classList.remove('sidebar-resizing');keep(width);drawCharts();};
      bar.addEventListener('pointermove',move);bar.addEventListener('pointerup',up);bar.addEventListener('pointercancel',up);
    });
    bar.addEventListener('dblclick',()=>{width=apply(DEF);keep(width);drawCharts();});
    bar.addEventListener('keydown',event=>{const step=event.shiftKey?40:10,d={ArrowLeft:-step,ArrowRight:step}[event.key];if(event.key==='Home'||event.key==='End'){width=apply(event.key==='Home'?MIN:MAX);}else if(d){width=apply(width+d);}else return;event.preventDefault();keep(width);drawCharts();});
  })();
  $('logout').addEventListener('click',()=>run(async()=>{await BU.api.auth.logout();BU.session.clear();location.assign('login.html');},$('logout')));
  $('account-name').textContent=session.user.display_name;$('account-role').textContent='Người bán';
  restore();
  run(async()=>{
    const me=await api('/v4/auth/me');BU.session.set({...session,user:me.user});
    if(me.user.role!=='seller'){location.assign(BU.session.home(me.user.role));return;}
    session.user=me.user;state.profile=me.demo_profile || null;$('account-name').textContent=me.user.display_name;
    const responses=await Promise.all([api('/v4/applications'),api('/v4/public/demo-stores').catch(error=>{if(error.status===404)return null;throw error;}),api('/v4/public/features').catch(()=>null),api('/v4/shops/platforms').catch(()=>null)]);
    if(responses[2])state.features={...state.features,...responses[2]};
    state.platforms=responses[3]?.platforms || [];
    state.items=responses[0].items || [];state.stores=responses[1]?.stores || [];state.demo=!!responses[1];
    await loadNotices();
    // Back from the platform's sign-in page (OAuth callback → workspace.html?shop_connection=… or ?shop_connect_error=…).
    let back={};try{const q=new URLSearchParams(location.search || '');back={id:q.get('shop_connection'),error:q.get('shop_connect_error')};if(back.id||back.error)history.replaceState(null,'',location.pathname);}catch(_){ /* no URL */ }
    if(back.id||back.error){restore();local.start='stores';showWizard();if(back.error){notice(OAUTH_ERRORS[back.error] || OAUTH_ERRORS.PLATFORM_ERROR,true);return;}await createFromConnection(back.id);return;}
    const unfinished=state.items.find(a=>!['disbursed','repaying','closed','rejected','out_of_scope'].includes(a.status));
    if(unfinished)await open(unfinished.id);
    else if(state.items.length)await open(state.items[0].id,false);
    else {restore();renderHome();showWizard();}
  });
})();
