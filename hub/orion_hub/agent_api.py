# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scoped delegates of paired owners. Sensitive request/response data is never logged."""
from __future__ import annotations

import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import inbox, phone
from .security import hash_token, now_iso, verify_device_request
from .link import Event, require_mesh

SCOPES = frozenset({"devices.read", "notifications.read", "sms.read", "actions.propose",
                    "inbox.read", "inbox.propose", "inbox.result"})
DEFAULT_SCOPES = ["devices.read", "notifications.read"]
MAX_BODY = 16_384
SOURCE_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_SCOPES), min_length=1, max_length=7)
    days: int = Field(default=7, ge=1, le=30)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target: str = Field(min_length=1, max_length=80)
    type: str
    payload: dict


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,80}$")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=2000)
    action: Action


def initialize(db):
    """Extend the existing session store; delegates are not a second device identity."""
    with db.connect() as c:
        columns = {r[1] for r in c.execute("PRAGMA table_info(web_sessions)")}
        if "scopes_json" not in columns:
            c.execute("ALTER TABLE web_sessions ADD COLUMN scopes_json TEXT")
        if "owner_device_id" not in columns:
            c.execute("ALTER TABLE web_sessions ADD COLUMN owner_device_id TEXT")
        if "agent" not in {r[1] for r in c.execute("PRAGMA table_info(inbox)")}:
            # Preserve explicit delegate ownership across token rotation. Owner-posted
            # items remain owner-owned; their source label does not authorize a delegate.
            c.execute("ALTER TABLE inbox ADD COLUMN agent TEXT")
            c.execute("UPDATE inbox SET agent=(SELECT name FROM web_sessions WHERE substr(id_hash,1,16)=substr(inbox.source,7)) "
                      "WHERE source LIKE 'agent:%' AND proposal_json NOT LIKE '%\"action\"%'")


def issue(db, owner: dict, body: dict) -> dict:
    try:
        grant = Grant.model_validate(body)
        if len(set(grant.scopes)) != len(grant.scopes) or not set(grant.scopes) <= SCOPES or not grant.name.strip():
            raise ValueError()
    except ValueError:
        raise ValueError("Invalid delegate grant") from None
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=grant.days)).isoformat()
    identifier = hash_token(token)
    db.execute("INSERT INTO web_sessions(id_hash,name,csrf_hash,expires_at,created_at,scopes_json,owner_device_id) "
               "VALUES(?,?,?,?,?,?,?)", (identifier, grant.name.strip(), "", expires, now_iso(),
                                         json.dumps(sorted(grant.scopes)), owner["id"]))
    return {"id": identifier, "token": token, "name": grant.name.strip(), "scopes": sorted(grant.scopes), "expires_at": expires}


def authenticate(db, request, scope: str) -> dict:
    require_mesh(request)
    if request.headers.get("origin") or request.cookies.get("orion_session"):
        raise HTTPException(403, "Delegates require their scoped bearer credential")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or not 32 <= len(auth[7:]) <= 128:
        raise HTTPException(401, "Missing delegate credential")
    row = db.row("SELECT * FROM web_sessions WHERE id_hash=?", (hash_token(auth[7:]),))
    try:
        if not row or not row["owner_device_id"] or not row["scopes_json"]:
            raise ValueError()
        if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            raise ValueError()
        if not db.row("SELECT id FROM devices WHERE id=?", (row["owner_device_id"],)):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "Delegate expired or revoked") from None
    if scope not in json.loads(row["scopes_json"]):
        raise HTTPException(403, "Delegate lacks required scope")
    return row


def action_event(item_id: str, action: dict) -> dict:
    return {"id": str(uuid5(NAMESPACE_URL, "orion:approved-action:" + item_id)),
            "type": action["type"], "ttl_seconds": 30, "targets": [action["target"]], "payload": action["payload"]}


def validate_action(connection, action: dict, source: str):
    try:
        parsed = Action.model_validate(action)
        if parsed.type not in {"notification.command", "sms.send"} or parsed.target == source:
            raise ValueError()
        target = connection.execute("SELECT capabilities_json FROM link_devices WHERE device_id=?", (parsed.target,)).fetchone()
        required = "notifications" if parsed.type == "notification.command" else "sms"
        if not target or required not in json.loads(target[0]):
            raise ValueError()
        event = Event.model_validate(action_event("validation", parsed.model_dump()))
        if parsed.type == "notification.command":
            phone.apply(connection, source, event, time.time())
        else:
            # Features owns the retained thread and forbids recipient overrides.
            from . import features
            features.apply(connection, source, event, time.time())
    except (ValueError, TypeError, KeyError):
        raise ValueError("Action unavailable or invalid") from None


