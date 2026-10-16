"""C1 API integration check using isolated SQLite state in /tmp.

Run: python -B frontend/tests/c1-api-check.py
Then: C1_API_EVIDENCE=/tmp/c1-api-evidence.json node frontend/tests/c1-check.mjs

Calls real FastAPI endpoints in-process. The sandbox blocks worker-thread
wakeup sockets, so synchronous request callables run inline. This verifies
HTTP shapes and behavior, not backend concurrency or browser rendering.
No backend files, shared database, or bytecode are written.
"""
import os, sys, uuid, json, asyncio
from pathlib import Path
uid = uuid.uuid4().hex
os.environ.update(DATABASE_URL=f'sqlite:////tmp/c1-verify-{uid}.db', APP_ENV='dev', CREDIT_LEDGER_KEY='devkey', LLM_ENABLED='false', BUOYUP_AUTOPILOT='false', PYTHONDONTWRITEBYTECODE='1', BUOYUP_CHAIN_BACKEND='local',BUOYUP_CHAIN_URL='')
sys.dont_write_bytecode=True
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root / 'BackEnd' / 'src'))
import httpx
import anyio.to_thread
# Local sandbox disallows the worker-thread wakeup socket: run callables inline for in-process HTTP verification.
async def inline_run_sync(func, *args, **kwargs):
 return func(*args)
anyio.to_thread.run_sync = inline_run_sync
from app.main import app
from app.platform.config import settings
assert settings.database_url == os.environ['DATABASE_URL']
accounts=[('lan','seller',None),('officer','officer',None),('admin','admin',None),('webank','bank','WEBANK'),('cmb','bank','CMB'),('icbc','bank','ICBC'),('vcb','bank','VCB')]
evidence={'database_url':settings.database_url,'demos':[], 'errors':{}}
def record(r): return {'status':r.status_code,'body':r.json() if r.content else None}
async def main():
 async with app.router.lifespan_context(app):
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
   for name,role,bank in accounts:
    r=await c.post('/v4/auth/login',json={'email':name+'@buoyup.vn','password':'BuoyUp@2026'})
    assert r.status_code == 200, record(r)
    login=r.json(); assert login['user']['role']==role and login['user']['bank_code']==bank
    headers={'Authorization':'Bearer '+login['token']}
    me=await c.get('/v4/auth/me',headers=headers); assert me.status_code==200 and me.json()['user']==login['user']
    if role=='bank':
     # Loan circle: the bank portal reads its syndicate rounds; the old sign-off queue is gone.
     syn=await c.get('/v4/bank/syndicate',headers=headers); assert syn.status_code==200 and syn.json()['bank']==bank and isinstance(syn.json()['items'],list), record(syn)
     old=await c.get('/v4/bank/approvals',headers=headers); assert old.status_code==404, record(old)
     evidence.setdefault('bank_syndicate',{})[bank]=syn.status_code
    elif role=='seller':
     denied=await c.get('/v4/bank/syndicate',headers=headers); assert denied.status_code==403, record(denied)
    logout=await c.post('/v4/auth/logout',headers=headers); assert logout.status_code==204
    revoked=await c.get('/v4/auth/me',headers=headers); assert revoked.status_code==401
    evidence['demos'].append({'email':name+'@buoyup.vn','login':record(r),'me':record(me),'logout':record(logout),'revoked':record(revoked)})
   body={'email':'c1-'+uid+'@example.com','password':'BuoyUp@2026','display_name':'Kiểm thử C1','accept_terms':True}
   r=await c.post('/v4/auth/register',json=body); assert r.status_code==201 and r.json()['user']['role']=='seller'
   evidence['registration']=record(r)
   me=await c.get('/v4/auth/me',headers={'Authorization':'Bearer '+r.json()['token']}); assert me.status_code==200
   evidence['registration_me']=record(me)
   r=await c.post('/v4/auth/register',json=body); assert r.status_code==409 and r.json()['error']['details']['field']=='email'
   evidence['errors']['conflict']=record(r)
   for field,value in [('email','invalid'),('password','bad'),('accept_terms',False)]:
    r=await c.post('/v4/auth/register',json={**body,field:value})
    assert r.status_code==400 and r.json()['error']['details']['field']==field
    evidence['errors'][field]=record(r)
   evidence['invalid_login_attempts']=[]
   for attempt in range(6):
    r=await c.post('/v4/auth/login',json={'email':'missing-'+uid+'@example.com','password':'wrong'})
    assert r.status_code==(401 if attempt<5 else 429), record(r)
    evidence['invalid_login_attempts'].append(record(r))
   evidence['public']={}
   for name in ['overview','demo-stores']:
    evidence['public'][name]=record(await c.get('/v4/public/'+name))
   evidence['pages']={}
   for name in ['index.html','login.html','register.html','bank.html','workspace.html','admin.html']:
    r=await c.get('/app/giaodien/'+name); evidence['pages'][name]={'status':r.status_code,'bytes':len(r.content)}
    assert r.status_code==200
 Path('/tmp/c1-api-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
 print(json.dumps({'result':'PASS','demos':len(evidence['demos']),'registration':evidence['registration']['status'],'field_errors':list(evidence['errors']),'invalid_login_statuses':[x['status'] for x in evidence['invalid_login_attempts']],'public':{k:v['status'] for k,v in evidence['public'].items()},'pages':evidence['pages'],'bank_syndicate':evidence['bank_syndicate'],'artifact':'/tmp/c1-api-evidence.json'},ensure_ascii=False))
asyncio.run(main())
