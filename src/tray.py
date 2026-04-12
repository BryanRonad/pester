"""
Pester system tray icon.
Runs on the main thread (required by pystray on Windows).
"""

import os
import sys
import threading
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


def _show_stats():
    import tkinter as tk
    try:
        import analytics
        stats = analytics.get_today_stats()
        alltime = analytics.get_alltime_stats()
    except Exception as e:
        stats = {}
        alltime = {"error": str(e)}

    win = tk.Tk()
    win.title("Pester Stats")
    win.attributes("-topmost", True)
    win.resizable(False, False)
    win.configure(bg="#1e1e1e")

    FG = "#ffffff"
    BG = "#1e1e1e"
    FONT = ("Segoe UI", 9)
    FONT_H = ("Segoe UI", 10, "bold")

    def row(parent, label, value):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", pady=1)
        tk.Label(f, text=label, font=FONT, bg=BG, fg="#aaaaaa", width=18, anchor="w").pack(side="left")
        tk.Label(f, text=str(value), font=FONT, bg=BG, fg=FG, anchor="w").pack(side="left")

    pad = tk.Frame(win, bg=BG, padx=16, pady=12)
    pad.pack()

    tk.Label(pad, text="Today", font=FONT_H, bg=BG, fg="#ff8c00").pack(anchor="w", pady=(0, 4))
    row(pad, "Cost", f"${stats.get('cost_usd', 0):.4f}")
    row(pad, "Sessions", stats.get("sessions", 0))
    row(pad, "Messages", stats.get("messages", 0))
    row(pad, "Tokens in", f"{stats.get('input_tokens', 0):,}")
    row(pad, "Cache write", f"{stats.get('cache_creation_tokens', 0):,}")
    row(pad, "Cache read", f"{stats.get('cache_read_tokens', 0):,}")
    row(pad, "Tokens out", f"{stats.get('output_tokens', 0):,}")

    tk.Label(pad, text="All Time", font=FONT_H, bg=BG, fg="#ff8c00").pack(anchor="w", pady=(12, 4))
    row(pad, "Total cost", f"${alltime.get('cost_usd', 0):.2f}")
    row(pad, "Active days", alltime.get("active_days", 0))
    row(pad, "Total tokens", f"{alltime.get('total_tokens', 0):,}")

    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"+{sw//2 - w//2}+{sh//2 - h//2}")
    win.mainloop()


def run_tray() -> None:
    """Start the system tray icon. Blocks — must be called from main thread."""
    import pystray
    from pystray import MenuItem, Menu

    icon_image = _get_icon_image()

    def on_stats(icon, item):
        threading.Thread(target=_show_stats, daemon=True).start()

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
        MenuItem("Stats", on_stats),
        MenuItem("Open Config", on_config),
        Menu.SEPARATOR,
        MenuItem("Restart", on_restart),
        MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon("pester", icon_image, "Pester", menu)
    icon.run()
