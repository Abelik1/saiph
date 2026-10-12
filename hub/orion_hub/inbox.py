# SPDX-License-Identifier: AGPL-3.0-or-later
"""One list of things for the owner: notices (a new assignment, new notes) and proposals
(add this to the calendar?). The hub is the only record, so a decision made on the phone,
the desktop or the laptop is seen by all of them, and only the first decision counts.

Proposal lifecycle: new -> accepted | dismissed; accepted -> applied once the calendar
automation has created the events (a failure keeps it accepted, with the error, to retry).
Notices: new -> done.
"""
from __future__ import annotations
import json, re
from datetime import datetime
from .db import Database
from .security import now_iso

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")
KINDS = {"notice", "proposal"}
# What each decision may do, and the status it leaves.
DECISIONS = {"proposal": {"accept": "accepted", "dismiss": "dismissed"}, "notice": {"done": "done", "dismiss": "done"}}
MAX_EVENTS, MAX_REMINDERS, MAX_REMINDER_MINUTES = 6, 5, 40320  # Google allows reminders up to 4 weeks ahead


def moment(value) -> str:
    text = str(value or "").strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{text!r} is not an ISO date or date and time") from None
    return text


def clean_proposal(proposal) -> dict:
    """Calendar events to create if the owner accepts."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get("events"), list) or not 0 < len(proposal["events"]) <= MAX_EVENTS:
        raise ValueError(f"A proposal needs \"events\": 1-{MAX_EVENTS} calendar events")
    events = []
    for row in proposal["events"]:
        if not isinstance(row, dict) or not str(row.get("title", "")).strip():
            raise ValueError("Each proposed event needs a title")
        reminders = row.get("reminders") or []
        if not isinstance(reminders, list) or len(reminders) > MAX_REMINDERS or \
                not all(isinstance(m, int) and 0 <= m <= MAX_REMINDER_MINUTES for m in reminders):
            raise ValueError(f"reminders is a list of at most {MAX_REMINDERS} minute counts (0-{MAX_REMINDER_MINUTES})")
        events.append({"title": str(row["title"]).strip()[:200], "start": moment(row.get("start")),
                       "end": moment(row["end"]) if row.get("end") else None, "all_day": bool(row.get("all_day")),
                       "reminders": reminders, "location": str(row.get("location") or "")[:200],
                       "description": str(row.get("description") or "")[:2000]})
    return {"events": events, "calendar": str(proposal.get("calendar") or "")[:200]}


def item(row: dict | None) -> dict | None:
    if not row:
        return None
    row = dict(row)
    row["proposal"] = json.loads(row.pop("proposal_json") or "{}") or None
    return row


def get(db: Database, item_id: str) -> dict | None:
    return item(db.row("SELECT * FROM inbox WHERE id=?", (item_id,)))


def listing(db: Database, status: str | None = None, limit: int = 200) -> list[dict]:
    if status:
        rows = db.rows("SELECT * FROM inbox WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
    else:
        rows = db.rows("SELECT * FROM inbox ORDER BY created_at DESC LIMIT ?", (limit,))
    return [item(row) for row in rows]


def post(db: Database, body: dict, agent: str | None = None) -> tuple[dict, bool]:
    """Add an item, or refresh its text while it is still undecided. Returns (item, created).

    `agent` is the delegate that owns a new item; the caller checks ownership of an existing one."""
    item_id, kind = str(body.get("id", "")), body.get("kind")
    if not ID_RE.match(item_id):
        raise ValueError("id must be 2-81 lowercase letters, digits or dashes")
    if kind not in KINDS:
        raise ValueError("kind must be notice or proposal")
    title = str(body.get("title") or "").strip()[:200]
    if not title:
        raise ValueError("title is required")
    link = str(body.get("link") or "").strip()[:500]
    if link and not link.startswith("https://"):
        raise ValueError("link must be an https:// address")
    proposal = clean_proposal(body.get("proposal")) if kind == "proposal" else {}
    values = (str(body.get("source") or "orion").strip()[:40], title, str(body.get("body") or "").strip()[:2000], link,
              json.dumps(proposal, separators=(",", ":")))
    now = now_iso()
    with db.connect() as c:
        created = c.execute("INSERT OR IGNORE INTO inbox(id,kind,source,title,body,link,proposal_json,status,created_at,updated_at,agent) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (item_id, kind, *values, "new", now, now, agent)).rowcount == 1
        if not created:
            # A decided item is never reopened or rewritten by the tool that proposed it.
            c.execute("UPDATE inbox SET source=?,title=?,body=?,link=?,proposal_json=?,updated_at=? WHERE id=? AND status='new' AND kind=?",
                      (*values, now, item_id, kind))
    return get(db, item_id), created


def decide(db: Database, item_id: str, decision: str, by: str) -> tuple[dict, bool]:
    """The first decision wins; a later one from another device changes nothing. Returns (item, changed)."""
    current = get(db, item_id)
    if not current:
        raise LookupError("No such item")
    status = DECISIONS[current["kind"]].get(decision)
    if not status:
        raise ValueError(f"A {current['kind']} can be: " + ", ".join(DECISIONS[current["kind"]]))
    now = now_iso()
    with db.connect() as c:
        changed = c.execute("UPDATE inbox SET status=?,decided_by=?,decided_at=?,updated_at=? WHERE id=? AND status='new'",
                            (status, by[:80], now, now, item_id)).rowcount == 1
    return get(db, item_id), changed


def result(db: Database, item_id: str, ok: bool, text: str) -> dict:
    """The calendar automation reports back on an accepted proposal."""
    current = get(db, item_id)
    if not current:
        raise LookupError("No such item")
    if current["status"] not in {"accepted", "applied"}:
        raise ValueError("Only an accepted proposal can be applied")
    now = now_iso()
    db.execute("UPDATE inbox SET status=?,result=?,updated_at=? WHERE id=?",
               ("applied" if ok else "accepted", str(text or "")[:1000], now, item_id))
    return get(db, item_id)
