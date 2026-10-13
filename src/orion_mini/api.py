# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local REST API that tools use to report into Orion (schema ``orion.api/v1``).

It listens on 127.0.0.1 only and requires the bearer token from ``api.json`` in
Orion's data folder. Requests carrying an ``Origin`` header are refused, so a web
page in a browser cannot reach it. Tools that find Orion closed write the same
request into ``inbox/``; Orion replays those files through the same handler.

    GET    /v1/health                           no token; confirms Orion is listening
    GET    /v1/plugins                          plugins registered on this computer
    PUT    /v1/plugins/{id}/status              current state of the tool
    POST   /v1/plugins/{id}/events              append timeline events
    PUT    /v1/plugins/{id}/ticker/{item}       add or replace a status-bar item
    DELETE /v1/plugins/{id}/ticker/{item}       remove a status-bar item
    PUT    /v1/plugins/{id}/reviews             replace the items waiting for a decision
    PUT    /v1/plugins/{id}/calendar            replace the tool's deadlines, exams and classes
    GET    /v1/ticker                           everything currently in the status bar
    POST   /v1/app/restart                      close and relaunch this build (live HTTP only)
    POST   /v1/app/call                         opt-in allowlisted app action (see automation.py; live HTTP only)
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .storage import read_json, write_json

API_SCHEMA = "orion.api/v1"
DEFAULT_PORT = 47815
MAX_BODY = 64 * 1024
INBOX_BATCH = 200
ROUTE = re.compile(r"^/v1/plugins/([a-z0-9-]+)(?:/(status|events|ticker|reviews|calendar)(?:/([a-z0-9-]+))?)?$")


class ApiError(Exception):
    def __init__(self, code: int, error: str, message: str):
        super().__init__(message)
        self.code, self.error = code, error


def handle(workspace, method: str, path: str, body: dict | None) -> tuple[int, dict]:
    """Route one request. Shared by HTTP and the offline inbox."""
    plugins = workspace.plugins
    # describe() rather than state(): only the Qt thread polls running commands.
    described = lambda: [plugins.describe(entry) for entry in list(plugins.entries)]
    try:
        if path == "/v1/health" and method == "GET":
            return 200, {"ok": True, "schema": API_SCHEMA, "machine": workspace.settings["machine"]["name"]}
        if path == "/v1/plugins" and method == "GET":
            return 200, {"plugins": [{"id": row["id"], "name": row["name"], "approved": row["approved"], "status": row["status"]}
                                     for row in described()]}
        if path == "/v1/ticker" and method == "GET":
            return 200, {"items": plugins.ticker(described())}
        if path == "/v1/enrollment/import" and method == "POST":
            if not isinstance(body, dict) or set(body) != {"path"} or not isinstance(body["path"], str):
                raise ApiError(400, "invalid_body", "Send an invitation file path.")
            return 200, workspace.dispatch("enrollment.import", body)
        match = ROUTE.match(path)
        if not match or not match.group(2):
            raise ApiError(404, "not_found", "No such endpoint.")
        plugin_id, resource, item = match.groups()
        if method in {"PUT", "POST"} and not isinstance(body, dict):
            raise ApiError(400, "invalid_body", "Send a JSON object.")
        if resource == "status" and method == "PUT" and not item:
            return 200, {"status": plugins.set_status(plugin_id, body)}
        if resource == "events" and method == "POST" and not item:
            return 200, {"added": plugins.add_events(plugin_id, body)}
        if resource == "reviews" and method == "PUT" and not item:
            return 200, {"items": plugins.set_reviews(plugin_id, body)}
        if resource == "calendar" and method == "PUT" and not item:
            return 200, {"events": plugins.set_calendar(plugin_id, body)}
        if resource == "ticker" and item and method == "PUT":
            return 200, {"item": plugins.put_ticker(plugin_id, item, body)}
        if resource == "ticker" and item and method == "DELETE":
            plugins.delete_ticker(plugin_id, item)
            return 200, {"ok": True}
        raise ApiError(405, "method_not_allowed", "That method is not supported here.")
    except ApiError as error:
        return error.code, {"error": error.error, "message": str(error)}
    except LookupError as error:
        # A tool reporting from a computer where its plugin is not enabled.
        return 404, {"error": "plugin_not_registered", "message": str(error)}
    except ValueError as error:
        return 422, {"error": "invalid", "message": str(error)}


def discovery(root: Path) -> dict:
    """Keep the token stable across restarts so long-running tools stay valid."""
    saved = read_json(root / "api.json", {}) or {}
    token = saved.get("token") if isinstance(saved.get("token"), str) and len(saved["token"]) >= 32 else secrets.token_urlsafe(32)
    return {"schema": API_SCHEMA, "token": token}


