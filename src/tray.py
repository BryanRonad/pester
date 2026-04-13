"""
Pester system tray icon.
Runs on the main thread (required by pystray on Windows).
"""

import os
import sys
from pathlib import Path


def _get_icon_image():
    from PIL import Image
    # Try assets/ relative to repo root (two dirs up from src/)
    candidates = [
        Path(__file__).parent.parent / "assets" / "icon.png",
        Path(sys.executable).parent / "assets" / "icon.png",  # PyInstaller bundle
    ]
    for p in candidates:
        if p.exists():
            return Image.open(p).convert("RGBA")
    # Generate fallback icon in memory
    img = Image.new("RGBA", (64, 64), (255, 140, 0, 255))
    return img


def _open_config():
    import config as cfg
    path = cfg.get_config_path()
    os.startfile(str(path))


def run_tray() -> None:
    """Start the system tray icon. Blocks — must be called from main thread."""
    import pystray
    from pystray import MenuItem, Menu

    icon_image = _get_icon_image()

    def on_config(icon, item):
        _open_config()

    def on_restart(icon, item):
        icon.stop()
        import subprocess
        script = Path(__file__).parent / "pester.py"
        subprocess.Popen(
            [sys.executable, str(script)],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        sys.exit(0)

    def on_quit(icon, item):
        icon.stop()
        sys.exit(0)

    menu = Menu(
        MenuItem("Pester — Running", None, enabled=False),
        Menu.SEPARATOR,
        MenuItem("Open Config", on_config),
        Menu.SEPARATOR,
        MenuItem("Restart", on_restart),
        MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon("pester", icon_image, "Pester", menu)
    icon.run()
