# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
import base64, hashlib, hmac, secrets, time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException, Request, WebSocket
from .db import Database

def now_iso(): return datetime.now(timezone.utc).isoformat()
def b64e(b:bytes): return base64.b64encode(b).decode()
def b64d(s:str): return base64.b64decode(s.encode(), validate=True)
def sha256_hex(b:bytes): return hashlib.sha256(b).hexdigest()

def create_pairing_code(db:Database, minutes:int=10)->str:
    code=f"{secrets.randbelow(100_000_000):08d}"; salt=secrets.token_bytes(24)
    digest=hashlib.scrypt(code.encode(),salt=salt,n=2**14,r=8,p=1,dklen=32)
    expires=(datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat()
    db.execute("INSERT INTO pairing_codes(id,salt_b64,digest_b64,expires_at) VALUES(?,?,?,?)",(uuid4().hex,b64e(salt),b64e(digest),expires))
    return code

def consume_pairing_code(db:Database, code:str)->bool:
    now=datetime.now(timezone.utc)
    for row in db.rows("SELECT * FROM pairing_codes WHERE used_at IS NULL"):
        if datetime.fromisoformat(row["expires_at"]) < now: continue
        digest=hashlib.scrypt(code.encode(),salt=b64d(row["salt_b64"]),n=2**14,r=8,p=1,dklen=32)
        if hmac.compare_digest(digest,b64d(row["digest_b64"])):
            # Claim it in the same statement that checks it is unused, so two
            # simultaneous requests with one code cannot both succeed.
            with db.connect() as c:
                return c.execute("UPDATE pairing_codes SET used_at=? WHERE id=? AND used_at IS NULL",(now.isoformat(),row["id"])).rowcount==1
    return False

def canonical(method:str,path_qs:str,timestamp:str,nonce:str,body:bytes)->bytes:
    return f"{method.upper()}\n{path_qs}\n{timestamp}\n{nonce}\n{sha256_hex(body)}".encode()

def verify_device_request(db:Database, request:Request|WebSocket, body:bytes):
    device_id=request.headers.get("x-orion-device-id",""); timestamp=request.headers.get("x-orion-timestamp","")
    nonce=request.headers.get("x-orion-nonce",""); signature=request.headers.get("x-orion-signature","")
    if not all((device_id,timestamp,nonce,signature)): raise HTTPException(401,"Missing device signature headers")
    try: ts=int(timestamp)
    except ValueError: raise HTTPException(401,"Invalid timestamp")
    if abs(int(time.time())-ts)>60: raise HTTPException(401,"Expired request")
    device=db.row("SELECT * FROM devices WHERE id=?",(device_id,))
    if not device: raise HTTPException(401,"Unknown device")
    try:
        key=serialization.load_der_public_key(b64d(device["public_key_der_b64"]))
        if not isinstance(key,ec.EllipticCurvePublicKey): raise ValueError()
        path_qs=request.url.path + (("?"+request.url.query) if request.url.query else "")
        method="GET" if isinstance(request,WebSocket) else request.method
        key.verify(b64d(signature),canonical(method,path_qs,timestamp,nonce,body),ec.ECDSA(hashes.SHA256()))
    except Exception: raise HTTPException(401,"Invalid signature")
    try: db.execute("INSERT INTO nonces(device_id,nonce,seen_at) VALUES(?,?,?)",(device_id,nonce,now_iso()))
    except Exception: raise HTTPException(409,"Replay rejected")
    db.execute("UPDATE devices SET last_seen_at=? WHERE id=?",(now_iso(),device_id))
    return {"kind":"device","id":device_id,"name":device["name"]}

def hash_token(value:str)->str: return hashlib.sha256(value.encode()).hexdigest()
