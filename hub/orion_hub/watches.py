# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
import hashlib, requests
from datetime import datetime, timezone
from urllib.parse import urljoin
from .db import Database
from .net import validate_watch_url
from .push import push_all
from .security import now_iso

MAX_BYTES=2_000_000

def fetch(url:str)->tuple[int,bytes,str]:
    current=url
    for _ in range(4):
        validate_watch_url(current)
        with requests.get(current,timeout=20,allow_redirects=False,stream=True,headers={"User-Agent":"OrionHub/0.1 personal monitor"}) as r:
            if r.status_code in {301,302,303,307,308} and r.headers.get("location"):
                current=urljoin(current,r.headers["location"]); continue
            # Stop reading at the limit rather than holding the whole body first.
            content=b""
            for chunk in r.iter_content(65536):
                content+=chunk
                if len(content)>MAX_BYTES: raise ValueError("Response is larger than 2 MB")
            return r.status_code,content,current
    raise ValueError("Too many redirects")

def check_watch(db:Database,row:dict)->dict:
    checked=now_iso()
    try:
        status,content,final_url=fetch(row["url"]); digest=hashlib.sha256(content).hexdigest(); changed=bool(row.get("last_hash")) and digest!=row.get("last_hash")
        text=f"HTTP {status}" + (" — content changed" if changed else "")
        db.execute("UPDATE watches SET last_checked_at=?,last_hash=?,last_status=?,updated_at=? WHERE id=?",(checked,digest,text,checked,row["id"]))
        if changed:
            db.event("watch_changed",row["name"],f"{row['name']} changed ({status}).",{"watch_id":row["id"],"url":final_url},checked)
            push_all(db,"Saiph update",f"{row['name']} changed",{"kind":"watch_changed","watch_id":row["id"]})
        return {"changed":changed,"status":status,"hash":digest}
    except Exception as e:
        db.execute("UPDATE watches SET last_checked_at=?,last_status=?,updated_at=? WHERE id=?",(checked,f"error: {str(e)[:180]}",checked,row["id"]))
        db.event("watch_error",row["name"],str(e)[:500],{"watch_id":row["id"]},checked); return {"changed":False,"error":str(e)}

def due(row:dict)->bool:
    if not row.get("enabled"): return False
    if not row.get("last_checked_at"): return True
    last=datetime.fromisoformat(row["last_checked_at"]); return (datetime.now(timezone.utc)-last).total_seconds() >= int(row["interval_hours"])*3600
