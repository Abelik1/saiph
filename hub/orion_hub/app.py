# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
import asyncio, json, logging, os, secrets, time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from . import inbox, releases, phone, peer, features, continuity, agent_api, phone_backup, desktop_releases, cloud_provisioning
from .automations import load_automations, run_automation
from .db import Database
from .link import Bus, require_mesh
from .net import validate_watch_url
from .push import push_all, push_data
from .security import consume_pairing_code, hash_token, now_iso, verify_device_request
from .watches import check_watch, due

DATA=Path(os.environ.get("ORION_HUB_DATA","./data")); DB=Database(DATA/"orion-hub.sqlite3")
agent_api.initialize(DB)
LINK=Bus(DB)
AUTOMATIONS=Path(os.environ.get("ORION_HUB_AUTOMATIONS","./config/automations.json"))
PAIR_ATTEMPTS:list[float]=[]
log=logging.getLogger("orion_hub")

def pair_rate_limit():
    now=time.time(); PAIR_ATTEMPTS[:]=[t for t in PAIR_ATTEMPTS if now-t<60]
    if len(PAIR_ATTEMPTS)>=10: raise HTTPException(429,"Too many pairing attempts; try again shortly")
    PAIR_ATTEMPTS.append(now)

class PairClaim(BaseModel):
    code:str=Field(min_length=6,max_length=32); name:str=Field(min_length=1,max_length=80); public_key_der_b64:str
class TaskIn(BaseModel): title:str=Field(min_length=1,max_length=240); notes:str=""; due_at:str|None=None
class WatchIn(BaseModel): name:str=Field(min_length=1,max_length=120); url:str; interval_hours:int=Field(default=8,ge=1,le=168)
class PushIn(BaseModel): token:str=Field(min_length=20,max_length=4096)

async def principal(request:Request, body:bytes|None=None):
    if request.cookies.get("orion_session"):
        row=DB.row("SELECT * FROM web_sessions WHERE id_hash=?",(hash_token(request.cookies["orion_session"]),))
        if row and not row.get("scopes_json") and not row.get("owner_device_id") and datetime.fromisoformat(row["expires_at"])>datetime.now(timezone.utc):
            if request.method not in {"GET","HEAD"} and hash_token(request.headers.get("x-orion-csrf",""))!=row["csrf_hash"]: raise HTTPException(403,"CSRF check failed")
            return {"kind":"web","id":"web","name":row["name"]}
    return verify_device_request(DB,request,body if body is not None else await request.body())

def task_rows():
    rows=DB.rows("SELECT * FROM tasks ORDER BY done ASC, COALESCE(due_at,'9999') ASC, updated_at DESC LIMIT 200")
    for r in rows: r["done"]=bool(r["done"])
    return rows

def watch_rows():
    rows=DB.rows("SELECT * FROM watches ORDER BY name");
    for r in rows: r["enabled"]=bool(r["enabled"])
    return rows

@asynccontextmanager
async def lifespan(app: FastAPI):
    phone_backup.reconcile(DB)
    task=asyncio.create_task(scheduler())
    link_task=asyncio.create_task(link_cleanup())
    try:
        yield
    finally:
        task.cancel()
        link_task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.gather(link_task,return_exceptions=True)

app=FastAPI(title="Saiph Hub",version="0.1.0",docs_url=None,redoc_url=None,lifespan=lifespan)

async def link_cleanup():
    while True:
        await asyncio.to_thread(LINK.store.cleanup)
        await asyncio.to_thread(continuity.dispatch, DB)
        await asyncio.sleep(1)

@app.websocket("/v1/link")
async def link_socket(socket:WebSocket):
    await LINK.connect(socket)

@app.get("/v1/link/devices")
async def link_devices(request:Request):
    require_mesh(request)
    verify_device_request(DB,request,b"")
    return {"devices":LINK.presence()}

@app.get("/v1/link/events")
async def link_events(request:Request,limit:int=50):
    require_mesh(request)
    verify_device_request(DB,request,b"")
    rows=DB.rows("SELECT * FROM link_events WHERE expires_at>? AND payload_json IS NOT NULL ORDER BY created_at DESC LIMIT ?",(time.time(),max(1,min(limit,100))))
    return {"events":[LINK.store.envelope(row) for row in rows]}

@app.get("/v1/link/phone")
async def phone_state(request:Request):
    require_mesh(request)
    verify_device_request(DB,request,b"")
    return {**phone.snapshot(DB, LINK.presence()), **features.snapshot(DB)}

