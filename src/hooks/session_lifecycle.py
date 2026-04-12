#!/usr/bin/env python3
"""
Pester - Session Lifecycle Hook
Notifies the Pester app when sessions start/end so it can spawn/remove mascots.
Also sends terminal PID so Pester can focus the right terminal window.
"""

import sys
import json
import os
import urllib.request


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


def find_terminal_info():
    """Walk up process tree to find the terminal app PID and name."""
    terminal_pid = 0
    terminal_app = ""
    KNOWN_TERMINALS = {
        "WindowsTerminal", "Code", "Cursor", "idea64", "pycharm64",
        "devenv", "sublime_text", "notepad++",
    }
    try:
        import psutil
        proc = psutil.Process()
        for parent in proc.parents():
            name = parent.name().replace(".exe", "")
            if name in KNOWN_TERMINALS:
                terminal_pid = parent.pid
                terminal_app = name
    except Exception:
        pass
    return terminal_pid, terminal_app, terminal_app


def notify(event, session_id, cwd="", terminal_pid=0, terminal_app="", terminal_process=""):
    payload = json.dumps({
        "event": event,
        "session_id": session_id,
        "cwd": cwd,
        "terminal_pid": terminal_pid,
        "terminal_app": terminal_app,
        "terminal_process": terminal_process,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{PESTER_URL}/session",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


def is_bypass_mode():
    """Check if Claude was started with --dangerously-skip-permissions."""
    try:
        import psutil
        proc = psutil.Process()
        for parent in proc.parents():
            cmdline = " ".join(parent.cmdline())
            if "dangerously-skip-permissions" in cmdline:
                return True
    except Exception:
        pass
    return False


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    # Don't spawn a mascot at all in bypass mode
    if is_bypass_mode():
        sys.exit(0)

    event = data.get("hook_event_name", "")
    session_id = data.get("session_id", "unknown")
    cwd = data.get("cwd", "")

    if event == "SessionStart":
        terminal_pid, terminal_app, terminal_process = find_terminal_info()
        notify(event, session_id, cwd, terminal_pid, terminal_app, terminal_process)
    elif event == "SessionEnd":
        notify(event, session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
