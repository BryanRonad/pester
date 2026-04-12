"""
Pester approval popup.
Shows a topmost tkinter window for each pending tool approval request.
One popup at a time — subsequent requests are queued.
"""

import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable


_popup_queue: queue.Queue = queue.Queue()
_popup_thread: threading.Thread | None = None
_popup_thread_lock = threading.Lock()


def _format_tool_input(tool_input: dict) -> str:
    """Extract the most useful single-line summary of tool_input."""
    if not tool_input:
        return ""
    for key in ("command", "file_path", "path", "query", "pattern"):
        if key in tool_input:
            val = str(tool_input[key])
            return val[:120] + ("..." if len(val) > 120 else "")
    # Fallback: first value
    first = next(iter(tool_input.values()), "")
    val = str(first)
    return val[:120] + ("..." if len(val) > 120 else "")


def _show_one(request: dict, on_approve: Callable, on_deny: Callable, on_always: Callable) -> None:
    """Show a single popup and block until the user decides."""
    decided = threading.Event()
    result = [None]

    root = tk.Tk()
    root.title("Pester")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.configure(bg="#1e1e1e")

    # --- Layout ---
    FONT_TITLE = ("Segoe UI", 11, "bold")
    FONT_BODY = ("Segoe UI", 9)
    FONT_SMALL = ("Segoe UI", 8)
    BG = "#1e1e1e"
    FG = "#ffffff"
    ORANGE = "#ff8c00"
    GREEN = "#4ade80"
    RED = "#f87171"
    YELLOW = "#fbbf24"

    header = tk.Frame(root, bg=ORANGE, padx=12, pady=8)
    header.pack(fill="x")
    tk.Label(header, text="! Pester", font=FONT_TITLE, bg=ORANGE, fg="#000").pack(anchor="w")

    body = tk.Frame(root, bg=BG, padx=14, pady=10)
    body.pack(fill="both")

    tool_name = request.get("tool_name", "Unknown")
    session_id = request.get("session_id", "")[:8]
    detail = _format_tool_input(request.get("tool_input", {}))

    tk.Label(body, text=f"Tool:  {tool_name}", font=FONT_BODY, bg=BG, fg=FG, anchor="w").pack(fill="x")
    if detail:
        tk.Label(body, text=f"Args:  {detail}", font=FONT_BODY, bg=BG, fg="#aaaaaa", anchor="w",
                 wraplength=340, justify="left").pack(fill="x", pady=(2, 0))
    tk.Label(body, text=f"Session: ...{session_id}", font=FONT_SMALL, bg=BG, fg="#666666", anchor="w").pack(fill="x", pady=(4, 0))

    # Countdown bar
    timeout = max(1, int(request.get("timeout_seconds", 60) or 60))
    countdown_var = tk.StringVar(value=f"Auto-deny in {timeout}s")
    tk.Label(body, textvariable=countdown_var, font=FONT_SMALL, bg=BG, fg="#888888", anchor="w").pack(fill="x", pady=(6, 2))
    progress = ttk.Progressbar(body, maximum=timeout, value=timeout, length=340)
    progress.pack(fill="x")

    # Buttons
    btn_frame = tk.Frame(root, bg=BG, padx=14, pady=10)
    btn_frame.pack(fill="x")

    def do_approve():
        result[0] = "approve"
        decided.set()
        root.destroy()

    def do_always():
        result[0] = "always"
        decided.set()
        root.destroy()

    def do_deny():
        result[0] = "deny"
        decided.set()
        root.destroy()

    tk.Button(btn_frame, text="Allow  [Y]", command=do_approve,
              bg=GREEN, fg="#000", font=FONT_BODY, relief="flat", padx=10, pady=5).pack(side="left", padx=(0, 6))
    tk.Button(btn_frame, text="Always  [A]", command=do_always,
              bg=YELLOW, fg="#000", font=FONT_BODY, relief="flat", padx=10, pady=5).pack(side="left", padx=(0, 6))
    tk.Button(btn_frame, text="Deny  [N]", command=do_deny,
              bg=RED, fg="#000", font=FONT_BODY, relief="flat", padx=10, pady=5).pack(side="left")

    # Keyboard shortcuts
    root.bind("<Return>", lambda e: do_approve())
    root.bind("y", lambda e: do_approve())
    root.bind("Y", lambda e: do_approve())
    root.bind("a", lambda e: do_always())
    root.bind("A", lambda e: do_always())
    root.bind("<Escape>", lambda e: do_deny())
    root.bind("n", lambda e: do_deny())
    root.bind("N", lambda e: do_deny())

    # Position: bottom-right
    root.update_idletasks()
    w = root.winfo_reqwidth()
    h = root.winfo_reqheight()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"+{sw - w - 20}+{sh - h - 60}")

    # Countdown timer
    remaining = [timeout]

    def tick():
        if result[0] is not None:
            return
        remaining[0] -= 1
        progress["value"] = remaining[0]
        countdown_var.set(f"Auto-deny in {remaining[0]}s")
        if remaining[0] <= 0:
            do_deny()
        else:
            root.after(1000, tick)

    root.after(1000, tick)
    root.focus_force()
    root.mainloop()

    # Dispatch result
    if result[0] == "approve":
        on_approve()
    elif result[0] == "always":
        on_always()
    else:
        on_deny()


def _popup_worker() -> None:
    """Worker thread: drain the popup queue one at a time."""
    while True:
        item = _popup_queue.get()
        if item is None:
            break
        request, on_approve, on_deny, on_always = item
        try:
            _show_one(request, on_approve, on_deny, on_always)
        except Exception as e:
            # If popup crashes, auto-deny
            on_deny()
        finally:
            _popup_queue.task_done()


def start_popup_worker() -> None:
    """Start the background thread that shows popups. Call once at startup."""
    global _popup_thread
    with _popup_thread_lock:
        if _popup_thread is None or not _popup_thread.is_alive():
            _popup_thread = threading.Thread(target=_popup_worker, daemon=True)
            _popup_thread.start()


def enqueue_request(request: dict) -> None:
    """Called by server callback when a new request arrives. Thread-safe."""
    import server as srv
    import config as cfg
    request_id = request["request_id"]
    config = cfg.load_config()
    request_with_config = dict(request)
    request_with_config["timeout_seconds"] = config.get("timeout_seconds", 60)

    def on_approve():
        srv.approve(request_id)

    def on_deny():
        srv.deny(request_id, "Denied via Pester")

    def on_always():
        tool_name = srv.always_allow(request_id)
        if tool_name:
            # Persist to config
            try:
                data = config
                if tool_name not in data.get("auto_approve", []):
                    data.setdefault("auto_approve", []).append(tool_name)
                    cfg.save_config(data)
            except Exception:
                pass

    _popup_queue.put((request_with_config, on_approve, on_deny, on_always))