@app.get("/v1/link/continuity")
async def continuity_state(request:Request):
    require_mesh(request)
    verify_device_request(DB,request,b"")
    return continuity.snapshot(DB)

async def desktop_release_principal(request: Request):
    require_mesh(request)
    if request.headers.get('origin') or request.cookies.get('orion_session'):
        raise HTTPException(403, 'Use a paired desktop for packaged updates')
    return await asyncio.to_thread(verify_device_request, DB, request, b'')

@app.get('/v1/link/desktop/releases/{platform}/{profile}')
async def desktop_release_metadata(request: Request, platform: str, profile: str):
    await desktop_release_principal(request)
    try:
        release = await asyncio.to_thread(desktop_releases.latest, DATA, platform, profile)
    except (OSError, ValueError):
        raise HTTPException(404, 'Desktop release unavailable') from None
    return Response(content=json.dumps({'release': release}), media_type='application/json', headers={'Cache-Control': 'no-store'})


async def cloud_principal(request: Request, body=b''):
    require_mesh(request)
    if request.headers.get('origin') or request.cookies.get('orion_session'):
        raise HTTPException(403, 'Use a paired device for Cloud setup')
    return await asyncio.to_thread(verify_device_request, DB, request, body)


@app.get('/v1/link/cloud')
async def cloud_status(request: Request):
    device = await cloud_principal(request)
    try:
        value = await asyncio.to_thread(cloud_provisioning.status, DB, device['id'])
    except (OSError, ValueError):
        raise HTTPException(503, cloud_provisioning.ERROR) from None
    return Response(content=json.dumps(value), media_type='application/json', headers={'Cache-Control': 'no-store'})


@app.post('/v1/link/cloud/profile')
async def cloud_profile(request: Request):
    raw = await agent_api.bounded_raw(request)
    device = await cloud_principal(request, raw)
    try:
        body = agent_api.decode_body(raw)
        value = await asyncio.to_thread(cloud_provisioning.provision, DB, device['id'], body)
    except (OSError, ValueError):
        raise HTTPException(503, cloud_provisioning.ERROR) from None
    return Response(content=json.dumps(value), media_type='application/json', headers={'Cache-Control': 'no-store'})

@app.get('/v1/link/desktop/artifacts/{platform}/{profile}/{digest}')
async def desktop_release_download(request: Request, platform: str, profile: str, digest: str):
    await desktop_release_principal(request)
    try:
        source, size = await asyncio.to_thread(desktop_releases.open_artifact, DATA, platform, profile, digest)
    except (OSError, ValueError):
        raise HTTPException(404, 'Desktop artifact unavailable') from None
    def chunks():
        try:
            while chunk := source.read(1024 * 1024):
                yield chunk
        finally:
            source.close()
    return StreamingResponse(chunks(), media_type='application/octet-stream',
                             headers={'Content-Length': str(size), 'X-Orion-SHA256': digest, 'Cache-Control': 'no-store'})

@app.post("/v1/link/enrollment")
async def device_enrollment(request:Request):
    require_mesh(request)
    if request.headers.get('origin') or request.cookies.get('orion_session'):
        raise HTTPException(403, 'Use a paired device for enrollment')
    raw = await agent_api.bounded_raw(request)
    verify_device_request(DB, request, raw)
    if agent_api.decode_body(raw) != {}:
        raise HTTPException(400, 'Enrollment accepts no supplied address or credentials')
    # Bound retained codes and CPU; invalid/expired codes cannot accumulate forever.
    DB.execute('DELETE FROM pairing_codes WHERE expires_at<? OR used_at IS NOT NULL', (now_iso(),))
    if len(DB.rows('SELECT id FROM pairing_codes WHERE used_at IS NULL')) >= 10:
        raise HTTPException(429, 'Too many active invitations; wait for one to expire')
    from .enrollment import create_enrollment
    artifact = await asyncio.to_thread(create_enrollment, DB)
    return Response(content=json.dumps(artifact), media_type='application/json', headers={'Cache-Control': 'no-store'})

@app.post("/v1/link/backups/bootstrap")
async def phone_backup_bootstrap(request:Request):
    require_mesh(request)
    if request.headers.get("origin") or request.cookies.get("orion_session"):
        raise HTTPException(403,"Use the paired device for backup setup")
    raw=await agent_api.bounded_raw(request)
    owner=verify_device_request(DB,request,raw)
    if agent_api.decode_body(raw) != {}:
        raise HTTPException(400,"Backup setup accepts no supplied account or path")
    try:
        result=await asyncio.to_thread(phone_backup.bootstrap,DB,owner["id"])
    except (OSError,ValueError,ImportError):
        raise HTTPException(503,"Private phone backup setup or storage is unavailable") from None
    return Response(content=json.dumps(result),media_type="application/json",headers={"Cache-Control":"no-store"})

