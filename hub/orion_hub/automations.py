# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
import json, os, subprocess
from pathlib import Path
from uuid import uuid4
from .db import Database
from .security import now_iso

def load_automations(path:Path)->dict:
    if not path.exists(): return {}
    data=json.loads(path.read_text(encoding="utf-8")); return {str(x["id"]):x for x in data.get("automations",[])}

def run_automation(db:Database, config_path:Path, automation_id:str)->dict:
    item=load_automations(config_path).get(automation_id)
    if not item or not item.get("enabled",False): raise ValueError("Automation is not enabled or does not exist")
    command=item.get("command")
    if not isinstance(command,list) or not command or not all(isinstance(v,str) and v for v in command): raise ValueError("Automation command must be a fixed argv list")
    run_id=uuid4().hex; started=now_iso(); db.execute("INSERT INTO automation_runs(id,automation_id,status,started_at) VALUES(?,?,?,?)",(run_id,automation_id,"running",started))
    allowed_env={k:os.environ[k] for k in item.get("pass_env",[]) if k in os.environ}; env={"PATH":os.environ.get("PATH","") ,**allowed_env}
    # Python/Windows needs this to load the OS random-number provider. It is
    # infrastructure, not an application credential; keep the rest allowlisted.
    if os.name=="nt" and "SYSTEMROOT" in os.environ: env["SYSTEMROOT"]=os.environ["SYSTEMROOT"]
    try:
        result=subprocess.run(command,cwd=item.get("cwd") or None,env=env,capture_output=True,text=True,timeout=min(int(item.get("timeout_seconds",300)),900),encoding="utf-8",errors="replace")
        status="succeeded" if result.returncode==0 else "failed"; out=result.stdout[-16000:]; err=result.stderr[-8000:]
    except subprocess.TimeoutExpired as e:
        status="timed_out"; out=(e.stdout or "")[-16000:] if isinstance(e.stdout,str) else ""; err="Timed out"
    finished=now_iso(); db.execute("UPDATE automation_runs SET status=?,stdout=?,stderr=?,finished_at=? WHERE id=?",(status,out,err,finished,run_id))
    db.event("automation",f"Automation {item.get('name',automation_id)} {status}",err or out[-500:] or status,{"run_id":run_id,"automation_id":automation_id},finished)
    return {"id":run_id,"automation_id":automation_id,"status":status,"stdout":out,"stderr":err,"started_at":started,"finished_at":finished}
