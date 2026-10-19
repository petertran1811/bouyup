/* No dependencies. Run BackEnd/.venv/bin/python -B Frontend/tests/v4-api-check.py first, then node v4-ui-check.mjs.
 * Executes the real seller/staff scripts with API evidence and a minimal DOM.
 * Verifies behavior and escaping; it does not validate browser layout/focus. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
const flowSample=JSON.parse(fs.readFileSync(new URL('./fixtures/flow-sample.json',import.meta.url),'utf8'));
const evidence=JSON.parse(fs.readFileSync(process.env.V4_API_EVIDENCE || '/tmp/v4-qa-api-evidence.json','utf8'));
class Element {
  constructor(){this.innerHTML='';this.textContent='';this.hidden=false;this.dataset={};this.attrs={};this.events={};this.isConnected=true;this.disabled=false;this.value='';this.style={setProperty(){}};const s=new Set();this.classList={add:x=>s.add(x),remove:x=>s.delete(x),contains:x=>s.has(x),toggle:(x,on)=>{if(on??!s.has(x))s.add(x);else s.delete(x);}};}
  addEventListener(n,f){(this.events[n]||=[]).push(f)}
  setAttribute(n,v){this.attrs[n]=v} removeAttribute(n){delete this.attrs[n]} focus(){} showModal(){this.open=true} close(){this.open=false} scrollIntoView(){} matches(selector){return selector==='[data-split]' && this.dataset.split!=null} closest(selector){return selector.startsWith('[data-') ? (this.dataset[selector.slice(6,-1).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]!=null?this:null) : this}
  querySelector(){return new Element()} querySelectorAll(){return []} appendChild(child){child.parentNode=this;return child}
}
const settle=async()=>{for(let i=0;i<100;i++)await Promise.resolve()};
const SRC={'admin-v4.js':'quan-tri/admin-v4.js','workspace-v4.js':'nguoi-ban/workspace-v4.js'};
// opts.face: the account registered a face (BU.face stub, user.face_enrolled); opts.faceError: the face
// re-check rejects with that code; opts.otpCancel: the SMS OTP box (otp-sms.js stub) is cancelled.
function setup(script, responder,role='seller', authenticated=true, storage=new Map(), opts={}){
 const elements=new Map(),calls=[],timers=new Map(),timerDelays=new Map();let timerId=0;
 const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
 el('drawer').hidden=true; const document=new Element();document.getElementById=el;document.body=new Element();document.activeElement=new Element();
 const request=async(path,options={})=>{calls.push({path,options});const out=structuredClone(await responder(path,options));if(opts.face&&path==='/v4/auth/me'&&out?.user)out.user.face_enrolled=true;return out};
 const redirects=[], savedSessions=[], otpCalls=[], faceCalls=[]; const BU={requireRole:()=>authenticated?({user:{role,display_name:'Test',email:'test@example.com',...(opts.face?{face_enrolled:true}:{})}}):null,session:{set:v=>savedSessions.push(v),home:r=>r+'.html'},api:{request},motion:{init(){},reduced:()=>true},
  otp:{verify:async o=>{otpCalls.push(o);if(opts.otpCancel)throw Object.assign(Error('Đã hủy xác thực bằng mã OTP.'),{code:'CANCELLED'});return {method:'otp',phone:'+84912345678',phone_masked:'•••• 678',verified_at:'2026-10-18T00:00:00Z'}}}};
 if(opts.face)BU.face={verify:async()=>{faceCalls.push(1);if(opts.faceError)throw Object.assign(Error('Không dùng được khuôn mặt.'),{code:opts.faceError});return 'fv-1'}};
 const sessionStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)};
 const ctx=vm.createContext({sessionStorage,BU,document,console,URL,Intl,Date,Set,Map,Number,String,Error,Promise,JSON,Math,Object,Array,encodeURIComponent,navigator:{},location:{origin:'http://testserver',assign:p=>redirects.push(p),replace:p=>redirects.push(p)},TextEncoder,Uint8Array,matchMedia:()=>({matches:true,addEventListener(){}}),setTimeout:(fn,delay)=>{timers.set(++timerId,fn);timerDelays.set(timerId,delay);return timerId},clearTimeout:id=>timers.delete(id),setInterval:()=>0,clearInterval(){},crypto:webcrypto,FormData:class extends Map{constructor(f){super(f.values)}getAll(k){const v=this.get(k);return Array.isArray(v)?v:[v].filter(x=>x!=null)}}});ctx.window=ctx;
 vm.runInContext(fs.readFileSync(new URL('../src/'+SRC[script],import.meta.url),'utf8'),ctx,{filename:script});
 const event=async(name,target)=>{for(const f of document.events[name]||[])f({target,preventDefault(){}});await settle()};
 const click=async(action,data={})=>{const target=new Element();target.dataset={action,...data};await event('click',target)};
 const submit=async(name,values)=>{const form=new Element();form.id=name;form.dataset={form:name,index:'0'};form.values=Object.entries(values);await event('submit',form)};
 const flush=async()=>{const callbacks=[...timers.values()];timers.clear();for(const fn of callbacks)await fn();await settle()};
 return {el,ctx,calls,event,click,submit,flush,timers,timerDelays,redirects,savedSessions,storage,otpCalls,faceCalls};
}
let count=0;
async function check(name,fn){await fn();count++;console.log('PASS '+name)}
const plain=value=>JSON.parse(JSON.stringify(value));
const n=value=>new Intl.NumberFormat('vi-VN').format(value);
const BOXES=['credit_inquiry','share_partners','data_processing'];
const lan=evidence.lan;
function sellerResponse(app, overrides={}){
 return async(path,options)=>{
  if(overrides[path])return overrides[path](options);
  if(path==='/v4/auth/me')return {user:{role:'seller',display_name:'Test',email:'test@example.com'}};
  if(path==='/v4/applications')return {items:[app]};
  if(path==='/v4/public/demo-stores')return {stores:[]};
  if(path==='/v4/public/features')return {cccd_ocr:true};
  if(path===`/v4/applications/${app.id}`)return app;
  if(path===`/v4/applications/${app.id}/contract`)return lan.contract;
  if(path.endsWith('/messages'))return {items:[]};
  if(path.endsWith('/trace'))return {events:[],chain:[]};
  if(path.startsWith('/v4/loans/'))return lan.loan;
  throw Error('Unexpected API '+path);
 }
}
// "other" never becomes an application: it stops at the store connection (HANDOVER 16.7, checks below).
const SCENARIOS=['lan','noevid','notes','ecig','tea','shoes','company','young','electronics','thin','personal','nobank'];
await check('every loan-circle API outcome routes to the wizard without seller technical panels',async()=>{
 const cases=SCENARIOS.map(name=>[name,evidence[name].application]).concat([['lan offered',lan.offered_app],['lan selected',lan.selected_app],['lan disbursed',lan.disbursed_app]]);
 for(const [name,app] of cases){
  const e=setup('workspace-v4.js',sellerResponse(app));await settle();await e.click('open',{id:app.id});
  const html=e.el('wizard-screen').innerHTML;
  assert(html.length>100,name);assert(e.el('seller-wizard').open,name);
  assert(!/llm_notes|AML-|RISK[-_]|POL-\d|LAW-|lookup_public_store|Pha [012]|Agent \d/.test(html),name);
  assert(!/accept-offer|smaller_offer|sweep|tỷ lệ trích/i.test(html),name+' shows no old-model offer');
  assert(!e.calls.some(x=>x.path.endsWith('/trace')),'seller does not fetch technical trace');
  if(app.status==='offered')assert(html.includes('data-form="choice"'),name+' opens the choice screen');
  if(app.status==='rejected'||app.status==='out_of_scope')assert(html.includes('wizard-close'),name);
  if(app.status==='escalated')assert(html.includes('Chờ chút nhé'),name);
 }
 const young=evidence.young.application;assert(young.verification.eligible_from);
 const e=setup('workspace-v4.js',sellerResponse(young));await settle();await e.click('open',{id:young.id});
 assert(e.el('wizard-screen').innerHTML.includes('Có thể đủ điều kiện từ'));
});
await check('chat opens beside the wizard once verification is done, never before',async()=>{
 const done=lan.offered_app,why='Hồ sơ cần cán bộ tín dụng xem thêm.\n\nLý do:\n• Lý do một.\n• Lý do hai.\n\nBạn có thể:\n• Việc nên làm.';
 const e=setup('workspace-v4.js',sellerResponse(done,{[`/v4/applications/${done.id}/messages`]:()=>({items:[{from:'agent2',text:why}]})}));await settle();await e.click('open',{id:done.id});await settle();
 assert(e.el('seller-wizard').classList.contains('split'),'verified case shows the chat');assert(!e.el('wizard-chat').hidden);
 // Phase E (lỗi 3): the "vì sao" answer keeps its lines: headline, "• " reasons as a list, "Bạn có thể:" apart.
 const log=e.el('chat-log').innerHTML;
 assert(log.includes('<p>Lý do:</p><ul><li>Lý do một.</li><li>Lý do hai.</li></ul><p>Bạn có thể:</p><ul><li>Việc nên làm.</li></ul>'),log);
 const early={...structuredClone(done),status:'verifying',offer:null,next_action:{key:'verify'},verification:{...done.verification,state:'IN_PROGRESS'}};
 const f=setup('workspace-v4.js',sellerResponse(early));await settle();await f.click('open',{id:early.id});
 assert(!f.el('seller-wizard').classList.contains('split'),'no chat during verification');assert(f.el('wizard-chat').hidden);
});
await check('first-run asks the borrower type and unfinished applications open on the three consent boxes',async()=>{
 const app=structuredClone(lan.application);app.status='identified';app.loan_id=null;app.offer=null;app.next_action={key:'consent'};
 const fresh=setup('workspace-v4.js',sellerResponse(app,{'/v4/applications':()=>({items:[]})}));await settle();
 const welcome=fresh.el('wizard-screen').innerHTML;
 assert(fresh.el('seller-wizard').open);assert(welcome.includes('Bắt đầu'));
 assert(welcome.includes('value="individual_business" checked'));assert(welcome.includes('value="company"'));assert(welcome.includes('Hộ kinh doanh'));assert(welcome.includes('Doanh nghiệp'));
 const unfinished=setup('workspace-v4.js',sellerResponse(app));await settle();
 const html=unfinished.el('wizard-screen').innerHTML;
 assert(unfinished.el('seller-wizard').open);assert(html.includes('Cho phép BuoyUp kiểm tra hồ sơ'));
 for(const box of BOXES)assert(new RegExp(`name="${box}" +required`).test(html),box+' is a separate unticked box');
 assert(!/name="(credit_inquiry|share_partners|data_processing)" checked/.test(html));
 assert(!html.includes('value="face"'),'no registered face: no face option');assert(html.includes('value="otp" checked'));assert(!html.includes('tail'),'no bank accounts any more');
 const withFace=setup('workspace-v4.js',sellerResponse(app),'seller',true,new Map(),{face:true});await settle();
 const faceHtml=withFace.el('wizard-screen').innerHTML;assert(faceHtml.includes('value="face" checked')&&faceHtml.includes('value="otp"'),'a registered face is offered first');
 await unfinished.click('wizard-close');assert.equal(unfinished.el('seller-wizard').open,false);
 await unfinished.click('resume');assert(unfinished.el('seller-wizard').open);assert(unfinished.el('wizard-screen').innerHTML.includes('Cho phép BuoyUp kiểm tra hồ sơ'));
});
await check('multiple stores confirm one at a time and safely escape store names',async()=>{
 const app=structuredClone(lan.application);app.status='draft';app.loan_id=null;app.offer=null;app.next_action={key:'identity'};
 app.stores=[{...app.stores[0],entity:'<img src=x onerror=alert(1)>'},{...app.stores[0],entity:'Cửa hàng thứ hai'}];
 const e=setup('workspace-v4.js',sellerResponse(app));await settle();
 let html=e.el('wizard-screen').innerHTML;assert(html.includes('Gian hàng 1/2'));assert(html.includes('&lt;img'));assert(!html.includes('<img src=x'));assert(!html.includes('Cửa hàng thứ hai'));
 await e.click('confirm-store');html=e.el('wizard-screen').innerHTML;
 assert(html.includes('Gian hàng 2/2'));assert(html.includes('Cửa hàng thứ hai'));assert(!html.includes('identity-tile'));
 await e.click('wizard-back');assert(e.el('wizard-screen').innerHTML.includes('Gian hàng 1/2'));
 await e.click('confirm-store');await e.click('wizard-close');
 const reload=setup('workspace-v4.js',sellerResponse(app),'seller',true,e.storage);await settle();
 assert(reload.el('wizard-screen').innerHTML.includes('Gian hàng 2/2'));
 await reload.click('confirm-store');assert(reload.el('wizard-screen').innerHTML.includes('identity-tile'));
});
await check('staff-only escalation reasons stay a generic seller outcome',async()=>{
 for(const name of ['company','notes','tea','shoes']){
  const app=structuredClone(evidence[name].application);app.decision={...(app.decision||{}),reason:{law:'AML-CDD-01 Luật Chống rửa tiền',factor:'AML-CDD-01 RISK-06 llm_notes',fix:'POL-03 <b>x</b>'}};
  const e=setup('workspace-v4.js',sellerResponse(app));await settle();await e.click('open',{id:app.id});
  const html=e.el('wizard-screen').innerHTML;
  assert(html.includes('Chờ chút nhé'),name);
  assert(!/AML|RISK|POL-|llm_notes|pass.through|rửa tiền|<b>/i.test(html),name);
 }
});
await check('consent boxes require all three, sign server bytes and a failed draft retries only on explicit action',async()=>{
 const app=structuredClone(lan.application);app.status='identified';app.loan_id=null;app.offer=null;app.consent=null;app.next_action={key:'consent'};
 const document={consent_id:'CS-test',application:app.code,scopes:BOXES,method:'otp',signed_at:'2026-10-13T00:00:00Z',expires_at:'2027-10-13T00:00:00Z'};
 const draft={alg:'ed25519',document,message:JSON.stringify(document)};
 const path=`/v4/applications/${app.id}/consent/draft`;const drafts=[];
 const original=setup('workspace-v4.js',sellerResponse(app,{[path]:({body})=>{drafts.push(plain(body));return draft}}));await settle();
 await original.submit('consent-boxes',{credit_inquiry:'on',share_partners:'on',method:'otp'});
 assert.equal(drafts.length,0,'two boxes are not enough');assert.equal(original.el('wizard-notice').hidden,false);assert.match(original.el('wizard-notice').textContent,/ba ô/);
 await original.submit('consent-boxes',{credit_inquiry:'on',share_partners:'on',data_processing:'on',method:'otp'});
 assert.deepEqual(drafts,[{scopes:BOXES,method:'otp'}]);
 const html=original.el('wizard-screen').innerHTML;assert(html.includes('sign-consent'));assert(html.includes('mã OTP'));
 await original.click('wizard-close');
 const stored=JSON.parse(original.storage.get(`bu_seller_wizard:test@example.com:${app.id}`));assert.equal(stored.consentStep,2);assert.equal(stored.signMethod,'otp');
 let fail=true;
 const restored=setup('workspace-v4.js',sellerResponse(app,{[path]:()=>{if(fail)throw Error('Không lấy được bản ủy quyền.');return draft}}),'seller',true,original.storage);await settle();
 assert.equal(restored.calls.filter(x=>x.path===path).length,1);assert.equal(restored.el('wizard-notice').hidden,false);
 assert(restored.el('wizard-screen').innerHTML.includes('data-action="consent-draft"'));assert(!restored.el('wizard-screen').innerHTML.includes('sign-consent'));
 await restored.flush();await restored.click('wizard-close');await restored.click('resume');await restored.flush();
 assert.equal(restored.calls.filter(x=>x.path===path).length,1,'closing/reopening does not start a retry loop');
 fail=false;await restored.click('consent-draft');assert.equal(restored.calls.filter(x=>x.path===path).length,2);
 assert.deepEqual(plain(restored.calls.at(-1).options.body),{scopes:BOXES,method:'otp'});
 assert(restored.el('wizard-screen').innerHTML.includes('sign-consent'));
 let signed=null;
 const responder=sellerResponse(app,{[path]:()=>draft,[`/v4/applications/${app.id}/consent`]:async({body})=>{
  const sig=body.signature;assert.equal(sig.alg,'ed25519');assert.equal(sig.public_key.length,64);assert.equal(sig.sig.length,128);
  assert.deepEqual(plain(body.scopes),BOXES);assert.equal(body.method,'face');assert.equal(body.face_verify_id,'fv-1');assert(!('accounts' in body));
  const key=await webcrypto.subtle.importKey('raw',Buffer.from(sig.public_key,'hex'),'Ed25519',false,['verify']);
  signed=await webcrypto.subtle.verify('Ed25519',key,Buffer.from(sig.sig,'hex'),new TextEncoder().encode(draft.message));return app;
 }});
 const e=setup('workspace-v4.js',responder,'seller',true,new Map(),{face:true});await settle();await e.click('open',{id:app.id});
 await e.submit('consent-boxes',{credit_inquiry:'on',share_partners:'on',data_processing:'on',method:'face'});
 assert(!e.calls.some(x=>x.path.endsWith('/consent')));
 await e.submit('sign-consent',{confirm:'on'});
 for(let i=0;i<100&&signed===null;i++)await new Promise(r=>setTimeout(r,5));assert.equal(signed,true);await settle();
 assert.equal(e.faceCalls.length,1);assert.equal(e.otpCalls.length,0,'the face re-check passed: no OTP');
 const revoked=structuredClone(lan.offered_app);revoked.next_action={key:'consent'};revoked.consent.revoked_at='2026-10-13T01:00:00Z';
 const renewal=setup('workspace-v4.js',sellerResponse(revoked));await settle();await renewal.click('open',{id:revoked.id});
 assert(renewal.el('wizard-screen').innerHTML.includes('Cho phép BuoyUp kiểm tra hồ sơ'));assert(!renewal.el('wizard-screen').innerHTML.includes('data-form="choice"'));
});
await check('choice screen quotes amount and due day (system tenor, instalments), sends the selection and ignores stale quotes',async()=>{
 const app=structuredClone(lan.offered_app),o=app.offer,quotePath=`/v4/applications/${app.id}/quote`;
 const quote=body=>({...lan.quote,amount:body.amount,tenor_m:body.tenor_m,method:body.method,method_label:body.method==='revenue'?'Trả theo doanh thu':'Trả góp',total_interest:4321,total_due:body.amount+4321,revenue_rate:body.method==='revenue'?.12:null});
 let selected;
 const e=setup('workspace-v4.js',sellerResponse(app,{[quotePath]:({body})=>quote(body),[`/v4/applications/${app.id}/select`]:({body})=>{selected=plain(body);return lan.selected_app}}));await settle();await e.click('open',{id:app.id});
 let html=e.el('wizard-screen').innerHTML;
 assert(html.includes('Ngân hàng đã duyệt hạn mức'));assert(html.includes('Tối đa '+n(o.limit)+' tệ'));
 // Phase E (lỗi 1): an approval with reasons shows Agent 3's explanation on the choice screen (list + buttons).
 const why=app.decision.explanation;assert(why.because.length&&html.includes('class="decision-explain"')&&html.includes('class="explain-because"'),'explanation block');
 assert(html.includes('Vì sao')&&html.includes('data-action="explain-ask"'),'reasons and the action buttons');
 const plain1=structuredClone(lan.offered_app);plain1.decision={...plain1.decision,explanation:{...plain1.decision.explanation,because:[]}};
 const g=setup('workspace-v4.js',sellerResponse(plain1));await settle();await g.click('open',{id:plain1.id});
 assert(!g.el('wizard-screen').innerHTML.includes('decision-explain'),'a plain approval without reasons shows no block');
 assert(html.includes(`type="range" min="${o.slider.min}" max="${o.slider.max}" step="${o.slider.step}" value="${o.suggested}"`));
 // Review 17/10/2026: no tenor or method choice; both are shown as facts.
 assert(!html.includes('name="tenor_m"'));assert(!html.includes('value="revenue"'));assert(html.includes(`${n(o.tenor_max)} tháng`));
 assert(html.includes('Tài khoản WeBank của bạn'));assert(html.includes('name="due_day"')&&html.includes('min="1" max="28"'));
 for(const b of app.syndicate.split)assert(html.includes(`${b.name} ${Math.round(b.pct*100)}%`),b.bank);
 assert(/type="submit" class="btn btn-primary" disabled/.test(html),'cannot select before the quote arrives');
 assert.equal(e.calls.filter(x=>x.path===quotePath).length,0);await e.flush();
 assert.deepEqual(plain(e.calls.filter(x=>x.path===quotePath).at(-1).options.body),{amount:o.suggested,tenor_m:o.tenor_max,method:'installment',due_day:10});
 assert(e.el('choice-quote').innerHTML.includes(n(4321)));assert(e.el('choice-quote').innerHTML.includes('Lịch trả dự kiến'));
 const form=new Element();form.dataset.form='choice';form.values=Object.entries({amount:'150000',due_day:'28'});
 const input=new Element();input.name='amount';input.closest=selector=>selector==='[data-form="choice"]'?form:null;
 await e.event('input',input);assert.equal(e.el('choice-amount-label').textContent,n(150000)+' tệ');
 await e.flush();assert.deepEqual(plain(e.calls.filter(x=>x.path===quotePath).at(-1).options.body),{amount:150000,tenor_m:o.tenor_max,method:'installment',due_day:28});
 assert(e.el('choice-quote').innerHTML.includes(n(154321)));
 // A slower reply for an older choice never overwrites the screen.
 let finish;const pending=new Promise(r=>finish=r);const real=e.ctx.BU.api.request;e.ctx.BU.api.request=async()=>pending;
 await e.event('input',input);const run=e.flush();await e.click('wizard-close');await e.click('resume');e.el('choice-quote').innerHTML='new screen';finish(quote({amount:1,tenor_m:3,method:'installment'}));await run;
 assert.equal(e.el('choice-quote').innerHTML,'new screen');e.ctx.BU.api.request=real;
 await e.submit('choice',{amount:'150000',due_day:'28'});
 assert.deepEqual(selected,{amount:150000,due_day:28});
 await settle();assert(e.calls.some(x=>x.path===`/v4/applications/${app.id}/contract`),'selection opens the contract');
});
await check('contract screen shows the disclosure, keeps signing locked for the reading time and sends the signature body',async()=>{
 const app=structuredClone(lan.selected_app),k=structuredClone(lan.contract);k.terms=[...k.terms,'<script>alert(1)</script>'];
 // A first loan is a seed loan (≤ 100.000, all to the business account); keep the supplier branch covered
 // with the split a later loan above 100.000 gets.
 if(!k.needs.supplier_account){k.payee={kind:'split',to_account:Math.max(0,k.amount-20000),to_supplier:20000,supplier:'SUP-0091'};k.needs={...k.needs,supplier_account:true};}
 const e=setup('workspace-v4.js',sellerResponse(app,{[`/v4/applications/${app.id}/contract`]:()=>k}));await settle();await settle();
 let html=e.el('wizard-screen').innerHTML;
 assert.equal(e.calls.filter(x=>x.path.endsWith('/contract')).length,1);
 assert(html.includes('Đọc bảng chi phí và hợp đồng'));assert(html.includes(`ít nhất ${k.read_seconds} giây`));
 assert(html.includes(`Còn ${k.read_seconds} giây đọc`));assert(/disabled id="sign-submit"/.test(html));
 for(const v of [k.amount,k.total_interest,k.total_due,k.schedule[0].payment])assert(html.includes(n(v)),'figure '+v);
 for(const b of k.banks)assert(html.includes(`${b.name} ${n(b.amount)} tệ`),b.bank);
 assert(html.includes('trả thẳng nhà cung cấp')||html.includes('trả thẳng '+k.payee.supplier));
 assert(html.includes('name="supplier_account"'),'amount above 100.000 asks the supplier account');assert(!html.includes('name="guarantee"'),'no guarantee for an individual business');
 assert(html.includes('name="use_of_funds_commitment" required'));assert(html.includes('name="read_ack" required'));
 assert(!html.includes('<script>alert'));assert(html.includes('&lt;script&gt;alert(1)'));
 await e.flush();assert.match(e.el('read-timer').textContent,/^Còn \d+ giây đọc$/);
 const company={...k,read_seconds:0,needs:{supplier_account:false,guarantee:true},payee:{kind:'account'}};
 let body;
 const f=setup('workspace-v4.js',sellerResponse(app,{[`/v4/applications/${app.id}/contract`]:()=>company,[`/v4/applications/${app.id}/sign`]:({body:b})=>{body=plain(b);return lan.disbursed_app}}));await settle();await settle();
 html=f.el('wizard-screen').innerHTML;assert(html.includes('Bạn có thể ký'));assert(/type="submit" class="btn btn-primary" id="sign-submit"/.test(html));
 assert(html.includes('name="guarantee" required'));assert(!html.includes('name="supplier_account"'));
 assert(html.includes('value="otp" checked')&&!html.includes('value="face"'),'no registered face: the contract is signed with the OTP');
 await f.submit('sign',{webank_account:'12',use_of_funds_commitment:'on',guarantee:'on',read_ack:'on',method:'otp'});
 assert.equal(body,undefined);assert.equal(f.otpCalls.length,0,'a bad account number is refused before the OTP');
 await f.submit('sign',{webank_account:' 6222000012345 ',use_of_funds_commitment:'on',guarantee:'on',read_ack:'on',method:'otp'});
 assert.deepEqual(body,{read_ack:true,webank_account:'6222000012345',use_of_funds_commitment:true,guarantee:true,method:'otp',otp_verified:true});
 assert.equal(f.otpCalls.length,1);assert.match(f.otpCalls[0].sub,/ký hợp đồng/);
 html=f.el('wizard-screen').innerHTML;assert(html.includes('Đã giải ngân!'));assert(html.includes(n(lan.loan.amount)));
 let signed;
 const g=setup('workspace-v4.js',sellerResponse(app,{[`/v4/applications/${app.id}/contract`]:()=>({...k,read_seconds:0}),[`/v4/applications/${app.id}/sign`]:({body:b})=>{signed=plain(b);return lan.disbursed_app}}),'seller',true,new Map(),{face:true});await settle();await settle();
 assert(g.el('wizard-screen').innerHTML.includes('value="face" checked'),'a registered face is offered first');
 await g.submit('sign',{webank_account:'6222000012345',supplier_account:' 88880001 ',use_of_funds_commitment:'on',read_ack:'on',method:'face'});
 assert.deepEqual(signed,{read_ack:true,webank_account:'6222000012345',use_of_funds_commitment:true,guarantee:false,method:'face',supplier_account:'88880001',face_verify_id:'fv-1'});
 // The face cannot be checked ("Dùng mã OTP thay thế", no camera, no model): the OTP box signs instead.
 for(const code of ['USE_OTP','FACE_UNAVAILABLE']){
  signed=null;const h2=setup('workspace-v4.js',sellerResponse(app,{[`/v4/applications/${app.id}/contract`]:()=>({...k,read_seconds:0}),[`/v4/applications/${app.id}/sign`]:({body:b})=>{signed=plain(b);return lan.disbursed_app}}),'seller',true,new Map(),{face:true,faceError:code});await settle();await settle();
  await h2.submit('sign',{webank_account:'6222000012345',supplier_account:'88880001',use_of_funds_commitment:'on',read_ack:'on',method:'face'});
  assert.equal(signed.method,'otp',code);assert.equal(signed.otp_verified,true);assert(!('face_verify_id' in signed));
  assert.equal(h2.otpCalls.length,1);assert.equal(Boolean(h2.otpCalls[0].reason),code!=='USE_OTP','the reason is shown when the server has no face model');
 }
 // Cancelling the OTP box signs nothing.
 signed=null;const c2=setup('workspace-v4.js',sellerResponse(app,{[`/v4/applications/${app.id}/contract`]:()=>({...k,read_seconds:0}),[`/v4/applications/${app.id}/sign`]:({body:b})=>{signed=plain(b);return lan.disbursed_app}}),'seller',true,new Map(),{otpCancel:true});await settle();await settle();
 await c2.submit('sign',{webank_account:'6222000012345',supplier_account:'88880001',use_of_funds_commitment:'on',read_ack:'on',method:'otp'});
 assert.equal(signed,null);assert.match(c2.el('wizard-notice').textContent,/hủy xác thực/);
 const paid=(lan.loan?.payee || lan.disbursed_app?.payee || {});
 assert(g.el('wizard-screen').innerHTML.includes(paid.to_supplier?'trả thẳng nhà cung cấp':'Tiền đã vào tài khoản kinh doanh WeBank'));
});
await check('re-choosing from the contract posts the saved selection again',async()=>{
 const app=structuredClone(lan.selected_app);let again;
 const storage=new Map([[`bu_seller_wizard:test@example.com:${app.id}`,JSON.stringify({key:'sign',choice:{amount:120000,tenor_m:6,method:'installment',due_day:5}})]]);
 const e=setup('workspace-v4.js',sellerResponse(app,{[`/v4/applications/${app.id}/select`]:({body})=>{again=plain(body);return app}}),'seller',true,storage);await settle();await settle();
 await e.click('rechoose');assert.deepEqual(again,{amount:120000,tenor_m:6,method:'installment',due_day:5});
});
await check('missing optional demo discovery does not block real store entry',async()=>{
 const app=lan.application,missing=()=>{throw Object.assign(new Error('Not found'),{status:404})};
 const e=setup('workspace-v4.js',sellerResponse(app,{'/v4/public/demo-stores':missing}));await settle();
 await e.click('new');await e.submit('welcome',{tier:'2',borrower_type:'individual_business'});await e.click('demo-picker');
 assert(e.el('wizard-screen').innerHTML.includes('store_url'));assert(!e.el('notice').classList.contains('error'));
});
// HANDOVER 16.7 · Kết nối cửa hàng: ownership is proven before an application exists (real API shapes from v4-api-check).
const CONNECT=evidence.connect;
const err=(body)=>Object.assign(new Error(body.error.message),{status:400,code:body.error.code,details:body.error.details||{}});
function connectResponder(app,extra={}){
 const C=CONNECT.tmall,seen={created:null,lookup:[],start:[],verify:[]};
 const responder=sellerResponse(app,{
  '/v4/applications':o=>{if(o.method==='POST'){seen.created=plain(o.body);return app}return {items:[]}},
  '/v4/shops/platforms':()=>CONNECT.platforms,
  '/v4/shops/connect/lookup':o=>{seen.lookup.push(plain(o.body));return C.lookup},
  '/v4/shops/connect/start':o=>{seen.start.push(plain(o.body));return C.start},
  [`/v4/shops/connect/${C.start.connect_id}/verify`]:o=>{seen.verify.push(plain(o.body));return C.verify},...extra});
 return {responder,seen,C};
}
await check('store connection: preview, code to the registered phone checked by the server, then the application',async()=>{
 const app=structuredClone(evidence.tmall.application);app.status='draft';app.loan_id=null;app.offer=null;app.next_action={key:'identity'};
 const {responder,seen,C}=connectResponder(app);
 const e=setup('workspace-v4.js',responder);await settle();
 await e.submit('welcome',{tier:'2',borrower_type:'individual_business'});
 let html=e.el('wizard-screen').innerHTML;
 assert(html.includes('Kết nối cửa hàng')&&html.includes('Dán link cửa hàng của bạn'));assert(!html.includes('data-action="oauth"'),'no platform button without its keys');
 assert(!/type="password"|mật khẩu Tmall|mật khẩu Douyin/i.test(html),'never asks for the platform password');
 await e.submit('stores',{store_url:C.lookup.shop&&evidence.tmall.application.stores[0].url});
 assert.deepEqual(seen.lookup,[{url:evidence.tmall.application.stores[0].url}]);assert.equal(seen.start.length,0,'no code before the seller asks');
 html=e.el('wizard-screen').innerHTML;
 assert(html.includes('Xác nhận bạn là chủ cửa hàng')&&html.includes(C.lookup.shop.subject_masked)&&html.includes(C.lookup.shop.shop_name));
 assert(html.includes('Gửi mã tới số đăng ký của cửa hàng '+C.lookup.phone_masked));assert(!html.includes('otp-sms-body'));
 await e.click('shop-send');html=e.el('wizard-screen').innerHTML;
 assert.equal(seen.start.length,1);assert(html.includes('Mã đã gửi tới số điện thoại đăng ký của cửa hàng '+C.start.phone_masked+'. Nếu đó không phải số của bạn, bạn không phải chủ cửa hàng này.'));
 assert(html.includes('otp-sms-body')&&html.includes(C.start.dev_code),'the code arrives as the text message');
 await e.submit('shop-code',{code:C.start.dev_code});
 assert.deepEqual(seen.verify,[{code:C.start.dev_code}]);
 assert.deepEqual(seen.created,{tier:2,borrower_type:'individual_business',shop_connection_id:C.verify.connection.id});
 html=e.el('wizard-screen').innerHTML;
 assert(html.includes('Đây có phải cửa hàng của bạn?')&&html.includes('Đã xác minh quyền sở hữu qua số điện thoại đăng ký cửa hàng'),html);
 assert(!/\bdemo\b|mô phỏng|giả lập/i.test(html),'no demo wording on the seller screens');
});
await check('someone else\'s store: the code goes to the owner\'s phone, nothing to type it from',async()=>{
 const O=CONNECT.other,app=structuredClone(lan.application);
 const {responder,seen}=connectResponder(app,{'/v4/shops/connect/lookup':()=>O.lookup,'/v4/shops/connect/start':()=>O.start});
 const e=setup('workspace-v4.js',responder);await settle();
 await e.submit('welcome',{tier:'2',borrower_type:'individual_business'});await e.submit('stores',{store_url:'https://haohuo.jinritemai.com/views/shop/index?id=58828'});
 await e.click('shop-send');const html=e.el('wizard-screen').innerHTML;
 assert(html.includes('•••• 451')&&html.includes('Nếu đó không phải số của bạn, bạn không phải chủ cửa hàng này.'));
 assert(!html.includes('otp-sms-body'),'no text message: the phone is not the seller\'s');assert.equal(seen.created,null);
});
await check('a link nobody connected says SHOP_NOT_CONNECTED and offers the sample stores',async()=>{
 const {responder,seen}=connectResponder(lan.application,{'/v4/shops/connect/lookup':()=>{throw err(CONNECT.unknown)},'/v4/public/demo-stores':()=>({stores:[{scenario:'tmall',label:'Mẫu',url:'https://x',borrower_type:'individual_business'}]})});
 const e=setup('workspace-v4.js',responder);await settle();
 await e.submit('welcome',{tier:'2',borrower_type:'individual_business'});await e.submit('stores',{store_url:'https://shop.tmall.com/abc'});
 const html=e.el('wizard-screen').innerHTML;
 assert(html.includes('Chưa kết nối được cửa hàng này. Hãy kết nối cửa hàng qua sàn, hoặc chọn một gian hàng mẫu.'));assert(html.includes('data-action="demo-picker"'));
 assert.equal(seen.created,null,'no application, no copy of another dossier');
});
await check('unsupported link falls back to the registration number, still through the store connection',async()=>{
 const app=structuredClone(evidence.tmall.application);app.status='draft';app.loan_id=null;app.offer=null;app.next_action={key:'identity'};
 const {responder,seen,C}=connectResponder(app,{'/v4/shops/connect/lookup':o=>{seen.lookup.push(plain(o.body));if(!o.body.reg_no)throw err(CONNECT.unsupported);return C.lookup}});
 const e=setup('workspace-v4.js',responder);await settle();await e.submit('welcome',{tier:'2',borrower_type:'company'});
 await e.submit('stores',{store_url:'https://unknown.example/shop',reg_no:''});
 assert(e.el('wizard-screen').innerHTML.includes('Số đăng ký kinh doanh'));assert(!/type="url"[^>]*required/.test(e.el('wizard-screen').innerHTML));
 await e.submit('stores',{store_url:'https://unknown.example/shop',reg_no:'92330110MA2HYAQ71K'});
 assert.deepEqual(seen.lookup[1],{reg_no:'92330110MA2HYAQ71K'});
 await e.click('shop-send');assert.deepEqual(seen.start[0],{reg_no:'92330110MA2HYAQ71K'});
 await e.submit('shop-code',{code:C.start.dev_code});
 assert.deepEqual(seen.created,{tier:2,borrower_type:'company',shop_connection_id:C.verify.connection.id});
 assert(e.el('wizard-screen').innerHTML.includes('confirm-store'));
});
await check('platform buttons appear only for platforms BuoyUp has keys for, and open the platform\'s own page',async()=>{
 const {responder}=connectResponder(lan.application,{'/v4/shops/platforms':()=>({platforms:[{platform:'tmall',name:'Tmall',oauth:true},{platform:'douyin',name:'Douyin',oauth:false}],registered_phone_code:true}),
  '/v4/shops/connect/oauth/tmall/start?format=json':()=>({authorize_url:'https://oauth.taobao.com/authorize?client_id=k&state=s'})});
 const e=setup('workspace-v4.js',responder);await settle();await e.submit('welcome',{tier:'2',borrower_type:'individual_business'});
 const html=e.el('wizard-screen').innerHTML;assert(html.includes('Kết nối qua Tmall')&&!html.includes('Kết nối qua Douyin'));
 assert(html.includes('BuoyUp không bao giờ hỏi mật khẩu tài khoản sàn'));
 await e.click('oauth',{platform:'tmall'});assert.deepEqual(e.redirects,['https://oauth.taobao.com/authorize?client_id=k&state=s']);
});
await check('API prose is escaped on the choice screen',async()=>{
 const app=structuredClone(lan.offered_app);app.offer.explanation='<script>alert(1)</script>';app.syndicate.split[0].name='<img src=x>';
 const e=setup('workspace-v4.js',sellerResponse(app));await settle();await e.click('open',{id:app.id});
 const html=e.el('wizard-screen').innerHTML;assert(!html.includes('<script>alert'));assert(html.includes('&lt;script'));assert(!html.includes('<img src=x'));assert(html.includes('&lt;img src=x&gt;'));
});
await check('plan wizard submits entered amounts (no brand, no supplier) with optional statements and the declaration',async()=>{
 const app=structuredClone(lan.application);app.status='consented';app.loan_id=null;app.offer=null;app.next_action={key:'plan'};
 const bodies=[];
 const e=setup('workspace-v4.js',sellerResponse(app,{[`/v4/applications/${app.id}/plan`]:({body})=>{bodies.push(plain(body));return app}}));await settle();await e.click('open',{id:app.id});
 await e.submit('plan-step',{event:'11.11',item:'Áo'});
 await e.submit('plan-step',{qty:'1000',price:'80.5'});
 await e.submit('plan-step',{own_capital:'110000',inventory:'12000',other_loans:'5000'});
 assert.equal(bodies.length,0,'plan waits for step four');
 const html=e.el('wizard-screen').innerHTML;assert(html.includes('Doanh thu và ảnh chụp (tùy chọn)'));assert.equal((html.match(/name="st_month"/g)||[]).length,3);assert(html.includes('Gửi kế hoạch'));
 assert(html.includes('data-statement-images')&&html.includes('name="declaration" required')&&html.includes('Tôi cam đoan'));
 await e.submit('statements',{st_month:['2026-09','2026-08',''],st_revenue:['180000','175000',''],declare_images:'on'});
 assert.equal(bodies.length,0,'no declaration, no plan');
 await e.submit('statements',{st_month:['2026-09','2026-08',''],st_revenue:['180000','175000',''],declare_images:'on',declaration:'on'});
 const sent=bodies[0];assert(sent);
 assert.equal(sent.own_capital,110000);assert.equal(sent.qty,1000);assert.equal(sent.price,80.5);assert(!('supplier' in sent)&&!('brand' in sent));assert.equal(sent.declaration,true);assert.equal(sent.inventory,12000);assert.equal(sent.other_loans,5000);assert.equal(sent.event,'11.11');
 assert(!('suggested' in sent)&&!('submitted' in sent));
 assert.deepEqual(sent.statements,[{month:'2026-09',revenue:180000},{month:'2026-08',revenue:175000}]);
 await e.submit('statements',{st_month:['',''],st_revenue:['',''],declaration:'on'});
 assert(!('statements' in bodies[1]),'empty statements are optional and not sent');
});
await check('identity needs both CCCD sides read and the face scan; tier one follows verify without a plan',async()=>{
 const app=structuredClone(lan.application);app.status='draft';app.tier=1;app.loan_id=null;app.offer=null;app.next_action={key:'identity'};app.identity={};
 // CCCD OCR switched off: the simulated CCCD tile, as before.
 const off=setup('workspace-v4.js',sellerResponse(app,{'/v4/public/features':()=>({cccd_ocr:false})}));await settle();await off.click('confirm-store');
 assert(!off.el('wizard-screen').innerHTML.includes('data-cccd='));await off.click('identity-tile',{key:'cccd'});await off.click('identity-tile',{key:'face'});
 assert(!/data-action="identity" disabled/.test(off.el('wizard-screen').innerHTML),'tiles alone unlock the step when OCR is off');
 const after={...app,status:'identified',next_action:{key:'consent'}};
 const noScan=setup('workspace-v4.js',sellerResponse(app));await settle();await noScan.click('confirm-store');
 let html=noScan.el('wizard-screen').innerHTML;assert(html.includes('data-cccd="front"')&&html.includes('data-cccd="back"'));
 await noScan.click('identity-tile',{key:'face'});assert(/data-action="identity" disabled/.test(noScan.el('wizard-screen').innerHTML),'face alone is not enough');
 app.cccd_scans={front:{side:'front',fields:{name:{value:'示例用户'},id_number:{value:'440106199001011235'},birth_date:{value:'1990-01-01'}},warnings:[]},back:{side:'back',fields:{issuing_authority:{value:'测试公安机关'},validity_period:{value:'2020.01.01-2040.01.01'}},warnings:[]}};
 // No registered face: the tile is the SMS OTP box; the identity step sends otp_verified instead of the face.
 assert(html.includes('Xác thực bằng mã OTP'));
 const e=setup('workspace-v4.js',sellerResponse(app,{[`/v4/applications/${app.id}/identity`]:({body})=>{assert.deepEqual(plain(body),{cccd:true,face:false,otp_verified:true,otp_phone:'•••• 678'});return after}}));await settle();await e.click('confirm-store');
 html=e.el('wizard-screen').innerHTML;assert(html.includes('440106••••••••1235')&&!html.includes('440106199001011235'),'the number is masked on screen');
 assert(/data-action="identity" disabled/.test(html));
 await e.click('identity-tile',{key:'face'});assert(!/data-action="identity" disabled/.test(e.el('wizard-screen').innerHTML));
 assert.equal(e.otpCalls.length,1);assert(e.el('wizard-screen').innerHTML.includes('Đã xác thực bằng mã OTP'));await e.click('identity');
 assert(e.el('wizard-screen').innerHTML.includes('Cho phép BuoyUp kiểm tra hồ sơ'));
 // A registered face: the camera first; a passed re-check sends its id, a failed one ("Dùng mã OTP thay thế",
 // no face model) falls through to the OTP box; a cancelled OTP leaves the tile undone.
 for(const [faceError,expected] of [[null,{cccd:true,face:true,face_verify_id:'fv-1'}],['USE_OTP',{cccd:true,face:false,otp_verified:true,otp_phone:'•••• 678'}],['FACE_UNAVAILABLE',{cccd:true,face:false,otp_verified:true,otp_phone:'•••• 678'}]]){
  let sent=null;const f=setup('workspace-v4.js',sellerResponse(app,{[`/v4/applications/${app.id}/identity`]:({body})=>{sent=plain(body);return after}}),'seller',true,new Map(),{face:true,...(faceError?{faceError}:{})});await settle();await f.click('confirm-store');
  assert(f.el('wizard-screen').innerHTML.includes('Quét khuôn mặt'));await f.click('identity-tile',{key:'face'});await f.click('identity');
  assert.deepEqual(sent,expected,String(faceError));assert.equal(f.faceCalls.length,1);assert.equal(f.otpCalls.length,faceError?1:0);
 }
 const gone=setup('workspace-v4.js',sellerResponse(app),'seller',true,new Map(),{otpCancel:true});await settle();await gone.click('confirm-store');
 await gone.click('identity-tile',{key:'face'});assert(/data-action="identity" disabled/.test(gone.el('wizard-screen').innerHTML),'a cancelled OTP does not unlock the step');
 const verifying={...after,status:'consented',next_action:{key:'verify'}};
 const done={...structuredClone(lan.offered_app),id:app.id,tier:1};
 const v=setup('workspace-v4.js',sellerResponse(verifying,{[`/v4/applications/${app.id}/verify`]:()=>done}));await settle();
 assert(v.calls.some(x=>x.path.endsWith('/verify')));assert(!v.calls.some(x=>x.path.endsWith('/plan')));
 assert(v.el('wizard-screen').innerHTML.includes('Đã xác minh xong')&&!v.el('wizard-screen').innerHTML.includes('Đang xác minh'),'a finished check is titled as done');assert(!v.el('wizard-screen').innerHTML.includes('Kế hoạch'),'tier one has no plan row');
 await v.click('wizard-next');
 assert(v.el('wizard-screen').innerHTML.includes('data-form="choice"'));assert(!v.el('wizard-screen').innerHTML.includes('plan-step'));
});
await check('clarification renders and submits only the chosen extra fields',async()=>{
 const app=structuredClone(lan.application);app.status='needs_answer';app.loan_id=null;app.next_action={key:'answer'};
 app.verification.questions=[{flag:'test-flag',text:'Làm rõ tồn kho',choices:[{key:'fix',label:'Cập nhật tồn kho',needs:['inventory']},{key:'confirmed',label:'Thông tin đúng',needs:[]}]}];
 let submitted;
 const e=setup('workspace-v4.js',sellerResponse(app,{[`/v4/applications/${app.id}/answers`]:({body})=>{submitted=body;return app}}));await settle();
 assert(!e.el('wizard-screen').innerHTML.includes('name="inventory"'));
 const form=new Element();form.dataset.form='answer';form.values=Object.entries({choice:'fix'});
 e.el('wizard-screen').querySelector=selector=>selector==='form'?form:new Element();
 const radio=new Element();radio.name='choice';radio.value='fix';radio.closest=()=>form;
 e.ctx.CSS={escape:x=>x};await e.event('change',radio);
 assert(e.el('wizard-screen').innerHTML.includes('name="inventory"'));assert(!e.el('wizard-screen').innerHTML.includes('name="bank"'));
 await e.submit('answer',{choice:'fix',inventory:'999',store_url:'https://unused.example',bank:'CMB'});
 assert.deepEqual(plain(submitted),{flag:'test-flag',choice:'fix',inventory:999});
 await e.submit('answer',{choice:'confirmed',inventory:'999'});
 assert.deepEqual(plain(submitted),{flag:'test-flag',choice:'confirmed'});
});
await check('loan drawer shows schedule and balance, minimum/prepay send the right requests, no simulation forms',async()=>{
 const app=structuredClone(lan.disbursed_app),l=structuredClone(lan.loan),id=encodeURIComponent(l.id);
 l.notices=[{id:'nt-q',at:'2026-11-12T00:00:00Z',level:'yellow',kind:'question',text:'Tiền về thấp <img src=x>',question:{text:'Vì sao?',choices:[{key:'season',label:'Mùa thấp điểm'}]},answer:null},...l.notices];
 const closed={...structuredClone(lan.loan_prepaid),notices:[]},sent={};
 let current=l;const record=(name,result)=>({body})=>{sent[name]=plain(body);const {transfer,...loan}=result;current=loan;return result};
 const e=setup('workspace-v4.js',sellerResponse(app,{
  ['/v4/loans/'+id]:()=>current,
  [`/v4/loans/${id}/minimum`]:record('minimum',{...l,schedule:l.schedule.map((r,i)=>i===1?{...r,choice:'minimum'}:r),next_due:{...l.next_due,minimum_payment:l.minimum.quote.payment}}),
  [`/v4/loans/${id}/simulate-inflow`]:record('inflow',l),[`/v4/loans/${id}/simulate-transfer`]:record('transfer',{...l,transfer:{amount:100,kind:'personal'}}),
  [`/v4/loans/${id}/simulate-advance`]:record('advance',l),[`/v4/loans/${id}/notices/nt-q/answer`]:record('answer',l),
  [`/v4/loans/${id}/prepay`]:record('prepay',closed),[`/v4/loans/${id}/receiving-account`]:record('receiving',closed),
  '/v4/me/notices':()=>({items:current.notices.map(x=>({...x,scope:'loan',loan_id:l.id,title:'Thông báo khoản vay',read_at:null})),unread:current.notices.length}),
  '/v4/me/notices/read':({body})=>{sent.read=plain(body);return {unread:0};},
 }));await settle();
 assert.equal(e.el('seller-wizard').open,undefined,'a disbursed case opens on the home page');
 // Home v6 (17/10/2026): a bank-app home with feature tiles; the loan has its own page, the chat too.
 let html=e.el('workspace-main').innerHTML;
 for(const v of ['history','repay','chat','stats','reports','loan','schedule','apply','notices','complaints','account'])assert(html.includes(`dash-tile t-${v}`),'tile '+v);
 assert(html.includes('BuoyUp cần bạn trả lời 1 câu hỏi'),'urgent notice banner on the home page');
 await e.click('go',{view:'chat'});html=e.el('workspace-main').innerHTML;
 assert(html.includes('class="chat-first'),'chat page');assert(html.includes('data-action="loan-drawer"'));
 await e.click('go',{view:'loan'});html=e.el('workspace-main').innerHTML;
 for(const v of [l.amount,l.principal_outstanding,l.account.balance,l.next_due.payment_est,l.minimum.quote.payment,l.prepay_quote.total])assert(html.includes(n(v)),'figure '+v);
 assert.equal((html.match(/<tr><td>\d+<\/td>/g)||[]).length,l.schedule.length);assert(html.includes('Đã trả'));assert(html.includes('Sắp tới'));
 assert(html.includes('data-action="loan-minimum"'));assert(html.includes('data-action="loan-prepay"'));
 // Review 17/10/2026: no simulated money in or out on the seller screen; money arrives from WeBank.
 for(const form of ['inflow','transfer','advance'])assert(!html.includes(`data-form="${form}"`),form);
 await e.click('go',{view:'notices'});html=e.el('workspace-main').innerHTML;
 assert(!html.includes('<img src=x'));assert(html.includes('&lt;img src=x&gt;'));
 await e.click('go',{view:'loan'});
 assert(html.includes('lãi '+n(l.repayments[0].detail.interest)));
 await e.click('notice-answer',{notice:'nt-q',choice:'season'});assert.deepEqual(sent.answer,{choice:'season'});
 // SELLER_SERVICES_PLAN §3.2: both money buttons open a confirmation first (amount, interest/principal, tick, OTP).
 await e.click('loan-minimum');assert.equal(sent.minimum,undefined,'no request before the confirmation');
 let box=e.el('bu-dialog').innerHTML;assert(e.el('bu-dialog').open&&box.includes('data-form="pay-confirm"'));
 for(const v of [l.minimum.quote.payment,l.minimum.quote.interest,l.minimum.quote.principal])assert(box.includes(n(v)),'minimum figure '+v);
 assert(box.includes('name="ack"')&&!box.includes('name="otp"'),'the code is typed in the SMS OTP box, not here');
 assert(box.includes('value="otp" checked')&&!box.includes('value="face"'),'no registered face: OTP is the default');
 await e.submit('pay-confirm',{method:'otp'});assert.equal(sent.minimum,undefined,'the tick is required');assert.equal(e.otpCalls.length,0);
 await e.submit('pay-confirm',{ack:'on',method:'otp'});assert.deepEqual(sent.minimum,{confirm:true,method:'otp'});assert(e.el('workspace-main').innerHTML.includes('tối thiểu'));
 assert.equal(e.otpCalls.length,1,'the OTP box opened once');assert.match(e.otpCalls[0].sub,/khoản trả/);
 html=e.el('workspace-main').innerHTML;assert(html.includes('· tối thiểu '+n(l.minimum.quote.payment)),'Kỳ tới shows the minimum after choosing it');
 assert(!html.includes('khoảng '+n(l.next_due.payment_est)),'not the full instalment');
 await e.click('loan-prepay');assert.equal(sent.prepay,undefined);box=e.el('bu-dialog').innerHTML;
 for(const v of [l.prepay_quote.total,l.prepay_quote.principal])assert(box.includes(n(v)),'prepay figure '+v);
 await e.submit('pay-confirm',{ack:'on',method:'otp'});assert.deepEqual(sent.prepay,{confirm:true,method:'otp'});
 html=e.el('workspace-main').innerHTML;assert(html.includes('data-form="receiving"'));assert(!html.includes('data-action="loan-prepay"'));assert(!html.includes('data-form="inflow"'));
 await e.submit('receiving',{bank:'CMB',number:'62220000999'});assert.deepEqual(sent.receiving,{bank:'CMB',number:'62220000999'});
});
await check('payment box: the SMS OTP box confirms; a cancelled OTP pays nothing; a face that cannot be checked falls back to OTP',async()=>{
 const app=structuredClone(lan.disbursed_app),l=structuredClone(lan.loan),id=encodeURIComponent(l.id);l.notices=[];
 const run=async(opts,method)=>{
  const sent=[];const e=setup('workspace-v4.js',sellerResponse(app,{['/v4/loans/'+id]:()=>l,[`/v4/loans/${id}/minimum`]:({body})=>{sent.push(plain(body));return l},'/v4/me/notices':()=>({items:[],unread:0})}),'seller',true,new Map(),opts);await settle();
  await e.click('go',{view:'loan'});await e.click('loan-minimum');const box=e.el('bu-dialog').innerHTML;
  await e.submit('pay-confirm',{ack:'on',method});return {e,sent,box};
 };
 let r=await run({otpCancel:true},'otp');
 assert.deepEqual(r.sent,[],'a cancelled OTP pays nothing');assert.equal(r.e.otpCalls.length,1);assert(r.e.el('bu-dialog').open,'the payment box stays open');
 r=await run({face:true},'face');
 assert(r.box.includes('value="face" checked')&&r.box.includes('value="otp"'));assert.deepEqual(r.sent,[{confirm:true,method:'face',face_verify_id:'fv-1'}]);assert.equal(r.e.otpCalls.length,0);
 r=await run({face:true,faceError:'USE_OTP'},'face');
 assert.deepEqual(r.sent,[{confirm:true,method:'otp'}]);assert.equal(r.e.faceCalls.length,1);assert.equal(r.e.otpCalls.length,1);
 r=await run({face:true,faceError:'CANCELLED'},'face');
 assert.deepEqual(r.sent,[]);assert.equal(r.e.otpCalls.length,0);assert(r.e.el('bu-dialog').open,'a cancelled face scan reopens the payment box');
});
function staffResponse(app,overrides={}){
 return async(path,options)=>{
  if(overrides[path])return overrides[path](options);
  if(path==='/v4/auth/me')return {user:{role:'admin',id:'tester',email:'admin@buoyup.vn'}};
  const key=path.slice(3);
  if(evidence.staff[key])return evidence.staff[key];
  if(path==='/v4/applications')return {items:[app]};
  if(path===`/v4/applications/${app.id}`)return app;
  if(path.endsWith('/messages'))return {items:[{from:'agent2',text:'API message',blocked_numbers:2}]};
  if(path.endsWith('/trace'))return evidence.lan.trace;
  if(path==='/v4/postaudit/reports')return {items:[evidence.staff.postaudit.report]};
  if(path==='/v4/postaudit/proposals')return {items:evidence.staff.postaudit.proposals};
  if(path.startsWith('/v4/chain/blocks'))return evidence.staff['/chain/blocks'];
  if(path===`/v4/chain/withdrawals/${evidence.withdrawal.id}`)return evidence.withdrawal;
  if(path.startsWith('/v4/loans/'))return evidence.lan.loan;
  if(['/v4/regions','/v4/withdrawals'].includes(path))throw Object.assign(new Error('Feature missing'),{status:404});
  return {items:[]};
 };
}
await check('notices: one centre for case, loan and report notices, unread dots, read on open, badge from the API',async()=>{
 const app=structuredClone(lan.disbursed_app),l=structuredClone(lan.loan);
 const items=[{id:'nt-app',scope:'application',application_id:app.id,kind:'limit_approved',level:'info',title:'Ngân hàng đã duyệt hạn mức',text:'Hạn mức <b>100.000</b>',at:'2026-10-17T02:00:00Z',read_at:null,action:{view:'apply',id:app.id}},
  {id:'srp_1',scope:'report',report_id:'srp_1',kind:'month',level:'info',title:'Báo cáo tháng 2026-10',text:'Tháng 10 bạn bán được',at:'2026-10-16T02:00:00Z',read_at:null,action:{view:'report',id:'srp_1'}},
  {id:'nt-loan',scope:'loan',loan_id:l.id,kind:'disbursed',level:'warn',title:'Đã giải ngân',text:'Tiền đã về',at:'2026-10-15T02:00:00Z',read_at:'2026-10-15T03:00:00Z',action:{view:'loan',id:l.id}}];
 let read=null;
 const e=setup('workspace-v4.js',sellerResponse(app,{'/v4/me/notices':()=>({items,unread:2}),'/v4/me/notices/read':({body})=>{read=plain(body);return {unread:0};}}));await settle();
 assert(e.el('profile-nav').innerHTML.includes('aria-label="2 mục mới">2<'),'badge = unread from the API');
 assert(e.el('workspace-main').innerHTML.includes('2 chưa đọc'),'tile shows the unread count');
 await e.click('go',{view:'notices'});await settle();
 const html=e.el('workspace-main').innerHTML;
 for(const t of ['Ngân hàng đã duyệt hạn mức','Báo cáo tháng 2026-10','Đã giải ngân','Tiền đã về'])assert(html.includes(t),t);
 assert(!html.includes('<b>100.000</b>')&&html.includes('&lt;b&gt;'),'API prose is escaped');
 assert.equal((html.match(/class="notice-dot"/g)||[]).length,2,'dots on unread items only');
 assert(html.includes(`data-action="open" data-id="${app.id}"`),'a case notice opens the case');assert(html.includes('data-view="loan"'),'a loan notice opens the loan');
 assert.deepEqual(read,{ids:['nt-app','srp_1']},'opening the page marks the shown unread items read');
 assert(!e.el('profile-nav').innerHTML.includes('nav-count'),'badge cleared after reading');
});
await check('reports: Báo cáo page in the sidebar and a dashboard tile, list → report with coverage, 3 figures, charts, print; opened from a notice',async()=>{
 const app=structuredClone(lan.disbursed_app),month=structuredClone(lan.report_month),closing=structuredClone(lan.report_closing);
 month.data.summary+=' <img src=x>';
 const list={items:[...lan.reports.items.map(x=>x.kind==='month'?{...x,summary:month.data.summary}:x),{...closing,data:undefined}],unread:2};
 const notes=[{id:month.id,scope:'report',report_id:month.id,kind:'month',level:'info',title:'Báo cáo tháng 2026-10',text:'Tháng 10',at:month.at,read_at:null,action:{view:'report',id:month.id}}];
 const opened=[],printed=[];
 const e=setup('workspace-v4.js',sellerResponse(app,{'/v4/me/reports':()=>list,[`/v4/me/reports/${month.id}`]:()=>{opened.push(month.id);return month;},
  [`/v4/me/reports/${closing.id}`]:()=>{opened.push(closing.id);return closing;},'/v4/me/notices':()=>({items:notes,unread:1}),'/v4/me/notices/read':()=>({unread:0}),
  '/v4/me/bank':()=>({account:{balance:1,currency:'CNY',number_masked:'•••• 1'},loans:[],movements:[],totals:{month_in:50000,coverage:{share:0.45,basis:'tax',month:'2026-10'}}})}));
 e.ctx.print=()=>printed.push(1);await settle();
 assert(e.el('profile-nav').innerHTML.includes('data-view="reports"'),'sidebar item');
 let html=e.el('workspace-main').innerHTML;
 assert(html.includes('dash-tile t-reports'),'dashboard tile');assert(html.includes('≈ 45 % doanh thu của bạn'),'coverage line under "Tiền hàng về tháng này"');
 await e.click('go',{view:'history'});await settle();html=e.el('workspace-main').innerHTML;
 assert(html.includes('Ra <strong>0 tệ</strong>')&&html.includes('Vào <strong class="pos">0 tệ</strong>')&&!html.includes('−-0'),'zero totals have no sign');
 await e.click('go',{view:'reports'});await settle();html=e.el('workspace-main').innerHTML;
 assert(html.includes('Báo cáo tháng 10/2026')&&html.includes('Báo cáo tất toán khoản vay'),'list of periods');
 assert(!html.includes('<img src=x>'),'list prose escaped');
 await e.click('open-report',{id:month.id});await settle();html=e.el('workspace-main').innerHTML;
 assert.deepEqual(opened,[month.id]);
 assert(html.includes('report-coverage')&&html.includes(month.data.notes[0].slice(0,30)),'coverage line');
 assert.equal((html.match(/class="kpi-card"/g)||[]).length,3,'three figures');
 for(const v of [month.data.sales.webank_in,month.data.expenses.total,month.data.cash.closing])assert(html.includes(n(v)),'figure '+v);
 assert(html.includes('data-chart="rep-exp"'),'hbars of the expense groups');assert(!html.includes('<img src=x>')&&html.includes('&lt;img src=x&gt;'),'summary escaped');
 assert(html.includes('data-action="report-print"'));await e.click('report-print');assert.equal(printed.length,1,'window.print()');
 assert(!/0x[0-9a-f]{8}/.test(html)&&!html.includes('sha256:'),'no chain hashes for the seller');
 await e.click('report-list');await e.click('open-report',{id:closing.id});await settle();html=e.el('workspace-main').innerHTML;
 assert(html.includes('Khoản vay')&&html.includes('Tổng lãi thật')&&html.includes(n(closing.data.loan_summary.total_interest)),'closing: loan summary');
 assert(html.includes('Lần vay sau'),'closing: next time');
 // From the notification centre: the report notice opens that report.
 await e.click('go',{view:'notices'});await settle();html=e.el('workspace-main').innerHTML;
 assert(html.includes(`data-action="open-report" data-id="${month.id}"`)&&html.includes('Xem báo cáo'),'notice button opens the report');
 await e.click('open-report',{id:month.id});await settle();assert(e.el('workspace-main').innerHTML.includes('report-page'));
 // The sidebar entry goes back to the list.
 await e.click('go',{view:'reports'});await settle();assert(e.el('workspace-main').innerHTML.includes('report-list'));
});
await check('staff tabs render full API flags, algorithm terms, sealed phases, gate, chat and chain',async()=>{
 const app=evidence.lan.staff_application,e=setup('admin-v4.js',staffResponse(app),'admin');await settle();await e.click('case',{id:app.id});
 assert(!e.el('drawer').hidden);const firstTab=new Element();firstTab.dataset.caseTab='a1';await e.event('click',firstTab);assert(e.el('drawer-body').innerHTML.includes('Cờ xác minh'));assert(e.el('manual').innerHTML.includes('Chưa khả dụng'));assert(e.el('chain-status').innerHTML.includes('Chuỗi cục bộ'));
 for(const tab of ['a1','algo','a2','a3','gate','chain']){
  const target=new Element();target.dataset.caseTab=tab;await e.event('click',target);
  assert(e.el('drawer-body').innerHTML.length>100);assert(e.el('tabs').innerHTML.includes(`data-case-tab="${tab}"`));
  if(tab==='algo')assert(e.el('drawer-body').innerHTML.includes(new Intl.NumberFormat('vi-VN').format(app.offer.card.amount)));
  if(tab==='a2')assert(e.el('drawer-body').innerHTML.includes('Số liệu bị chặn: 2'));
  if(tab==='a3')assert(e.el('drawer-body').innerHTML.includes(app.control.phase1.seal.hash));
 }
 assert(!e.el('reports').innerHTML.includes('Mô phỏng'));assert(e.el('proposals').innerHTML.includes('Xem và duyệt'));
});
await check('staff errors remain visible in modal and incomplete preoffer cannot continue',async()=>{
 const app=structuredClone(evidence.lan.staff_application);app.offer=null;app.plan={suggested:{price:80}};app.status='escalated';
 const e=setup('admin-v4.js',staffResponse(app,{['/v4/chain/cases/'+app.id+'/verify']:()=>{throw Object.assign(new Error('API failure'),{status:500});}}),'admin');await settle();await e.click('case',{id:app.id});
 assert(!e.el('drawer-body').innerHTML.includes('value="continue"'));assert(e.el('drawer-body').innerHTML.includes('hoàn tất kế hoạch'));
 await e.click('verify-case',{id:app.id});assert.equal(e.el('drawer-notice').textContent,'API failure');assert.equal(e.el('drawer-notice').hidden,false);
});
await check('decryption matrix uses actual opened pieces and reduced-motion PBFT advances without timers',async()=>{
 const app=evidence.lan.staff_application,keys=evidence.decryption.map((x,i)=>({...x,private_key_hex:i.toString(16).padStart(64,'0')}));
 const e=setup('admin-v4.js',staffResponse(app,{
  '/v4/chain/keys':()=>({items:keys}),
  [`/v4/chain/withdrawals/${evidence.withdrawal.id}/decrypt`]:({body})=>({opened:keys.find(k=>k.private_key_hex===body.private_key_hex).opened,fingerprints_ok:true,merkle_ok:true})
 }),'admin');await settle();await e.click('withdrawal',{id:evidence.withdrawal.id});await e.click('try-keys');
 const matrix=e.el('key-matrix').innerHTML;assert(matrix.includes('Ai đọc được gì'));assert(matrix.includes('Khóa này không mở được ô nào'));assert(matrix.includes('Công khai'));
 assert.equal(e.calls.filter(x=>x.path.endsWith('/decrypt')).length,keys.length);
 assert(!e.el('keys-panel').innerHTML.includes(keys[0].private_key_hex));
 await e.click('pbft-play');assert(e.el('pbft').innerHTML.includes('2 / 10'));assert.equal(e.timers.size,0);
});
await check('missing session mounts no seller or staff console and stale identity redirects',async()=>{
 for(const script of ['workspace-v4.js','admin-v4.js']){const e=setup(script,()=>{throw Error('No request allowed')},script.startsWith('workspace')?'seller':'admin',false);assert.equal(e.calls.length,0)}
 const app=evidence.lan.application,e=setup('workspace-v4.js',sellerResponse(app,{'/v4/auth/me':()=>({user:{role:'bank'}})}));await settle();assert.deepEqual(e.redirects,['bank.html']);assert(!e.calls.some(x=>x.path==='/v4/applications'));
});
await check('manual form sends catalog currency and decimal shares without deriving bank amounts',async()=>{
 const app=evidence.lan.staff_application;let submitted;
 const e=setup('admin-v4.js',staffResponse(app,{
  '/v4/regions':()=>({regions:[{code:'CN',currency:'CNY',provinces:[{code:'CN-GD',name:'Quảng Đông'}]}]}),
  '/v4/withdrawals/manual':({body})=>{submitted=body;return {id:'WD-test',simulated:true};}
 }),'admin');await settle();
 const form=new Element();form.id='manual-form';form.values=Object.entries({requestId:'frontend-test',region:'CN',province:'CN-GD',user:'Test',account:'DEMO',amount:'10000',reason:'Kiểm thử'});
 const splits=[['WEBANK','40'],['CMB','30'],['ICBC','30']].map(([bank,value])=>{const el=new Element();el.dataset.split=bank;el.value=value;return el});
 form.querySelectorAll=()=>splits;
 await e.event('submit',form);assert(submitted);assert.equal(submitted.currency,'CNY');assert.equal(submitted.demo,true);assert.equal(submitted.amount,10000);
 assert.deepEqual(JSON.parse(JSON.stringify(submitted.split)),[{bank:'WEBANK',pct:.4},{bank:'CMB',pct:.3},{bank:'ICBC',pct:.3}]);assert(submitted.split.every(x=>!('amount' in x)));
});
{
const app=structuredClone(evidence.lan.application);
app.loan_id='loan-chain-test'; app.status='disbursed'; app.next_action={key:'view_loan'};
const loan={...evidence.lan.loan,id:app.loan_id,withdrawal_id:'WD/chain-test'};
const endpoint='/v4/chain/withdrawals/WD%2Fchain-test';
const responder=record=>sellerResponse(app,{['/v4/loans/'+loan.id]:()=>loan,[endpoint]:record});
await check('remote seller confirmation is escaped and cached without rebuilding home',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);
 const e=setup('workspace-v4.js',responder(()=>pending));await settle();
 await e.click('wizard-close');
 assert.equal(e.calls.filter(c=>c.path===endpoint).length,1);
 const home=e.el('workspace-main').innerHTML;
 resolve({simulated:false,block:'<25>',remote:{confirmedNodes:4,totalNodes:4},explorer_url:'https://example.test/explorer/?a=1&b=2'});await settle();
 const html=e.el('home-loan-chain').innerHTML;
 assert.match(html,/FISCO BCOS.*&lt;25&gt;.*4\/4 nút xác nhận/);
 assert.match(html,/rel="noopener noreferrer"/);assert.match(html,/a=1&amp;b=2/);
 assert.equal(e.el('workspace-main').innerHTML,home);
 await e.click('wizard-close');assert.equal(e.calls.filter(c=>c.path===endpoint).length,1);
});
await check('local confirmation and failed requests cache silently',async()=>{
 const e=setup('workspace-v4.js',responder(()=>({simulated:true})));await settle();
 assert.equal(e.el('home-loan-chain').innerHTML,'Giải ngân đã ghi sổ');
 const f=setup('workspace-v4.js',responder(()=>{throw Error('offline')}));await settle();await f.click('wizard-close');
 assert.equal(f.calls.filter(c=>c.path===endpoint).length,1);assert(!f.el('notice').classList.contains('error'));
});
await check('unsafe URLs are omitted and stale completion never changes the new screen',async()=>{
 const e=setup('workspace-v4.js',responder(()=>({simulated:false,explorer_url:'javascript:alert(1)'})));await settle();
 assert(!e.el('home-loan-chain').innerHTML.includes('<a'));
 let resolve;const pending=new Promise(r=>resolve=r);
 const f=setup('workspace-v4.js',responder(()=>pending));await settle();await f.click('new');
 f.el('home-loan-chain').innerHTML='new screen';
 resolve({simulated:true});await settle();assert.equal(f.el('home-loan-chain').innerHTML,'new screen');
});

}
const realChain={mode:'remote',simulated:false,url:'https://fs.buoyup.app',explorer_url:'https://fs.buoyup.app/explorer/',height:28,group:1,consensus:'PBFT',nodes:[{id:'node<0>',status:'up',sealer:true,block:28}],contracts:{AuditTrail:'0x1234567890123456789012345678901234567890'},catalog_sync:{at:'2026-10-14T04:52:00Z',ok:true,banks:10,keys:10}};
await check('real chain status, mixed withdrawals, remote key selection and sync refresh',async()=>{
 const app=evidence.lan.staff_application,local={id:'WD-local',simulated:true},real={id:'WD-real',simulated:false,block:25,tx:'0xabc',explorer_url:'https://fs.buoyup.app/explorer/#/tx/0xabc',remote:{sealedBy:'node<0>',confirmedNodes:4,totalNodes:4}};
 const keys=[{code:'demo',private_key_hex:'a'.repeat(64),chain_private_key_hex:'b'.repeat(64)}];
 let synced=false;
 const e=setup('admin-v4.js',staffResponse(app,{
  '/v4/chain/status':()=>realChain,
  '/v4/chain/withdrawals':()=>({items:[real,local]}),
  '/v4/chain/withdrawals/WD-real':()=>real,
  '/v4/chain/withdrawals/WD-local':()=>local,
  '/v4/chain/keys':()=>({items:keys}),
  '/v4/chain/withdrawals/WD-real/decrypt':({body})=>{assert.equal(body.private_key_hex,keys[0].chain_private_key_hex);return {opened:['mine'],fingerprints_ok:true}},
  '/v4/chain/withdrawals/WD-local/decrypt':({body})=>{assert.equal(body.private_key_hex,keys[0].private_key_hex);return {opened:[]}},
  '/v4/chain/sync':options=>{assert.equal(options.method,'POST');synced=true;return {ok:true}}
 }),'admin');await settle();
 const html=e.el('chain-status').innerHTML;
 assert.match(html,/FISCO BCOS · chuỗi thật/);assert(!html.includes('Mô phỏng'));
 assert.match(html,/11:52 \(giờ VN\) · 10 ngân hàng · 10 khóa/);assert.match(html,/Sealer/);assert.match(html,/node&lt;0&gt;/);assert.match(html,/rel="noopener noreferrer"/);
 assert.match(html,/data-id="0x1234567890123456789012345678901234567890"/);
 assert.match(e.el('blocks-title').textContent,/Khối cục bộ/);assert.equal(e.el('blocks-hint').hidden,false);
 assert.match(e.el('chain-disclosure').textContent,/4 nút.*không dùng cho production/);
 assert.match(e.el('withdrawals').innerHTML,/Chuỗi thật/);assert.match(e.el('withdrawals').innerHTML,/Chuỗi cục bộ/);assert(!/Mô phỏng/.test(e.el('withdrawals').innerHTML));
 await e.click('withdrawal',{id:real.id});assert.match(e.el('withdrawal-detail').innerHTML,/4\/4/);assert.match(e.el('withdrawal-detail').innerHTML,/node&lt;0&gt;/);
 assert.match(e.el('decrypt-commands').textContent,/https:\/\/fs.buoyup.app\/explorer\/decrypt_withdrawal.py/);assert(!e.el('decrypt-commands').textContent.includes('/v4/chain/withdrawals'));
 await e.click('try-keys');
 e.el('keys-panel').hidden=true; // The minimal DOM does not parse the rendered hidden attribute.
 await e.click('show-keys');assert.match(e.el('keys-panel').innerHTML,new RegExp(keys[0].chain_private_key_hex));assert(!e.el('keys-panel').innerHTML.includes(keys[0].private_key_hex));
 await e.click('withdrawal',{id:local.id});await e.click('try-keys');assert.match(e.el('decrypt-commands').textContent,/testserver\/v4\/chain\/withdrawals\/WD-local/);
 await e.click('chain-sync');assert(synced);assert.equal(e.calls.filter(c=>c.path==='/v4/chain/status').length,2);
});
await check('chain sync is admin-only and local/down/error states stay honest',async()=>{
 const app=evidence.lan.staff_application;
 const officer=setup('admin-v4.js',staffResponse(app,{'/v4/auth/me':()=>({user:{role:'officer'}}),'/v4/chain/status':()=>realChain}),'officer');await settle();
 assert(!officer.el('chain-status').innerHTML.includes('chain-sync'));await officer.click('chain-sync');assert(!officer.calls.some(c=>c.path==='/v4/chain/sync'));
 const local=setup('admin-v4.js',staffResponse(app,{'/v4/chain/status':()=>({mode:'local',simulated:true})}),'admin');await settle();await local.click('chain-sync');
 assert(!local.calls.some(c=>c.path==='/v4/chain/sync'));assert.match(local.el('chain-status').innerHTML,/Chuỗi cục bộ/);assert.equal(local.el('blocks-hint').hidden,true);
 const failed=setup('admin-v4.js',staffResponse(app,{'/v4/chain/status':()=>({...realChain,explorer_url:'javascript:alert(1)',catalog_sync:{ok:false,error:'<script>sync failed</script>'}}),'/v4/chain/sync':()=>{throw Object.assign(Error('CHAIN_UNAVAILABLE'),{status:503})}}),'admin');await settle();
 assert(!failed.el('chain-status').innerHTML.includes('javascript:'));assert.match(failed.el('chain-status').innerHTML,/&lt;script&gt;sync failed/);
 await failed.click('chain-sync');assert.match(failed.el('board-notice').textContent,/CHAIN_UNAVAILABLE/);
 const down=setup('admin-v4.js',staffResponse(app,{'/v4/chain/status':()=>{throw Object.assign(Error('CHAIN_UNAVAILABLE'),{status:503})}}),'admin');await settle();assert.match(down.el('chain-status').innerHTML,/CHAIN_UNAVAILABLE/);
});
await check('staff syndicate rounds and split stay escaped on the Agent 3 tab',async()=>{
 const app=structuredClone(evidence.lan.staff_application);
 assert(app.syndicate.rounds.length);app.syndicate.rounds[0].responses[0]={...app.syndicate.rounds[0].responses[0],name:'Bank <b>X</b>',reason:'Chỉ nhận hạng A <img>',ms:1500};
 const e=setup('admin-v4.js',staffResponse(app),'admin');await settle();await e.click('case',{id:app.id});const tab=new Element();tab.dataset.caseTab='a3';await e.event('click',tab);
 const html=e.el('drawer-body').innerHTML;
 assert(html.includes('Các ngân hàng duyệt song song'));assert(html.includes('Vòng '+new Intl.NumberFormat('vi-VN').format(app.syndicate.rounds[0].amount)));
 assert.match(html,/Bank &lt;b&gt;X&lt;\/b&gt;/);assert.match(html,/Chỉ nhận hạng A &lt;img&gt;/);assert.match(html,/1\.5 giây/);assert(!html.includes('<img>'));
 for(const b of app.syndicate.split)assert(html.includes(b.name),b.bank);
});
const escapeHtml=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const flowResponse=(app,flow,overrides={})=>staffResponse(app,{[`/v4/applications/${app.id}/flow`]:()=>flow,...overrides});
await check('full flow is the default accessible tab and renders the real loan-circle sample end to end',async()=>{
 const app=evidence.lan.staff_application,e=setup('admin-v4.js',flowResponse(app,flowSample),'admin');await settle();await e.click('case',{id:app.id});
 const html=e.el('drawer-body').innerHTML,tabs=e.el('tabs').innerHTML,num=v=>new Intl.NumberFormat('vi-VN').format(v);
 assert.match(tabs,/data-case-tab="flow"/);assert.match(tabs,/Toàn bộ luồng/);assert(tabs.indexOf('data-case-tab="flow"')<tabs.indexOf('data-case-tab="a1"'));
 assert.equal(e.el('drawer-body').attrs['aria-labelledby'],'case-tab-flow');assert.equal(e.el('drawer-body').attrs.role,'tabpanel');
 assert.equal(e.calls.filter(c=>c.path.endsWith('/flow')).length,1);
 for(const text of ['Đầu vào','Agent 1','Agent 2','Agent 3','B12 · Các ngân hàng duyệt song song','Chọn khoản vay và hợp đồng','Giải ngân','B11','Chuỗi',flowSample.seller.name,flowSample.seller.email,flowSample.seller.store,flowSample.seller.platform,flowSample.params_version,'Nguồn Agent 1','Khớp phiếu đã lưu','Nhu cầu vốn','Khả năng trả','Trần loại người vay','Trần quyết định','Tổng phải trả','Hạn mức ngân hàng duyệt','Người vay chọn','Trần tỷ lệ doanh thu'])assert(html.includes(text),text);assert(!html.includes('Dữ liệu mẫu')&&!html.includes('Mô phỏng'),'no simulation labels');
 assert(!/Trần trích|sweep_/.test(html),'no sweep-era labels');
 for(const block of flowSample.blocks){
  assert(html.includes(escapeHtml(block.title)),block.block+' title');assert(html.includes(escapeHtml(block.question)),block.block+' question');
  for(const input of block.inputs)for(const key of ['name','shown','source'])assert(html.includes(escapeHtml(input[key])),block.block+' '+key);
  for(const step of block.steps)assert(html.includes(escapeHtml(step)),block.block+' formula');
 }
 assert.equal((html.match(/<details\b[^>]*data-flow-block/g)||[]).length,flowSample.blocks.length);
 assert.equal((html.match(/<details\b[^>]*\bopen\b[^>]*data-flow-block|<details\b[^>]*data-flow-block[^>]*\bopen\b/g)||[]).length,flowSample.blocks.length);
 assert.match(html,/<th[^>]*>Điểm<\/th>/);
 for(const input of flowSample.blocks.find(b=>b.block==='B6').inputs)assert(html.includes('>'+input.points+'</td>'),'B6 points '+input.points);
 const b12=flowSample.b12,b11=flowSample.b11;
 for(const r of b12.rounds)for(const x of r.responses){assert(html.includes(escapeHtml(x.name)),x.bank);assert(html.includes(escapeHtml(x.reason)),x.reason);if(x.ms!=null)assert(html.includes((x.ms/1000).toFixed(1)+' giây'));}
 assert(html.includes('Vòng '+num(b12.rounds[0].amount)+' CNY'));assert(html.includes('Dẫn đầu'));assert(html.includes('Đối tác'));
 for(const leg of b12.legs){assert(html.includes(escapeHtml(leg.contract_id)),leg.bank);assert(html.includes(num(leg.amount)+' CNY'))}
 for(const s of b12.shares)assert(html.includes(num(s.repaid)+' CNY'),'repaid '+s.bank);
 for(const r of b11.schedule){assert(html.includes('<td>'+r.due_date+'</td>'),'row '+r.k)}
 for(const text of [flowSample.b10.flags[0].note,flowSample.agent2.rationale[0].claim,flowSample.agent2.rationale[0].evidence_ref,flowSample.gate.conditions[0].text,b11.rule,flowSample.contract.id,flowSample.chain[0].remote.tx])assert(html.includes(escapeHtml(text)),text);
 assert.match(html,/4\s*\/\s*4/);assert.match(html,/Chuỗi thật/);assert(html.includes(num(flowSample.selection.amount)+' CNY'));assert.match(html,/40\s*%/);
 for(const link of html.match(/<a\b[^>]*target="_blank"[^>]*>/g)||[])assert(link.includes('rel="noopener noreferrer"'));
 assert(html.includes(escapeHtml(flowSample.withdrawal.explorer_url)));
 const cards=flowSample.blocks.map(()=>Object.assign(new Element(),{open:true}));
 e.el('drawer-body').querySelectorAll=selector=>selector==='details[data-flow-block]'?cards:[];
 await e.click('flow-collapse');assert(cards.every(card=>!card.open));await e.click('flow-expand');assert(cards.every(card=>card.open));
});
await check('full flow escapes API prose and refuses unsafe explorer links',async()=>{
 const app=evidence.lan.staff_application,flow=structuredClone(flowSample),tokens=[];
 const poison=key=>{const value='<img src=x onerror="'+key+'">&\'';tokens.push(value);return value};
 flow.seller.name=poison('seller');flow.seller.email=poison('email');flow.seller.store=poison('store');flow.params_version=poison('params');flow.error=poison('error');
 flow.sources[0].tool=poison('tool');flow.sources[0].id=poison('source');flow.b10.checks[0].rule=poison('rule');flow.b10.flags[0].note=poison('flag');
 flow.blocks[0].title=poison('title');flow.blocks[0].question=poison('question');flow.blocks[0].inputs[0].name=poison('input');flow.blocks[0].inputs[0].shown=poison('shown');flow.blocks[0].inputs[0].source=poison('origin');flow.blocks[0].steps=[poison('step')];flow.blocks[0].output.group=poison('output');flow.blocks[1].note=poison('note');flow.blocks[0].matches=false;
 flow.agent2.rationale[0].claim=poison('claim');flow.agent2.rationale[0].evidence_ref=poison('reference');flow.agent2.card.payee=poison('payee');flow.gate.conditions[0].text=poison('gate');
 flow.b12.question=poison('b12');flow.b12.rounds[0].responses[0].name=poison('bank');flow.b12.rounds[0].responses[0].reason=poison('answer');flow.b12.split[0].name=poison('split');flow.b12.legs[0].contract_id=poison('leg');flow.b12.shares[0].contract_id=poison('contract');
 flow.selection.method_label=poison('method');flow.contract.id=poison('contract-id');flow.withdrawal.sealed_by=poison('sealer');
 flow.b11.rule=poison('monitoring');flow.b11.use_of_funds.supplier=poison('supplier');flow.b11.schedule[0].due_date=poison('due');flow.chain[0].kind=poison('chain');flow.chain[0].remote.tx=poison('remote');
 flow.withdrawal.explorer_url='javascript:alert(1)';flow.chain.forEach(x=>{x.remote.explorer_url='data:text/html,<script>alert(1)</script>'});
 const e=setup('admin-v4.js',flowResponse(app,flow),'admin');await settle();await e.click('case',{id:app.id});const html=e.el('drawer-body').innerHTML;
 for(const token of tokens){assert(html.includes(escapeHtml(token)),token);assert(!html.includes(token),token)}
 assert(!/<img\b|<script\b/.test(html));assert(!/href="(?:javascript:|data:)/.test(html));assert(html.includes('Lệch phiếu đã lưu'));
});
await check('flow handles pre-payout nulls, unsent banks, computation notices and unavailable endpoints',async()=>{
 const app=evidence.lan.staff_application,flow={application:flowSample.application,seller:flowSample.seller,params_version:'v4.0',params_rebuilt:false,error:'Đang chờ dữ liệu <pending>',sources:[],b10:null,blocks:[],agent2:null,agent3:null,gate:null,decision:null,b12:{status:'pending'},selection:null,contract:null,withdrawal:null,b11:null,chain:[]};
 const e=setup('admin-v4.js',flowResponse(app,flow),'admin');await settle();await e.click('case',{id:app.id});
 const html=e.el('drawer-body').innerHTML;
 assert.match(html,/Đang chờ dữ liệu &lt;pending&gt;/);assert(!html.includes('undefined'));assert(html.includes('Giải ngân'));
 assert(html.includes('Chưa gửi ngân hàng.'));assert(html.includes('Người vay chưa chọn.'));assert(html.includes('Theo dõi bắt đầu sau giải ngân.'));
 const empty=setup('admin-v4.js',flowResponse(app,null),'admin');await settle();await empty.click('case',{id:app.id});assert(!empty.el('drawer').hidden);assert(empty.el('drawer-body').innerHTML.length>0);assert(!/undefined|TypeError/.test(empty.el('drawer-body').innerHTML));
 const f=setup('admin-v4.js',flowResponse(app,null,{[`/v4/applications/${app.id}/flow`]:()=>{throw Error('Flow failed <offline>')}}),'admin');await settle();await f.click('case',{id:app.id});
 assert(!f.el('drawer').hidden);assert.match(f.el('drawer-body').innerHTML,/Flow failed &lt;offline&gt;/);
 const tab=new Element();tab.dataset.caseTab='a1';await f.event('click',tab);assert(f.el('drawer-body').innerHTML.includes('Cờ xác minh'));
});
await check('stale flow replies never reopen or replace a newer case',async()=>{
 const app=evidence.lan.staff_application,next={...app,id:'next-case',code:'NEXT-CASE'};let resolve;
 const pending=new Promise(r=>resolve=r),e=setup('admin-v4.js',flowResponse(app,flowSample,{
  [`/v4/applications/${app.id}/flow`]:()=>pending,
  '/v4/applications/next-case':()=>next,'/v4/applications/next-case/flow':()=>({...flowSample,seller:{...flowSample.seller,name:'Current seller'}})
 }),'admin');await settle();await e.click('case',{id:app.id});assert(!e.el('drawer').hidden);assert.match(e.el('drawer-body').innerHTML,/Đang tải/);await e.click('case',{id:next.id});
 assert.equal(e.el('drawer-title').textContent,'NEXT-CASE');const current=e.el('drawer-body').innerHTML;resolve(flowSample);await settle();assert.equal(e.el('drawer-title').textContent,'NEXT-CASE');assert.equal(e.el('drawer-body').innerHTML,current);
});
await check('seller filter debounces, submits on Enter, clears and escapes seller emails',async()=>{
 const app=evidence.lan.staff_application,query='Lan + & @',path='/v4/applications?seller='+encodeURIComponent(query),row={...app,seller_name:'Tên <seller>',seller_email:'mail<seller>@example.test'};
 const e=setup('admin-v4.js',staffResponse(app,{[path]:()=>({items:[row]})}),'admin');await settle();const input=e.el('seller-filter');input.id='seller-filter';
 input.value='Lan';await e.event('input',input);input.value=query;await e.event('input',input);
 assert.equal(e.calls.filter(c=>c.path.includes('?seller=')).length,0);assert.equal(e.timers.size,1);assert.equal(e.timerDelays.get([...e.timers.keys()][0]),300);
 await e.flush();assert.equal(e.calls.filter(c=>c.path===path).length,1);assert.match(e.el('credit-apps').innerHTML,/Tên &lt;seller&gt;/);assert.match(e.el('credit-apps').innerHTML,/mail&lt;seller&gt;@example.test/);
 await e.event('input',input);await e.submit('seller-filter-form',{seller:query});assert.equal(e.calls.filter(c=>c.path===path).length,2);await e.flush();assert.equal(e.calls.filter(c=>c.path===path).length,2,'Enter cancels pending debounce');
 const before=e.calls.filter(c=>c.path==='/v4/applications').length;await e.click('seller-filter-clear');assert.equal(input.value,'');assert.equal(e.calls.filter(c=>c.path==='/v4/applications').length,before+1);
});
await check('seller filter ignores stale successful and failed responses',async()=>{
 for(const fail of [false,true]){
  const app=evidence.lan.staff_application;let resolve,reject;const old=new Promise((yes,no)=>{resolve=yes;reject=no});
  const e=setup('admin-v4.js',staffResponse(app,{'/v4/applications?seller=old':()=>old,'/v4/applications?seller=new':()=>({items:[{...app,seller_name:'Newest seller',seller_email:'new@example.test'}]})}),'admin');await settle();
  const input=e.el('seller-filter');input.id='seller-filter';input.value='old';await e.submit('seller-filter-form',{seller:'old'});input.value='new';await e.submit('seller-filter-form',{seller:'new'});
  const current=e.el('credit-apps').innerHTML;assert(current.includes('Newest seller'));
  if(fail)reject(Error('Stale failure'));else resolve({items:[{...app,seller_name:'Stale seller'}]});await settle();assert.equal(e.el('credit-apps').innerHTML,current);assert(!e.el('board-notice').textContent.includes('Stale failure'));
 }
});
console.log(`${count} v4 UI groups passed. Browser layout and focus remain separate.`);
