#!/usr/bin/env python3
"""
Pester - PermissionRequest Hook
Intercepts Claude Code's built-in permission prompts (Yes/No/Don't ask again)
and routes them through the Pester overlay instead.
"""

import sys
import json
import os
import urllib.request
import urllib.error
import time

POLL_INTERVAL = 0.5


def _find_config_path():
    """Find pester.config.json: user override > bundled default."""
    user_config = os.path.join(os.environ.get("APPDATA", ""), "pester", "pester.config.json")
    if os.path.isfile(user_config):
        return user_config
    # Bundled: script is in src/hooks/, config is two dirs up
    bundled = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "pester.config.json")
    if os.path.isfile(bundled):
        return bundled
    return None


def load_config():
    config_path = _find_config_path()
    if not config_path:
        return {"auto_approve": [], "always_block": [], "timeout_seconds": 300}
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"auto_approve": [], "always_block": [], "timeout_seconds": 300}


def _get_pester_url():
    config = load_config()
    port = config.get("port", 9001)
    return f"http://localhost:{port}"


PESTER_URL = _get_pester_url()


def check_server():
    try:
        req = urllib.request.Request(f"{PESTER_URL}/health", method="GET")
        resp = urllib.request.urlopen(req, timeout=1)
        return resp.status == 200
    except Exception:
        return False


def send_permission_request(tool_name, tool_input, session_id):
    payload = json.dumps({
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": session_id,
        "timestamp": time.time()
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{PESTER_URL}/request",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        resp = urllib.request.urlopen(req, timeout=2)
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("request_id")
    except Exception:
        return None


def poll_for_decision(request_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                f"{PESTER_URL}/decision/{request_id}",
                method="GET"
            )
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read().decode("utf-8"))
            status = data.get("status")
            if status == "pending":
                time.sleep(POLL_INTERVAL)
                continue
            elif status == "approved":
                return "allow", data.get("message", "")
            elif status == "passthrough":
                return "passthrough", ""
            elif status == "denied":
                return "deny", data.get("message", "User denied this action")
            elif status == "timeout":
                config = load_config()
                if config.get("auto_deny_on_timeout", True):
                    return "deny", "Request timed out - auto-denied"
                return "passthrough", ""
            else:
                time.sleep(POLL_INTERVAL)
                continue
        except urllib.error.URLError:
            return None, "Pester app not responding"
        except Exception:
            time.sleep(POLL_INTERVAL)
            continue
    config = load_config()
    if config.get("auto_deny_on_timeout", True):
        return "deny", "Hook polling timed out"
    return "passthrough", ""


def send_cost_update(session_id, cost_usd):
    if cost_usd <= 0:
        return
    try:
        payload = json.dumps({
            "event": "CostUpdate",
            "session_id": session_id,
            "cost_usd": cost_usd,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{PESTER_URL}/session",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass


def main():
    raw_input = sys.stdin.read()
    try:
        hook_input = json.loads(raw_input)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})
    session_id = hook_input.get("session_id", "unknown")

    # Send cost update if available
    cost_data = hook_input.get("cost", {})
    cost_usd = cost_data.get("total_cost_usd", 0) if isinstance(cost_data, dict) else 0
    if cost_usd > 0:
        send_cost_update(session_id, cost_usd)

    config = load_config()

    # Check auto-approve list
    if tool_name in config.get("auto_approve", []):
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {"behavior": "allow"}
            }
        }
        print(json.dumps(result))
        sys.exit(0)

    # Check always-block list
    if tool_name in config.get("always_block", []):
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "deny",
                    "message": f"Blocked: {tool_name} is in always_block list"
                }
            }
        }
        print(json.dumps(result))
        sys.exit(0)

    # Check if Pester is running
    if not check_server():
        sys.exit(0)  # Fall back to Claude Code's own prompt

    # Send request to Pester overlay
    request_id = send_permission_request(tool_name, tool_input, session_id)
    if not request_id:
        sys.exit(0)

    # Block and wait for user decision
    timeout = config.get("timeout_seconds", 300)
    decision, message = poll_for_decision(request_id, timeout)

    if decision == "allow":
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {"behavior": "allow"}
            }
        }
        print(json.dumps(result))
        sys.exit(0)
    elif decision == "passthrough":
        # Mascot is hidden — exit with no output so Claude Code shows its own prompt
        sys.exit(0)
    elif decision == "deny":
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "deny",
                    "message": message if message else "Denied via Pester"
                }
            }
        }
        print(json.dumps(result))
        sys.exit(0)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
