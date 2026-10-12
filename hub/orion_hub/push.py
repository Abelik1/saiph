# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
import json, logging, os, requests

SCOPE="https://www.googleapis.com/auth/firebase.messaging"
log=logging.getLogger("orion_hub.push")

def push_all(db,title:str,body:str,data:dict|None=None)->int:
    """Notify every device with a push token. A delivery failure is logged, never
    raised: the event it reports has already happened and been recorded."""
    sent=0
    for device in db.rows("SELECT push_token FROM devices WHERE push_token IS NOT NULL"):
        try: sent+=send_fcm(device["push_token"],title,body,data)
        except Exception: log.exception("FCM delivery failed")
    return sent

def push_data(db,data:dict)->int:
    """A data-only message: the phone draws (or withdraws) the notification itself,
    so an item decided on another device can disappear from this one."""
    sent=0
    for device in db.rows("SELECT push_token FROM devices WHERE push_token IS NOT NULL"):
        try: sent+=send_fcm(device["push_token"],"","",data,notify=False)
        except Exception: log.exception("FCM delivery failed")
    return sent

def send_fcm(token:str,title:str,body:str,data:dict|None=None,notify:bool=True)->bool:
    credentials_path=os.environ.get("ORION_FIREBASE_CREDENTIALS","")
    project_id=os.environ.get("ORION_FIREBASE_PROJECT_ID","")
    if not credentials_path or not project_id or not token: return False
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    creds=service_account.Credentials.from_service_account_file(credentials_path,scopes=[SCOPE]); creds.refresh(Request())
    payload={"message":{"token":token,"data":{str(k):str(v) for k,v in (data or {}).items()},"android":{"priority":"high"}}}
    if notify: payload["message"]["notification"]={"title":title,"body":body}
    r=requests.post(f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",headers={"Authorization":f"Bearer {creds.token}","Content-Type":"application/json"},json=payload,timeout=15)
    return 200 <= r.status_code < 300
