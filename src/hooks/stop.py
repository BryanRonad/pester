#!/usr/bin/env python3
"""
Pester - Stop Hook
Fires when Claude finishes a response. Shows a notification on the mascot.
If the mascot app is not running, launches it first, then notifies.
Falls back to a Windows system notification only if the app fails to start.
"""

import sys
import json
import os
import time
import urllib.request
import subprocess


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


def pester_running(url):
    try:
        req = urllib.request.Request(f"{url}/health", method="GET")
        resp = urllib.request.urlopen(req, timeout=1)
        return resp.status == 200
    except Exception:
        return False


def launch_pester():
    """Launch the Pester app and wait up to 5 seconds for it to start."""
    import sys
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pester.py")
    if os.path.exists(src):
        subprocess.Popen([sys.executable, src], creationflags=subprocess.DETACHED_PROCESS)


def notify_pester(url, session_id, message):
    try:
        payload = json.dumps({
            "event": "Notification",
            "session_id": session_id,
            "message": message,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{url}/session",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


def system_notification(title, message):
    """Show a Windows system notification as last-resort fallback."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)  # MB_ICONINFORMATION
    except Exception:
        pass


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    session_id = data.get("session_id", "unknown")
    url = _get_pester_url()

    if not pester_running(url):
        launch_pester()
        # Wait up to 5 seconds for the app to start
        for _ in range(10):
            time.sleep(0.5)
            if pester_running(url):
                break

    if pester_running(url):
        # App is running — notify it. If there's no active session (bypass mode),
        # the app will create a temporary mascot to show the notification.
        notify_pester(url, session_id, "Claude finished coding! ✓")
    else:
        # App failed to start — fall back to system notification
        system_notification("Pester", "Claude finished coding!")

    sys.exit(0)


if __name__ == "__main__":
    main()
