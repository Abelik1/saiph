# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed Orion Hub client for the Windows desktop app.

The desktop gets its own P-256 identity; it never shares the Android key.
"""
from __future__ import annotations
import base64, hashlib, json, re, ssl, time, urllib.request, urllib.error
from pathlib import Path
import certifi
from uuid import uuid4
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _key(path:Path):
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(),password=None)
    key=ec.generate_private_key(ec.SECP256R1()); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    try: path.chmod(0o600)
    except OSError: pass
    return key

# certifi (installed with requests), not the Windows store: an expired cached ISRG Root X2
# cross-sign there makes Python 3.10's OpenSSL reject the hub's valid Let's Encrypt chain.
_TLS=ssl.create_default_context(cafile=certifi.where())

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None

def _request(url:str,path:str,method:str="GET",body:dict|None=None,headers:dict|None=None,timeout:int=20):
    data=json.dumps(body,separators=(",",":")).encode() if body is not None else None
    # Cloudflare answers 403 to the default Python-urllib User-Agent.
    req=urllib.request.Request(url.rstrip("/")+path,data=data,method=method,headers={"Accept":"application/json","User-Agent":"OrionMini-desktop",**({"Content-Type":"application/json"} if body is not None else {}),**(headers or {})})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(), urllib.request.HTTPSHandler(context=_TLS))
        with opener.open(req,timeout=timeout) as r:
            raw = r.read(4_000_001)
            if len(raw) > 4_000_000:
                raise RuntimeError('Saiph Hub response is too large.')
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        # An untrusted server response must not echo pairing codes into the UI.
        raise RuntimeError(f"Saiph Hub returned HTTP {e.code}.") from None
    # A read timeout surfaces as a bare TimeoutError (OSError), not URLError.
    except (urllib.error.URLError, OSError): raise RuntimeError("Cannot reach Saiph Hub.") from None

def pair(root:Path,base_url:str,code:str,name:str="Saiph desktop")->dict:
    from urllib.parse import urlsplit
    parsed = urlsplit(base_url)
    if (any(ord(char) <= 32 for char in base_url) or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("Use a Saiph Hub origin without credentials or a path.")
    if parsed.scheme == "http":
        from .enrollment import mesh_origin
        try:
            if parsed.hostname == 'pi.orion.internal':
                from .link_client import mesh_url
                mesh_url(base_url)
            else:
                base_url = mesh_origin(base_url)
        except (OSError, ValueError):
            raise ValueError("Remote Saiph Hub must use HTTPS or a private mesh HTTP origin.") from None
    key=_key(root/"hub-device-key.pem")
    pub=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    result=_request(base_url,"/v1/pairing/claim","POST",{"code":code.strip(),"name":name.strip() or "Saiph desktop","public_key_der_b64":pub})
    if not isinstance(result, dict) or not isinstance(result.get('device_id'), str) or not re.fullmatch(r'dev_[a-f0-9]{32}', result['device_id']):
        raise RuntimeError('Saiph Hub returned an invalid pairing response.')
    return {"base_url":base_url.rstrip("/"),"device_id":result["device_id"],"paired":True}

def signed(root:Path,config:dict,path:str,method:str="GET",body:dict|None=None):
    base=config.get("base_url","").rstrip("/"); device=config.get("device_id","")
    if not base or not device: raise ValueError("Pair the desktop with Saiph Hub first.")
    raw=json.dumps(body,separators=(",",":")).encode() if body is not None else b""
    return _request(base,path,method,body,signed_headers(root,device,path,method,raw))

def signed_headers(root:Path,device:str,path:str,method:str="GET",raw:bytes=b"")->dict:
    """Also used by Link's signed WebSocket upgrade; no new identity format."""
    ts=str(int(time.time())); nonce=str(uuid4()); digest=hashlib.sha256(raw).hexdigest()
    canonical=f"{method.upper()}\n{path}\n{ts}\n{nonce}\n{digest}".encode(); sig=_key(root/"hub-device-key.pem").sign(canonical,ec.ECDSA(hashes.SHA256()))
    return {"X-Orion-Device-Id":device,"X-Orion-Timestamp":ts,"X-Orion-Nonce":nonce,"X-Orion-Signature":base64.b64encode(sig).decode()}


# ---------------------------------------------------------------- inbox
# Notices and calendar proposals live on the hub, so a decision made on the phone,
# the desktop or the laptop is the same decision everywhere.
def inbox(root:Path,config:dict,status:str|None=None)->list[dict]:
    return signed(root,config,"/v1/inbox"+(f"?status={status}" if status else ""))["items"]

def decide(root:Path,config:dict,item_id:str,decision:str)->dict:
    return signed(root,config,f"/v1/inbox/{item_id}/decide","POST",{"decision":decision})

def local_config(root:Path)->dict:
    """This computer's pairing, as saved by Orion Mini's Settings."""
    for name in ("connections.json","settings.json"):
        path=root/name
        if path.is_file():
            hub=json.loads(path.read_text(encoding="utf-8-sig")).get("hub") or {}
            if hub.get("device_id"): return hub
    return {}

def main(argv=None)->int:
    """Scoped delegate CLI; an explicit --credential file is required:

        python -m orion_mini.hub_client --credential delegate.json list [--status accepted]
        python -m orion_mini.hub_client --credential delegate.json post item.json        # {"id","kind","title",...} or a list of them
        python -m orion_mini.hub_client --credential delegate.json result <id> ok|failed "what happened"
    """
    import sys
    from .agent_client import main as agent_main
    return agent_main(sys.argv[1:] if argv is None else argv)

if __name__=="__main__":
    raise SystemExit(main())
