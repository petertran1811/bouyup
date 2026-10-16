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
  const statusNames = {draft:'Đang lập hồ sơ',identified:'Đang lập hồ sơ',consented:'Đang lập hồ sơ',verifying:'Đang xác minh',verified:'Đã xác minh',needs_answer:'Cần bạn làm rõ',offered:'Ngân hàng đã duyệt hạn mức',in_control:'Đang kiểm tra',selected:'Chờ ký hợp đồng',signed:'Đang giải ngân',expired:'Hạn mức hết hiệu lực',escalated:'Chờ cán bộ',rejected:'Chưa được duyệt',out_of_scope:'Chưa đủ điều kiện',disbursed:'Đã giải ngân',repaying:'Đang trả nợ',closed:'Đã tất toán',active:'Đang trả nợ',overdue:'Cần trả nợ'};
  const groups = ['quần áo','thực phẩm đóng gói','thực phẩm rời','thực phẩm chức năng','dược','thiết bị y tế I','thiết bị y tế II','thiết bị y tế III','thuốc lá điện tử','dịch thuốc lá điện tử','điện tử','khác'];
  const auths = ['Tôi là chủ nhãn hiệu','Có ủy quyền phân phối','Không có ủy quyền','Chưa rõ'];
  // Loan circle, Stage 1: three separate boxes, none pre-ticked, each linked to its own text.
  const scopes = [
    {key:'credit_inquiry',label:'Ủy quyền tra cứu tín dụng cho WeBank và các ngân hàng hợp tác',covers:'Báo cáo tín dụng; điểm liên ngân hàng',doc:'van-ban/tra-cuu-tin-dung.html'},
    {key:'share_partners',label:'Đồng ý chuyển hồ sơ vay cho các ngân hàng hợp tác trong danh sách đính kèm',covers:'Hồ sơ vay và kết quả thẩm định',doc:'van-ban/ngan-hang-hop-tac.html'},
    {key:'data_processing',label:'Đồng ý xử lý thông tin khuôn mặt và dữ liệu tài chính để xác thực và thẩm định',covers:'Khuôn mặt (xác thực, ký); dữ liệu thuế; ảnh doanh thu bạn tự nộp',doc:'van-ban/xu-ly-du-lieu.html'}
  ];
  const borrowerTypes=[['individual_business','Hộ kinh doanh','Vay tối đa 200.000 tệ · kỳ hạn 3, 6, 12 tháng'],['company','Doanh nghiệp','Kỳ hạn 3, 6, 12, 24, 36 tháng · cần bảo lãnh của người đại diện']];
  const methods=[['installment','Trả góp cố định','Gốc chia đều mỗi tháng + lãi theo ngày thực tế'],['revenue','Trả theo doanh thu','Mỗi tháng trả một tỷ lệ doanh thu, không thấp hơn mức tối thiểu']];
  const field = (key, label, value='', type='text', extra='') => `<label class="v4-field">${label}<input name="${key}" type="${type}" value="${esc(value)}" ${extra}></label>`;
  const select = (key, label, values, value) => `<label class="v4-field">${label}<select name="${key}">${values.map(v => `<option ${v === value ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
  const button = (action, text, primary=false, extra='') => `<button type="button" class="btn ${primary ? 'btn-primary' : ''}" data-action="${action}" ${extra}>${text}</button>`;
  const submit = (text, extra='') => `<div class="wizard-actions"><button type="submit" class="btn btn-primary" ${extra}>${text}</button></div>`;
  const facts = entries => `<dl class="v4-facts">${entries.map(([label,value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join('')}</dl>`;
  const details = (label, html, extra='') => `<details ${extra} class="wizard-details"><summary>${label}</summary>${html}</details>`;
  const api = (path, method='GET', body) => BU.api.request(path, {method,body,timeout:60000});
  const appPath = (tail='') => `/v4/applications/${encodeURIComponent(state.app.id)}${tail}`;
  let state = {app:null,items:[],stores:[],demo:false,profile:null,loan:null,selected:null,quotePending:false,complaints:[],complaintChannel:''};
  let complaintOpen=false;
  const complaintStatus={acknowledged:'Đã tiếp nhận',in_review:'Cán bộ đang xem',escalated:'Đã chuyển trưởng nhóm',answered:'Đã trả lời'};
  const complaintCategories=[['rejection','Bị từ chối'],['limit','Hạn mức bị giảm'],['fees','Lãi và phí'],['debit','Trích nợ'],['data','Dữ liệu cá nhân'],['other','Khác']];
  let local, busy=false, modalOpen=false, returnFocus=null, consentDraft=null, consentBody=null, consentDraftAttempt=false;
  let chatVisible=false;
  const chatEl=document.getElementById('wizard-chat');
  const chat={appId:null,items:[],sending:false,loaded:false,error:''};
  let chatFollow=true, chatScrollTop=0, chatUnread=false, chatRendered='';
  let homeLoanAppId=null, homeLoanExpanded=null;
  const loanChainCache=new Map();
  const CHAT_SUGGEST=['Vì sao hạn mức của tôi là số này?','Doanh thu 12 tháng của tôi thế nào?','Trả góp và trả theo doanh thu khác gì nhau?','Ngân hàng nào cho tôi vay?'];
  let loading='', verifyReview=false, verifyAttempt='', quoteTimer, quoteSerial=0, navigationSerial=0, pollTimer;
  const key = () => state.app?.next_action?.key || 'none';
  const storageKey = () => `bu_seller_wizard:${session.user.id || session.user.email}:${state.app?.id || 'new'}`;
  function freshLocal() { return {key:key(),start:'welcome',tier:2,borrower_type:'individual_business',urls:[state.profile?.store_url || ''],reg_no:'',fallback:false,confirmed:false,confirmIndex:0,identity:{cccd:false,face:false},consentStep:0,boxes:{},signMethod:'face',planStep:0,plan:null,statements:[],answer:null,choice:null}; }
  function restore() {
    local=freshLocal();
    try { const saved=JSON.parse(sessionStorage.getItem(storageKey())); if(saved) local={...local,...saved}; } catch (_) { /* Storage is optional. */ }
    if(local.key!==key()) { local.consentStep=0;local.planStep=0;local.answer=null; }
    local.key=key();
    if(state.app) {
      local.identity={cccd:!!state.app.identity?.cccd,face:!!state.app.identity?.face,...local.identity};
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
  function readChoice(fd) { return {amount:Number(fd.get('amount')),tenor_m:Number(fd.get('tenor_m')),method:fd.get('method') || 'installment',due_day:Number(fd.get('due_day') || 10)}; }
  function welcome() {
    return title('Chào mừng',`Chào ${copy(session.user.display_name)}, cùng xem bạn vay được bao nhiêu.`, `<form data-form="welcome"><p><strong>Bạn vay với tư cách</strong></p><div class="wizard-choices">${borrowerTypes.map(([k,label,caption])=>`<label class="wizard-choice"><input type="radio" name="borrower_type" value="${k}" ${local.borrower_type===k?'checked':''}><span><strong>${label}</strong><small>${caption}</small></span></label>`).join('')}</div><input type="hidden" name="tier" value="2">${submit('Bắt đầu')}</form>`);
  }
  function stores() {
    return title('Link gian hàng',local.fallback?'Không đọc được link; bạn có thể dùng đăng ký kinh doanh.':'Dán link để BuoyUp đọc thông tin cửa hàng.', `<form data-form="stores"><div id="store-links">${local.urls.map((url,i)=>field('store_url',i?'Gian hàng thêm':'Dán link gian hàng của bạn',url,'url',`${!i&&!local.fallback?'required':''} maxlength="500" placeholder="https://…"`)).join('')}</div><div class="wizard-link-actions">${button('store-add','+ thêm gian hàng',false,local.urls.length>=5?'disabled':'')}${state.demo?button('demo-picker','Dùng gian hàng mẫu'):''}</div><div id="registration-fallback" ${local.fallback?'':'hidden'}>${field('reg_no','Số đăng ký kinh doanh',local.reg_no,'text',`${local.fallback?'required':''} maxlength="40"`)}</div>${submit('Tiếp tục')}</form>`);
  }
  function demoPicker() {return title('Gian hàng mẫu','Chọn một tình huống để thử hồ sơ.',`<div class="wizard-demo-picker">${state.stores.map((s,i)=>button('demo',copy(s.label),false,`data-index="${i}"`)).join('')}</div>`);}
  function confirmation() {
    const stores=state.app.stores || [],s=stores[local.confirmIndex] || stores[0] || {};
    return title('Đây có phải cửa hàng của bạn?','Kiểm tra thông tin trước khi tiếp tục.', `${stores.length>1?`<small>Gian hàng ${local.confirmIndex+1}/${stores.length}</small>`:''}<section class="wizard-store"><h2>${copy(s.entity)}</h2>${facts([['Nền tảng',copy(({douyin:'Douyin',taobao:'Taobao',tmall:'Tmall',jd:'JD',pinduoduo:'Pinduoduo',kuaishou:'Kuaishou'})[s.platform] || s.platform)],['Điểm gian hàng',num(s.rating)],['Đăng ký kinh doanh',copy(s.reg_no)],['Hoạt động từ',day(s.registry?.registered)]])}</section><div class="wizard-actions">${button('confirm-store','Đúng, tiếp tục',true)}</div>${button('wrong-store','Không phải')}`);
  }
  function identity() {
    return title('Xác thực danh tính','Chạm vào từng mục. Quét khuôn mặt mở camera để so với khuôn mặt bạn đã đăng ký; CCCD là mô phỏng.', `<div class="wizard-tiles">${[['cccd','Chụp CCCD'],['face','Quét khuôn mặt']].map(([k,label])=>`<button type="button" class="btn wizard-tile" data-action="identity-tile" data-key="${k}" data-done="${!!local.identity[k]}" aria-pressed="${!!local.identity[k]}"><span aria-hidden="true">${local.identity[k]?'✓':'◎'}</span><strong>${label}</strong></button>`).join('')}</div><div class="wizard-actions">${button('identity','Tiếp tục',true,local.identity.cccd&&local.identity.face?'':'disabled')}</div>`);
  }
  function consent() {
    if(local.consentStep<2) return title('Ba ô đồng ý','Đọc từng văn bản và đánh dấu từng ô. Thiếu một ô thì hồ sơ không thể tiếp tục.', `<form data-form="consent-boxes"><div class="wizard-consent-boxes">${scopes.map(x=>`<label class="v4-check"><input type="checkbox" name="${x.key}" ${local.boxes?.[x.key]?'checked':''} required><span><strong>${x.label}</strong><br><small>${x.covers} · <a href="${x.doc}" target="_blank" rel="noopener">Đọc văn bản</a></small></span></label>`).join('')}</div><p><strong>Ký bằng</strong></p><div class="wizard-choices">${[['face','Khuôn mặt'],['otp','Mã OTP gửi về điện thoại']].map(([k,l])=>`<label class="wizard-choice"><input type="radio" name="method" value="${k}" ${local.signMethod===k?'checked':''}><span>${l}</span></label>`).join('')}</div>${submit('Tiếp tục')}</form>`);
    const d=consentDraft?.document;
    return title('Ký ủy quyền','Kiểm tra và ký bằng '+(local.signMethod==='otp'?'mã OTP':'khuôn mặt')+'.', `<ul class="wizard-scope-list">${scopes.map(x=>`<li>${x.label}</li>`).join('')}</ul>${details('Xem chi tiết',`<p>Thời điểm ký: ${esc(d?.signed_at || 'Chưa có thông tin')}<br>Hết hạn: ${esc(d?.expires_at || 'Chưa có thông tin')}</p>`)}${consentDraft?`<form data-form="sign-consent"><label class="v4-check"><input type="checkbox" name="confirm" required><span>Tôi đồng ý cả ba nội dung trên.</span></label>${submit('Ký')}</form>`:`<div class="wizard-actions">${button('consent-draft','Lấy bản ủy quyền',true)}</div>`}`);
  }
  function plan() {
    const p=local.plan || {},currency=esc(state.app.currency || 'CNY'),unit=currency==='CNY'?'tệ':currency==='VND'?'đồng':currency;
    const screens=[
      ['Bạn nhập hàng cho dịp nào?','Gợi ý đã có sẵn; hãy sửa theo dự định của bạn.',`${field('event','Dịp bán hàng',p.event,'text','required maxlength="40"')}${field('item','Mặt hàng',p.item,'text','required maxlength="120"')}${details('Xem chi tiết',select('group','Nhóm hàng',groups,p.group)+field('brand','Nhãn hiệu',p.brand,'text','maxlength="80"')+select('auth','Quyền nhãn hiệu',auths,p.auth)+field('flavor','Hương vị (nếu có)',p.flavor,'text','maxlength="40"'))}`],
      ['Nhập bao nhiêu?','Điền số lượng, giá nhập và nhà cung cấp.',`${field('qty','Số lượng',p.qty,'number','required min="1" max="10000000" step="1"')}${field('price',`Giá nhập mỗi sản phẩm (${unit})`,p.price,'number','required min="0.01" max="1000000" step="0.01"')}${field('supplier','Nhà cung cấp',p.supplier,'text','required maxlength="40"')}`],
      ['Bạn đã có sẵn bao nhiêu?','Điền số tiền theo tình hình hiện tại.',`${field('own_capital',`Vốn tự có (${unit})`,p.own_capital,'number','required min="0" max="1000000000" step="1"')}${field('inventory',`Giá trị tồn kho (${unit})`,p.inventory,'number','required min="0" max="1000000000" step="1"')}${field('other_loans',`Các khoản vay khác (${unit})`,p.other_loans,'number','required min="0" max="1000000000" step="1"')}`]
    ];
    if(local.planStep===3){
      const rows=[...(local.statements || [])];while(rows.length<3)rows.push({month:'',revenue:''});
      return title('Ảnh doanh thu (tùy chọn)','Nộp doanh thu trong trang quản lý cửa hàng tối đa 6 tháng gần nhất. Khớp với thuế thì hạn mức có thể cao hơn; bỏ trống cũng được.',`<form data-form="statements">${rows.map(r=>`<div class="v4-grid">${field('st_month','Tháng',r.month,'month','')}${field('st_revenue',`Doanh thu (${unit})`,r.revenue,'number','min="0" max="1000000000" step="1"')}</div>`).join('')}${button('statement-add','+ thêm tháng',false,rows.length>=6?'disabled':'')}${submit('Gửi kế hoạch')}</form>`);
    }
    const screen=screens[local.planStep];return title(screen[0],screen[1],`<form data-form="plan-step">${screen[2]}${submit('Tiếp tục')}</form>`);
  }
  function checklist() {
    const steps=state.app.verification?.steps || [];
    const items=[['Gian hàng',['link']],['Đăng ký kinh doanh',['registry']],['Danh tính',['identity']],['Doanh thu theo thuế',['revenue']],['Tín dụng và điểm liên ngân hàng',['sources']],...(state.app.tier===2?[['Kế hoạch',['plan']]]:[])];
    return title('Đang xác minh',verifyReview?'Đã nhận kết quả; cùng xem bước tiếp theo.':'BuoyUp đang kiểm tra thông tin bạn đã đồng ý.', `<ol class="wizard-checklist">${items.map(([label,keys])=>{const found=steps.filter(s=>keys.includes(s.key));const status=found.some(s=>s.status==='fail')?'fail':found.some(s=>s.status==='warn')?'warn':found.length&&found.every(s=>['ok','skip'].includes(s.status))?'ok':'pending';return `<li data-status="${status}">${label}<small>${status==='ok'?'Đã kiểm tra':status==='pending'?'Đang chờ':'Cần xem xét'}</small></li>`;}).join('')}</ol><div class="wizard-actions">${verifyReview?button('wizard-next','Tiếp tục',true):button('verify','Thử lại',true,busy||!verifyAttempt?'disabled':'')}</div>`);
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
    const syn=state.app.syndicate || {},ch=local.choice || {amount:o.suggested || o.limit,tenor_m:o.tenor_max,method:'installment',due_day:10};
    local.choice=ch;
    const q=state.selected,currency=o.currency;
    const banks=(syn.split || []).map(b=>`${esc(b.name)} ${Math.round(b.pct*100)}%`).join(' · ');
    const why=sellerText(o.explanation).split(/(?<=[.!?])\s/)[0] || '';
    return title('Ngân hàng đã duyệt hạn mức',`Bạn chọn số tiền, kỳ hạn, hình thức và ngày trả trong hạn mức này; không cần duyệt lại.`,
      `<p class="wizard-amount">Tối đa ${money(o.limit,currency)}</p>${facts([['Ngân hàng cùng cho vay',banks || '—'],['Hạn mức hiệu lực đến',day(o.expires_at)],['Gợi ý vay vừa đủ',money(o.suggested,currency)]])}<p class="wizard-explanation">${esc(why)}</p>
      <form data-form="choice"><label class="v4-field">Số tiền muốn vay<input name="amount" id="choice-amount" type="range" min="${esc(o.slider?.min ?? 0)}" max="${esc(o.slider?.max ?? o.limit)}" step="${esc(o.slider?.step ?? 100)}" value="${esc(ch.amount)}"></label><p id="choice-amount-label" class="wizard-amount">${money(ch.amount,currency)}</p>
      ${select('tenor_m','Kỳ hạn (tháng)',(o.tenors || []).map(String),String(ch.tenor_m))}
      <div class="wizard-choices">${methods.map(([k,l,cap])=>`<label class="wizard-choice"><input type="radio" name="method" value="${k}" ${ch.method===k?'checked':''}><span><strong>${l}</strong><small>${cap}</small></span></label>`).join('')}</div>
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
      <div class="wizard-choices">${[['face','Ký bằng khuôn mặt'],['otp','Ký bằng mã OTP']].map(([v,l],i)=>`<label class="wizard-choice"><input type="radio" name="method" value="${v}" ${i?'':'checked'}><span>${l}</span></label>`).join('')}</div>
      <p id="read-timer" class="v4-muted" role="status">${left?`Còn ${left} giây đọc`:'Bạn có thể ký'}</p>${submit('Ký hợp đồng',left?'disabled id="sign-submit"':'id="sign-submit"')}</form>${button('rechoose','Chọn lại khoản vay')}`);
  }
  function outcome() {
    const a=state.app,k=key(),l=state.loan,currency=l?.currency || a.offer?.currency || a.currency;
    if(k==='view_loan') {
      const payee=l?.payee || a.payee || {};
      const destination=payee.to_supplier?`${num(payee.to_account)} đã vào tài khoản kinh doanh WeBank; ${num(payee.to_supplier)} trả thẳng nhà cung cấp ${copy(payee.supplier)}.`:'Tiền đã vào tài khoản kinh doanh WeBank của bạn.';
      return title('Đã giải ngân!',destination,`<p class="wizard-amount">${money(l?.amount,currency)}</p>${facts([['Kỳ trả đầu tiên',`${day(l?.first_due_date)} · ${money(l?.schedule?.[0]?.payment_est,currency)}`]])}<div class="wizard-actions">${button('view-loan','Xem khoản vay',true)}</div>`);
    }
    if(k==='reapply')return title('Hạn mức đã hết hiệu lực','Hạn mức chỉ có hiệu lực 7 ngày. Bạn có thể nộp hồ sơ mới với dữ liệu cập nhật.',`<div class="wizard-actions">${button('new','Nộp hồ sơ mới',true)}</div>`);
    if(k==='wait_officer')return title('Cán bộ sẽ xem hồ sơ','BuoyUp sẽ cập nhật khi có kết quả.',`<p>${a.expected_review_at?`Dự kiến: ${day(a.expected_review_at)}`:'Thời gian dự kiến sẽ được cập nhật khi cán bộ nhận hồ sơ.'}</p><div class="wizard-actions">${button('complaint-open','Gửi khiếu nại')}${button('refresh','Kiểm tra kết quả',true)}</div>`);
    if(['wait_banks','wait_payout'].includes(k))return title(k==='wait_payout'?'Đang giải ngân':'Các ngân hàng đang duyệt','Bạn có thể đóng và quay lại; hồ sơ vẫn được lưu.',`<p role="status">Đang chờ xác nhận kết quả…</p><div class="wizard-actions">${button('refresh','Kiểm tra kết quả',true)}</div>`);
    const reason=a.decision?.reason || a.verification?.reason;
    return title(statusNames[a.status] || 'Kết quả hồ sơ',reason?copy(reason.factor):'Hồ sơ cần cán bộ xem.',`${reason?.fix?`<p>${copy(reason.fix)}</p>`:''}${a.verification?.eligible_from?`<p>Có thể đủ điều kiện từ ${day(a.verification.eligible_from)}.</p>`:''}${a.status==='rejected'&&state.complaintChannel?`<p class="v4-muted">Không đồng ý với kết quả? Bạn có thể gửi khiếu nại ngay tại đây hoặc qua ${copy(state.complaintChannel)}.</p>`:''}<div class="wizard-actions">${a.status==='rejected'?button('complaint-open','Gửi khiếu nại'):''}${button('wizard-close','Về gian hàng',true)}</div>`);
  }
  function screen() {
    if(loading==='stores')return title('Đang đọc gian hàng','BuoyUp đang lấy thông tin cửa hàng của bạn.','<p role="status">Vui lòng đợi một chút…</p>');
    if(loading==='control')return title('Đang ký và giải ngân','Các ngân hàng chuyển vốn vào tài khoản trung gian tại WeBank, rồi giải ngân cho bạn.','<p role="status">Vui lòng đợi một chút…</p>');
    if(!state.app)return local.start==='welcome'?welcome():local.picker&&state.demo?demoPicker():stores();
    if(complaintOpen)return complaintScreen();
    if(key()==='identity'&&!local.confirmed)return confirmation();
    if(verifyReview)return checklist();
    return ({identity,consent,plan,verify:checklist,answer,select:choose,sign:contractScreen})[key()]?.() || outcome();
  }
  function renderWizard(focus=true) {
    if(!modalOpen)return;
    const active=document.activeElement,retain=!focus&&$('wizard-screen').contains?.(active);
    const expanded=!focus?[...$('wizard-screen').querySelectorAll('details[open]')].map(d=>d.querySelector('summary')?.textContent):[];
    const current=loading==='stores'?2:loading==='control'?9:!state.app?(local.start==='welcome'?1:2):verifyReview?6:({identity:local.confirmed?3:2,consent:4,plan:5,verify:6,answer:6,wait_banks:7,select:7,sign:8})[key()] || 9;
    $('wizard-count').textContent=`Bước ${current}/9`;$('wizard-progress').value=current;
    $('wizard-back').disabled=!!loading || (state.app&&['verify','wait_banks','wait_payout'].includes(key())&&!verifyReview);
    $('wizard-demo').hidden=!(state.demo || state.app?.simulated);
    $('wizard-screen').innerHTML=screen();
    syncChat();
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
      const bullet=/^\s*[*-]\s+(.*)$/.exec(line),num=/^\s*\d+\.\s+(.*)$/.exec(line),kind=bullet?'ul':num?'ol':null;
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
  const loanSignature=l=>l?JSON.stringify([l.status,l.outstanding,l.monitored_at,l.clock,l.account?.balance,(l.notices||[]).map(n=>[n.id,!!n.answer])]):'';
  setInterval(()=>{
    if(document.hidden||modalOpen||busy||!state.loan?.id)return;
    const id=state.loan.id;
    api(`/v4/loans/${encodeURIComponent(id)}`).then(l=>{
      if(state.loan?.id!==id||modalOpen||loanSignature(l)===loanSignature(state.loan))return;
      // Do not pull the page from under the seller: wait while they type, focus a control or read an open section.
      const main=$('workspace-main'),active=document.activeElement;
      if(active&&active!==main&&(main.contains(active)||active===$('chat-input')))return;
      if(main.querySelector('details[open]'))return;
      state.loan=l;renderHome();
    }).catch(()=>{});
  },60000);
  function loanChainText(record) {
    if(record?.simulated===true)return 'Giải ngân ghi trên sổ mô phỏng';
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
  const ROW_STATUS={upcoming:'Sắp tới',paid:'Đã trả',minimum:'Đã trả tối thiểu',overdue:'Quá hạn',paid_late:'Trả muộn',prepaid:'Đã trả trước'};
  function homeLoan() {
    const l=state.loan;if(!l)return `<p>Khoản vay đang được chuẩn bị. Hãy kiểm tra lại sau.</p>${button('refresh','Làm mới')}`;
    const c=l.currency,n=l.next_due,open=['active','overdue'].includes(l.status);
    const rows=`<table class="v4-schedule"><thead><tr><th>Kỳ</th><th>Ngày</th><th>Dự kiến</th><th>Trạng thái</th></tr></thead><tbody>${(l.schedule || []).map(r=>`<tr><td>${num(r.k)}</td><td>${day(r.due_date)}</td><td>${num(r.amount_due ?? r.payment_est)}</td><td>${esc(ROW_STATUS[r.status] || r.status)}${r.choice==='minimum'&&r.status==='upcoming'?' · tối thiểu':''}</td></tr>`).join('')}</tbody></table>`;
    const actions=open?`<div class="wizard-actions">${l.minimum?.allowed?button('loan-minimum',`Kỳ tới chỉ trả tối thiểu ${money(l.minimum.quote?.payment,c)}`):''}${button('loan-prepay',`Trả hết hôm nay ${money(l.prepay_quote?.total,c)}`)}</div>${l.minimum&&!l.minimum.allowed&&l.minimum.why?`<p class="v4-muted">${copy(l.minimum.why)}</p>`:''}`:'';
    const demo=state.demo&&open?details('Mô phỏng (demo)',`<p class="v4-muted">Giả lập tiền hàng về, chi tiêu từ tài khoản kinh doanh và thời gian trôi qua để xem hệ thống trích nợ, nhắc hạn, tính lãi phạt.</p><form data-form="inflow">${field('amount',`Tiền hàng về (${esc(c)})`,'','number','required min="1" step="1"')}${submit('Mô phỏng tiền về')}</form><form data-form="transfer">${field('amount',`Chi ra (${esc(c)})`,'','number','required min="1" step="1"')}${select('kind','Chi cho',['supplier','personal','other','securities','real_estate'],'supplier')}${submit('Mô phỏng chi tiền')}</form><form data-form="advance">${field('to','Đi tới ngày','', 'date',`required min="${esc(l.clock)}"`)}${submit('Cho thời gian trôi')}</form>`):'';
    return `${facts([['Số tiền vay',money(l.amount,c)],['Dư nợ gốc',money(l.principal_outstanding,c)],['Lãi suất năm',pct(l.rate)],['Hình thức',esc(l.method_label)],['Số dư tài khoản kinh doanh',money(l.account?.balance,c)],['Kỳ tới',n?`${day(n.due_date)} · khoảng ${money(n.payment_est,c)}`:'—']].concat(l.owed_now?[['Đang quá hạn',`<strong>${money(l.owed_now,c)}</strong> (${num(l.overdue_days)} ngày)`]]:[]).concat([['Ngày theo hệ thống',day(l.clock)]]))}
      <p id="home-loan-chain" class="home-loan-chain" ${loanChainCache.get(l.id)?'':'hidden'}>${loanChainCache.get(l.id) || ''}</p>${actions}<h3>Lịch trả</h3>${rows}${loanNotices(l)}<h3>Lịch sử trả nợ</h3>${l.repayments?.length?`<ul class="v4-repayments">${l.repayments.map(r=>`<li>${day(r.detail?.as_of || r.at)} · Đã trả ${money(r.amount,c)}${r.detail?` (lãi phạt ${num(r.detail.penalty)}, lãi ${num(r.detail.interest)}, gốc ${num(r.detail.principal)})`:''}</li>`).join('')}</ul>`:'<p>Chưa có lần trả nợ.</p>'}${l.status==='closed'?`<form data-form="receiving">${field('bank','Ngân hàng nhận tiền hàng mới',l.receiving_account?.bank,'text','required maxlength="60"')}${field('number','Số tài khoản',l.receiving_account?.number,'text','required pattern="[0-9]{6,20}"')}${submit('Đổi tài khoản nhận tiền hàng')}</form>`:''}${demo}`;
  }
  function homeLoanPanel() {
    const l=state.loan,urgent=(l?.notices || []).filter(urgentNotice);
    const alerts=urgent.length?`<div class="home-loan-alerts"><h3>BuoyUp cần bạn trả lời</h3><ul class="loan-notices">${urgent.map(loanNotice).join('')}</ul></div>`:'';
    return `<section class="home-loan-panel" aria-label="Khoản vay của bạn">${alerts}<details id="home-loan-details" class="home-loan-details" ${homeLoanExpanded?'open':''}><summary><strong>Khoản vay của bạn</strong>${l?`<span class="home-loan-preview">Đã vay ${money(l.amount,l.currency)}<br>Dư nợ gốc ${money(l.principal_outstanding,l.currency)}</span>`:''}</summary><div class="home-loan-content">${homeLoan()}</div></details></section>`;
  }
  function renderHome() {
    const previousDetails=$('home-loan-details');
    if(homeLoanAppId===state.app?.id&&typeof previousDetails?.open==='boolean')homeLoanExpanded=previousDetails.open;
    else {homeLoanAppId=state.app?.id;homeLoanExpanded=matchMedia('(min-width: 1100px)').matches;}
    parkChat();
    $('demo-banner').hidden=!(state.demo || state.app?.simulated);
    $('project-list').innerHTML=button('new','+ Hồ sơ vay mới');
    $('application-nav').innerHTML='<h2>Hồ sơ của bạn</h2>'+state.items.map(a=>`<button class="project-button ${a.id===state.app?.id?'active':''}" data-action="open" data-id="${esc(a.id)}"><span class="project-title">${copy(a.store_entity || 'Gian hàng của bạn')}</span><small>${esc(statusNames[a.status] || 'Đang cập nhật')}</small></button>`).join('');
    $('profile-nav').innerHTML='<h2>Hỗ trợ</h2><p>BuoyUp đồng hành cùng bạn qua từng bước.</p>';
    const a=state.app,on=chatOpen();
    const summary=!a?`<section class="v4-panel"><h2>Vốn cho mùa bán hàng</h2><p>Cùng xem bạn có thể vay bao nhiêu.</p>${button('resume','Bắt đầu',true)}</section>`:a.loan_id?homeLoanPanel():`<section class="v4-panel home-loan-panel"><h2>${esc(statusNames[a.status] || 'Hồ sơ của bạn')}</h2><p>${copy(a.stores?.[0]?.entity || 'Thông tin của bạn đã được lưu.')}</p>${button('resume',key()==='none'?'Xem kết quả':'Tiếp tục hồ sơ',true)}</section>`;
    $('workspace-main').classList.toggle('has-home-chat',on);
    $('workspace-main').innerHTML=`<div class="v4-wrap v4-home ${on?'chat-home':''}"><div class="v4-heading"><div><h1>Gian hàng của tôi</h1><p class="v4-muted">Chào ${copy(session.user.display_name)}, theo dõi hồ sơ và khoản vay tại đây.</p></div></div><div class="${on?'v4-home-grid':''}">${summary}${on?'<div id="home-chat-slot" class="home-chat-slot"></div>':''}</div>${complaintsPanel()}${a?`<p class="v4-muted complaint-link">Cần khiếu nại về hồ sơ hoặc khoản vay? ${button('complaint-home','Gửi khiếu nại')}</p>`:''}</div>`;
    BU.motion.init($('workspace-main'));
    if(!modalOpen)syncChat();
    loadLoanChain();
  }
  function showWizard() {
    returnFocus=document.activeElement;closeSidebar();modalOpen=true;notice('');
    if(!$('seller-wizard').open)$('seller-wizard').showModal();renderWizard();pump();
  }
  function closeWizard() {capture();modalOpen=false;complaintOpen=false;quoteSerial++;state.quotePending=false;clearTimeout(quoteTimer);clearTimeout(pollTimer);$('seller-wizard').close();renderHome();const target=returnFocus?.isConnected?returnFocus:$('workspace-main');target?.focus({preventScroll:true});}
  async function refreshList() {const data=await api('/v4/applications');state.items=data.items || [];await loadComplaints();}
  async function loadComplaints() {try{const c=await api('/v4/complaints');state.complaints=c.items || [];state.complaintChannel=c.channel || '';}catch(_) { /* The list stays as it was. */ }}
  // Review item 4: the complaint desk. The reasons recorded for the decision are attached by the server.
  function complaintScreen() {
    const a=state.app,s=a?.status,def=s==='rejected'?'rejection':a?.loan_id?'debit':s==='offered'||s==='selected'?'limit':'other';
    const reason=a?.decision?.reason;
    return title('Gửi khiếu nại','BuoyUp gửi kèm lý do đã ghi trong hồ sơ, xác nhận ngay và trả lời có lý do trong 5 ngày làm việc. Người xem xét là cán bộ khác người đã quyết định.',`${reason?`<p class="v4-muted">Lý do đã ghi: ${copy(reason.factor)}</p>`:''}<form data-form="complaint"><label class="v4-field">Nội dung khiếu nại<select name="category">${complaintCategories.map(([k,l])=>`<option value="${k}" ${k===def?'selected':''}>${l}</option>`).join('')}</select></label><label class="v4-field">Bạn muốn BuoyUp xem lại điều gì?<textarea name="text" rows="4" required minlength="5" maxlength="2000"></textarea></label>${state.complaintChannel?`<p class="v4-muted">Hoặc gọi ${copy(state.complaintChannel)}.</p>`:''}<div class="wizard-actions"><button class="btn" type="button" data-action="complaint-cancel">Quay lại</button><button class="btn btn-primary" type="submit">Gửi khiếu nại</button></div></form>`);
  }
  function complaintsPanel() {
    if(!state.complaints.length)return '';
    return `<section class="v4-panel complaints-panel"><h2>Khiếu nại của bạn</h2><ul class="complaint-list">${state.complaints.map(c=>`<li><strong>${esc(c.id)} · ${esc(c.category_label)}</strong><span class="bu-badge">${esc(complaintStatus[c.status] || c.status)}</span><p>${c.answer?copy(c.answer):`Trả lời trước ${day(c.answer_due)}${c.extension_note?` (gia hạn: ${copy(c.extension_note)})`:''}`}</p></li>`).join('')}</ul></section>`;
  }
  async function applyApp(a,restoreDraft=false) {
    const previous=key();state.app=a;state.quotePending=false;if(previous!==key()||state.selected?.appId!==a.id)state.selected=null;state.contract=null;
    if(restoreDraft)restore();else if(previous!==key()){local.key=key();local.consentStep=0;local.planStep=0;local.answer=null;consentDraft=null;consentBody=null;consentDraftAttempt=false;}
    if(!Object.keys(local.plan || {}).length && a.plan)local.plan={...(a.plan.suggested || a.plan)};
    state.loan=a.loan_id?await api(`/v4/loans/${encodeURIComponent(a.loan_id)}`):null;
    save();renderHome();renderWizard();
  }
  async function open(id,show=true) {
    const serial=++navigationSerial;quoteSerial++;clearTimeout(quoteTimer);clearTimeout(pollTimer);consentDraft=null;consentBody=null;consentDraftAttempt=false;verifyReview=false;verifyAttempt='';
    const a=await api(`/v4/applications/${encodeURIComponent(id)}`);if(serial!==navigationSerial)return;
    await applyApp(a,true);if(show)showWizard();
  }
  async function mutate(tail,body={},method='POST') {const a=await api(appPath(tail),method,body);await applyApp(a?.id&&a?.next_action?a:await api(appPath()));await refreshList();renderHome();renderWizard();}
  async function run(fn,control) {
    if(busy)return;busy=true;if(control)control.disabled=true;
    $('workspace-main').setAttribute('aria-busy','true');$('seller-wizard').setAttribute('aria-busy','true');notice('');
    try {await fn();}
    catch(error) {
      if(error.details?.fallback==='reg_no'){local.fallback=true;save();}
      if(error.details?.field==='face_verify_id'){local.identity.face=false;local.faceVerifyId=null;save();}
      if(error.code==='INVALID_STATE'&&state.app){try{await applyApp(await api(appPath()));}catch(_) { /* Keep the original error. */ }}
      loading='';renderWizard(false);notice(error.message,true);
    } finally {busy=false;loading='';$('workspace-main').removeAttribute('aria-busy');$('seller-wizard').setAttribute('aria-busy','false');if(control?.isConnected)control.disabled=false;renderWizard(false);pump();}
  }
  // Identity step: the camera re-checks the face registered at sign-up (1:1 + turn challenge).
  // Accounts without a registered face, or a server without the face model, keep the simulated tile.
  async function faceRecheck() {
    if(busy)return;busy=true;notice('');
    try {
      local.faceVerifyId=await window.BU.face.verify();local.identity.face=true;
    } catch(error) {
      if(error.code==='FACE_UNAVAILABLE'||error.code==='FACE_NOT_ENROLLED'){local.faceVerifyId=null;local.identity.face=true;}
      else if(error.code!=='CANCELLED')notice(error.message,true);
    } finally {busy=false;save();renderWizard(false);}
  }
  async function draftConsent() {
    consentDraftAttempt=true;
    consentBody={scopes:scopes.map(s=>s.key),method:local.signMethod || 'face'};
    consentDraft=await api(appPath('/consent/draft'),'POST',consentBody);
    if(consentDraft.alg!=='ed25519'||typeof consentDraft.message!=='string'||!consentDraft.document)throw new Error('Bản ủy quyền chưa hợp lệ. Vui lòng thử lại.');
    local.consentStep=2;save();renderWizard();
  }
  function pump() {
    clearTimeout(pollTimer);if(!modalOpen||busy||!state.app)return;
    if(key()==='verify'&&!verifyAttempt){verifyAttempt=state.app.id;run(async()=>{await mutate('/verify');verifyReview=key()!=='verify';renderWizard();});return;}
    if(key()==='consent'&&local.consentStep===2&&!consentDraft&&!consentDraftAttempt){run(draftConsent);return;}
    if(['wait_banks','wait_payout','wait_officer'].includes(key()))pollTimer=setTimeout(()=>run(async()=>{await applyApp(await api(appPath()));}),6000);
    if(key()==='select'&&!state.selected&&!state.quotePending)requestQuote();
    if(key()==='sign'&&!state.contract&&!busy)run(openContract);
  }
  function back() {
    if(busy||loading)return;capture();notice('');
    if(!state.app){if(local.picker)local.picker=false;else if(local.start==='stores')local.start='welcome';else{closeWizard();return;}}
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
    if(action==='complaint-open'){complaintOpen=true;renderWizard();return;}
    if(action==='complaint-home'){complaintOpen=true;showWizard();return;}
    if(action==='complaint-cancel'){complaintOpen=false;renderWizard();return;}
    if(action==='new'){capture();navigationSerial++;quoteSerial++;clearTimeout(quoteTimer);verifyReview=false;verifyAttempt='';consentDraft=null;consentBody=null;state.app=null;state.loan=null;restore();renderHome();showWizard();return;}
    if(action==='wizard-next') {if(verifyReview){verifyReview=false;}else if(key()==='consent')local.consentStep++;save();renderWizard();pump();return;}
    if(action==='confirm-store'){if(local.confirmIndex<(state.app.stores?.length || 1)-1)local.confirmIndex++;else local.confirmed=true;save();renderWizard();return;}
    if(action==='wrong-store'){const urls=state.app.stores?.map(s=>s.url) || [''];state.app=null;state.loan=null;restore();local.start='stores';local.urls=urls;save();renderHome();renderWizard();return;}
    if(action==='store-add'){capture();if(local.urls.length<5)local.urls.push('');save();renderWizard(false);$('store-links').querySelectorAll('input')[local.urls.length-1]?.focus();return;}
    if(action==='demo-picker'){if(!state.demo)return;capture();local.picker=!local.picker;save();renderWizard();return;}
    if(action==='demo'){local.urls=[state.stores[Number(b.dataset.index)].url];local.picker=false;save();renderWizard(false);$('store-links').querySelector('input')?.focus();return;}
    if(action==='statement-add'){capture();if((local.statements || []).length<6){local.statements=[...(local.statements || []),{month:'',revenue:''}];while(local.statements.length<4)local.statements.push({month:'',revenue:''});}save();renderWizard(false);return;}
    if(action==='identity-tile'&&b.dataset.key==='face'&&window.BU.face){faceRecheck();return;}
    if(action==='identity-tile'){local.identity[b.dataset.key]=true;save();renderWizard(false);return;}
    run(async()=>{
      if(action==='open')await open(b.dataset.id);
      if(action==='refresh'){await applyApp(await api(appPath()));await refreshList();renderHome();}
      if(action==='notice-answer'){state.loan=await api(`/v4/loans/${encodeURIComponent(state.loan.id)}/notices/${encodeURIComponent(b.dataset.notice)}/answer`,'POST',{choice:b.dataset.choice});renderHome();notice('Cảm ơn bạn, BuoyUp đã ghi nhận.');}
      if(action==='identity')await mutate('/identity',{cccd:local.identity.cccd,face:local.identity.face,...(local.faceVerifyId?{face_verify_id:local.faceVerifyId}:{})});
      if(action==='consent-draft')await draftConsent();
      if(action==='verify'){verifyAttempt=state.app.id;await mutate('/verify');verifyReview=key()!=='verify';}
      if(action==='human')await mutate('/request-human',{reason:'Người bán muốn cán bộ hỗ trợ xem xét hồ sơ.'});
      if(action==='rechoose'){state.contract=null;await mutate('/select',local.choice);}
      if(action==='loan-minimum'){state.loan=await api(`/v4/loans/${encodeURIComponent(state.loan.id)}/minimum`,'POST',{});renderHome();notice('Kỳ tới bạn chỉ trả mức tối thiểu.');}
      if(action==='loan-prepay'){state.loan=await api(`/v4/loans/${encodeURIComponent(state.loan.id)}/prepay`,'POST',{});await applyApp(await api(appPath()));await refreshList();renderHome();notice('Đã trả trước, không mất phí.');}
    },b);
  });
  document.addEventListener('submit',event=>{
    const form=event.target.closest('[data-form]');if(!form)return;event.preventDefault();
    const fd=new FormData(form),data=Object.fromEntries(fd);
    if(form.dataset.form==='welcome'){local.tier=Number(data.tier);local.borrower_type=data.borrower_type || local.borrower_type;local.start='stores';save();renderWizard();return;}
    run(async()=>{
      switch(form.dataset.form){
        case 'stores': {
          local.urls=fd.getAll('store_url').map(v=>v.trim()).filter(Boolean);local.reg_no=data.reg_no?.trim() || '';save();
          if(!local.urls.length&&!local.reg_no)throw new Error('Dán ít nhất một link gian hàng.');
          if(local.urls.length>5)throw new Error('Vui lòng nhập tối đa 5 gian hàng.');
          const body={tier:local.tier,borrower_type:local.borrower_type || 'individual_business',store_urls:local.fallback&&local.reg_no?[]:local.urls};if(local.reg_no)body.reg_no=local.reg_no;
          loading='stores';renderWizard();const a=await api('/v4/applications','POST',body);loading='';local.confirmed=false;local.key=a.next_action.key;await applyApp(a);await refreshList();renderHome();break;
        }
        case 'consent-boxes': {
          local.boxes=Object.fromEntries(scopes.map(x=>[x.key,fd.has(x.key)]));local.signMethod=data.method || 'face';save();
          if(!scopes.every(x=>local.boxes[x.key]))throw new Error('Cần đánh dấu đủ ba ô đồng ý.');
          await draftConsent();break;
        }
        case 'sign-consent': {
          if(!fd.has('confirm'))throw new Error('Vui lòng xác nhận đồng ý ủy quyền.');
          if(!consentDraft||!consentBody)throw new Error('Vui lòng quay lại để lấy bản ủy quyền.');
          const subtle=window.crypto?.subtle;if(!subtle)throw new Error('Cần HTTPS hoặc localhost để ký ủy quyền.');
          let signingKey;try{signingKey=await subtle.generateKey({name:'Ed25519'},false,['sign','verify']);}catch(_){throw new Error('Vui lòng dùng trình duyệt mới có hỗ trợ ký ủy quyền.');}
          const hex=buffer=>Array.from(new Uint8Array(buffer),b=>b.toString(16).padStart(2,'0')).join('');
          const sig=await subtle.sign('Ed25519',signingKey.privateKey,new TextEncoder().encode(consentDraft.message));
          const publicKey=await subtle.exportKey('raw',signingKey.publicKey);
          await mutate('/consent',{...consentBody,signature:{alg:'ed25519',public_key:hex(publicKey),sig:hex(sig)}});break;
        }
        case 'plan-step': {
          local.plan={...local.plan,...data};save();
          local.planStep++;save();renderWizard();break;
        }
        case 'statements': {
          local.statements=readStatements(fd);save();
          const p={...local.plan};delete p.suggested;delete p.submitted;delete p.statements;
          ['qty','price','inventory','own_capital','other_loans'].forEach(k=>p[k]=Number(p[k]));p.flavor=p.flavor || null;
          if(local.statements.length)p.statements=local.statements.map(r=>({month:r.month,revenue:Number(r.revenue)}));
          await mutate('/plan',p,'PUT');break;
        }
        case 'choice': {
          local.choice=readChoice(fd);save();
          await mutate('/select',local.choice);break;
        }
        case 'sign': {
          const body={read_ack:fd.has('read_ack'),webank_account:String(data.webank_account || '').trim(),use_of_funds_commitment:fd.has('use_of_funds_commitment'),guarantee:fd.has('guarantee'),method:data.method || 'face'};
          if(data.supplier_account)body.supplier_account=data.supplier_account.trim();
          loading='control';renderWizard();await mutate('/sign',body);break;
        }
        case 'complaint': {
          const body={category:data.category,text:String(data.text || '').trim()};
          if(body.text.length<5)throw new Error('Mô tả ngắn nội dung khiếu nại (ít nhất 5 ký tự).');
          if(state.app?.id)body.application_id=state.app.id;if(state.loan?.id)body.loan_id=state.loan.id;
          const c=await api('/v4/complaints','POST',body);complaintOpen=false;await loadComplaints();renderHome();renderWizard();
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
  document.addEventListener('change',event=>{
    if(event.target.name==='choice'&&event.target.closest('[data-form="answer"]')){capture();renderWizard(false);[...$('wizard-screen').querySelectorAll('[name="choice"]')].find(input=>input.value===event.target.value)?.focus();}
  });
  function requestQuote() {
    if(!state.app?.offer)return;
    const ch=local.choice || {amount:state.app.offer.suggested || state.app.offer.limit,tenor_m:state.app.offer.tenor_max,method:'installment',due_day:10};
    const serial=++quoteSerial,id=state.app.id;
    clearTimeout(quoteTimer);state.quotePending=true;
    quoteTimer=setTimeout(async()=>{
      try {
        const q=await api(`/v4/applications/${encodeURIComponent(id)}/quote`,'POST',{amount:ch.amount,tenor_m:ch.tenor_m,method:ch.method,due_day:Math.min(28,Math.max(1,ch.due_day || 10))});
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
  $('chat-suggest').addEventListener('click',event=>{const b=event.target.closest('[data-chat-suggest]');if(b)sendChat(b.dataset.chatSuggest);});
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
  $('sidebar-width').addEventListener('input',event=>document.body.style.setProperty('--sidebar-width',event.target.value+'px'));
  $('logout').addEventListener('click',()=>run(async()=>{await BU.api.auth.logout();BU.session.clear();location.assign('login.html');},$('logout')));
  $('account-name').textContent=session.user.display_name;$('account-role').textContent='Người bán';
  restore();
  run(async()=>{
    const me=await api('/v4/auth/me');BU.session.set({...session,user:me.user});
    if(me.user.role!=='seller'){location.assign(BU.session.home(me.user.role));return;}
    session.user=me.user;state.profile=me.demo_profile || null;$('account-name').textContent=me.user.display_name;
    const responses=await Promise.all([api('/v4/applications'),api('/v4/public/demo-stores').catch(error=>{if(error.status===404)return null;throw error;})]);
    state.items=responses[0].items || [];state.stores=responses[1]?.stores || [];state.demo=!!responses[1];
    const unfinished=state.items.find(a=>!['disbursed','repaying','closed','rejected','out_of_scope'].includes(a.status));
    if(unfinished)await open(unfinished.id);
    else if(state.items.length)await open(state.items[0].id,false);
    else {restore();renderHome();showWizard();}
  });
})();
