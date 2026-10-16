"""Verify frontend v4 contracts with every loan-circle demo flow in an isolated temporary DB.
Run: BackEnd/.venv/bin/python -B Frontend/tests/v4-api-check.py
Evidence: /tmp/v4-qa-api-evidence.json. This is HTTP contract evidence, not browser QA.
No production database, backend files, or bytecode are written. The inline worker
shim matches c1-api-check.py for sandboxes that block thread wakeup sockets.
The 20-second contract reading clock is rewound in the temporary DB (as BackEnd/src/tests/lc.py does), never slept.
"""
import os,sys,json,asyncio,uuid
from datetime import date,datetime,timedelta
from pathlib import Path
os.environ.update(DATABASE_URL=f'sqlite:////tmp/v4-qa-{uuid.uuid4().hex}.db',APP_ENV='dev',CREDIT_LEDGER_KEY='devkey',LLM_ENABLED='false',BUOYUP_AUTOPILOT='false',PYTHONDONTWRITEBYTECODE='1',BUOYUP_CHAIN_BACKEND='local',BUOYUP_CHAIN_URL='',BUOYUP_AGENT5_MIN_SAMPLE='20')
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'BackEnd'/'src'))
import httpx,anyio.to_thread
async def inline(fn,*args,**kw): return fn(*args)
anyio.to_thread.run_sync=inline
from app.main import app
from app.platform.db.session import session_scope
from app.platform.tables import BuApplication,save_json
BOXES=['credit_inquiry','share_partners','data_processing']
EXPECTED={'lan':'offered','noevid':'offered','notes':'escalated','ecig':'rejected','tea':'escalated','shoes':'escalated','company':'escalated','young':'out_of_scope','other':'rejected','electronics':'offered','thin':'offered','nobank':'rejected'}
def rewind_contract(app_id,seconds=30):
 """The disclosure's reading clock, moved back instead of sleeping 20 s."""
 with session_scope() as s:
  row=s.get(BuApplication,app_id);doc=dict(row.doc);ct=dict(doc['contract'])
  ct['issued_at']=(datetime.fromisoformat(ct['issued_at'].rstrip('Z'))-timedelta(seconds=seconds)).isoformat()+'Z'
  doc['contract']=ct;save_json(row,'doc',doc)