def replay_inbox(workspace) -> int:
    """Apply requests that tools queued while Orion was closed, oldest first."""
    inbox = workspace.root / "inbox"
    if not inbox.is_dir():
        return 0
    applied = 0
    for file in sorted(inbox.glob("*.json"))[:INBOX_BATCH]:
        try:
            request = json.loads(file.read_text(encoding="utf-8-sig"))
            code, result = handle(workspace, str(request["method"]).upper(), str(request["path"]), request.get("body"))
        except (OSError, ValueError, KeyError, TypeError) as error:
            code, result = 400, {"error": "invalid_request", "message": str(error)}
        if code >= 400:
            rejected = inbox / "rejected"
            rejected.mkdir(exist_ok=True)
            write_json(rejected / (file.stem + ".error.json"), result)
            file.replace(rejected / file.name)
        else:
            file.unlink(missing_ok=True)
            applied += 1
    return applied


def app_call(workspace, body) -> tuple[int, dict]:
    """Live authenticated HTTP only; the offline inbox cannot reach app actions."""
    call = getattr(workspace, "automation_call", None)
    if call is None:
        return 503, {"error": "unavailable", "message": "App actions are unavailable in this process."}
    if (not isinstance(body, dict) or set(body) - {"method", "args"} or not isinstance(body.get("method"), str)
            or not isinstance(body.get("args", {}), dict)):
        return 400, {"error": "invalid_body", "message": "Send {\"method\": ..., \"args\": {...}}."}
    try:
        return 200, {"result": call(body["method"], body.get("args", {}))}
    except PermissionError as error:
        return 403, {"error": "forbidden", "message": str(error)}
    except TimeoutError:
        return 504, {"error": "timeout", "message": "The app did not finish the action in time."}
    except (ValueError, LookupError, OSError, RuntimeError, TypeError) as error:
        return 400, {"error": "failed", "message": str(error)}


class ApiServer:
    def __init__(self, workspace, port: int | None = None):
        self.workspace = workspace
        self.requested_port = DEFAULT_PORT if port is None else port
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.info = {"running": False, "url": "", "error": "", "discovery": str(workspace.root / "api.json")}

    def start(self) -> dict:
        details = discovery(self.workspace.root)
        token = details["token"]
        workspace = self.workspace

        class Handler(BaseHTTPRequestHandler):
            server_version = "OrionMini"

            def log_message(self, *_args):
                pass

            def reply(self, code: int, payload: dict):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def serve(self, method: str):
                port = self.server.server_address[1]
                if self.headers.get("Origin") or self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                    return self.reply(403, {"error": "forbidden", "message": "Only local tools may call this API."})
                path = self.path.split("?", 1)[0].rstrip("/") or "/"
                if path != "/v1/health":
                    supplied = self.headers.get("Authorization", "")
                    if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
                        return self.reply(401, {"error": "unauthorized", "message": "Send the token from api.json as a Bearer token."})
                body = None
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self.reply(413, {"error": "too_large", "message": "Request bodies are limited to 64 KB."})
                if length:
                    try:
                        body = json.loads(self.rfile.read(length))
                    except ValueError:
                        return self.reply(400, {"error": "invalid_json", "message": "The body is not valid JSON."})
                if path == "/v1/app/restart" and method == "POST":
                    # Live authenticated callers only: an inbox replay at startup
                    # must never be able to restart the app again.
                    restart = getattr(workspace, "request_restart", None)
                    if restart is None:
                        return self.reply(503, {"error": "unavailable", "message": "Restart is unavailable in this process."})
                    self.reply(202, {"restarting": True, "pid": os.getpid()})
                    return restart()
                if path == "/v1/phone/send" and method == "POST":
                    # Live authenticated callers only (Send to phone from a file manager);
                    # the owner still confirms the phone before anything is sent.
                    request = getattr(workspace, "request_send_files", None)
                    if request is None:
                        return self.reply(503, {"error": "unavailable", "message": "Sending is unavailable in this process."})
                    if not isinstance(body, dict) or set(body) != {"paths"}:
                        return self.reply(400, {"error": "invalid_body", "message": "Send a list of file paths."})
                    from .send_files import validate
                    try:
                        paths = validate(body["paths"])
                    except (ValueError, OSError) as error:
                        return self.reply(400, {"error": "invalid_files", "message": str(error)})
                    request(paths)
                    return self.reply(202, {"confirming": True, "files": len(paths)})
                if path == "/v1/app/call" and method == "POST":
                    return self.reply(*app_call(workspace, body))
                self.reply(*handle(workspace, method, path, body))

            def do_GET(self): self.serve("GET")
            def do_PUT(self): self.serve("PUT")
            def do_POST(self): self.serve("POST")
            def do_DELETE(self): self.serve("DELETE")

        for port in ([self.requested_port, 0] if self.requested_port else [0]):
            try:
                self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
                break
            except OSError as error:
                self.info["error"] = f"Port {port} is in use ({error.strerror or error}); using a free port instead."
        if not self.server:
            self.info["error"] = "The local API could not start."
            return self.info
        self.server.daemon_threads = True
        url = f"http://127.0.0.1:{self.server.server_address[1]}"
        write_json(self.workspace.root / "api.json", {**details, "url": url, "pid": os.getpid(),
                                                      "machine": self.workspace.settings["machine"]["name"]})
        self.thread = threading.Thread(target=self.server.serve_forever, name="orion-api", daemon=True)
        self.thread.start()
        self.info.update(running=True, url=url)
        return self.info

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self.info["running"] = False
