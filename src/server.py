"""
Pester HTTP server.
Runs on localhost:9001 (configurable). Receives tool approval requests from
Claude Code hook scripts and serves decisions back to them.
"""

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

# In-memory store: request_id -> {tool_name, tool_input, session_id, timestamp, status, message}
_requests: dict[str, dict] = {}
_requests_lock = threading.Lock()

# Session events for analytics: list of {event, session_id, ...}
_session_events: list[dict] = []
_session_lock = threading.Lock()

# Callback fired when a new /request arrives — used by pester.py to show popup
_approval_callback: Optional[Callable[[dict], None]] = None


def set_approval_callback(fn: Callable[[dict], None]) -> None:
    global _approval_callback
    _approval_callback = fn


def approve(request_id: str, message: str = "") -> None:
    with _requests_lock:
        if request_id in _requests:
            _requests[request_id]["status"] = "approved"
            _requests[request_id]["message"] = message


def deny(request_id: str, message: str = "Denied via Pester") -> None:
    with _requests_lock:
        if request_id in _requests:
            _requests[request_id]["status"] = "denied"
            _requests[request_id]["message"] = message


def always_allow(request_id: str) -> str | None:
    """Mark approved and return the tool_name so caller can persist it to config."""
    with _requests_lock:
        if request_id in _requests:
            _requests[request_id]["status"] = "approved"
            _requests[request_id]["message"] = "Always allowed via Pester"
            return _requests[request_id].get("tool_name")
    return None


def get_session_events() -> list[dict]:
    with _session_lock:
        return list(_session_events)


class _Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):  # silence access log
        pass

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Optional[dict]:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, ValueError):
            return None

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return

        if self.path.startswith("/decision/"):
            request_id = self.path[len("/decision/"):]
            with _requests_lock:
                req = _requests.get(request_id)
            if req is None:
                self._send_json(404, {"error": "not found"})
                return
            self._send_json(200, {
                "status": req["status"],
                "message": req.get("message", ""),
            })
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/request":
            data = self._read_json()
            if data is None:
                self._send_json(400, {"error": "bad json"})
                return
            request_id = str(uuid.uuid4())
            entry = {
                "request_id": request_id,
                "tool_name": data.get("tool_name", ""),
                "tool_input": data.get("tool_input", {}),
                "session_id": data.get("session_id", "unknown"),
                "timestamp": data.get("timestamp", 0),
                "status": "pending",
                "message": "",
            }
            with _requests_lock:
                _requests[request_id] = entry
            if _approval_callback:
                threading.Thread(
                    target=_approval_callback,
                    args=(entry,),
                    daemon=True,
                ).start()
            self._send_json(200, {"request_id": request_id})
            return

        if self.path == "/session":
            data = self._read_json()
            if data:
                with _session_lock:
                    _session_events.append(data)
            self._send_json(200, {"ok": True})
            return

        self._send_json(404, {"error": "not found"})


def start(port: int = 9001) -> HTTPServer:
    """Start the HTTP server in a daemon thread. Returns the server instance."""
    server = HTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
