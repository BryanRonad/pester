"""
Pester approval popup.
Shows a topmost tkinter window for each pending tool approval request.
One popup at a time — subsequent requests are queued.
"""

import queue
import threading
import tkinter as tk
from typing import Callable


_popup_queue: queue.Queue = queue.Queue()
_popup_thread: threading.Thread | None = None
_popup_thread_lock = threading.Lock()
_last_position: tuple[int, int] | None = None


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


def _show_one(request: dict, on_approve: Callable, on_deny: Callable, on_always: Callable, on_passthrough: Callable) -> None:
    """Show a single popup and block until the user decides."""
    result = [None]

    root = tk.Tk()
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.overrideredirect(True)
    root.configure(bg="#1e1e1e")

    # --- Layout ---
    FONT_BODY = ("Segoe UI", 9)
    FONT_SMALL = ("Segoe UI", 8)
    FONT_CAPTION = ("Segoe UI", 9)
    BG = "#1e1e1e"
    PANEL = "#252526"
    FG = "#ffffff"
    TRACK = "#3a3d41"
    FILL = "#22c55e"
    GREEN = "#4ade80"
    RED = "#f87171"
    YELLOW = "#fbbf24"

    shell = tk.Frame(root, bg=PANEL, highlightbackground="#3a3d41", highlightthickness=1)
    shell.pack(fill="both", expand=True)

    title_bar = tk.Frame(shell, bg=PANEL, padx=10, pady=8)
    title_bar.pack(fill="x")

    tk.Label(title_bar, text="Pester", font=FONT_CAPTION, bg=PANEL, fg=FG, anchor="w").pack(side="left")

    def close_popup(_event=None):
        do_deny()

    close_button = tk.Label(title_bar, text="x", font=FONT_CAPTION, bg=PANEL, fg="#cfcfcf", padx=6, pady=0, cursor="hand2")
    close_button.pack(side="right")

    body = tk.Frame(shell, bg=BG, padx=14, pady=10)
    body.pack(fill="both")

    tool_name = request.get("tool_name", "Unknown")
    session_id = request.get("session_id", "")
    detail = _format_tool_input(request.get("tool_input", {}))

    tk.Label(body, text=f"Tool:  {tool_name}", font=FONT_BODY, bg=BG, fg=FG, anchor="w").pack(fill="x")
    if detail:
        tk.Label(body, text=f"Args:  {detail}", font=FONT_BODY, bg=BG, fg="#aaaaaa", anchor="w",
                 wraplength=340, justify="left").pack(fill="x", pady=(2, 0))
    tk.Label(body, text=f"Session: {session_id}", font=FONT_SMALL, bg=BG, fg="#666666", anchor="w").pack(fill="x", pady=(4, 0))

    # Countdown bar
    timeout = max(1, int(request.get("timeout_seconds", 60) or 60))
    steal_focus = bool(request.get("steal_focus", True))
    timeout_behavior = request.get("timeout_behavior", "deny")
    countdown_prefix = {
        "deny": "Auto-deny",
        "dismiss": "Auto-dismiss",
        "allow": "Auto-allow",
    }.get(timeout_behavior, "Auto-deny")
    countdown_label = f"{countdown_prefix} in {timeout}s"
    countdown_var = tk.StringVar(value=countdown_label)
    tk.Label(body, textvariable=countdown_var, font=FONT_SMALL, bg=BG, fg="#888888", anchor="w").pack(fill="x", pady=(6, 2))
    progress_width = 340
    progress_height = 18
    progress = tk.Canvas(
        body,
        width=progress_width,
        height=progress_height,
        bg=BG,
        highlightthickness=0,
        bd=0,
    )
    progress.pack(fill="x")
    progress.create_rectangle(
        0,
        0,
        progress_width,
        progress_height,
        fill=TRACK,
        outline="",
    )
    progress_fill = progress.create_rectangle(
        0,
        0,
        progress_width,
        progress_height,
        fill=FILL,
        outline="",
    )

    # Buttons
    btn_frame = tk.Frame(shell, bg=BG, padx=14, pady=10)
    btn_frame.pack(fill="x")

    def do_approve():
        result[0] = "approve"
        root.destroy()

    def do_always():
        result[0] = "always"
        root.destroy()

    def do_deny():
        result[0] = "deny"
        root.destroy()

    close_button.bind("<Button-1>", close_popup)
    close_button.bind("<Enter>", lambda e: close_button.configure(bg="#3a3d41"))
    close_button.bind("<Leave>", lambda e: close_button.configure(bg=PANEL))

    drag_origin = {"x": 0, "y": 0}

    def start_drag(event):
        drag_origin["x"] = event.x_root - root.winfo_x()
        drag_origin["y"] = event.y_root - root.winfo_y()

    def drag_window(event):
        global _last_position
        x = event.x_root - drag_origin["x"]
        y = event.y_root - drag_origin["y"]
        _last_position = (x, y)
        root.geometry(f"+{x}+{y}")

    title_bar.bind("<ButtonPress-1>", start_drag)
    title_bar.bind("<B1-Motion>", drag_window)

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

    # Position: restore last position, or default to bottom-right
    root.update_idletasks()
    if _last_position is not None:
        root.geometry(f"+{_last_position[0]}+{_last_position[1]}")
    else:
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
        fill_width = int(progress_width * (remaining[0] / timeout))
        progress.coords(progress_fill, 0, 0, fill_width, progress_height)
        label = f"{countdown_prefix} in {remaining[0]}s"
        countdown_var.set(label)
        if remaining[0] <= 0:
            if timeout_behavior == "allow":
                do_approve()
            elif timeout_behavior == "dismiss":
                # passthrough — close without a decision so the hook falls back to Claude Code
                result[0] = "passthrough"
                root.destroy()
            else:
                do_deny()
        else:
            root.after(1000, tick)

    root.after(1000, tick)
    if steal_focus:
        root.focus_force()
    root.mainloop()

    # Dispatch result
    if result[0] == "approve":
        on_approve()
    elif result[0] == "always":
        on_always()
    elif result[0] == "passthrough":
        on_passthrough()
    else:
        on_deny()


def _popup_worker() -> None:
    """Worker thread: drain the popup queue one at a time."""
    while True:
        item = _popup_queue.get()
        if item is None:
            break
        request, on_approve, on_deny, on_always, on_passthrough = item
        try:
            _show_one(request, on_approve, on_deny, on_always, on_passthrough)
        except Exception:
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
    request_with_config["steal_focus"] = config.get("steal_focus", True)
    request_with_config["timeout_behavior"] = config.get("timeout_behavior", "deny")

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

    def on_passthrough():
        with srv._requests_lock:
            if request_id in srv._requests:
                srv._requests[request_id]["status"] = "passthrough"

    _popup_queue.put((request_with_config, on_approve, on_deny, on_always, on_passthrough))