@app.post("/v1/link/peer/verify")
async def peer_verify(request:Request, proof:peer.Proof):
    require_mesh(request)
    receiver = verify_device_request(DB, request, await request.body())
    return peer.verify(DB, receiver["id"], proof)

async def scheduler():
    while True:
        # One bad row, automation file or push credential must not stop every
        # later check until the service is restarted.
        try: await scheduler_cycle()
        except Exception: log.exception("Scheduler cycle failed")
        await asyncio.sleep(60)

async def scheduler_cycle():
    try:
        await asyncio.to_thread(cloud_provisioning.reconcile, DB)
    except cloud_provisioning.CloudError:
        log.warning('Cloud access reconciliation needs administrator attention')
    for row in watch_rows():
        if due(row): await asyncio.to_thread(check_watch,DB,row)
    now=now_iso()
    for task in DB.rows("SELECT * FROM tasks WHERE done=0 AND due_at IS NOT NULL AND due_at<=? AND notified_at IS NULL",(now,)):
        DB.execute("UPDATE tasks SET notified_at=?,updated_at=? WHERE id=?",(now,now,task["id"]))
        DB.event("task_due",task["title"],task.get("notes") or "Task is due",{"task_id":task["id"]},now)
        push_all(DB,"Saiph task due",task["title"],{"kind":"task_due","task_id":task["id"]})
    for aid,item in load_automations(AUTOMATIONS).items():
        interval=item.get("interval_hours")
        if not item.get("enabled") or not interval: continue
        last=DB.row("SELECT started_at FROM automation_runs WHERE automation_id=? ORDER BY started_at DESC LIMIT 1",(aid,))
        if not last or (datetime.now(timezone.utc)-datetime.fromisoformat(last["started_at"])).total_seconds()>=float(interval)*3600:
            await asyncio.to_thread(run_automation,DB,AUTOMATIONS,aid)
    DB.execute("DELETE FROM nonces WHERE seen_at<?",((datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(),))

@app.get("/v1/health")
def health(): return {"ok":True,"service":"orion-hub","version":"0.1.0","time":now_iso()}
@app.post("/v1/pairing/claim")
def pair(body:PairClaim):
    pair_rate_limit()
    if not consume_pairing_code(DB,body.code): raise HTTPException(401,"Invalid or expired pairing code")
    try:
        import base64; raw=base64.b64decode(body.public_key_der_b64,validate=True)
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        key=serialization.load_der_public_key(raw)
        if not isinstance(key,ec.EllipticCurvePublicKey) or key.curve.name!="secp256r1": raise ValueError()
    except Exception: raise HTTPException(400,"Expected a P-256 SubjectPublicKeyInfo key")
    device_id="dev_"+uuid4().hex; DB.execute("INSERT INTO devices(id,name,public_key_der_b64,created_at) VALUES(?,?,?,?)",(device_id,body.name.strip(),body.public_key_der_b64,now_iso()))
    return {"device_id":device_id}
@app.post("/web/session")
def web_login(payload:dict,response:Response):
    pair_rate_limit()
    code=str(payload.get("code","")).strip()
    if not consume_pairing_code(DB,code): raise HTTPException(401,"Invalid or expired pairing code")
    token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24); now=datetime.now(timezone.utc); expires=now+timedelta(hours=12)
    DB.execute("INSERT INTO web_sessions(id_hash,name,csrf_hash,expires_at,created_at) VALUES(?,?,?,?,?)",(hash_token(token),str(payload.get("name") or "browser")[:80],hash_token(csrf),expires.isoformat(),now.isoformat()))
    response.set_cookie("orion_session",token,httponly=True,secure=True,samesite="strict",max_age=43200,path="/")
    return {"ok":True,"csrf":csrf,"expires_at":expires.isoformat()}
@app.post("/web/logout")
def web_logout(request:Request,response:Response):
    token=request.cookies.get("orion_session");
    if token: DB.execute("DELETE FROM web_sessions WHERE id_hash=?",(hash_token(token),))
    response.delete_cookie("orion_session",path="/"); return {"ok":True}

@app.get("/v1/dashboard")
async def dashboard(request:Request):
    await principal(request); return {"tasks":task_rows(),"watches":watch_rows(),"events":DB.rows("SELECT * FROM events ORDER BY id DESC LIMIT 80"),"automations":[{"id":k,"name":v.get("name",k),"description":v.get("description","")} for k,v in load_automations(AUTOMATIONS).items() if v.get("enabled")]}
