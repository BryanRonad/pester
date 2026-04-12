"""
Pester — Windows Claude Code permission guardian.
Entry point: starts HTTP server + popup worker, then runs system tray (blocking).
"""

import sys
import os

# Allow imports from src/ when running as script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server
import popup
import tray
from config import load_config


def main():
    config = load_config()
    port = config.get("port", 9001)

    # Check not already running
    import socket
    test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        test.bind(("127.0.0.1", port))
        test.close()
    except OSError:
        print(f"Pester is already running on port {port}.")
        sys.exit(1)

    # Start HTTP server
    server.start(port)

    # Start popup worker thread
    popup.start_popup_worker()

    # Wire server → popup
    server.set_approval_callback(popup.enqueue_request)

    print(f"Pester running on port {port}. Check system tray.")

    # Start tray (blocks main thread)
    tray.run_tray()


if __name__ == "__main__":
    main()