def review_action(connection, action: dict):
    """Owner-facing facts come from retained phone authority, never agent prose."""
    device = connection.execute("SELECT name FROM devices WHERE id=?", (action["target"],)).fetchone()
    result = {"phone": device[0] if device else "Phone", "type": action["type"]}
    payload = action["payload"]
    if action["type"] == "sms.send":
        row = connection.execute("SELECT data_json FROM phone_features WHERE device_id=? AND kind='thread' AND item_key=?",
                                 (action["target"], str(payload["thread"]))).fetchone()
        result.update({"operation": "Send SMS reply", "recipients": json.loads(row[0])["recipients"], "text": payload["text"]})
    else:
        row = connection.execute("SELECT data_json FROM phone_notifications WHERE device_id=? AND notification_key=?",
                                 (action["target"], payload["key"])).fetchone()
        notification = json.loads(row[0])
        operation = payload["operation"]
        label = {"reply": "Reply to notification", "dismiss": "Dismiss notification", "open": "Open on phone"}.get(operation, "Run notification action")
        if operation == "action":
            label = next(a["label"] for a in notification["actions"] if a["index"] == payload["index"])
        result.update({"operation": label, "app": notification["app"], "title": notification["title"]})
        if operation == "reply":
            result["text"] = payload["text"]
    return result


def propose(db, principal: dict, body: dict):
    try:
        proposal = Proposal.model_validate(body)
        if not proposal.title.strip():
            raise ValueError()
    except ValueError:
        raise ValueError("Invalid action proposal") from None
    saved = {"action": proposal.action.model_dump(), "agent": {"id": principal["id_hash"], "name": principal["name"],
                                                               "owner": principal["owner_device_id"]}}
    now = now_iso()
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        old = c.execute("SELECT * FROM inbox WHERE id=?", (proposal.id,)).fetchone()
        if old:
            previous = json.loads(old["proposal_json"])
            if {k: previous.get(k) for k in ("action", "agent")} != saved or old["title"] != proposal.title or old["body"] != proposal.body:
                raise ValueError("Proposal ID conflict")
            return inbox.item(dict(old)), False
        validate_action(c, proposal.action.model_dump(), principal["owner_device_id"])
        saved["review"] = review_action(c, saved["action"])
        c.execute("INSERT INTO inbox(id,kind,source,title,body,link,proposal_json,status,created_at,updated_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?)", (proposal.id, "proposal", "agent", proposal.title, proposal.body,
                                               "", json.dumps(saved, separators=(",", ":")), "new", now, now))
    return inbox.get(db, proposal.id), True


def is_action(row: dict | None) -> bool:
    return bool(row and isinstance(row.get("proposal"), dict) and "action" in row["proposal"])


def decide_action(db, bus, item_id: str, decision: str, approver: dict):
    """Commit owner approval with one queue insert. No agent may call this function."""
    if approver.get("kind") != "device":
        raise ValueError("Approve phone actions from a paired device")
    if decision not in {"accept", "dismiss"}:
        raise ValueError("Choose accept or dismiss")
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM inbox WHERE id=?", (item_id,)).fetchone()
        current = inbox.item(dict(row)) if row else None
        if not is_action(current):
            raise LookupError("No action proposal")
        if current["status"] != "new":
            return current, False
        proposal = current["proposal"]
        if decision == "accept":
            grant = c.execute("SELECT * FROM web_sessions WHERE id_hash=?", (proposal["agent"]["id"],)).fetchone()
            if not grant or not grant["scopes_json"] or "actions.propose" not in json.loads(grant["scopes_json"]) or \
                    datetime.fromisoformat(grant["expires_at"]) <= datetime.now(timezone.utc) or \
                    not c.execute("SELECT id FROM devices WHERE id=?", (grant["owner_device_id"],)).fetchone():
                raise ValueError("Proposal delegate expired or revoked; dismiss this item")
            validate_action(c, proposal["action"], approver["id"])
            if review_action(c, proposal["action"]) != proposal["review"]:
                raise ValueError("Phone action context changed; dismiss this item and request a fresh proposal")
            # Parent integration factors the existing Store.publish body into this
            # method so validation, dedup and capacity limits remain identical.
            bus.store.publish_in_transaction(c, approver["id"], action_event(item_id, proposal["action"]), time.time())
            status, result = "applied", "Approved action queued for the phone"
        else:
            status, result = "dismissed", ""
        c.execute("UPDATE inbox SET status=?,result=?,decided_by=?,decided_at=?,updated_at=? WHERE id=? AND status='new'",
                  (status, result, approver["name"][:80], now_iso(), now_iso(), item_id))
    return inbox.get(db, item_id), True