@app.post("/v1/tasks")
async def create_task(request:Request, body:TaskIn):
    raw=await request.body(); await principal(request,raw); now=now_iso(); tid="task_"+uuid4().hex
    DB.execute("INSERT INTO tasks(id,title,notes,due_at,created_at,updated_at) VALUES(?,?,?,?,?,?)",(tid,body.title.strip(),body.notes,utc_due(body.due_at),now,now)); return DB.row("SELECT * FROM tasks WHERE id=?",(tid,))
def utc_due(value:str|None)->str|None:
    # The scheduler compares due_at to now as text, which only works when every
    # value is UTC in the same ISO form. A time without an offset is taken as UTC.
    if not value: return None
    try: when=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError: raise HTTPException(400,"due_at must be an ISO 8601 date and time")
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
@app.post("/v1/tasks/{task_id}/toggle")
async def toggle_task(task_id:str,request:Request):
    raw=await request.body(); await principal(request,raw); row=DB.row("SELECT * FROM tasks WHERE id=?",(task_id,));
    if not row: raise HTTPException(404,"Task not found")
    DB.execute("UPDATE tasks SET done=?,updated_at=? WHERE id=?",(0 if row["done"] else 1,now_iso(),task_id)); return {"ok":True}
@app.post("/v1/watches")
async def create_watch(request:Request,body:WatchIn):
    raw=await request.body(); await principal(request,raw)
    try: url=validate_watch_url(body.url)
    except ValueError as e: raise HTTPException(400,str(e))
    now=now_iso(); wid="watch_"+uuid4().hex; DB.execute("INSERT INTO watches(id,name,url,interval_hours,created_at,updated_at) VALUES(?,?,?,?,?,?)",(wid,body.name.strip(),url,body.interval_hours,now,now)); return DB.row("SELECT * FROM watches WHERE id=?",(wid,))
@app.post("/v1/watches/{watch_id}/check")
async def run_watch(watch_id:str,request:Request):
    raw=await request.body(); await principal(request,raw); row=DB.row("SELECT * FROM watches WHERE id=?",(watch_id,));
    if not row: raise HTTPException(404,"Watch not found")
    return await asyncio.to_thread(check_watch,DB,row)
@app.post("/v1/devices/push-token")
async def push_token(request:Request,body:PushIn):
    raw=await request.body(); p=await principal(request,raw)
    if p["kind"]!="device": raise HTTPException(400,"Push tokens belong to paired devices")
    DB.execute("UPDATE devices SET push_token=? WHERE id=?",(body.token,p["id"])); return {"ok":True}
@app.post("/v1/automations/{automation_id}/run")
async def automation(automation_id:str,request:Request):
    raw=await request.body(); await principal(request,raw)
    try: result=await asyncio.to_thread(run_automation,DB,AUTOMATIONS,automation_id)
    except ValueError as e: raise HTTPException(404,str(e))
    push_all(DB,"Saiph automation",f"{automation_id}: {result['status']}",{"kind":"automation","run_id":result["id"]})
    return result
def inbox_push(row:dict):
    """Tell phones to show or withdraw this item's notification."""
    if agent_api.is_action(row):
        push_data(DB,{"type":"inbox","id":row["id"],"kind":row["kind"],"status":row["status"],"source":"agent",
                      "proposal_type":"phone_action","title":"Phone action needs your approval","body":"Open Saiph to review it"})
        return
    push_data(DB,{"type":"inbox","id":row["id"],"kind":row["kind"],"status":row["status"],"source":row["source"],
                  "title":("Needs your OK: " if row["kind"]=="proposal" else "")+row["title"],"body":row["body"][:300]})
app.include_router(agent_api.router(DB, LINK, inbox_push))
@app.get("/v1/inbox")
async def inbox_list(request:Request,status:str|None=None):
    await principal(request); return {"items":inbox.listing(DB,status)}
@app.post("/v1/inbox")
async def inbox_post(request:Request):
    raw=await request.body(); await principal(request,raw)
    try: row,created=inbox.post(DB,json.loads(raw or b"{}"))
    except (ValueError,TypeError,AttributeError) as e: raise HTTPException(400,str(e))
    if created: inbox_push(row)
    return {"item":row,"created":created}
