/* BuoyUp v4 staff console. Financial values come exclusively from API responses. */
(function () {
  'use strict';
  const session = BU.requireRole(['officer', 'admin']);
  if (!session) return;
  let admin = session.user.role === 'admin';
  const $ = id => document.getElementById(id);
  const esc = v => String(v == null ? '—' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = (v, c) => v == null ? '—' : new Intl.NumberFormat('vi-VN').format(v) + (c ? ' ' + c : '');
  const pct = v => v == null ? '—' : new Intl.NumberFormat('vi-VN', {style:'percent', maximumFractionDigits:2}).format(v);
  const statuses = {draft:'Bản nháp',identified:'Đã định danh',consented:'Đã ủy quyền',verifying:'Đang xác minh',verified:'Đã xác minh',offered:'Ngân hàng đã duyệt hạn mức',in_control:'Đang kiểm soát',selected:'Đã chọn, chờ ký',signed:'Đã ký, đang giải ngân',expired:'Hạn mức hết hiệu lực',no_partner:'Không ngân hàng nào nhận',paid:'Đã trả',minimum:'Trả tối thiểu',upcoming:'Sắp tới',paid_late:'Trả muộn',prepaid:'Trả trước',timeout:'Quá 30 giây',decline:'Từ chối',not_sent:'Không gửi',disbursed:'Đã giải ngân',repaying:'Đang trả',closed:'Đã tất toán',rejected:'Đã từ chối',escalated:'Chờ cán bộ',needs_answer:'Cần trả lời',out_of_scope:'Ngoài phạm vi',active:'Hoạt động',overdue:'Quá hạn',ok:'Đạt',fail:'Không đạt',warn:'Cần chú ý',pending:'Chờ xử lý',skip:'Bỏ qua',open:'Đang mở',resolved_by_check:'Đã kiểm chứng',explained_unverified:'Đã giải thích, chưa kiểm chứng',hard:'Vi phạm bắt buộc',green:'Xanh · Thấp',yellow:'Vàng · Vừa',red:'Đỏ · Cao',up:'Hoạt động',down:'Gián đoạn',true:'Đạt',false:'Không đạt',approve:'Duyệt',reject:'Từ chối',smaller:'Giảm phương án',escalate:'Chuyển cán bộ',VERIFIED:'Đã xác minh',REJECTED:'Đã từ chối',OUT_OF_SCOPE:'Ngoài phạm vi',ESCALATED:'Chờ cán bộ'};
  const badge = v => {
    const tone=['rejected','reject','fail','hard','red','overdue',false].includes(v)?'badge-bad':['warn','yellow','escalated','escalate','needs_answer','pending','open'].includes(v)?'badge-warn':['approve','approved','disbursed','closed','ok','green','VERIFIED',true].includes(v)?'badge-ok':'badge-muted';
    return '<span class="badge '+tone+'">'+esc(statuses[v] || v)+'</span>';
  };
  const json = (v, title = 'Dữ liệu chi tiết') => '<details><summary>' + esc(title) + '</summary><pre>' + esc(JSON.stringify(v, null, 2)) + '</pre></details>';
  const btn = (label, action, id = '') => '<button type="button" class="btn btn-sm" data-action="' + action + '" data-id="' + esc(id) + '">' + esc(label) + '</button>';
  const label = code => (window.OFFICER_LABELS || {})[code] || code;
  const items = data => Array.isArray(data) ? data : data && data.items || [];
  const table = (headers, rows) => rows.length ? '<div class="table-wrap"><table><thead><tr>' + headers.map(x => '<th>' + esc(x) + '</th>').join('') + '</tr></thead><tbody>' + rows.map(row => '<tr>' + row.map(x => '<td>' + x + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>' : '<p class="empty">Chưa có dữ liệu.</p>';
  const facts = data => '<dl class="v4-facts">' + Object.entries(data || {}).map(([k,v]) => '<div><dt>' + esc(label(k)) + '</dt><dd>' + (v && typeof v === 'object' ? json(v) : esc(v)) + '</dd></div>').join('') + '</dl>';
  const api = (path, method = 'GET', body) => BU.api.request('/v4' + path, {method, body});
  const empty = '<p class="empty">Chưa khả dụng trên máy chủ này.</p>';
  const CASE_TABS=[['flow','Toàn bộ luồng'],['a1','Agent 1'],['algo','Thuật toán'],['a2','Agent 2'],['a3','Agent 3'],['gate','Cổng'],['chain','Chuỗi']];
  const state = {banks:[], regions:[], app:null, messages:[], trace:{}, flow:null, flowLoading:false, flowError:null, keys:[], withdrawal:null, chain:null, tab:'flow', timer:null, step:0, returnFocus:null, navigation:0, sellerTimer:null, sellerRequest:0};
  function notice(text, error) {
    $('board-notice').textContent = text; $('board-notice').className = error ? 'notice v4-error' : 'notice';
    const modal=$('drawer-notice');
    if(modal && !$('drawer').hidden){modal.textContent=text;modal.hidden=!text;modal.className=error?'notice v4-error':'notice';}
  }
  async function panel(id, path, render) { try { const data = await api(path); $(id).innerHTML = render(data); return data; } catch(e) { $(id).innerHTML = e.status === 404 ? empty : '<p class="v4-error">' + esc(e.message) + '</p>'; } }
  async function action(task, button) { if(button && button.disabled)return; if(button) button.disabled = true; try { await task(); } catch(e) { notice(e.status === 404 ? 'Chức năng này chưa khả dụng trên máy chủ.' : e.message+(Array.isArray(e.details?.problems)?' '+e.details.problems.join(' '):''), true); } finally { if(button && button.isConnected) button.disabled = false; } }
  const appRows = data => table(['Hồ sơ / người bán','Trạng thái','Đề nghị / đề xuất','Hạng','Cờ mở','Lý do / cập nhật'], items(data).map(a => [btn(a.code || a.id,'case',a.id)+'<br>'+esc(a.seller_name || a.store_entity)+'<br><span class="v4-chain-note">'+esc(a.seller_email)+'</span>',badge(a.status),esc(money(a.amount_requested,a.currency))+' / '+esc(money(a.amount_offered,a.currency)),esc(a.grade),esc(a.flags_open),esc(label(a.why || ''))+'<br>'+esc(a.updated_at)]));
  async function loadApplications() {
    const serial=++state.sellerRequest, seller=$('seller-filter').value.trim();
    $('credit-apps').setAttribute('aria-busy','true');
    try {
      const data=await api('/applications'+(seller?'?seller='+encodeURIComponent(seller):''));
      if(serial!==state.sellerRequest)return;
      $('credit-count').textContent=items(data).length;
      $('credit-apps').innerHTML=items(data).length?appRows(data):'<p class="empty">Không có hồ sơ phù hợp.</p>';
    } catch(e) {
      if(serial!==state.sellerRequest)return;
      $('credit-count').textContent='';
      $('credit-apps').innerHTML='<p class="v4-error">'+esc(e.message)+'</p>';
    } finally { if(serial===state.sellerRequest)$('credit-apps').setAttribute('aria-busy','false'); }
  }
  // Review item 4: the complaint desk queue (deadline first; overdue ones flagged).
  const COMPLAINT_STATUS={acknowledged:'Đã tiếp nhận',in_review:'Đang xem',escalated:'Quá hạn · trưởng nhóm',answered:'Đã trả lời'};
  async function loadComplaints() { await panel('complaints','/complaints',d=>{
    const list=items(d);$('complaints-count').textContent=list.filter(c=>c.status!=='answered').length;
    if(!list.length)return '<p class="empty">Chưa có khiếu nại.</p>';
    return table(['Mã','Nội dung','Hồ sơ','Trạng thái','Hạn trả lời','Lý do đã ghi','Thao tác'],list.map(c=>{
      const mine=c.assigned_to===session.user.id, open=c.status!=='answered';
      const act=!open?esc(c.outcome_label)+'<br><span class="v4-chain-note">'+esc(c.answer)+'</span>'
        :!c.assigned_to||(!mine&&c.status==='escalated')?btn('Nhận xem','complaint-assign',c.id)
        :mine?'<form class="v4-form complaint-answer" data-complaint="'+esc(c.id)+'"><label class="sr-only" for="co-'+esc(c.id)+'">Kết quả</label><select id="co-'+esc(c.id)+'" name="outcome"><option value="upheld">Giữ nguyên</option><option value="changed">Điều chỉnh</option><option value="reopened">Mở lại hồ sơ</option></select><label class="sr-only" for="ct-'+esc(c.id)+'">Trả lời</label><textarea id="ct-'+esc(c.id)+'" name="text" rows="2" minlength="10" required placeholder="Trả lời kèm lý do"></textarea><button class="btn btn-sm btn-primary" type="submit">Gửi trả lời</button></form>'
        :'<span class="v4-chain-note">Cán bộ khác đang xem</span>';
      const reason=c.reasons?.reason;
      return [esc(c.id)+'<br><span class="v4-chain-note">'+esc(c.channel)+'</span>',esc(c.category_label)+'<br><span class="v4-chain-note">'+esc(c.text)+'</span>',
        c.application_id?btn('Mở hồ sơ','case',c.application_id):'—','<span class="badge '+(c.overdue||c.status==='escalated'?'badge-bad':c.status==='answered'?'badge-ok':'badge-warn')+'">'+esc(c.overdue&&c.status!=='escalated'?'Quá hạn':COMPLAINT_STATUS[c.status]||c.status)+'</span>',
        esc(new Date(c.answer_due).toLocaleDateString('vi-VN')),reason?esc(reason.factor):'—',act];}));
  }); }
  function submitSellerFilter() { clearTimeout(state.sellerTimer);state.sellerTimer=null;return loadApplications(); }
  async function load() {
    notice('Đang tải dữ liệu v4…');
    await Promise.allSettled([
      panel('applications','/officer/queue', d => { $('queue-count').textContent = items(d).length; return appRows(d); }),
      submitSellerFilter(), loadComplaints(),
      loadPortfolio(), loadLoans(), loadBanks(), loadChain(), loadPostaudit(),
      ...(admin ? [loadUsers(),panel('audit','/admin/audit', d => table(['Thời điểm','Vai trò','Sự kiện','Chi tiết'],items(d).map(x => [esc(x.at),esc(x.actor),esc(x.summary || x.kind),json(x)])))] : [])
    ]);
    await loadManual();
    $('updated-at').textContent = 'Đã cập nhật ' + new Date().toLocaleTimeString('vi-VN');
    notice('Dữ liệu tài chính do API cung cấp. Mọi thao tác được ghi vào nhật ký.');
  }
  async function loadPortfolio() {
    try { const p = await api('/portfolio'), k = p.kpis || {};
      $('kpis').innerHTML = [['loans_active','Khoản vay hoạt động'],['outstanding','Dư nợ'],['disbursed_total','Đã giải ngân'],['approval_rate','Tỷ lệ duyệt'],['avg_amount','Khoản vay bình quân'],['red_alerts','Cảnh báo đỏ']].map(([key,title]) => '<div class="kpi"><div class="kpi-label">'+title+'</div><div class="kpi-value">'+(key==='approval_rate'?pct(k[key]):money(k[key],['loans_active','red_alerts'].includes(key)?null:p.currency))+'</div></div>').join('');
      $('alliance').innerHTML = table(['Ngân hàng','Dư nợ','Tỷ trọng'],(p.by_bank||[]).map(b=>[esc(b.bank),money(b.outstanding,b.currency),'<meter min="0" max="1" value="'+Number(b.share_pct || 0)+'" aria-label="Tỷ trọng"></meter> '+pct(b.share_pct)]));
      $('risk').innerHTML = table(['Hạng','Khoản vay','Dư nợ'],(p.by_grade||[]).map(x=>[esc(x.grade),esc(x.count ?? x.loans),money(x.outstanding ?? x.exposure,x.currency)]));
      $('events').innerHTML = table(['Sự kiện','Dư nợ','Thiếu hụt 50%','Tỷ lệ thiếu hụt'],(p.by_event||[]).map(x=>[esc(x.event),money(x.exposure,x.currency),money(x.shortfall_50pct,x.currency),pct(x.shortfall_ratio)]));
      $('auto-approval').innerHTML = p.auto_approval ? table(['Nhóm','Tỷ lệ nợ xấu','Duyệt tự động'],p.auto_approval.map(x=>[esc(x.group || x.key),pct(x.npl_ratio),badge(x.enabled?'Bật':'Tắt')+(admin?btn(x.enabled?'Tắt':'Bật','auto',x.group || x.key).replace('data-action="auto"','data-action="auto" role="switch" aria-checked="'+Boolean(x.enabled)+'"'):'')])) : empty;
      state.auto = p.auto_approval || [];
    } catch(e) { $('kpis').innerHTML = '<p class="v4-error">'+esc(e.message)+'</p>'; }
  }
  // Agents 4 and 5 run on their own in the backend (autopilot); show when and what they found.
  const clock=v=>{if(!v)return '—';const d=new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(v)?v:v+'Z');return isNaN(d)?esc(v):d.toLocaleString('vi-VN',{hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit'});};
  const every=s=>s>=3600?(s/3600).toLocaleString('vi-VN')+' giờ':Math.round(s/60)+' phút';
  async function loadAutopilot() {
    try {
      const a=await api('/autopilot/status'),off=a.enabled?'':' '+badge('Đang tắt');
      $('autopilot-a4').innerHTML=badge('Tự chạy')+off+' Agent 4 tự giám sát mỗi '+every(a.agent4.interval_seconds)+' và ngay khi tiền về. Lần gần nhất: '+clock(a.agent4.last_run_at)+(a.agent4.last_run_at?' ('+esc(a.agent4.loans)+' khoản vay, '+esc(a.agent4.alerts)+' cảnh báo)':'')+' · lần tới: '+clock(a.agent4.next_run_at)+(a.agent4.error?' · <span class="v4-error">'+esc(a.agent4.error)+'</span>':'');
      $('autopilot-a5').innerHTML=badge('Tự chạy')+off+' Agent 5 tự hậu kiểm mỗi '+every(a.agent5.interval_seconds)+', sớm hơn khi có khoản tất toán hoặc cảnh báo đỏ. Lần gần nhất: '+clock(a.agent5.last_run_at)+(a.agent5.report_id?' ('+esc(a.agent5.proposals)+' đề xuất)':'')+(a.agent5.skipped?' · '+esc(a.agent5.skipped):'')+(a.agent5.due_reason?' · sắp chạy vì '+esc(a.agent5.due_reason):'')+' · lần tới: '+clock(a.agent5.next_run_at)+(a.agent5.error?' · <span class="v4-error">'+esc(a.agent5.error)+'</span>':'');
    } catch(_) { /* staff-only status; the panels still work without it */ }
  }
  async function loadLoans() {
    loadAutopilot();
    await Promise.allSettled([
      panel('credit-loans','/loans',d=>table(['Khoản vay','Người bán','Số tiền','Dư nợ','Cảnh báo','Sử dụng vốn'],items(d).map(x=>[btn(x.application_code || x.id,'loan',x.id),esc(x.seller_name),money(x.amount,x.currency),money(x.outstanding,x.currency),badge((x.early_warning||{}).level || x.status),esc((x.use_of_funds||{}).status)]))),
      panel('watchlist','/alerts',d=>table(['Mức','Nội dung','Tín hiệu','Thao tác'],items(d).map(x=>[badge(x.level),esc(x.text),json(x.signals),x.acked?badge('Đã xác nhận'):btn('Xác nhận','ack',x.id)])))
    ]);
  }
  function openDrawer(title, subtitle, html, tabs = false) { state.returnFocus = document.activeElement; $('drawer-title').textContent=title; $('drawer-sub').textContent=subtitle || ''; $('drawer-body').innerHTML=html; $('drawer-notice').hidden=true; $('tabs').hidden=!tabs; if(!tabs){$('drawer-body').removeAttribute('role');$('drawer-body').removeAttribute('aria-labelledby');} $('drawer').hidden=false; $('drawer-backdrop').hidden=false; document.body.style.overflow='hidden'; $('drawer-close').focus(); }
  function closeDrawer() { state.navigation++; $('drawer').hidden=true; $('drawer-backdrop').hidden=true; document.body.style.overflow=''; if(state.returnFocus && state.returnFocus.isConnected) state.returnFocus.focus(); }
  const LEVELS={approve:'Đồng ý',smaller:'Phương án nhỏ hơn',escalate:'Chuyển cán bộ',reject:'Từ chối',warn:'Cảnh báo'};
  async function openCase(id) {
    const serial=++state.navigation, path='/applications/'+encodeURIComponent(id);
    const [app, messages, trace] = await Promise.all([api(path),api(path+'/messages').catch(e=>{if(e.status===404)return {items:[],unavailable:true};throw e;}),api(path+'/trace').catch(e=>{if(e.status===404)return {chain:[],unavailable:true};throw e;})]);
    if(serial!==state.navigation)return;
    state.app=app;state.messages=items(messages);state.messagesUnavailable=messages.unavailable;state.trace=trace;state.tab='flow';state.flow=null;state.flowError=null;state.flowLoading=true;
    openDrawer(app.code || app.id, statuses[app.status]||app.status,'',true);renderCase();
    try { const flow=await api(path+'/flow');if(serial===state.navigation)state.flow=flow; }
    catch(e) { if(serial===state.navigation)state.flowError=e.status===404?'Luồng tính toán chưa khả dụng trên máy chủ này.':e.message; }
    finally { if(serial===state.navigation){state.flowLoading=false;if(state.tab==='flow')renderCase();} }
  }
  // HANDOVER 16.7: how far each source of Agent 1's record is checked, and the store connection behind the case.
  const EVIDENCE_SOURCES=[['store','Trang cửa hàng'],['registry','Đăng ký kinh doanh'],['identity','Người vay là chủ cửa hàng'],['revenue','Doanh thu']];
  const EVIDENCE_LEVELS={platform_oauth:'Đăng nhập sàn (OAuth)',registered_phone_otp:'Mã gửi tới số điện thoại đăng ký của cửa hàng',registry_lookup:'Tra cứu đăng ký kinh doanh',self_declared:'Người vay tự khai',sample_data:'Dữ liệu mẫu'};
  const VIA={otp_registered_phone:'Mã gửi tới số điện thoại đăng ký của cửa hàng',oauth:'Đăng nhập sàn (OAuth)'};
  function evidenceBlock(a,v){
    const ev=v.evidence;if(!ev)return '';
    const c=a.shop_connection,r=(a.identity||{}).result||{};
    const checks={match:'Khớp',mismatch:'Không khớp',not_comparable:'Không so được',no_card:'Chưa có CCCD'};
    const rows=EVIDENCE_SOURCES.map(([k,l])=>[esc(l),esc(EVIDENCE_LEVELS[ev[k]]||ev[k]||'—')]);
    return '<h3>Mức kiểm chứng</h3>'+table(['Nguồn','Mức kiểm chứng'],rows)
      +(c?'<p class="v4-muted">Kết nối cửa hàng '+esc(c.id)+' · '+esc(VIA[c.verified_via]||c.verified_via)+(c.phone_masked?' '+esc(c.phone_masked):'')+' · '+esc(String(c.verified_at||'').slice(0,16).replace('T',' '))+'</p>':'<p class="v4-muted">Hồ sơ không có kết nối cửa hàng.</p>')
      +(r.ownership?'<p class="v4-muted">Tên trên CCCD: '+esc(checks[r.name_check]||r.name_check)+' · 4 số cuối CCCD: '+esc(checks[r.id_tail_check]||r.id_tail_check)+' · Tài khoản quyết toán đứng tên chủ thể: '+(r.account_owner_match==null?'Không có dữ liệu':r.account_owner_match?'Có':'Không')+'</p>':'');
  }
  function renderCase() {
    const a=state.app,v=a.verification||{},o=a.offer||{},c=a.control||{};
    $('tabs').innerHTML=CASE_TABS.map(([id,title])=>'<button type="button" class="tab '+(state.tab===id?'is-active':'')+'" role="tab" id="case-tab-'+id+'" aria-controls="drawer-body" tabindex="'+(state.tab===id?'0':'-1')+'" aria-selected="'+(state.tab===id)+'" data-case-tab="'+id+'">'+title+'</button>').join('');
    let html='';
    if(state.tab==='flow')html=renderFlow();
    if(state.tab==='a1') html=badge(v.state||a.status)+'<ol class="v4-stepper">'+(v.steps||[]).map(s=>'<li><strong>'+esc(s.n)+'. '+esc(s.title)+'</strong> '+badge(s.status)+'<code>'+esc(s.tool)+'</code><p>'+esc(s.summary)+'</p></li>').join('')+'</ol>'+evidenceBlock(a,v)+'<h3>Cờ xác minh</h3>'+table(['Mã','Trạng thái','Hệ quả','Bằng chứng'],(v.flags||[]).map(f=>[esc(label(f.code)),badge(f.status),esc(f.penalty || f.note),'<a href="#tool-'+esc(f.evidence_tool_call)+'">'+esc(f.evidence_tool_call)+'</a>']))+'<h3>Lời gọi công cụ</h3>'+(v.tool_calls||[]).map(t=>'<article id="tool-'+esc(t.id)+'" class="v4-ledger"><strong>'+esc(t.id)+' · '+esc(t.tool)+'</strong> '+json({input:t.input,output:t.output,at:t.at})+'</article>').join('')+json(v.llm_notes || a.llm_notes,'Ghi chú nội bộ')+facts({record_hash:v.record_hash,chain_tx:v.chain_tx});
    if(state.tab==='algo') html='<p>Dữ liệu các khối do lõi tính toán trả về.</p>'+table(['Khối','Đầu ra'],Object.entries(o.blocks||{}).map(([k,b])=>['<span id="block-'+esc(k)+'">'+esc(k)+'</span>',facts(b)]))+'<h3>Từ số xin đến phương án</h3>'+facts({'Số xin':money(o.requested,o.currency),'Nhu cầu':money((o.blocks||{}).B3?.need,o.currency),'Khả năng trả':money((o.blocks||{}).B8?.affordability,o.currency),'Hạn mức':money(o.limit,o.currency),'Gợi ý vay vừa đủ':money(o.suggested,o.currency),'Điểm':o.score,'Hạng trước':o.blocks?.B6?.grade_before,'Hạng sau':o.grade})+table(['Lý do','Khối','Tác động'],(o.reason_codes||[]).map(x=>[esc(x.text),esc(x.block),money(x.impact,o.currency)]))+json(o.points,'Điểm từng tiêu chí');
    if(state.tab==='a2') html=(state.messagesUnavailable?empty:'')+'<h3>Lý do đề xuất</h3>'+(a.proposal?.rationale||[]).map(r=>'<p>'+esc(r.claim)+' <button class="btn btn-sm" data-evidence="'+esc(r.evidence_ref)+'">'+esc(r.evidence_ref)+'</button></p>').join('')+'<div class="admin-chat">'+state.messages.map(m=>'<article class="admin-message '+(m.from==='seller'?'is-user':'')+'"><strong>'+esc(m.from)+'</strong><p class="message-prose">'+esc(m.text)+'</p>'+((m.blocked_numbers>0)?badge('Số liệu bị chặn: '+m.blocked_numbers):'')+(m.card?json(m.card,'Phiếu phương án'):'')+'</article>').join('')+'</div>';
    if(state.tab==='a3') html=sellerToldView(a.decision?.explanation)+'<h3>Pha 0 · Sàn quyết định '+esc(LEVELS[c.phase0?.floor]||c.phase0?.floor)+'</h3>'+table(['Quy tắc','Kết quả','Mức','Giá trị'],(c.phase0?.results||[]).map(r=>[esc(r.code),badge(r.ok===true?'Đạt':r.ok===false?'Không đạt':'Mô hình đánh giá'),esc(LEVELS[r.level]||r.level),esc(r.value)]))+'<h3>Pha 1 · Đánh giá độc lập đã niêm phong</h3>'+facts(c.phase1)+'<h3>Pha 2 · Đối chiếu bằng chứng</h3>'+facts(c.phase2)+'<h3>Quy tắc pháp lý · trích dẫn đã kiểm chứng</h3>'+(c.legal||[]).map(r=>'<article class="v4-ledger"><strong>'+esc(r.code)+'</strong> '+badge(r.ok?'Đạt':'Cần xử lý')+((r.in_force===false || r.effective===false)?badge('Chưa hiệu lực'):'')+'<p>'+esc(r.action||r.what)+'</p>'+(r.citations||[]).map(cite=>'<blockquote><code>'+esc(cite.article_id)+'</code><p>'+esc(cite.quote)+'</p></blockquote>').join('')+json(r)+'</article>').join('')+ragView(c.retrieval)+'<h3>Các ngân hàng duyệt song song</h3>'+((a.syndicate?.rounds)||[]).map(r=>'<h4>Vòng '+money(r.amount,o.currency)+'</h4>'+table(['Ngân hàng','Trả lời','Thời gian','Lý do'],r.responses.map(x=>[esc(x.name),badge(x.decision),x.ms==null?'—':esc((x.ms/1000).toFixed(1)+' giây'),esc(x.reason)]))).join('')+flowFacts({status:a.syndicate?.status,limit:a.syndicate?.limit,split:a.syndicate?.split,expires_at:a.syndicate?.expires_at},o.currency);
    if(state.tab==='gate') html='<h3>Cổng phê duyệt · '+esc(LEVELS[c.gate?.decision]||c.gate?.decision)+'</h3><ol class="v4-stepper">'+(c.gate?.conditions||[]).map(x=>'<li>'+badge(x.ok?'✓ Đạt':'! Chưa đạt')+' '+esc(x.text)+'</li>').join('')+'</ol>'+json(a.decision,'Quyết định');
    if(state.tab==='chain') html=(state.trace.unavailable?empty:'')+btn('Kiểm tra chuỗi hồ sơ','verify-case',a.id)+'<div id="case-verify" role="status"></div>'+(state.trace.chain||[]).map(e=>'<article class="v4-ledger"><strong>#'+esc(e.seq)+' '+esc(e.kind)+'</strong><p>'+esc(e.at)+'</p>'+facts({fingerprint:e.fingerprint,head:e.head,tx:e.tx,block:e.block})+btn('Sao chép hàm băm','copy',e.head || e.fingerprint)+'</article>').join('');
    const readyToContinue=a.tier===1 || (a.plan && ['qty','price','supplier','event'].every(k=>a.plan[k]!=null && a.plan[k]!==''));
    if(!a.offer && !readyToContinue) html+='<p class="notice">Người bán cần hoàn tất kế hoạch trước khi cán bộ có thể cho tiếp tục hồ sơ.</p>';
    if(a.status==='escalated' || a.status==='needs_answer') html+='<form id="decision-form" class="v4-form"><h3>Quyết định cán bộ</h3><label>Quyết định<select name="decision">'+(a.offer?'<option value="approve">Duyệt hạn mức (gửi ngân hàng)</option><option value="smaller_offer">Duyệt hạn mức nhỏ hơn</option>':(readyToContinue?'<option value="continue">Tiếp tục xác minh</option>':''))+'<option value="reject">Từ chối</option></select></label><label>Phương án<select name="option_id">'+(o.options||[]).map(x=>'<option value="'+esc(x.id)+'">'+esc(x.label || x.id)+' · '+money(x.amount,o.currency)+'</option>').join('')+'</select></label><label>Ghi chú<textarea name="note" required maxlength="1000"></textarea></label><button class="btn" type="submit">Ghi nhận quyết định</button></form>';
    $('drawer-body').innerHTML=html; $('drawer-body').setAttribute('role','tabpanel'); $('drawer-body').setAttribute('aria-labelledby','case-tab-'+state.tab); BU.motion.init($('drawer-body'));
  }
  // SELLER_SERVICES_PLAN §4: what Agent 3 told the seller about the decision, with where each sentence came from.
  function sellerToldView(e) {
    if(!e)return '';
    const act=x=>x.action?'<code>'+esc([x.action.view,x.action.data_type].filter(Boolean).join(' · '))+'</code>':'';
    return '<section class="v4-seller-told"><h3>Người bán đã được nói gì</h3><p><strong>'+esc(e.headline)+'</strong> '+badge(e.source==='llm'?'Mô hình viết lại':'Mẫu')+(e.hidden?' '+badge('Lý do được giữ kín'):'')+'</p>'
      +(e.because?.length?'<h4>Vì sao</h4><ul class="v4-flow-list">'+e.because.map(b=>'<li>'+esc(b.text)+(b.ref?' <code>'+esc(b.ref)+'</code>':'')+'</li>').join('')+'</ul>':'<p class="v4-muted">Không nêu lý do cho người bán.</p>')
      +(e.improve?.length?'<h4>Gợi ý cải thiện</h4><ul class="v4-flow-list">'+e.improve.map(i=>'<li>'+esc(i.text)+' '+act(i)+'</li>').join('')+'</ul>':'')+'</section>';
  }
  // Agent 3's law retrieval (RAG over the Chinese corpus): questions from the case, closest articles, and
  // whether retrieval surfaced an article each fired rule cites (an independent cross-check).
  function ragView(r){
    if(!r)return '';
    const mode=r.mode==='hybrid'?'Lai: BM25 + embedding đa ngôn ngữ':r.mode==='bm25'?'Chỉ BM25 (chưa có mô hình embedding)':'Lỗi truy xuất';
    return '<h3>Truy xuất điều luật (RAG)</h3><p class="v4-muted">'+esc(mode)+(r.model?' · '+esc(r.model):'')+'. Quyết định vẫn do quy tắc; bảng này cho thấy điều luật gần nhất với hồ sơ.</p>'
     +(r.rule_checks||[]).map(x=>'<p>'+badge(x.agrees?'Truy xuất xác nhận căn cứ':'Truy xuất chưa thấy căn cứ')+' <code>'+esc(x.rule)+'</code> trích '+esc(x.cited.join(', '))+'</p>').join('')
     +(r.queries||[]).map(q=>'<details><summary>'+esc(q.q)+'</summary>'+table(['Điều','Văn bản','Đoạn (tiếng Trung)','Điểm'],(q.hits||[]).map(h=>['<code>'+esc(h.article_id)+'</code>'+(h.in_force?'':' '+badge('Chưa hiệu lực')),esc(h.law),esc(h.snippet),esc(h.score)]))+'</details>').join('');
  }
  // Officers' law search (RAG over the Chinese or Vietnamese corpus): question → closest articles, with
  // the effective/repeal status of each; opening a row shows the whole article.
  async function lawSearch(fd){
    const q=String(fd.get('q')||'').trim(),j=fd.get('jurisdiction')||'VN',box=$('law-result');if(!q)return;
    box.innerHTML='<p role="status">Đang tìm…</p>';
    try{
      const r=await api('/legal/search?'+new URLSearchParams({q,jurisdiction:j,k:'6'}));
      const st=h=>h.status==='repealed'?badge('Đã bãi bỏ'):h.status==='partly_repealed'?badge('Bãi bỏ một phần'):!h.in_force?badge('Chưa hiệu lực'):'';
      box.innerHTML='<p class="v4-muted">'+esc(r.mode==='hybrid'?'Tìm lai: theo chữ + theo nghĩa (embedding)':'Tìm theo chữ (BM25)')+' · kho '+esc(j==='VN'?'Việt Nam':'Trung Quốc')+'</p>'
        +table(['Điều','Văn bản','Đoạn liên quan',''],(r.items||[]).map(h=>['<code>'+esc(h.article_id)+'</code>',esc(h.law)+' '+st(h),esc(h.snippet),'<button class="btn btn-sm" type="button" data-law-article="'+esc(h.article_id)+'">Xem điều</button>']));
    }catch(e){box.innerHTML='<p class="v4-error" role="alert">'+esc(e.message)+'</p>';}
  }
  document.addEventListener('click',async e=>{const b=e.target.closest('[data-law-article]');if(!b)return;
    try{const a=await api('/legal/articles/'+encodeURIComponent(b.dataset.lawArticle));openDrawer(a.law,a.article_id,'<p class="v4-muted">'+esc(a.status==='repealed'?'Đã bãi bỏ từ '+a.repealed_on:a.status==='partly_repealed'?'Bãi bỏ một phần từ '+a.repealed_on:'Hiệu lực từ '+(a.effective||'—'))+'</p><pre class="v4-law-text">'+esc(a.text)+'</pre>');}
    catch(err){notice(err.message,true);}});
  const FLOW_LABELS={challenger_pd:'Mô hình thách thức · xác suất vỡ nợ',debate_rounds:'Số vòng tranh luận A2 ↔ A3',cap_reached:'Chạm trần số vòng',independence:'Độc lập mô hình A2 / A3',computed:'Hạn mức tính được',seed:'Khoản vay mồi',thin_fate_cap:'Trần FATE mỏng',fate_alt:'Điểm thay thế FATE',affordability:'Khả năng trả',type_cap:'Trần loại người vay',suggested:'Gợi ý vay vừa đủ',prudence:'Hệ số thận trọng',tenors:'Khung kỳ hạn',tenor_max:'Kỳ hạn dài nhất',methods:'Hình thức trả',revenue_rate_max_tenor:'Tỷ lệ doanh thu (kỳ hạn dài nhất)',min_principal_share:'Phần gốc tối thiểu',method:'Hình thức',due_day:'Ngày trả',first_due_date:'Kỳ đầu',clock:'Ngày hệ thống',arrears:'Đang quá hạn',overdue_days:'Số ngày quá hạn',balance:'Số dư tài khoản',penalty:'Lãi phạt',interest:'Lãi',principal:'Gốc',since:'Quá hạn từ',penalty_to:'Lãi phạt tính đến',expires_at:'Hiệu lực đến',need:'Nhu cầu vốn',requested:'Số xin',unit_price_used:'Giá dùng',price_declared:'Giá khai',plan_value:'Giá trị kế hoạch',forecast:'Dự báo',prudent:'Dự báo thận trọng',growth_used:'Tăng trưởng dùng',sweep_cap:'Trần tỷ lệ doanh thu (giá vốn)',sweep_usable:'Trần tỷ lệ doanh thu dùng được',score:'Điểm',grade_before:'Hạng trước phạt',grade:'Hạng',rate:'Lãi năm',cashflow_cap:'Trần dòng tiền',group_cap:'Trần theo nhóm',absolute_cap:'Trần tuyệt đối',binding_cap:'Trần quyết định',sweep:'Tỷ lệ trích',grace_days:'Ân hạn (ngày)',max_interest:'Lãi tối đa',total_due:'Tổng phải trả',group:'Nhóm khách hàng',limit:'Hạn mức',amount:'Số tiền',repaid:'Đã trả',outstanding:'Còn phải trả',tenor_m:'Kỳ hạn (tháng)',option_id:'Phương án',first_sweep_date:'Bắt đầu trích',final_due_date:'Hạn cuối',payee:'Người nhận',status:'Trạng thái',before:'Trước kiểm tra',after:'Sau kiểm tra',share:'Tỷ lệ',pct:'Tỷ lệ',people:'Số người',groups:'Các cụm',linked:'Liên kết',bank:'Ngân hàng',split:'Chia ngân hàng',inflow:'Tiền về',swept:'Đã trích',chain_tx:'Giao dịch trên chuỗi',at:'Thời điểm',text:'Nội dung',level:'Mức',signals:'Tín hiệu',source:'Nguồn',code:'Mã',note:'Ghi chú',answer:'Trả lời',label:'Nội dung',question:'Câu hỏi',due:'Hạn kiểm tra',checked_at:'Ngày kiểm tra',supplier:'Nhà cung cấp',invoiced:'Giá trị hóa đơn',id:'Mã',contract_id:'Hợp đồng',policy_version:'Phiên bản chính sách',reason:'Lý do',fingerprint:'Dấu vân tay',tx:'Giao dịch',block:'Khối',sealed_by:'Niêm phong bởi',confirmed:'Nút xác nhận',nodes:'Tổng số nút',legs_mismatch:'Các phần giải ngân bị lệch',floor:'Sàn quyết định',phase1:'Pha 1 · Đánh giá độc lập',phase2:'Pha 2 · Đối chiếu bằng chứng',kind:'Kết luận',by:'Người quyết định',record_hash:'Hàm băm biên bản',steps:'Số bước',state:'Trạng thái xác minh',as_of:'Ngày đánh giá',signoff:'Xác nhận'};
  const FLOW_MONEY=new Set(['computed','thin_fate_cap','affordability','type_cap','suggested','balance','penalty','interest','principal','need','unit_price_used','price_declared','plan_value','forecast','prudent','cashflow_cap','group_cap','absolute_cap','limit','max_interest','total_due','amount','repaid','outstanding','inflow','swept','invoiced']);
  const FLOW_RATIOS=new Set(['revenue_rate_max_tenor','min_principal_share','prudence','growth_used','sweep_cap','sweep_usable','rate','sweep','share','pct','before','after']);
  const FLOW_STATUSES=new Set(['status','state','level','floor','phase1','phase2','kind']);
  function flowValue(value,key,currency) {
    if(value==null)return '—';
    if(Array.isArray(value))return value.length?'<ul class="v4-flow-list">'+value.map(x=>'<li>'+flowValue(x,key,currency)+'</li>').join('')+'</ul>':'Không có';
    if(typeof value==='object')return flowFacts(value,currency);
    if(typeof value==='boolean')return esc(value?'Có':'Không');
    if(typeof value==='number')return esc(FLOW_RATIOS.has(key)?pct(value):money(value,FLOW_MONEY.has(key)?currency:null));
    return esc(FLOW_STATUSES.has(key)?(statuses[value] || value):value);
  }
  function flowFacts(data,currency) {
    return '<dl class="v4-facts">'+Object.entries(data || {}).map(([key,value])=>'<div><dt>'+esc(FLOW_LABELS[key] || label(key))+'</dt><dd>'+flowValue(value,key,currency)+'</dd></div>').join('')+'</dl>';
  }
  const flowMatch = (matches,skipped) => skipped?'':matches===true?'<span class="badge badge-ok">✓ Khớp phiếu đã lưu</span>':matches===false?'<span class="badge badge-warn">⚠ Lệch phiếu đã lưu</span>':'<span class="badge badge-muted">Chưa có phiếu để đối chiếu</span>';
  const chainSeal = sealed => sealed===true?'<span class="badge badge-ok">✓ Phiếu đã lưu đúng bản niêm phong trên chuỗi</span>':sealed===false?'<span class="badge badge-warn">⚠ Phiếu đã lưu khác bản niêm phong trên chuỗi</span>':'';
  function flowBlock(block,index,currency) {
    const id=/^B[1-9]$/.test(block.block)?block.block:'block-'+index, points=block.block==='B6';
    const output={...(block.output || {})};
    if(output.binding_cap && FLOW_LABELS[output.binding_cap])output.binding_cap=FLOW_LABELS[output.binding_cap];
    return '<details open data-flow-block id="flow-'+id+'" class="v4-flow-block'+(block.status==='skipped'?' is-skipped':'')+'"><summary><span>'+esc(block.block)+' · '+esc(block.title)+'</span>'+flowMatch(block.matches,block.status==='skipped')+'</summary><div class="v4-flow-content"><p class="v4-flow-question">'+esc(block.question)+'</p>'+(block.status==='skipped'?'<p class="v4-flow-note">'+esc(block.note || 'Khối này không dùng cho hồ sơ hiện tại.')+'</p>':(block.note?'<p class="v4-flow-note">'+esc(block.note)+'</p>':'')+'<h5>Đầu vào</h5>'+table(['Tên','Giá trị','Nguồn',...(points?['Điểm']:[])],(block.inputs||[]).map(x=>[esc(x.name),esc(x.shown),esc(x.source),...(points?[esc(x.points)]:[])]))+'<h5>Cách tính</h5>'+((block.steps||[]).length?'<ol class="v4-flow-formulas">'+block.steps.map(line=>'<li>'+esc(line)+'</li>').join('')+'</ol>':'<p class="v4-flow-note">Chưa có bước tính.</p>')+'<h5>Đầu ra</h5>'+flowFacts(output,currency))+'</div></details>';
  }
  function renderFlow() {
    if(state.flowLoading)return '<p role="status">Đang tải toàn bộ luồng…</p>';
    if(state.flowError)return '<p class="notice v4-error" role="alert">'+esc(state.flowError)+'</p>';
    const f=state.flow;
    if(!f || !f.application)return '<p class="empty">Chưa có dữ liệu luồng.</p>';
    const a=f.application,s=f.seller||{},currency=a.currency,blocks=f.blocks||[],b3=blocks.find(b=>b.block==='B3'),b8=blocks.find(b=>b.block==='B8'),a2=f.agent2||{},a3=f.agent3||{},gate=f.gate||{},b10=f.b10||{},b12=f.b12,w=f.withdrawal,b11=f.b11;
    const requested=blocks.flatMap(b=>b.inputs||[]).find(x=>x.name==='Số xin' || x.name==='Số tiền xin');
    const binding=b8?.output?.binding_cap;
    const cap=b8?.output?.[binding] ?? (binding==='need'?b3?.output?.need:binding==='requested'?requested?.value:null);
    const summary=[['Xin',requested?.value],['Nhu cầu (B3)',b3?.output?.need],['Trần quyết định (B8)',cap],['Hạn mức ngân hàng duyệt',b12?.limit],['Người vay chọn',f.selection?.amount],['Giải ngân',w?(b11?.loan?.amount ?? f.contract?.amount):null]];
    const section=(title,content,id='')=>'<li class="v4-flow-step"'+(id?' id="'+id+'"':'')+'><h3>'+title+'</h3>'+content+'</li>';
    const evidence=ref=>'<button type="button" class="btn btn-sm" data-flow-ref="'+esc(ref)+'">'+esc(ref)+'</button>';
    let html='<div class="v4-flow">'+(f.error?'<p class="notice v4-error" role="alert">'+esc(f.error)+'</p>':'')+(f.params_rebuilt?'<p class="v4-flow-note">Phiếu được dựng lại bằng phiên bản tham số hiện tại: '+esc(f.params_version)+'.</p>':'')+flowMatch(f.matches)+chainSeal(f.sheet_on_chain)+'<ol class="v4-flow-summary" aria-label="Từ số xin đến giải ngân">'+summary.map(([title,amount])=>'<li><span>'+title+'</span><strong>'+esc(money(amount,currency))+'</strong></li>').join('')+'</ol><nav class="v4-flow-nav" aria-label="Đi tới khối tính toán">'+Array.from({length:12},(_,i)=>'<a href="#flow-B'+(i+1)+'">B'+(i+1)+'</a>').join('')+'</nav><div class="v4-actions">'+btn('Mở tất cả','flow-expand')+btn('Thu gọn','flow-collapse')+'</div><ol class="v4-flow-stepper">';
    html+=section('① Đầu vào & nguồn',flowFacts({'Người bán':s.name,'Email':s.email,'Cửa hàng':s.store,'Sàn':s.platform,'Mã hồ sơ':a.code,'Trạng thái':statuses[a.status]||a.status,'Tầng':a.tier,'Tiền tệ':currency,'Phiên bản tham số':f.params_version},currency)+'<h4>Nguồn Agent 1</h4>'+table(['Lời gọi','Công cụ'],(f.sources||[]).map(x=>[esc(x.id),esc(x.tool)])));
    html+=section('② Agent 1 · B10',flowFacts(f.agent1,currency)+'<h4>'+esc(b10.title || 'Kiểm tra gian lận')+'</h4><p>'+esc(b10.question)+'</p>'+table(['Kiểm tra','Giá trị','Quy tắc'],(b10.checks||[]).map(x=>[esc(x.name),flowValue(x.value,'',currency),esc(x.rule)]))+'<h4>Cờ xác minh</h4>'+table(['Mã','Trạng thái','Ghi chú','Hệ quả','Bằng chứng'],(b10.flags||[]).map(x=>[esc(x.code)+'<br>'+esc(label(x.code)),badge(x.status),esc(x.note),esc(x.penalty),x.evidence_tool_call?evidence('tool_calls.'+x.evidence_tool_call):'—']))+'<button type="button" class="btn btn-sm" data-case-tab="a1">Xem Agent 1</button>','flow-B10');
    html+=section('③ B1…B9 · Khối tính toán',blocks.map((block,i)=>flowBlock(block,i,currency)).join('') || '<p class="empty">Chưa có khối tính toán.</p>');
    html+=section('④ Agent 2','<p>Phương án đã chọn: <strong>'+esc(a2.option_id)+'</strong></p>'+flowFacts(a2.card,currency)+'<h4>Lý do và bằng chứng</h4><ul class="v4-flow-list">'+(a2.rationale||[]).map(r=>'<li>'+esc(r.claim)+' '+evidence(r.evidence_ref)+'</li>').join('')+'</ul>');
    html+=section('⑤ Agent 3 + Cổng',flowFacts(a3,currency)+ragView(f.retrieval)+'<h4>Điều kiện cổng</h4><ul class="v4-flow-list">'+(gate.conditions||[]).map(c=>'<li>'+badge(c.ok?'✓ Đạt':'! Chưa đạt')+' '+esc(c.text)+'</li>').join('')+'</ul><p>Kết luận cổng: '+badge(gate.decision)+'</p><h4>Quyết định cuối</h4>'+flowFacts(f.decision,currency));
    html+=section('⑥ B12 · Các ngân hàng duyệt song song',b12&&b12.status!=='pending'?'<p>'+esc(b12.question)+'</p>'+(b12.rounds||[]).map(r=>'<h4>Vòng '+esc(money(r.amount,currency))+'</h4>'+table(['Ngân hàng','Trả lời','Thời gian','Lý do'],(r.responses||[]).map(x=>[esc(x.name),badge(x.decision),x.ms==null?'—':esc((x.ms/1000).toFixed(1)+' giây'),esc(x.reason)]))).join('')+flowFacts({status:b12.result,limit:b12.limit,expires_at:b12.expires_at},currency)+'<h4>Tỷ lệ chia</h4>'+table(['Ngân hàng','Vai trò','Tỷ lệ'],(b12.split||[]).map(b=>[esc(b.name||b.bank),esc(b.role==='lead'?'Dẫn đầu':'Đối tác'),esc(pct(b.pct))]))+'<h4>Hợp đồng từng ngân hàng (khi ký)</h4>'+table(['Ngân hàng','Tỷ lệ','Số tiền','Hợp đồng'],(b12.legs||[]).map(b=>[esc(b.name||b.bank),esc(pct(b.pct)),esc(money(b.amount,currency)),esc(b.contract_id)]))+'<h4>Phần vốn và số đã thu</h4>'+table(['Ngân hàng','Tỷ lệ','Số tiền','Đã thu','Hợp đồng'],(b12.shares||[]).map(b=>[esc(b.bank),esc(pct(b.pct)),esc(money(b.amount,currency)),esc(money(b.repaid,currency)),esc(b.contract_id)])):'<p class="v4-flow-note">Chưa gửi ngân hàng.</p>','flow-B12');
    html+=section('⑥b Chọn khoản vay và hợp đồng',f.selection?flowFacts({amount:f.selection.amount,tenor_m:f.selection.tenor_m,method:f.selection.method_label,due_day:f.selection.due_day,total_due:f.selection.total_due},currency)+(f.contract?flowFacts({id:f.contract.id,status:f.contract.signed_at?'Đã ký '+f.contract.signed_at:'Chưa ký',chain_tx:f.contract.chain_tx},currency):''):'<p class="v4-flow-note">Người vay chưa chọn.</p>');
    html+=section('⑦ Giải ngân',w?withdrawalBadge(w)+flowFacts({id:w.id,tx:w.tx,block:w.block,sealed_by:w.sealed_by,'Nút xác nhận':w.confirmed!=null && w.nodes!=null?w.confirmed+'/'+w.nodes:'—',legs_mismatch:w.legs_mismatch},currency)+explorerLink(w.explorer_url):'<p class="v4-flow-note">Chưa giải ngân.</p>');
    html+=section('⑧ B11 · Theo dõi',b11?'<p>'+esc(b11.question)+'</p>'+flowFacts(b11.loan,currency)+'<h4>Cảnh báo sớm</h4>'+badge(b11.early_warning?.level)+flowFacts({score:b11.early_warning?.score,as_of:b11.early_warning?.as_of,signals:b11.early_warning?.signals},currency)+'<p>'+esc(b11.rule)+'</p><h4>Lịch trả</h4>'+table(['Kỳ','Ngày','Gốc','Lãi','Đã thu','Trạng thái'],(b11.schedule||[]).map(r=>[esc(r.k),esc(r.due_date),esc(money(r.principal_due ?? r.principal,currency)),esc(money(r.interest ?? r.interest_est,currency)),esc(money(r.paid,currency)),badge(r.status)]))+'<h4>Lịch sử thu nợ</h4>'+table(['Thời điểm','Số tiền','Chia ngân hàng','Giao dịch trên chuỗi'],(b11.repayments||[]).map(r=>[esc(r.at),esc(money(r.amount,currency)),flowValue(r.split,'split',currency),esc(r.chain_tx)]))+'<h4>Giao dịch tài khoản kinh doanh</h4>'+flowValue(b11.transfers,'',currency)+'<h4>Báo trung tâm tín dụng</h4>'+flowValue(b11.bureau,'',currency)+'<h4>Cảnh báo</h4>'+flowValue(b11.alerts,'',currency)+'<h4>Thông báo</h4>'+flowValue(b11.notices,'',currency)+'<h4>Sử dụng vốn</h4>'+flowFacts(b11.use_of_funds,currency)+'<h4>Nhắc trả</h4>'+flowValue(b11.reminders,'',currency):'<p class="v4-flow-note">Theo dõi bắt đầu sau giải ngân.</p>','flow-B11');
    html+=section('⑨ Chuỗi',badge(f.chain_mode==='remote'?'Chuỗi thật':f.chain_mode==='local'?'Chuỗi cục bộ':f.chain_mode)+(f.chain||[]).map(e=>'<article class="v4-ledger"><h4>#'+esc(e.seq)+' · '+esc(e.kind)+'</h4>'+flowFacts({fingerprint:e.fingerprint,tx:e.tx,block:e.block,at:e.at},currency)+(e.remote?'<h5>Giao dịch trên chuỗi thật</h5>'+flowFacts({tx:e.remote.tx,block:e.remote.block,status:e.remote.status},currency)+explorerLink(e.remote.explorer_url):'')+'</article>').join(''));
    return html+'</ol></div>';
  }
  async function loadBanks() { await panel('banks','/banks',d=>{state.banks=items(d);return table(['Ngân hàng','Khu vực','Tổng hạn mức','Đã dùng','Còn lại','Hợp đồng','Chi tiết'],state.banks.map(b=>[esc(b.name || b.code),esc(b.region)+' / '+esc(b.currency),money(b.limit_total,b.currency),money(b.limit_used ?? b.used,b.currency),money(b.limit_remaining ?? b.remaining,b.currency),esc(b.contract_id),btn('Chính sách / khóa','bank',b.code)]));}); }
  const groups=['quần áo','thực phẩm đóng gói','thực phẩm rời','thực phẩm chức năng','dược','thiết bị y tế I','thiết bị y tế II','thiết bị y tế III','thuốc lá điện tử','dịch thuốc lá điện tử','điện tử','khác'];
  async function openBank(code) { const serial=++state.navigation; const b=await api('/banks/'+encodeURIComponent(code)),p=b.policy||{};if(serial!==state.navigation)return;state.bank=b;
    let html=facts({region:b.region,currency:b.currency,contract_id:b.contract_id,public_key:b.public_key,public_key_fingerprint:b.public_key_fingerprint})+json(p,'Chính sách hiện hành');
    if(admin) html+='<form id="policy-form" class="v4-form"><label>Hạng tối thiểu<select name="min_grade">'+['A','B','C','D','E'].map(x=>'<option '+(p.min_grade===x?'selected':'')+'>'+x+'</option>').join('')+'</select></label>'+['min_amount','max_amount','max_rate','min_share'].map(k=>'<label>'+esc(({min_amount:'Số tiền tối thiểu',max_amount:'Số tiền tối đa',max_rate:'Lãi suất tối đa (thập phân)',min_share:'Tỷ lệ tối thiểu (≥ 0,30)'})[k])+'<input name="'+k+'" type="number" step="'+(k.includes('amount')?'1':'0.01')+'" min="'+(k==='min_share'?'0.30':'0')+'" '+(k==='min_share'?'max="1"':'')+' required value="'+esc(p[k])+'"></label>').join('')+'<fieldset><legend>Tầng được chấp nhận</legend>'+[1,2].map(x=>'<label><input type="checkbox" name="tiers" value="'+x+'" '+((p.tiers||[]).includes(x)?'checked':'')+'>Tầng '+x+'</label>').join('')+'</fieldset><fieldset><legend>Nhóm hàng loại trừ</legend>'+groups.map(x=>'<label><input type="checkbox" name="excluded_groups" value="'+x+'" '+((p.excluded_groups||[]).includes(x)?'checked':'')+'>'+x+'</label>').join('')+'</fieldset><button class="btn" type="submit">Lưu chính sách</button></form><form id="rotate-form" class="v4-form"><label>Khóa công khai X25519 mới (64 ký tự hex)<input name="public_key" pattern="[a-fA-F0-9]{64}" required autocomplete="off"></label><p>Khóa mới dùng cho bản ghi mới. Bản ghi cũ vẫn cần khóa cũ.</p><button class="btn" type="submit">Đăng ký / xoay khóa</button></form>';
    openDrawer('Ngân hàng '+b.code,b.name,html);
  }
  async function loadPostaudit() { await Promise.allSettled([
    panel('reports','/postaudit/reports',d=>items(d).map(r=>'<article class="v4-ledger"><h3>'+esc(r.id)+'</h3>'+(r.summary&&r.summary.text?'<div class="v4-summary"><strong>Agent 5 tóm tắt cho hội đồng rủi ro</strong> '+badge('Mô hình')+'<p class="v4-summary-text">'+esc(String(r.summary.text).replace(/\*\*|`/g,''))+'</p></div>':'')+facts({'Thời điểm':r.at,'Lượt thao túng bị chặn':r.manipulation_blocked,'Tỷ lệ A2 / A3 bất đồng':pct(r.a2_a3_disagreement_rate)})+table(['Chỉ tiêu','Phân khúc','Thực tế','Mục tiêu','Nhận định'],(r.findings||[]).map(f=>[esc(f.metric),esc(f.segment),esc(f.value),esc(f.target),esc(f.text)]))+json(r,'Cohort, thống kê quy tắc và trích dẫn')+'</article>').join('') || '<p class="empty">Chưa chạy hậu kiểm.</p>'),
    panel('proposals','/postaudit/proposals',d=>table(['Tham số','Trước / sau','Trạng thái','Lý do','Duyệt độc lập'],items(d).map(p=>[esc(p.param),esc(p.from)+' → '+esc(p.to),badge(p.status),esc(p.evidence),admin && (p.status==='pending'||p.status==='proposed') ? btn('Xem và duyệt','proposal',p.id):esc('Chỉ quản trị viên duyệt')]))),
    panel('params','/params',p=>facts({version:p.version,hash:p.hash,chain_tx:p.chain_tx})+json(p.ruleset,'Bộ quy tắc')+json(p.history,'Lịch sử phiên bản / đường dẫn thay đổi')+json(p.params,'Tham số hiện hành'))
  ]); }
  const pbftSteps=['Tiếp nhận yêu cầu','Kiểm tra tỷ lệ chia','Chi từ ngân quỹ','Chia mảnh và mã hóa','Niêm phong Merkle','Nút trưởng đề xuất','Phiếu prepare','Phiếu commit','Ghi khối','Trả biên nhận'];
  function drawPbft() { const step=state.step; $('pbft').innerHTML='<h3>Minh họa · 10 bước PBFT</h3><p>Minh họa quy trình, không phải tiến độ giao dịch trực tiếp.</p><div class="v4-nodes">'+[0,1,2,3].map(n=>'<div class="v4-node '+(n===Math.floor(step/3)%4?'is-leader':'')+'">node'+n+'<br>'+((n===Math.floor(step/3)%4)?'Nút trưởng':'Nút đồng thuận')+'</div>').join('')+'</div><p aria-live="polite">'+(step+1)+' / 10 · '+pbftSteps[step]+'</p><label>Bước minh họa<input id="pbft-step" type="range" min="0" max="9" value="'+step+'"></label><div class="v4-actions">'+btn('Lùi','pbft-back')+btn(state.timer?'Tạm dừng':'Phát','pbft-play')+btn('Tiếp','pbft-next')+'</div>'; }
  const externalUrl = value => {
    try { const url=new URL(value);return ['https:','http:'].includes(url.protocol)?url.href:''; } catch(_) { return ''; }
  };
  const explorerLink = (url, title='Explorer ↗') => {
    const href=externalUrl(url);
    return href?'<a class="v4-chain-link" href="'+esc(href)+'" target="_blank" rel="noopener noreferrer">'+esc(title)+'</a>':'';
  };
  const shortHash = value => value && String(value).length>20?String(value).slice(0,10)+'…'+String(value).slice(-8):value;
  const withdrawalBadge = w => badge(w.simulated===false?'Chuỗi thật':'Chuỗi cục bộ');
  function chainContext(remote) {
    $('blocks-title').textContent=remote?'Khối cục bộ (bản sao nội bộ)':'Các khối gần nhất';
    $('blocks-hint').hidden=!remote;
    $('blocks-hint').textContent='Các khối bên dưới là bản sao nội bộ. Xem khối thật trong explorer.';
    $('chain-disclosure-title').textContent='Những gì không bị ẩn · giới hạn hiện tại';
    $('chain-disclosure').textContent='Công khai: mã, thời điểm, số mảnh và kích thước; không công khai ngân hàng trong bản ghi mã hóa. Khóa đã lộ có thể đọc bản ghi cũ vĩnh viễn. Mỗi ngân hàng không tự kiểm được tổng tỷ lệ các phần. '+(remote?'Chuỗi thật là FISCO BCOS của đội: 4 nút trên cùng một máy. Khóa giải mã hiển thị công khai trên trang tổng quan của dịch vụ; không dùng cho production.':'Trong chế độ cục bộ, bốn nút chạy trên cùng một máy với một đơn vị vận hành, dùng ngân quỹ nội bộ và hàm băm sha3-256.')+' Khóa chủ thực tế phải nằm trong HSM/KMS.';
  }
  function renderChainStatus(d) {
    state.chain=d;
    const remote=d.mode==='remote', sync=d.catalog_sync;
    chainContext(remote);
    let html=badge(remote?'FISCO BCOS · chuỗi thật':'Chuỗi cục bộ')+(remote?explorerLink(d.explorer_url,'Mở explorer ↗'):'')+facts({height:d.height,group:d.group,consensus:d.consensus,mode:d.mode});
    html+=remote?table(['Nút','Trạng thái','Sealer','Khối'],(d.nodes||[]).map(n=>[esc(n.id),badge(n.status),esc(n.sealer===true?'Có':n.sealer===false?'Không':'—'),esc(n.block)])):table(['Nút','Trạng thái','Vai trò'],(d.nodes||[]).map(n=>[esc(n.id || n.name),badge(n.status || (n.up?'Hoạt động':'Không rõ')),esc(n.leader?'Nút trưởng':n.role)]));
    if(remote) {
      html+='<h3>Hợp đồng trên chuỗi</h3>'+table(['Hợp đồng','Địa chỉ','Sao chép'],Object.entries(d.contracts||{}).map(([name,address])=>[esc(name),'<code title="'+esc(address)+'">'+esc(shortHash(address))+'</code>',btn('Sao chép','copy',address)]));
      let line='Chưa có thông tin đồng bộ ngân hàng.';
      if(sync) {
        const date=sync.at?new Date(sync.at):null;
        const time=date&&!isNaN(date)?date.toLocaleTimeString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',hour:'2-digit',minute:'2-digit'}):'—';
        line=sync.ok?'Đồng bộ ngân hàng lúc '+time+' (giờ VN) · '+(sync.banks??'—')+' ngân hàng · '+(sync.keys??'—')+' khóa':'Đồng bộ ngân hàng lỗi: '+(sync.error||'Chưa đồng bộ thành công.');
      }
      html+='<p class="v4-chain-note'+(sync&&!sync.ok?' v4-error':'')+'">'+esc(line)+'</p>'+(admin?btn('Đồng bộ ngân hàng từ chuỗi','chain-sync'):'');
    }
    return html;
  }
  async function loadChain() {
    state.chain=null;
    await Promise.allSettled([
      panel('chain-status','/chain/status',renderChainStatus),
      panel('blocks','/chain/blocks?limit=20',d=>'<div class="v4-blocks">'+items(d).map(b=>'<article class="v4-ledger"><strong>Khối '+esc(b.height)+'</strong> '+badge('Nội bộ')+'<p>'+esc(b.at)+'</p><code>'+esc(b.hash)+'</code>'+json(b,'Dữ liệu khối')+'</article>').join('')+'</div>'),
      panel('withdrawals','/chain/withdrawals',d=>table(['Mã','Thời điểm','Mảnh','Kích thước','Khối','Sổ cái'],items(d).map(w=>[btn(w.id,'withdrawal',w.id),esc(w.at),esc(w.pieces),esc(w.size)+' byte',esc(w.block),withdrawalBadge(w)+(w.simulated===false?explorerLink(w.explorer_url):'')])))
    ]);
  }
  async function openWithdrawal(id) { const w=await api('/chain/withdrawals/'+encodeURIComponent(id));state.withdrawal=w;state.keys=[];
    const remote=w.remote||{};
    const chainFacts=w.simulated===false?facts({'Niêm phong bởi':remote.sealedBy,'Gửi tới':remote.submittedTo,'Nút xác nhận':remote.confirmedNodes!=null&&remote.totalNodes!=null?remote.confirmedNodes+'/'+remote.totalNodes:'—','Khối':w.block,'Giao dịch':w.tx})+explorerLink(w.explorer_url||remote.explorerUrl):'';
    $('withdrawal-detail').innerHTML='<h3>Lệnh '+esc(w.id)+'</h3>'+withdrawalBadge(w)+chainFacts+facts({merkle_root:w.merkle_root,tx:w.tx,pieces:w.pieces,slots:w.slots,size:w.size,merkle_ok:w.merkle_ok,record_ok:w.record_ok})+json(w.piece_fingerprints,'Dấu vân tay các mảnh')+btn('Xác minh lệnh','verify-withdrawal',w.id)+'<div id="withdrawal-verify"></div><form id="decrypt-form" class="v4-form"><label>Thử khóa riêng bất kỳ (64 ký tự hex)<input name="private_key_hex" type="password" required pattern="[a-fA-F0-9]{64}" autocomplete="off"></label><button class="btn" type="submit">Giải mã</button></form><div id="decrypt-result" role="status"></div>'+(admin?'<div class="v4-actions">'+btn('Giải mã bằng mọi khóa','try-keys')+btn('Hiện / ẩn khóa','show-keys')+'</div><div id="keys-panel" hidden></div><div id="key-matrix"></div>':'')+'<details><summary>Tự giải mã</summary><p>'+(w.simulated===false?'Dùng trình giải mã và khóa của dịch vụ chuỗi. Xem cách chạy bằng --help.':'Tải trình kiểm chứng từ máy chủ nếu đã khả dụng.')+' Thay khóa riêng trên máy của bạn, không lưu khóa vào lịch sử dùng chung.</p><pre id="decrypt-commands"></pre>'+btn('Sao chép lệnh','copy-commands')+'</details>';
    setCommands();
    $('withdrawal-detail').scrollIntoView({block:'nearest'});
  }
  const shellQuote = value => "'"+String(value).replace(/'/g,"'\\''")+"'";
  function setCommands(key = '<KHOA_RIENG_64_HEX>') {
    if (!$('decrypt-commands') || !state.withdrawal) return;
    const w=state.withdrawal;
    if(w.simulated===false) {
      const source=externalUrl(w.explorer_url||w.remote?.explorerUrl);
      const base=externalUrl(state.chain?.url)||(source?new URL(source).origin:'');
      $('decrypt-commands').textContent=base?'curl -f '+shellQuote(base.replace(/\/$/,'')+'/explorer/decrypt_withdrawal.py')+' -o decrypt_withdrawal.py\npython decrypt_withdrawal.py --help\n# Mã lệnh cần giải mã trên dịch vụ:\nprintf "%s\\n" '+shellQuote(w.id)+'\n# Dùng chain_private_key_hex của dịch vụ chuỗi.':'Chưa có địa chỉ dịch vụ chuỗi để tải trình giải mã.';
      return;
    }
    const endpoint=location.origin+'/v4/chain/withdrawals/'+encodeURIComponent(w.id);
    $('decrypt-commands').textContent='curl -f -H "Authorization: Bearer $BU_TOKEN" '+shellQuote(endpoint)+'\n'+
      'curl -f -H "Authorization: Bearer $BU_TOKEN" -H "Content-Type: application/json" --data '+shellQuote(JSON.stringify({private_key_hex:key}))+' '+shellQuote(endpoint+'/decrypt')+'\n'+
      'curl -f -H "Authorization: Bearer $BU_TOKEN" '+shellQuote(location.origin+'/v4/chain/decrypt_withdrawal.py')+' -o decrypt_withdrawal.py\npython decrypt_withdrawal.py --api '+shellQuote(location.origin)+' --token "$BU_TOKEN" --id '+shellQuote(w.id)+' --key '+shellQuote(key);
  }
  const recordKey = k => state.withdrawal?.simulated===false?k.chain_private_key_hex:k.private_key_hex;
  async function getKeys() { if(!state.keys.length) state.keys=items(await api('/chain/keys'));return state.keys; }
  async function tryKeys() { const keys=await getKeys(), results=[]; $('key-matrix').textContent='Đang giải mã bằng từng khóa…'; for(const k of keys) {const secret=recordKey(k);if(secret) results.push({key:k.code,...await api('/chain/withdrawals/'+encodeURIComponent(state.withdrawal.id)+'/decrypt','POST',{private_key_hex:secret})});}
    const pieces=[...new Set(results.flatMap(x=>x.opened||[]))];$('key-matrix').innerHTML='<h3>Ai đọc được gì · kết quả giải mã thực tế</h3>'+table(['Mảnh',...results.map(r=>r.key),'Công khai'],pieces.map(p=>[esc(p),...results.map(r=>badge((r.opened||[]).includes(p)?'✓ Đọc được':'Không đọc được')),badge('Không đọc được')]))+table(['Khóa','Dấu vân tay','Merkle','Mảnh mở được'],results.map(r=>[esc(r.key),badge(String(r.fingerprints_ok)),badge(String(r.merkle_ok)),esc((r.opened||[]).join(', ')||'Khóa này không mở được ô nào')])); }
  async function loadManual() { await panel('manual-list','/withdrawals',d=>table(['Lệnh chi','Thời điểm','Trạng thái','Kiểm chứng'],items(d).map(w=>[btn(w.id,'withdrawal',w.id),esc(w.at || w.created_at),badge(w.status || 'Đã ghi nhận'),btn('Xác minh','verify-manual',w.id)]))); try {const d=await api('/regions');state.regions=d.regions||d.items||[]; renderManual();} catch(e){$('manual').innerHTML=e.status===404?empty:'<p>'+esc(e.message)+'</p>';} }
  function renderManual() { $('manual').innerHTML='<form id="manual-form" class="v4-form"><label>Khu vực<select name="region" id="manual-region">'+state.regions.map(r=>'<option value="'+esc(r.code)+'">'+esc(r.name || r.code)+' / '+esc(r.currency)+'</option>').join('')+'</select></label><label>Tỉnh / thành<select required name="province" id="manual-province"></select></label><label>Người nhận<input name="user" required></label><label>Tài khoản<input name="account" required></label><label>Số tiền<input type="number" min="1" step="1" name="amount" required></label><label>Lý do<textarea name="reason" required minlength="3" maxlength="500"></textarea></label><label>Mã yêu cầu (giữ nguyên khi thử lại)<input name="requestId" readonly value="'+esc(crypto.randomUUID())+'"></label><fieldset><legend>Phân bổ ngân hàng · phần trăm</legend><div id="manual-splits"></div><output id="split-total">Tổng: 0%</output></fieldset><button class="btn" type="submit">Tạo lệnh chi</button></form>'; updateRegion(); }
  function updateRegion(){ const region=$('manual-region').value,r=state.regions.find(x=>x.code===region); $('manual-province').innerHTML=(r?.provinces||[]).map(p=>'<option value="'+esc(typeof p==='object'?p.code:p)+'">'+esc(typeof p==='object'?p.name:p)+'</option>').join('')||'<option value="">Chưa có tỉnh / thành</option>';$('manual-splits').innerHTML=state.banks.filter(b=>b.region===region && b.active!==false).map(b=>'<label>'+esc(b.code)+'<input type="number" data-split="'+esc(b.code)+'" min="0" max="100" step="0.01" value="0"></label>').join(''); }
  async function loadUsers(){await panel('users','/admin/users',d=>table(['Họ tên','Email','Vai trò','Trạng thái','Thao tác'],items(d).map(u=>[esc(u.display_name),esc(u.email),esc(u.role),badge(u.active?'Hoạt động':'Đã khóa'),u.id===session.user.id?'Tài khoản hiện tại':btn(u.active?'Vô hiệu hóa':'Kích hoạt',u.active?'deactivate':'activate',u.id)])));}
  document.addEventListener('click',event=>{
    const tab=event.target.closest('[data-case-tab]');if(tab){state.tab=tab.dataset.caseTab;renderCase();$('case-tab-'+state.tab)?.focus();return;}
    const flowRef=event.target.closest('[data-flow-ref]');if(flowRef){
      const [source,ref]=flowRef.dataset.flowRef.split('.');
      state.tab=source==='tool_calls'?'a1':'flow';renderCase();
      const target=$(source==='tool_calls'?'tool-'+ref:'flow-'+ref);
      if(target){target.open=true;target.scrollIntoView({block:'start'});target.setAttribute('tabindex','-1');target.focus();}
      else $('case-tab-'+state.tab)?.focus();
      return;
    }
    const evidence=event.target.closest('[data-evidence]');if(evidence){state.tab='algo';renderCase();const block=evidence.dataset.evidence.split('.')[1];document.getElementById('block-'+block)?.scrollIntoView();return;}
    const b=event.target.closest('[data-action]');if(!b)return;
    const id=b.dataset.id;
    action(async()=>{switch(b.dataset.action){
      case 'seller-filter-clear':$('seller-filter').value='';await submitSellerFilter();$('seller-filter').focus();break;
      case 'flow-expand':case 'flow-collapse':$('drawer-body').querySelectorAll('details[data-flow-block]').forEach(el=>el.open=b.dataset.action==='flow-expand');break;
      case 'case': await openCase(id);break;
      case 'bank': await openBank(id);break;
      case 'loan': {const l=await api('/loans/'+encodeURIComponent(id));openDrawer('Khoản vay '+(l.application_code||l.id),l.status,facts({'Số tiền':money(l.amount,l.currency),'Dư nợ gốc':money(l.principal_outstanding,l.currency),'Đã thu':money(l.repaid,l.currency),'Đang quá hạn':money(l.owed_now,l.currency)+' · '+(l.overdue_days||0)+' ngày','Lãi năm / lãi phạt':pct(l.rate)+' / '+pct(l.penalty_rate),'Hình thức':l.method_label,'Kỳ hạn':l.tenor_m+' tháng · ngày '+l.due_day,'Số dư TK kinh doanh':money(l.account?.balance,l.currency),'Ngày hệ thống':l.clock,'Hạn cuối':l.final_due_date})+'<h3>Lịch trả</h3>'+table(['Kỳ','Ngày','Phải trả','Đã thu','Trạng thái'],(l.schedule||[]).map(r=>[esc(r.k),esc(r.due_date),money(r.amount_due ?? r.payment_est,l.currency),money(r.paid,l.currency),badge(r.status)]))+(l.majority?'<p>'+esc(l.majority.text)+'</p>':'')+json(l.bureau,'Báo trung tâm tín dụng')+json(l.bank_report,'Báo cáo hằng ngày cho ngân hàng')+json(l.account?.transfers,'Giao dịch chi từ tài khoản kinh doanh')+'<h3>Ngân hàng đồng tài trợ</h3>'+table(['Ngân hàng','Tỷ lệ','Số tiền','Đã thu','Hợp đồng'],(l.shares||[]).map(x=>[esc(x.bank),pct(x.pct),money(x.amount,l.currency),money(x.repaid,l.currency),esc(x.contract_id)]))+'<h3>Agent 4 · thông báo cho người bán</h3>'+((l.notices||[]).length?table(['Thời điểm','Mức','Nội dung','Nguồn','Người bán trả lời'],l.notices.map(n=>[esc(n.at),badge(n.level==='red'?'Đỏ':'Vàng'),esc(n.text),esc(n.source==='llm'?'Mô hình':'Mẫu'),n.answer?esc(n.answer.label)+(n.answer.note?' · '+esc(n.answer.note):''):(n.question?'Chưa trả lời':'—')])):'<p>Chưa có thông báo.</p>')+'<h3>Sử dụng vốn</h3>'+facts(l.use_of_funds)+json(l.early_warning,'Cảnh báo sớm')+json(l.repayments,'Lịch sử thu nợ và chia ngân hàng')+json(l.reminders,'Nhắc trả')+btn('Mở hồ sơ','case',l.application_id));break;}
      case 'ack':await api('/alerts/'+encodeURIComponent(id)+'/ack','POST',{});await loadLoans();break;
      case 'complaint-assign':await api('/complaints/'+encodeURIComponent(id)+'/assign','POST',{});await loadComplaints();notice('Đã nhận xem khiếu nại '+id+'.');break;
      case 'verify-case':$('case-verify').innerHTML=facts(await api('/chain/cases/'+encodeURIComponent(id)+'/verify'));break;
      case 'chain-sync':if(!admin||state.chain?.mode!=='remote')return;{const result=await api('/chain/sync','POST',{});await loadChain();await loadBanks();if(!result.ok)throw new Error(result.error||'Đồng bộ ngân hàng thất bại.');notice('Đã đồng bộ ngân hàng từ chuỗi.');}break;
      case 'verify-all':$('chain-result').innerHTML=facts(await api('/chain/verify'));break;
      case 'withdrawal':await openWithdrawal(id);break;
      case 'verify-manual':$('manual-result').innerHTML=facts(await api('/withdrawals/'+encodeURIComponent(id)+'/verify'));break;
      case 'verify-withdrawal':try{$('withdrawal-verify').innerHTML=facts(await api('/withdrawals/'+encodeURIComponent(id)+'/verify'));}catch(e){if(e.status!==404)throw e;$('withdrawal-verify').innerHTML=empty;}break;
      case 'copy':if(state.keys.some(k=>recordKey(k)===id))setCommands(id);if(!navigator.clipboard)throw new Error('Hãy chọn và sao chép nội dung hiển thị.');await navigator.clipboard.writeText(id);notice('Đã sao chép.');break;
      case 'copy-commands':if(!navigator.clipboard)throw new Error('Hãy chọn và sao chép nội dung lệnh hiển thị.');await navigator.clipboard.writeText($('decrypt-commands').textContent);notice('Đã sao chép lệnh.');break;
      case 'try-keys':await tryKeys();break;
      case 'show-keys':{const el=$('keys-panel');if(!el.hidden){el.hidden=true;el.innerHTML='';break;}const keys=await getKeys();el.innerHTML='<p>Lưu ý: khóa chủ thực tế nằm trong HSM/KMS, ngân hàng tự giữ khóa riêng. Khóa lộ đọc được bản ghi cũ vĩnh viễn.</p>'+table(['Chủ khóa','Khóa riêng','Sao chép'],keys.map(k=>[esc(k.code),'<code>'+esc(recordKey(k))+'</code>',recordKey(k)?btn('Sao chép khóa','copy',recordKey(k)):'—']));el.hidden=false;break;}
      case 'pbft-back':state.step=Math.max(0,state.step-1);drawPbft();break;
      case 'pbft-next':state.step=Math.min(9,state.step+1);drawPbft();break;
      case 'pbft-play':if(state.timer){clearInterval(state.timer);state.timer=null;}else if(!BU.motion.reduced()){if(state.step===9)state.step=0;state.timer=setInterval(()=>{state.step=Math.min(9,state.step+1);if(state.step===9){clearInterval(state.timer);state.timer=null;}drawPbft();},1100);}else{state.step=Math.min(9,state.step+1);}drawPbft();break;
      case 'postaudit':await api('/postaudit/run','POST',{});await loadPostaudit();notice('Đã chạy hậu kiểm.');break;
      case 'proposal':openDrawer('Duyệt đề xuất',id,'<form id="proposal-form" class="v4-form"><input type="hidden" name="id" value="'+esc(id)+'"><label>Quyết định<select name="decision"><option value="approve">Phê duyệt</option><option value="reject">Từ chối</option></select></label><label>Lý do<textarea name="note" required></textarea></label><button class="btn" type="submit">Ghi quyết định</button></form>');break;
      case 'auto':{const x=state.auto.find(x=>(x.group||x.key)===id);await api('/admin/auto-approval/'+encodeURIComponent(id),'PUT',{enabled:!x.enabled});await loadPortfolio();break;}
      case 'activate':case 'deactivate':await api('/admin/users/'+encodeURIComponent(id),'PATCH',{active:b.dataset.action==='activate'});await loadUsers();break;
    }},b);
  });
  document.addEventListener('submit',event=>{const form=event.target;if(form.id==='seller-filter-form'){event.preventDefault();submitSellerFilter();return;}if(form.id==='law-form'){event.preventDefault();lawSearch(new FormData(form));return;}if(!['tick-form','decision-form','policy-form','rotate-form','decrypt-form','manual-form','user-form','proposal-form'].includes(form.id))return;event.preventDefault();const data=new FormData(form),body=Object.fromEntries(data);action(async()=>{switch(form.id){
    case 'tick-form':await api('/monitoring/tick','POST',body.as_of?body:{});await loadLoans();await loadPortfolio();notice('Đã chạy giám sát.');break;
    case 'decision-form':if(!body.option_id)delete body.option_id;await api('/officer/applications/'+encodeURIComponent(state.app.id)+'/decision','POST',body);await openCase(state.app.id);await load();break;
    case 'policy-form':body.tiers=data.getAll('tiers').map(Number);body.excluded_groups=data.getAll('excluded_groups');if(!body.tiers.length)throw new Error('Chọn ít nhất một tầng.');for(const k of ['min_amount','max_amount','max_rate','min_share'])body[k]=Number(body[k]);if(body.min_share<0.3)throw new Error('Tỷ lệ tối thiểu phải từ 30%.');if(body.max_amount<body.min_amount)throw new Error('Số tiền tối đa phải từ số tiền tối thiểu.');await api('/banks/'+encodeURIComponent(state.bank.code)+'/policy','PUT',body);await loadBanks();notice('Đã lưu chính sách ngân hàng.');closeDrawer();break;
    case 'rotate-form':await api('/banks/'+encodeURIComponent(state.bank.code)+'/public-key','PUT',body);notice('Đã đăng ký khóa công khai mới.');closeDrawer();await loadBanks();break;
    case 'decrypt-form':{const r=await api('/chain/withdrawals/'+encodeURIComponent(state.withdrawal.id)+'/decrypt','POST',body);$('decrypt-result').innerHTML=(r.opened||[]).length?facts({'Mở được':r.opened.join(', '),'Dấu vân tay':r.fingerprints_ok,'Merkle':r.merkle_ok})+json(r.pieces,'Các mảnh đã giải mã'):'<p>Khóa này không mở được ô nào.</p>';setCommands(body.private_key_hex);form.reset();break;}
    case 'manual-form':body.amount=Number(body.amount);body.currency=state.regions.find(r=>r.code===body.region)?.currency;body.demo=true;body.split=Array.from(form.querySelectorAll('[data-split]')).filter(x=>Number(x.value)>0).map(x=>({bank:x.dataset.split,pct:Number(x.value)/100}));if(Math.round(body.split.reduce((sum,x)=>sum+x.pct,0)*10000)!==10000)throw new Error('Tổng phân bổ phải đúng 100,00%.');const result=await api('/withdrawals/manual','POST',body);$('manual-result').innerHTML=facts(result);await loadChain();await loadManual();notice('Đã tạo lệnh chi.');break;
    case 'user-form':if(!body.bank_code)body.bank_code=null;await api('/admin/users','POST',body);form.reset();await loadUsers();notice('Đã tạo tài khoản.');break;
    case 'proposal-form':await api('/postaudit/proposals/'+encodeURIComponent(body.id)+'/decision','POST',{decision:body.decision,note:body.note});closeDrawer();await loadPostaudit();notice('Đã ghi quyết định hậu kiểm.');break;
  }},form.querySelector('button[type="submit"]'));});
  document.addEventListener('input',event=>{if(event.target.id==='seller-filter'){clearTimeout(state.sellerTimer);state.sellerRequest++;state.sellerTimer=setTimeout(submitSellerFilter,300);}if(event.target.id==='pbft-step'){state.step=Number(event.target.value);drawPbft();$('pbft-step').focus();}if(event.target.matches('[data-split]')){$('split-total').textContent='Tổng: '+new Intl.NumberFormat('vi-VN',{maximumFractionDigits:2}).format(Array.from(document.querySelectorAll('[data-split]')).reduce((s,x)=>s+Number(x.value),0))+'%';}});
  document.addEventListener('change',event=>{if(event.target.id==='manual-region')updateRegion();});
  document.addEventListener('keydown',event=>{
    if($('drawer').hidden)return;
    if(event.target.closest('[data-case-tab]') && ['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){
      const tabs=CASE_TABS.map(([id])=>id),index=tabs.indexOf(state.tab);
      const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
      event.preventDefault();state.tab=tabs[next];renderCase();$('case-tab-'+state.tab).focus();return;
    }
if(event.key==='Escape')closeDrawer();if(event.key==='Tab'){const nodes=Array.from($('drawer').querySelectorAll('button,input,textarea,select,a[href],summary')).filter(x=>!x.disabled&&x.getClientRects().length);const first=nodes[0],last=nodes[nodes.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}});
  document.addEventListener('submit',event=>{const form=event.target.closest('form.complaint-answer');if(!form)return;event.preventDefault();
    const fd=new FormData(form),id=form.dataset.complaint;
    action(async()=>{await api('/complaints/'+encodeURIComponent(id)+'/answer','POST',{outcome:fd.get('outcome'),text:String(fd.get('text')||'').trim()});await loadComplaints();await panel('applications','/officer/queue',d=>{$('queue-count').textContent=items(d).length;return appRows(d);});notice('Đã trả lời khiếu nại '+id+'.');},form.querySelector('button'));});
  $('drawer-close').addEventListener('click',closeDrawer);$('drawer-backdrop').addEventListener('click',closeDrawer);
  $('refresh').addEventListener('click',()=>action(load,$('refresh')));
  $('logout').addEventListener('click',()=>action(async()=>{await BU.api.auth.logout();BU.session.clear();location.replace('login.html');},$('logout')));
  document.querySelectorAll('[data-admin]').forEach(el=>el.hidden=!admin);$('role-label').textContent=admin?'Quản trị viên':'Cán bộ tín dụng';
  document.addEventListener('visibilitychange',()=>{if(document.hidden && state.timer){clearInterval(state.timer);state.timer=null;drawPbft();}});
  matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',e=>{if(e.matches){clearInterval(state.timer);state.timer=null;drawPbft();}});
  BU.motion.init();drawPbft();
  action(async()=>{
    const me=await api('/auth/me');
    if(!me || !me.user)throw new Error('Không xác minh được phiên đăng nhập.');
    BU.session.set({...session,user:me.user});
    if(!['officer','admin'].includes(me.user.role)){location.replace(BU.session.home(me.user.role));return;}
    admin=me.user.role==='admin';
    document.querySelectorAll('[data-admin]').forEach(el=>el.hidden=!admin);
    $('role-label').textContent=admin?'Quản trị viên':'Cán bộ tín dụng';
    await load();
    // The agents work in the background; pick up what they found once a minute while the tab is visible.
    setInterval(()=>{const a=document.activeElement;if(!document.hidden&&$('drawer').hidden&&!(a&&a.closest&&a.closest('form,details[open]'))){loadLoans();loadPostaudit();panel('applications','/officer/queue',d=>{$('queue-count').textContent=items(d).length;return appRows(d);});}},60000);
  });
})();
