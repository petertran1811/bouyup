/* Bank portal: every figure and authorized piece comes from v4. */
(function () {
  'use strict';
  if (!window.bankSession) return;
  var main = BU.shell.mount('#bank-shell', { title:'Ngân hàng đối tác' });
  if (!main) return;
  var state = { portfolio:null, withdrawals:[], syndicate:null, token:0 };
  var groups = ['quần áo','thực phẩm đóng gói','thực phẩm rời','thực phẩm chức năng','dược','thiết bị y tế I','thiết bị y tế II','thiết bị y tế III','thuốc lá điện tử','dịch thuốc lá điện tử','điện tử','khác'];
  function esc(value) { return String(value == null ? '' : value).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }
  function num(v) { return v == null ? '—' : new Intl.NumberFormat('vi-VN').format(v); }
  function money(v,c) { return v == null ? '—' : num(v)+' '+(c==='CNY'?'tệ':c==='VND'?'đồng':esc(c||'')); }
  function pct(v) { return v == null ? '—' : new Intl.NumberFormat('vi-VN',{style:'percent',maximumFractionDigits:2}).format(v); }
  function json(v) { return '<pre class="v4-json">'+esc(JSON.stringify(v,null,2))+'</pre>'; }
  function label(v) { return ({active:'Đang thu hồi',closed:'Đã tất toán',overdue:'Quá hạn',approve:'Đồng ý',decline:'Từ chối',timeout:'Quá 30 giây',not_sent:'Không gửi',no_partner:'Không ai nhận',offered:'Chờ người vay chọn',selected:'Chờ ký',signed:'Đã ký',disbursed:'Đã giải ngân',expired:'Hết hiệu lực',approved:'Đã duyệt',green:'Ổn định',yellow:'Cần theo dõi',red:'Cần cán bộ xem'})[v]||v||'—'; }
  function table(headers,rows) { return '<div class="table-wrap"><table><thead><tr>'+headers.map(function(h){return '<th>'+h+'</th>';}).join('')+'</tr></thead><tbody>'+(rows.length?rows.join(''):'<tr><td colspan="'+headers.length+'">Chưa có dữ liệu.</td></tr>')+'</tbody></table></div>'; }
  function errorText(e) { return e.status===404?'Chưa khả dụng. Chức năng đang được bổ sung.':e.message; }
  function notice(text,bad) { var n=main.querySelector('#bank-notice'); if(!n)return; n.textContent=text; n.className=bad?'v4-error':'v4-success'; n.hidden=false; }
  function explorerLink(w) {
    if (w.simulated !== false || !w.explorer_url) return '';
    try {
      var url = new URL(w.explorer_url);
      if (url.protocol !== 'https:' && url.protocol !== 'http:') return '';
      return '<a href="'+esc(url.href)+'" target="_blank" rel="noopener noreferrer">Xem trên explorer ↗</a>';
    } catch (e) { return ''; }
  }
  function chainTerms(bank) {
    var p=bank.policy||{}, chain=p.chain;
    if (!chain) return '';
    var contract=chain.contract||{};
    var facts=[['Số hợp đồng',esc(contract.no||'—')],['Trạng thái',esc(contract.status||'—')],['Hạn mức tín dụng',money(bank.limit_total,bank.currency)],['Điều khoản hoàn trả',esc(contract.reimbursement_terms||'—')],['Điều khoản phí',esc(contract.fee_terms||'—')],['Lãi suất',pct(p.min_rate)+' – '+pct(p.max_rate)+'/năm'],['Phần tối đa một khoản',pct(p.max_share)],['Tối đa mỗi khoản',money(p.max_share_amount,bank.currency)],['Tối thiểu mỗi lệnh',money(p.min_share_amount,bank.currency)],['Kỳ hạn tối đa',num(p.max_tenor_days)+' ngày'],['Tuổi cửa hàng tối thiểu',num(p.min_store_age_months)+' tháng'],['Điểm cửa hàng tối thiểu',num(p.min_store_rating)],['Phí',pct(p.fee_pct)]];
    return '<section class="v4-panel v4-bank-chain"><h2>Điều khoản trên chuỗi</h2><span class="bu-badge">FISCO BCOS · chuỗi thật</span><p class="v4-muted">Chỉ đọc · Điều khoản được thay đổi trên dịch vụ chuỗi. Bản gốc tiếng Anh từ chuỗi.</p><dl class="v4-bank-chain-facts">'+facts.map(function(f){return '<div><dt>'+f[0]+'</dt><dd>'+f[1]+'</dd></div>';}).join('')+'</dl><h3>Tóm tắt chính sách</h3><p>'+esc(chain.summary||'—')+'</p><h3>Khẩu vị rủi ro</h3><p>'+esc(chain.risk_appetite||'—')+'</p><div class="v4-grid">'+[['red_flags','Dấu hiệu cảnh báo'],['escalate_when','Trường hợp cần chuyển cấp'],['deal_breakers','Điều kiện loại trừ']].map(function(f){var items=Array.isArray(chain[f[0]])?chain[f[0]]:[];return '<div><h3>'+f[1]+'</h3>'+(items.length?'<ul>'+items.map(function(item){return '<li>'+esc(item)+'</li>';}).join('')+'</ul>':'<p class="v4-muted">Không có nội dung.</p>')+'</div>';}).join('')+'</div><p class="v4-muted">Phiên bản '+esc(chain.version==null?'—':chain.version)+' · Mã băm <code title="'+esc(chain.hash||'')+'">'+esc(chain.hash?String(chain.hash).slice(0,14)+'…':'—')+'</code></p></section>';
  }
  function policy(bank) {
    var p=bank.policy||{};
    return '<form id="bank-policy"><div class="v4-fields"><label>Hạng tối thiểu<select name="min_grade">'+['A','B','C','D','E'].map(function(g){return '<option'+(p.min_grade===g?' selected':'')+'>'+g+'</option>';}).join('')+'</select></label><fieldset><legend>Tầng khoản vay</legend>'+[1,2].map(function(t){return '<label><input type="checkbox" name="tiers" value="'+t+'"'+((p.tiers||[]).includes(t)?' checked':'')+'> Tầng '+t+'</label>';}).join('')+'</fieldset>'+[['min_amount','Số tiền tối thiểu',0,1],['max_amount','Số tiền tối đa',0,1],['max_rate','Lãi suất trần (tỷ lệ thập phân)',0.0001,0.0001],['min_share','Phần tối thiểu (0,30 = 30%)',0.30,0.0001]].filter(function(f){return !p.chain || f[0]!=='max_rate';}).map(function(f){return '<label>'+f[1]+'<input name="'+f[0]+'" type="number" required min="'+f[2]+'" step="'+f[3]+'"'+(f[0]==='min_share'?' max="1"':f[0]==='max_rate'?' max="0.36"':'')+' value="'+esc(p[f[0]])+'"></label>';}).join('')+'</div><fieldset><legend>Duyệt song song: ngành không cho vay</legend><div class="v4-fields">'+['thời trang','mỹ phẩm','tạp hóa','điện tử','khác'].map(function(g){return '<label><input type="checkbox" name="exclude_industries" value="'+esc(g)+'"'+((p.exclude_industries||[]).includes(g)?' checked':'')+'> '+esc(g)+'</label>';}).join('')+'</div></fieldset><fieldset><legend>Loại người vay nhận</legend>'+[['individual_business','Hộ kinh doanh'],['company','Doanh nghiệp']].map(function(t){return '<label><input type="checkbox" name="borrower_types" value="'+t[0]+'"'+((p.borrower_types||['individual_business','company']).includes(t[0])?' checked':'')+'> '+t[1]+'</label>';}).join('')+'</fieldset><div class="v4-fields"><label>Kỳ hạn tối đa (tháng)<input name="max_tenor_m" type="number" min="3" max="36" value="'+esc(p.max_tenor_m||36)+'"></label><label>Trễ hạn tối đa chấp nhận (ngày)<input name="max_late_days" type="number" min="0" max="90" value="'+esc(p.max_late_days==null?30:p.max_late_days)+'"></label></div><fieldset><legend>Nhóm hàng không nhận</legend><div class="v4-fields">'+groups.map(function(g){return '<label><input type="checkbox" name="excluded_groups" value="'+esc(g)+'"'+((p.excluded_groups||[]).includes(g)?' checked':'')+'> '+esc(g)+'</label>';}).join('')+'</div></fieldset><button class="bu-btn bu-btn--primary">Lưu chính sách</button></form>';
  }
  function render() {
    var d=state.portfolio,b=d.bank,c=b.currency,t=d.totals||{};
    main.innerHTML='<section class="v4-bank-hero"><p class="bu-eyebrow">BUOYUP / '+esc(b.code)+'</p><h1>'+esc(b.name)+'</h1><p>Mỗi ngân hàng chỉ thấy phần của mình. Dữ liệu được cấp theo quyền của phiên đăng nhập.</p>'+'<div class="v4-actions"><button class="bu-btn bu-btn--ghost" data-bank-action="refresh">Làm mới</button><a class="bu-btn bu-btn--ghost" href="index.html#security">Cơ chế bảo mật ↗</a></div></section><p id="bank-notice" role="status" hidden></p><div class="v4-bank-kpis">'+[['Hạn mức',b.limit_total],['Đã sử dụng',b.limit_used],['Còn lại',b.limit_remaining],['Phần vốn đã cấp',t.amount],['Đã thu',t.repaid],['Dư nợ phần của tôi',t.outstanding]].map(function(k){return '<dl><dt>'+k[0]+'</dt><dd>'+money(k[1],c)+'</dd></dl>';}).join('')+'</div>'+
      '<section class="v4-panel"><h2>Danh mục phần vốn</h2><p class="v4-muted">'+num(t.loans)+' khoản · '+num(t.active)+' đang hoạt động</p>'+table(['Khoản vay','Tỷ lệ','Phần vốn','Đã thu','Dư nợ','Hợp đồng','Trạng thái / cảnh báo'],(d.shares||[]).map(function(s){return '<tr><td><code>'+esc(s.loan_id)+'</code><br>'+esc(s.final_due_date)+'</td><td>'+pct(s.pct)+'</td><td data-numeric>'+money(s.amount,c)+'</td><td data-numeric>'+money(s.repaid,c)+'</td><td data-numeric>'+money(s.outstanding,c)+'</td><td>'+esc(s.contract_id)+'</td><td>'+esc(label(s.status))+'<br>'+esc(label(s.early_warning))+'</td></tr>';}))+'</section>'+
      '<section class="v4-panel"><h2>Lệnh giải ngân · phần của tôi</h2>'+(state.withdrawals===null?'<p>Chưa khả dụng.</p>':state.withdrawals.map(function(w){var mine=w.my_piece; return '<details><summary>'+esc(w.id)+' · '+esc(w.at)+' · '+(w.fingerprint_ok==null?'Chưa kiểm tra':w.fingerprint_ok?'Dấu vân tay khớp':'Dấu vân tay không khớp')+' · <span class="bu-badge">'+(w.simulated===false?'Chuỗi thật':'Chuỗi cục bộ')+'</span></summary>'+(explorerLink(w)?'<p>'+explorerLink(w)+'</p>':'')+'<p>Phần của tôi: '+(mine?pct(mine.pct)+' · '+money(mine.amount,c)+' · '+esc(mine.contract_id):'Chưa giải mã được bằng khóa hiện tại.')+'</p><h3>Tóm tắt được phép đọc</h3>'+json(w.summary)+'<button class="bu-btn bu-btn--ghost" data-bank-action="decrypt" data-id="'+esc(w.id)+'">Giải mã bằng khóa của tôi</button></details>';}).join('')||'<p>Chưa có lệnh giải ngân.</p>')+'</section>'+
      (state.syndicate===null?'':'<section class="v4-panel"><h2>Duyệt song song (giai đoạn 2)</h2><p class="v4-muted">Bộ điều phối gửi hồ sơ cho các ngân hàng cùng lúc; mỗi ngân hàng tự tra cứu tín dụng và trả lời trong 30 giây. Hai đối tác đồng ý: 40/30/30; một đối tác: 30/70. Phần quyết định của ngân hàng được tính theo chính sách đã khai.</p>'+table(['Hồ sơ','Hạng · loại','Câu trả lời của tôi','Kết quả · phần của tôi','Trạng thái'],state.syndicate.map(function(x){return '<tr><td>'+esc(x.application)+'<br><small>'+esc(x.industry||'')+' · '+esc(x.province||'')+'</small></td><td>'+esc(x.grade)+' · '+esc(x.borrower_type==='company'?'Doanh nghiệp':'Hộ kinh doanh')+'</td><td>'+(x.rounds.length?x.rounds.map(function(r){return money(r.amount,c)+': '+esc(label(r.decision))+(r.ms!=null?' ('+num(Math.round(r.ms/100)/10)+' giây)':'')+'<br><small>'+esc(r.reason)+'</small>';}).join('<br>'):'Ngân hàng dẫn đầu (không cần hỏi)')+'</td><td>'+esc(label(x.result))+(x.share?'<br>'+pct(x.share.pct)+' của '+money(x.limit,c):'')+'</td><td>'+esc(label(x.status))+'</td></tr>';}))+'</section>')+
      chainTerms(b)+'<div class="v4-grid"><section class="v4-panel"><h2>Chính sách tín dụng</h2>'+(b.policy&&b.policy.chain?'<p class="v4-muted">Biểu mẫu chỉ thay đổi quy tắc phía BuoyUp: hạng tối thiểu, tầng khoản vay, nhóm hàng loại trừ, số tiền khoản vay và phần tối thiểu. Điều khoản trên chuỗi được thay đổi trên dịch vụ chuỗi.</p>':'')+'<p class="v4-muted">Hợp đồng: '+esc(b.contract_id)+'</p>'+policy(b)+'</section><section class="v4-panel"><h2>Khóa mã hóa</h2><p class="v4-muted">Khóa công khai hiện tại</p><code style="overflow-wrap:anywhere">'+esc(b.public_key)+'</code><form id="bank-key"><label>Khóa công khai mới (hex)<textarea name="public_key" required rows="4" spellcheck="false"></textarea></label><p>Giữ khóa cũ để đọc các lệnh đã mã hóa.</p><button class="bu-btn bu-btn--ghost">Đăng ký khóa mới</button></form><h2>Giải mã lệnh</h2><form id="bank-decrypt"><label>Mã lệnh<input name="withdrawal_id" required></label><label>Khóa riêng (64 ký tự hex, để trống để dùng khóa phiên)<input name="private_key_hex" type="password" pattern="[0-9a-fA-F]{64}" autocomplete="off" spellcheck="false"></label><button class="bu-btn bu-btn--ghost">Giải mã</button></form><div id="bank-decrypt-result" role="status"></div></section></div>';
    BU.motion.init(main);
  }
  async function optional(fn) { try{return await fn();}catch(e){if(e.status===404)return null;throw e;} }
  async function load() {
    var token=++state.token;
    try {
      var results=await Promise.all([BU.api.bank.portfolio(),optional(BU.api.bank.withdrawals),optional(BU.api.bank.syndicate)]);
      if(token!==state.token)return;
      state.portfolio=results[0];state.withdrawals=results[1]?results[1].items||[]:null;
      state.syndicate=results[2]?results[2].items||[]:null;
      render();
    } catch(e) {
      if(e.status===401)return;
      main.innerHTML='<section class="v4-panel"><h1>Cổng ngân hàng</h1><p class="v4-error" role="alert">'+esc(errorText(e))+'</p><button class="bu-btn" data-bank-action="refresh">Thử lại</button></section>';
    }
  }
  async function decrypt(id,secret) {
    var r=await BU.api.chain.decrypt(id,secret?{private_key_hex:secret}:{}),h=main.querySelector('#bank-decrypt-result');
    h.innerHTML='<h3>Kết quả giải mã</h3><p>'+(r.opened&&r.opened.length?'Các ô đã mở: '+esc(r.opened.join(', ')):esc(r.message||'Khóa này không mở được ô nào.'))+'</p><p>'+(r.fingerprints_ok===true?'Dấu vân tay khớp. ':r.fingerprints_ok===false?'Dấu vân tay không khớp. ':'')+(r.merkle_ok===true?'Merkle khớp.':r.merkle_ok===false?'Merkle không khớp.':'')+'</p>'+json(r.pieces||{});
    h.scrollIntoView({block:'nearest'});
  }
  main.addEventListener('click',async function(event){
    var b=event.target.closest('[data-bank-action]');if(!b||b.disabled)return;b.disabled=true;
    try{if(b.dataset.bankAction==='refresh')await load();if(b.dataset.bankAction==='decrypt')await decrypt(b.dataset.id);}
    catch(e){if(e.status!==401)notice(errorText(e),true);}finally{b.disabled=false;}
  });
  main.addEventListener('submit',async function(event){
    event.preventDefault();var f=event.target,b=f.querySelector('button');if(b.disabled)return;b.disabled=true;var v=new FormData(f);
    try{
      if(f.id==='bank-policy'){
        var body={min_grade:v.get('min_grade'),tiers:v.getAll('tiers').map(Number),excluded_groups:v.getAll('excluded_groups'),exclude_industries:v.getAll('exclude_industries'),borrower_types:v.getAll('borrower_types'),max_tenor_m:Number(v.get('max_tenor_m')),max_late_days:Number(v.get('max_late_days'))};
        if(!body.borrower_types.length)throw new Error('Chọn ít nhất một loại người vay.');
        ['min_amount','max_amount','min_share'].concat(state.portfolio.bank.policy&&state.portfolio.bank.policy.chain?[]:['max_rate']).forEach(function(k){body[k]=Number(v.get(k));});
        if(!body.tiers.length)throw new Error('Chọn ít nhất một tầng khoản vay.');if(body.min_share<0.30)throw new Error('Phần tối thiểu phải từ 30%.');if(body.max_amount<body.min_amount)throw new Error('Số tiền tối đa phải từ số tiền tối thiểu.');
        await BU.api.banks.policy(state.portfolio.bank.code,body);await load();notice('Đã lưu chính sách.');
      }
      if(f.id==='bank-key'){if(!/^[a-fA-F0-9]{64}$/.test(String(v.get('public_key')).trim()))throw new Error('Khóa công khai cần đúng 64 ký tự hex.');await BU.api.banks.rotateKey(state.portfolio.bank.code,{public_key:String(v.get('public_key')).trim()});await load();notice('Đã đăng ký khóa công khai mới.');}
      if(f.id==='bank-decrypt'){var secret=String(v.get('private_key_hex')||'').trim();if(secret&&!/^[0-9a-fA-F]{64}$/.test(secret))throw new Error('Khóa riêng cần đúng 64 ký tự hex.');await decrypt(String(v.get('withdrawal_id')).trim(),secret);f.elements.private_key_hex.value='';}
    }catch(e){if(e.status!==401)notice(errorText(e),true);}finally{b.disabled=false;}
  });
  main.innerHTML='<section class="v4-panel" role="status">Đang xác minh phiên ngân hàng…</section>';
  BU.api.auth.me().then(function(data){
    if(!data||!data.user)throw new Error('Không xác minh được phiên ngân hàng.');
    BU.session.set({token:bankSession.token,expires_at:bankSession.expires_at,user:data.user});
    if(data.user.role!=='bank'){location.replace(BU.session.home(data.user.role));return;}return load();
  }).catch(function(e){if(e.status!==401)main.innerHTML='<p class="v4-error" role="alert">'+esc(errorText(e))+'</p>';});
})();