records={}
async def main():
 async with app.router.lifespan_context(app):
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
   async def raw(method,path,body=None,token=None):
    return await c.request(method,'/v4'+path,json=body,headers={'Authorization':'Bearer '+token} if token else {})
   async def req(method,path,body=None,token=None):
    r=await raw(method,path,body,token)
    assert r.status_code<300,(path,r.status_code,r.text[:1500])
    return r.json() if r.content else None
   seller=(await req('POST','/auth/login',{'email':'lan@buoyup.vn','password':'BuoyUp@2026'}))['token']
   admin=(await req('POST','/auth/login',{'email':'admin@buoyup.vn','password':'BuoyUp@2026'}))['token']
   stores=(await req('GET','/public/demo-stores'))['stores'];assert sorted(s['scenario'] for s in stores)==sorted(EXPECTED),[s['scenario'] for s in stores]
   async def start(url,borrower_type='individual_business',statements=None,trail=None):
    a=await req('POST','/applications',{'tier':2,'borrower_type':borrower_type,'store_urls':[url]},seller);p='/applications/'+a['id']
    if trail is not None:trail.append(a['status'])
    assert a['borrower_type']==borrower_type if 'borrower_type' in a else True
    if a['status']=='rejected':return a
    a=await req('POST',p+'/identity',{'cccd':True,'face':True},seller)
    if trail is not None:trail.append(a['status'])
    if a['status']!='identified':return a
    assert a['next_action']['key']=='consent'
    # Missing one of the three boxes is refused; all three (face or OTP) are accepted.
    bad=await raw('POST',p+'/consent',{'scopes':BOXES[:2],'method':'face'},seller);assert bad.status_code==400,(bad.status_code,bad.text)
    a=await req('POST',p+'/consent',{'scopes':BOXES,'method':'otp'},seller)
    assert a['status']=='consented' and a['next_action']['key']=='plan',(a['status'],a['next_action'])
    plan={k:v for k,v in a['plan']['suggested'].items()}
    if statements:plan['statements']=statements
    a=await req('PUT',p+'/plan',plan,seller);assert a['next_action']['key']=='verify'
    a=await req('POST',p+'/verify',{},seller)
    if trail is not None:trail.append(a['status'])
    for _ in range(6):
     if a['status']!='needs_answer':break
     q=a['verification']['questions'][0]
     a=await req('POST',p+'/answers',{'flag':q['flag'],'choice':q['choices'][0]['key']},seller)
     if trail is not None:trail.append(a['status'])
    return a
   lan_loan=None
   for store in stores:
    name=store['scenario'];r={'statuses':[]}
    a=await start(store['url'],'company' if name=='company' else 'individual_business',trail=r['statuses']);p='/applications/'+a['id'];r['id']=a['id']
    assert a['status']==EXPECTED[name],(name,a['status'],a.get('decision'))
    if a['status']=='offered':
     o=a['offer'];assert o['limit']>0 and o['expires_at'] and a['next_action']['key']=='select'
     assert a['syndicate']['status']=='approved' and a['syndicate']['split'],a['syndicate']
     assert set(a['syndicate'])<={'status','limit','split','reduced','approved_at','expires_at','hash'},'seller sees no per-bank answers'
     r['offer']=await req('GET',p+'/offer',token=seller)
     r['quote']=await req('POST',p+'/quote',{'amount':o['suggested'] or o['limit'],'tenor_m':o['tenor_max'],'method':'installment','due_day':10},seller)
     assert r['quote']['schedule'] and r['quote']['total_due']>r['quote']['amount']
     r['quote_revenue']=await req('POST',p+'/quote',{'amount':o['limit'],'tenor_m':o['tenors'][0],'method':'revenue','due_day':28},seller)
    if name=='lan':
     # Seed loan (review 16/10/2026): first loan = 50% of the computed 200.000.
     assert a['offer']['limit']==100000 and a['offer']['suggested']==100000 and a['offer']['blocks']['B8']['computed']==200000,a['offer']
     assert [b['bank'] for b in a['syndicate']['split']]==['WEBANK','CMB','ICBC'],a['syndicate']['split']
     r['offered_app']=a
     # Above the limit is refused; Stage 3 choice → Stage 4 contract → signature with the 20 s reading clock.
     over=await raw('POST',p+'/select',{'amount':a['offer']['limit']+1,'tenor_m':12,'method':'installment','due_day':10},seller);assert over.status_code==400,(over.status_code,over.text)
     a=await req('POST',p+'/select',{'amount':100000,'tenor_m':12,'method':'installment','due_day':10},seller);r['statuses'].append(a['status'])
     assert a['status']=='selected' and a['next_action']['key']=='sign'
     r['selected_app']=a
     k=await req('GET',p+'/contract',token=seller);r['contract']=k
     assert k['read_seconds']>=20 and k['schedule'] and not k['needs']['supplier_account'] and k['banks'],k  # ≤ 100.000: all to the business account
     sign={'read_ack':True,'webank_account':'6222000012345','use_of_funds_commitment':True,'supplier_account':'88880001','guarantee':False,'method':'face'}
     early=await raw('POST',p+'/sign',sign,seller);assert early.status_code>=400,'signing before the reading time must fail'
     rewind_contract(a['id'])
     a=await req('POST',p+'/sign',sign,seller);r['statuses'].append(a['status'])
     assert a['status']=='disbursed' and a['loan_id'] and a['next_action']['key']=='view_loan',(a['status'],a.get('next_action'))
     r['disbursed_app']=a;lid='/loans/'+a['loan_id'];l=await req('GET',lid,token=seller)
     assert l['amount']==100000 and l['schedule'] and l['account'] is not None and l['principal_outstanding']==100000,l
     r['loan_initial']=l
     l=await req('POST',lid+'/simulate-inflow',{'amount':50000},seller);r['loan_inflow']=l
     assert l['account']['balance']>=50000,l['account']
     t=await req('POST',lid+'/simulate-transfer',{'amount':1000,'kind':'supplier'},seller);assert 'transfer' in t and 'flag' not in t['transfer']
     first=l['schedule'][0]['due_date'];to=(date.fromisoformat(first)+timedelta(days=2)).isoformat()
     l=await req('POST',lid+'/simulate-advance',{'to':to},seller);r['loan_advanced']=l
     assert l['clock']==to and l['schedule'][0]['status']!='upcoming' and l['repayments'],(l['clock'],l['schedule'][0],l.get('repayments'))
     assert l['principal_outstanding']<100000,l['principal_outstanding']
     r['loan']=l;r['flow']=await req('GET',p+'/flow',token=admin);r['staff_loan']=await req('GET',lid,token=admin)
     assert r['flow']['b12'] and r['flow']['b12']['rounds'] and r['flow']['b11'] and r['flow']['b11']['schedule'],list(r['flow'])
     back=await raw('POST',lid+'/simulate-advance',{'to':first},seller);assert back.status_code==400
     # Prepay is paid from the business account: refused while it is short, accepted once money arrives.
     # The seller pays the supplier from the business account (≤ 100.000 loans pay no supplier directly).
     await req('POST',lid+'/simulate-transfer',{'amount':max(1,l['account']['balance']-1000),'kind':'supplier'},seller)
     short=await raw('POST',lid+'/prepay',{},seller);assert short.status_code==400 and short.json()['error']['details']['needed']>short.json()['error']['details']['balance'],short.text
     need=short.json()['error']['details']['needed']-short.json()['error']['details']['balance']
     await req('POST',lid+'/simulate-inflow',{'amount':need+1000},seller)
     l=await req('POST',lid+'/prepay',{},seller);r['loan_prepaid']=l
     assert l['status']=='closed' and l['principal_outstanding']==0 and l['prepay'],(l['status'],l['principal_outstanding'])
     l=await req('PUT',lid+'/receiving-account',{'bank':'CMB','number':'62220000999'},seller)
     assert l['receiving_account']['bank']=='CMB'
     a=await req('GET',p,token=seller);r['statuses'].append(a['status']);assert a['status']=='closed',a['status']
     lan_loan=a['loan_id']
    if name=='noevid':assert a['offer']['limit']==70000,a['offer']  # step70 of the 100.000 seed loan
    if name=='electronics':assert {(b['bank'],round(b['pct'],2)) for b in a['syndicate']['split']}=={('WEBANK',.3),('ICBC',.7)},a['syndicate']['split']
    if name=='nobank':assert (a.get('decision') or {}).get('reason') is not None
    r['staff_application']=await req('GET',p,token=admin)
    if name in ('lan','electronics','nobank'):assert r['staff_application']['syndicate']['rounds'],name
    r['application']=a;r['trace']=await req('GET',p+'/trace',token=seller)
    control=a.get('control') or {}
    assert 'phase0' not in control and 'phase1' not in control and 'legal' not in control
    assert 'resolved' not in (control.get('phase2') or {})
    flags=(a.get('verification') or {}).get('flags',[])
    assert not any(f['code'].startswith('AML-') or f['code']=='RISK_PASS_THROUGH' for f in flags)
    records[name]=r
    print(name,r['statuses'],flush=True)
   assert lan_loan
   # Optional revenue statements (plan step 4) are accepted with the plan.
   month=lambda i:(date.today().replace(day=1)-timedelta(days=28*i)).strftime('%Y-%m')
   a=await start(stores[0]['url'],statements=[{'month':month(i),'revenue':180000,'cost':0} for i in (1,2,3)])
   records['statements']={'status':a['status'],'statements':a.get('statements')}
   assert a['status']=='offered' and [x['month'] for x in a['statements']]==[month(i) for i in (1,2,3)],(a['status'],a.get('statements'))
   bad=await raw('PUT','/applications/'+a['id']+'/plan',{**a['plan'],'statements':[{'month':'2026/01','revenue':1}]},seller);assert bad.status_code==400 and bad.json()['error']['code']=='VALIDATION_ERROR',bad.text
   records['staff']={}
   for path in ['/officer/queue','/portfolio','/alerts','/banks','/params','/chain/status','/chain/blocks','/chain/withdrawals','/admin/users']:
    records['staff'][path]=await req('GET',path,token=admin)
   records['staff']['tick']=await req('POST','/monitoring/tick',{},admin)
   records['optional_endpoints']={}
   for path in ['/regions','/withdrawals','/chain/decrypt_withdrawal.py']:
    response=await c.get('/v4'+path,headers={'Authorization':'Bearer '+admin})
    assert response.status_code in [200,404],(path,response.status_code)
    records['optional_endpoints'][path]=response.status_code
   records['staff']['postaudit']=await req('POST','/postaudit/run',{},admin)
   # Human handoff before an offer must support the distinct continue decision (then the banks are asked).
   a=await req('POST','/applications',{'tier':2,'borrower_type':'individual_business','store_urls':[stores[0]['url']]},seller)
   p='/applications/'+a['id']
   a=await req('POST',p+'/identity',{'cccd':True,'face':True},seller)
   a=await req('POST',p+'/consent',{'scopes':BOXES,'method':'face'},seller)
   a=await req('PUT',p+'/plan',a['plan']['suggested'],seller)
   a=await req('POST',p+'/request-human',{'reason':'Đề nghị cán bộ hỗ trợ trước xác minh'},seller)
   assert a['status']=='escalated' and not a.get('offer') and a['next_action']['key']=='wait_officer',a['status']
   a=await req('POST','/officer'+p+'/decision',{'decision':'continue','note':'Đã đối chiếu hồ sơ'},admin)
   assert a['status']=='offered',(a['status'],a.get('decision'))
   records['preoffer_continue']=a
   # Public encrypted envelopes reveal no bank identities; each key opens only
   # its permitted pieces. Keys themselves are deliberately not saved to evidence.
   withdrawal=records['staff']['/chain/withdrawals']['items'][0]
   assert 'shares' not in withdrawal and 'banks' not in withdrawal
   wid=withdrawal['id'];records['withdrawal']=await req('GET','/chain/withdrawals/'+wid,token=admin);keys=(await req('GET','/chain/keys',token=admin))['items']
   opened=[]
   for key in keys:
    if not key.get('private_key_hex'):continue
    result=await req('POST','/chain/withdrawals/'+wid+'/decrypt',{'private_key_hex':key['private_key_hex']},admin)
    if not key['master']: assert set(result['opened']) <= {'summary',key['code']},result
    opened.append({'code':key['code'],'opened':result['opened']})
   assert any(not x['opened'] for x in opened),'Need a nonfunding key that opens no slots'
   records['decryption']=opened
   officer=(await req('POST','/auth/login',{'email':'officer@buoyup.vn','password':'BuoyUp@2026'}))['token']
   await req('GET','/officer/queue',token=officer)
   records['bank']={}
   for code in ['webank','cmb','icbc','vcb']:
    login=await req('POST','/auth/login',{'email':code+'@buoyup.vn','password':'BuoyUp@2026'})
    token=login['token'];records['bank'][code]={}
    for endpoint in ['/bank/portfolio','/bank/withdrawals','/bank/syndicate']:
     records['bank'][code][endpoint]=await req('GET',endpoint,token=token)
    gone=await c.get('/v4/bank/approvals',headers={'Authorization':'Bearer '+token});assert gone.status_code==404
    items=records['bank'][code]['/bank/syndicate']['items']
    for x in items:assert {'application','status','rounds','result','share'}<=set(x) and all(rr.get('bank',code.upper())==code.upper() for rr in x['rounds'])
    if code in ('webank','icbc'):assert any(x['share'] for x in items),code
   assert any(x['application']==records['lan']['application']['code'] for x in records['bank']['cmb']['/bank/syndicate']['items']) if records['lan']['application'].get('code') else True
   # Signed consent accepts exact server bytes and revocation blocks further tools.
   from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
   from cryptography.hazmat.primitives import serialization
   a=await req('POST','/applications',{'tier':1,'borrower_type':'individual_business','store_urls':[stores[0]['url']]},seller)
   p='/applications/'+a['id'];await req('POST',p+'/identity',{'cccd':True,'face':True},seller)
   consent_body={'scopes':BOXES,'method':'face'}
   draft=await req('POST',p+'/consent/draft',consent_body,seller)
   signing_key=Ed25519PrivateKey.generate()
   signature={'alg':'ed25519','public_key':signing_key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex(),'sig':signing_key.sign(draft['message'].encode()).hex()}
   signed=await req('POST',p+'/consent',{**consent_body,'signature':signature},seller)
   assert signed['consent']['signature']['simulated'] is False
   revoked=await req('POST',p+'/consent/revoke',{},seller)
   assert revoked['consent']['revoked_at'] and revoked['next_action']['key']=='consent'
   records['signed_consent']={'signed':signed['consent']['id'],'revoked':True}
   # Manual UI sends decimal shares, server derives every monetary split.
   regions=await req('GET','/regions',token=admin);region=next(r for r in regions['regions'] if r['code']=='CN')
   body={'requestId':'frontend-'+uuid.uuid4().hex,'user':'Người nhận thử','account':'DEMO-8826','amount':10000,'currency':region['currency'],'region':region['code'],'province':region['provinces'][0]['code'],'split':[{'bank':'WEBANK','pct':.4},{'bank':'CMB','pct':.3},{'bank':'ICBC','pct':.3}],'reason':'Kiểm thử hợp đồng giao diện','demo':True}
   manual=await req('POST','/withdrawals/manual',body,admin)
   assert sum(x['amount'] for x in manual['shares'])==body['amount']
   assert (await req('GET','/withdrawals/'+manual['id']+'/verify',token=admin))['ok']
   same=await req('POST','/withdrawals/manual',body,admin);assert same['id']==manual['id']
   records['manual_payout']={'id':manual['id'],'verified':True,'idempotent':True}
   group=records['staff']['/portfolio']['auto_approval'][0]['group']
   switch=await req('PUT','/admin/auto-approval/'+group,{'enabled':False,'note':'Kiểm thử chuyển mạch giao diện'},admin);assert not switch['enabled']
   await req('PUT','/admin/auto-approval/'+group,{'enabled':True,'mode':'auto'},admin)
   records['auto_switch']=True
   Path('/tmp/v4-qa-api-evidence.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
   print('Feature endpoints:',records['optional_endpoints'])
   print(f'PASS {len(EXPECTED)} demo scenarios; Lan select→contract→sign→loan→inflow→advance→prepay; staff, bank syndicate and Agent5. /tmp/v4-qa-api-evidence.json')
asyncio.run(main())