@app.post("/v1/inbox/{item_id}/decide")
async def inbox_decide(item_id:str,request:Request):
    raw=await request.body(); p=await principal(request,raw)
    try:
        decision=str(json.loads(raw or b"{}").get("decision",""))
        if agent_api.is_action(inbox.get(DB,item_id)):
            row,changed=agent_api.decide_action(DB,LINK,item_id,decision,p)
        else:
            row,changed=inbox.decide(DB,item_id,decision,p["name"])
    except LookupError as e: raise HTTPException(404,str(e))
    except (ValueError,AttributeError) as e: raise HTTPException(400,str(e))
    if changed: inbox_push(row)
    return {"item":row,"changed":changed}
@app.post("/v1/inbox/{item_id}/result")
async def inbox_result(item_id:str,request:Request):
    raw=await request.body(); await principal(request,raw); body=json.loads(raw or b"{}")
    if agent_api.is_action(inbox.get(DB,item_id)): raise HTTPException(400,"Phone action outcomes cannot be rewritten")
    try: row=inbox.result(DB,item_id,bool(body.get("ok")),str(body.get("result") or ""))
    except LookupError as e: raise HTTPException(404,str(e))
    except (ValueError,AttributeError) as e: raise HTTPException(400,str(e))
    if row["status"]=="applied": inbox_push(row)
    return {"item":row}
@app.get("/v1/app/android")
async def android_release(request:Request):
    await principal(request); return {"release":releases.latest(DATA)}
@app.get("/v1/app/android/apk")
async def android_apk(request:Request):
    await principal(request); release=releases.latest(DATA)
    if not release: raise HTTPException(404,"No Android build has been published")
    return FileResponse(releases.release_dir(DATA)/"orion.apk",media_type="application/vnd.android.package-archive",filename=f"Saiph-{release['version_name']}-{release['version_code']}.apk",headers={"X-Orion-Sha256":release["sha256"],"Cache-Control":"no-store"})

@app.get("/",response_class=HTMLResponse)
def web_ui():
    return HTMLResponse(WEB)
WEB='''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Saiph Hub</title><style>body{font:16px system-ui;max-width:900px;margin:40px auto;padding:0 18px;background:#0b1020;color:#eef2ff}button,input{font:inherit;padding:10px;border-radius:9px;border:1px solid #3b4668}button{cursor:pointer}section{background:#121a30;padding:18px;border-radius:16px;margin:14px 0}.muted{color:#9aa8c7}.done{text-decoration:line-through;opacity:.6}</style><h1>Saiph Hub</h1><p class=muted>Your private Raspberry Pi coordinator.</p><section id=pairing><h2>Pair browser</h2><input id=code placeholder="one-time code"><button onclick=login()>Pair</button><p id=err></p></section><main id=app hidden><button onclick=load()>Refresh</button><section id=android hidden><h2>Android app</h2><p><a id=apk href=/v1/app/android/apk>Download</a> <span id=apkver class=muted></span></p></section><section><h2>Tasks</h2><input id=title placeholder="New task"><button onclick=addTask()>Add</button><div id=tasks></div></section><section><h2>Website watches</h2><div id=watches></div></section><section><h2>Recent events</h2><div id=events></div></section></main><script>let csrf='';async function login(){let r=await fetch('/web/session',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({code:code.value,name:'Saiph web'})});if(!r.ok){err.textContent=await r.text();return}csrf=(await r.json()).csrf;pairing.hidden=true;app.hidden=false;load()}async function api(path,o={}){o.headers={...(o.headers||{}),'x-orion-csrf':csrf,'content-type':'application/json'};let r=await fetch(path,o);if(r.status===401||r.status===403){pairing.hidden=false;app.hidden=true;throw Error('Pair this browser again')}return r}async function load(){let d=await(await api('/v1/dashboard')).json();tasks.innerHTML=d.tasks.map(x=>`<p class="${x.done?'done':''}"><button onclick="toggle('${x.id}')">✓</button> ${esc(x.title)}</p>`).join('');watches.innerHTML=d.watches.map(x=>`<p><b>${esc(x.name)}</b><br><span class=muted>${esc(x.last_status||'not checked yet')}</span></p>`).join('');events.innerHTML=d.events.map(x=>`<p><b>${esc(x.title)}</b> — ${esc(x.body)}</p>`).join('');let a=(await(await api('/v1/app/android')).json()).release;android.hidden=!a;if(a)apkver.textContent=`${a.version_name} (build ${a.version_code})`}async function addTask(){if(!title.value.trim())return;await api('/v1/tasks',{method:'POST',body:JSON.stringify({title:title.value})});title.value='';load()}async function toggle(id){await api('/v1/tasks/'+id+'/toggle',{method:'POST',body:'{}'});load()}function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}</script>'''