async def bounded_raw(request):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY:
            raise HTTPException(413, "Request too large")
        raw.extend(chunk)
    return bytes(raw)


def decode_body(raw):
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError()
        return body
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(400, "Invalid request") from None


async def bounded_body(request):
    return decode_body(await bounded_raw(request))


def router(db, bus, notify):
    routes = APIRouter(prefix="/v1/agents")

    def owner(request, body=b""):
        require_mesh(request)
        if request.headers.get("origin") or request.cookies.get("orion_session"):
            raise HTTPException(403, "Use the paired owner device")
        return verify_device_request(db, request, body)

    @routes.post("/grants")
    async def create_grant(request: Request):
        raw = await bounded_raw(request)
        principal = owner(request, raw)
        body = decode_body(raw)
        try:
            return issue(db, principal, body)
        except ValueError:
            raise HTTPException(400, "Invalid delegate grant") from None

    @routes.get("/grants")
    async def grants(request: Request):
        principal = owner(request)
        return {"grants": [{"id": r["id_hash"], "name": r["name"], "scopes": json.loads(r["scopes_json"]), "expires_at": r["expires_at"]}
                           for r in db.rows("SELECT * FROM web_sessions WHERE owner_device_id=? AND scopes_json IS NOT NULL", (principal["id"],))]}

    @routes.delete("/grants/{identifier}")
    async def revoke(identifier: str, request: Request):
        principal = owner(request)
        db.execute("DELETE FROM web_sessions WHERE id_hash=? AND owner_device_id=? AND scopes_json IS NOT NULL", (identifier, principal["id"]))
        return {"ok": True}

    @routes.get("/devices")
    async def devices(request: Request):
        authenticate(db, request, "devices.read")
        return {"devices": bus.presence()}

    @routes.get("/notifications")
    async def notifications(request: Request, limit: int = 100):
        authenticate(db, request, "notifications.read")
        return {"notifications": phone.snapshot(db, [])['notifications'][:max(1, min(limit, 200))]}

    @routes.get("/messages")
    async def messages(request: Request, limit: int = 100):
        authenticate(db, request, "sms.read")
        from . import features
        return {"messages": features.snapshot(db)["messages"][:max(1, min(limit, 200))]}

    @routes.post("/actions")
    async def actions(request: Request):
        principal = authenticate(db, request, "actions.propose")
        body = await bounded_body(request)
        try:
            row, created = propose(db, principal, body)
        except (ValueError, TypeError):
            raise HTTPException(400, "Action proposal unavailable, invalid or conflicting") from None
        if created:
            notify(row)
        return {"item": row, "created": created}

    @routes.get("/inbox")
    async def read_inbox(request: Request, status: str | None = None):
        principal = authenticate(db, request, "inbox.read")
        # Agents can inspect only items they created, not the owner's unrelated inbox. Calendar items follow the
        # delegate's name, so a rotated token still sees what it posted; phone actions stay tied to one grant.
        return {"items": [r for r in inbox.listing(db, status) if
                          (not is_action(r) and r.get("agent") == principal["name"]) or
                          (is_action(r) and r["proposal"]["agent"]["id"] == principal["id_hash"])]}

    @routes.post("/inbox")
    async def calendar_post(request: Request):
        principal = authenticate(db, request, "inbox.propose")
        body = await bounded_body(request)
        # Calendar automation remains compatible without gaining device authority. Its source is only a label.
        source = body.get("source")
        body["source"] = source if isinstance(source, str) and SOURCE_RE.match(source) else "agent"
        previous = inbox.get(db, body.get("id", "") if isinstance(body.get("id"), str) else "")
        if previous and (is_action(previous) or previous.get("agent") != principal["name"]):
            raise HTTPException(409, "Item id belongs to another source")
        try:
            row, created = inbox.post(db, body, agent=principal["name"])
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(400, "Invalid calendar item") from None
        if created:
            notify(row)
        return {"item": row, "created": created}

    @routes.post("/inbox/{item_id}/result")
    async def calendar_result(item_id: str, request: Request):
        principal = authenticate(db, request, "inbox.result")
        body = await bounded_body(request)
        row = inbox.get(db, item_id)
        if not row or row.get("agent") != principal["name"] or is_action(row):
            raise HTTPException(404, "No calendar proposal")
        try:
            if not isinstance(body.get("ok"), bool):
                raise ValueError()
            row = inbox.result(db, item_id, body["ok"], str(body.get("result", ""))[:1000])
        except ValueError:
            raise HTTPException(400, "Only accepted calendar proposals can be applied") from None
        notify(row)
        return {"item": row}

    return routes
