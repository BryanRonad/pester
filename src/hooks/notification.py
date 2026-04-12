#!/usr/bin/env python3
"""
Pester - Notification Hook
Forwards Claude Code notifications to the Pester mascot as speech bubbles.
"""

import sys
import json
import urllib.request
import os


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


def _get_pester_url():
    config_path = _find_config_path()
    port = 9001
    if config_path:
        try:
            with open(config_path, "r") as f:
                port = json.load(f).get("port", 9001)
        except Exception:
            pass
    return f"http://localhost:{port}"


PESTER_URL = _get_pester_url()


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    session_id = data.get("session_id", "unknown")

    # "idle" notifications fire every time Claude stops waiting for input —
    # already handled by the Stop hook ("Claude finished coding! ✓"), so skip.
    if data.get("notification_type") == "idle":
        sys.exit(0)

    # Notification message can be in different fields
    message = data.get("message", "") or data.get("notification", "") or data.get("content", "")

    if not message:
        sys.exit(0)

    # Send to Pester
    try:
        payload = json.dumps({
            "event": "Notification",
            "session_id": session_id,
            "message": message[:200],  # truncate long messages
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{PESTER_URL}/session",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
