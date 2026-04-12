# Pester — Implementation Plan

Windows-native Claude Code permission guardian. Python replacement for
[Claude Guardian](https://github.com/anshaneja5/Claude-Guardian) (macOS/Swift).
Reference clone is at `reference/`.

---

## Architecture Overview

```
Claude Code (hook fires)
        │  stdin JSON
        ▼
  hook/pre_tool_use.py  ──POST /request──►  pester.exe (localhost:9001)
  hook/permission_request.py               │
        │  GET /decision/{id}              ├─ HTTP server thread
        │  (polls, blocks)                 ├─ Approval popup (tkinter, topmost)
        ▼                                  ├─ System tray (pystray)
  JSON decision back                       └─ Analytics reader (~/.claude/)
```

**Single process, three threads:**
- `main` thread → pystray tray icon (owns the Win32 message loop)
- `server` thread → `http.server` on localhost:9001
- `popup` thread → tkinter `Toplevel` window per request (spawned on demand)

**Config:** `%APPDATA%\pester\pester.config.json`

---

## File Layout

```
pester/
  reference/              ← Claude Guardian clone (read-only reference)
  src/
    pester.py             ← Entry point: wires server + tray together
    server.py             ← HTTP server (request queue + decision store)
    popup.py              ← tkinter approval dialog
    tray.py               ← pystray tray icon + menu
    analytics.py          ← ~/.claude/ JSONL reader for stats
    config.py             ← Load/save pester.config.json
    hooks/
      pre_tool_use.py
      permission_request.py
      session_lifecycle.py
      notification.py
      stop.py
  assets/
    icon.png              ← 64×64 tray icon (created in Phase 1)
  pester.config.json      ← Default config (bundled)
  setup.ps1               ← Installs hooks + startup registration
  uninstall.ps1
  requirements.txt
  build.bat               ← PyInstaller one-liner
```

---

## Phase 0: Reference & API Research ✅ (done)

**Sources consulted:**
- `reference/hook/*.py` — all five hook scripts read in full
- `reference/app/ClaudeGuardian/Sources/main.swift` — HTTP server API surface
- `reference/guardian.config.json` — default config schema

**HTTP API contract (from Swift server + hooks):**

| Endpoint | Method | Body | Response |
|---|---|---|---|
| `/health` | GET | — | `200 OK` |
| `/request` | POST | `{tool_name, tool_input, session_id, timestamp}` | `{request_id}` |
| `/decision/{id}` | GET | — | `{status, message?}` |
| `/session` | POST | `{event, session_id, ...}` | `200 OK` |

**Decision statuses:** `pending` / `approved` / `denied` / `timeout` / `passthrough`

**Config schema:**
```json
{
  "port": 9001,
  "timeout_seconds": 300,
  "notify_only": false,
  "auto_approve": ["Read", "Glob", "Grep", "LS"],
  "always_block": []
}
```

**Windows-specific fixes needed vs reference:**
- `is_bypass_mode()`: replace `ps` with `psutil` process tree walk
- `find_terminal_info()`: replace `ps` with `psutil`; detect Windows Terminal, VS Code, etc.
- `stop.py`: replace `open -a ClaudeGuardian` with `subprocess.Popen(["pester.exe"])`
- Config path: `%APPDATA%\pester\` instead of `~/.config/claude-guardian/`
- Startup registration: `winreg` HKCU Run key instead of LaunchAgent plist

**Dependencies:**
```
pystray>=0.19.5       # system tray (uses win32api on Windows)
Pillow>=10.0.0        # image handling for tray icon
psutil>=5.9.0         # process tree inspection
pyinstaller>=6.0.0    # .exe bundling
```
tkinter ships with Python on Windows — no extra install.

---

## Phase 1: Scaffold + Config

**Goal:** Repo structure, config module, default assets.

### Tasks

1. Create directory structure (`src/`, `src/hooks/`, `assets/`)
2. Write `requirements.txt`
3. Write `src/config.py`:
   - `get_config_path()` → `Path(os.environ["APPDATA"]) / "pester" / "pester.config.json"`
   - `load_config()` → merges file over defaults, creates dir+file if missing
   - `save_config(data)` → atomic write
   - `get_server_url()` → `http://localhost:{port}`
4. Write `pester.config.json` (default, bundled next to `src/`)
5. Create `assets/icon.png` — simple 64×64 solid-color placeholder (drawn with Pillow in a `make_icon.py` helper, not shipped as binary)
6. Write `build.bat`:
   ```bat
   pyinstaller --onefile --windowed --icon=assets\icon.ico --name pester src\pester.py
   ```

### Verification
- `python -c "from src.config import load_config; print(load_config())"` prints defaults
- Config file created at `%APPDATA%\pester\pester.config.json`

---

## Phase 2: HTTP Server

**Goal:** `server.py` — the in-process HTTP server that hook scripts talk to.

### Tasks

1. Write `src/server.py` using `http.server.BaseHTTPRequestHandler`:
   - Module-level `requests: dict[str, dict]` — the in-memory request store
   - `POST /request` → generate UUID, store `{tool_name, tool_input, session_id, timestamp, status: "pending"}`, return `{request_id}`
   - `GET /decision/{id}` → return current status + message
   - `POST /session` → fire-and-forget; store session events for analytics; call registered `on_session_event` callback
   - `GET /health` → `200 OK`
   - `approve(request_id, message="")` / `deny(request_id, message)` / `always_allow(request_id)` — called by the popup
2. Run server in a daemon thread: `threading.Thread(target=server.serve_forever, daemon=True)`
3. Callback hook: `server.set_approval_callback(fn)` — called when a new `/request` arrives, receives the full request dict; used by `pester.py` to trigger popup

### Verification
- Start server, `curl http://localhost:9001/health` → 200
- `curl -X POST /request` with sample JSON → get back `request_id`
- `curl /decision/{id}` → `{"status": "pending"}`
- Call `approve(id)` → `curl /decision/{id}` → `{"status": "approved"}`

---

## Phase 3: Hook Scripts

**Goal:** Five hook scripts, Windows-compatible, matching the reference API.

**Reference files:** `reference/hook/*.py` (copy structure, replace platform calls)

### Tasks

1. Write `src/hooks/pre_tool_use.py`:
   - Copy logic from `reference/hook/pre_tool_use.py`
   - Replace `_find_config_path()`: check `%APPDATA%\pester\pester.config.json`, then bundled sibling
   - Replace `is_bypass_mode()`: use `psutil` to walk parent process cmdlines
   - Remove `is_claude_allowed()` initially (add back if needed — it reads Claude's own settings.json, which is cross-platform already)
   - Keep all HTTP polling logic unchanged (pure Python stdlib)

2. Write `src/hooks/permission_request.py`:
   - Same config path fix as above
   - Logic is otherwise identical to reference

3. Write `src/hooks/session_lifecycle.py`:
   - Replace `find_terminal_info()` using `psutil`:
     ```python
     KNOWN_TERMINALS = {"WindowsTerminal", "Code", "Cursor", "idea64", "pycharm64"}
     # walk psutil.Process(os.getpid()).parents()
     # match .name() against KNOWN_TERMINALS
     ```
   - Replace `is_bypass_mode()` with psutil version

4. Write `src/hooks/notification.py`:
   - Config path fix only — logic is platform-agnostic

5. Write `src/hooks/stop.py`:
   - Replace `launch_guardian()`: `subprocess.Popen(["pester.exe"])` (or path from config)
   - Replace `system_notification()`: use `ctypes` to call `MessageBox` as last-resort fallback, or `win10toast` if available

### Verification
- Echo sample hook JSON to each script, verify it exits cleanly
- With server running: echo PreToolUse JSON → script should block → call `approve` → script exits 0 with allow JSON
- Test auto_approve shortcut (Read tool → no prompt)
- Test always_block (deny immediate exit)

---

## Phase 4: Approval Popup + System Tray

**Goal:** The visible UI — what the user actually sees.

### Tasks

**`src/popup.py`**
1. `show_popup(request: dict, on_approve, on_deny, on_always_allow)`:
   - Creates a `tk.Toplevel` (or root if first window) set `attributes('-topmost', True)`
   - Layout:
     ```
     ┌─────────────────────────────┐
     │  🔔 Pester                  │
     │  Tool: Bash                 │
     │  command: npm run build     │
     │  Session: abc123            │
     │                             │
     │  [Allow ✓]  [Always ★]  [Deny ✗] │
     │                             │
     │  Auto-deny in: 60s ████░░  │
     └─────────────────────────────┘
     ```
   - Countdown timer using `after()` — updates label + progress bar
   - Keyboard bindings: `<Return>` / `y` → approve; `<Escape>` / `n` → deny; `a` → always allow
   - On decision: call callback, destroy window
   - Window positioned: bottom-right corner (like a toast), using `winfo_screenwidth()`
2. One popup at a time — queue subsequent requests; show next after current resolves

**`src/tray.py`**
1. `build_tray_icon(server)` using `pystray.Icon`:
   - Icon image: load from `assets/icon.png` via Pillow
   - Menu items:
     - `Status: Running` (disabled label)
     - `---`
     - `Stats` → open a `tk.Toplevel` with today's cost/token summary (from `analytics.py`)
     - `---`
     - `Open Config` → `os.startfile(config_path)`
     - `Quit` → `icon.stop()` + `sys.exit(0)`
2. Run `icon.run()` on main thread (required by pystray on Windows)

**`src/pester.py`** (entry point)
1. Check if already running (bind port; fail fast with message if occupied)
2. Start server thread
3. Register `server.set_approval_callback(popup.enqueue_request)`
4. Start tray (blocking — main thread)

### Verification
- Launch `python src/pester.py` → tray icon appears in system tray
- POST a request to `/request` → popup appears topmost
- Click Allow → `/decision/{id}` returns `approved`
- Click Deny → returns `denied`
- Press Y → approved; press Esc → denied
- Countdown reaches 0 → auto-denied
- Right-click tray → menu appears with Stats + Quit
- Quit → process exits cleanly

---

## Phase 5: Analytics

**Goal:** Read `~/.claude/` JSONL data and show a stats summary in the tray menu.

**Reference:** `reference/app/ClaudeGuardian/Sources/ClaudeAnalytics.swift` (read for field names)

### Tasks

1. Write `src/analytics.py`:
   - `find_usage_files()` → glob `~/.claude/projects/**/*.jsonl`
   - Parse each line as JSON, extract: `costUSD`, `model`, `usage.input_tokens`, `usage.output_tokens`, `timestamp`
   - `get_today_stats()` → filter by today's date, sum cost + tokens
   - `get_alltime_stats()` → lifetime totals
   - Cache results for 60s (avoid re-reading on every menu open)

2. Stats window (spawned from tray menu):
   - Simple `tk.Toplevel`, read-only labels
   - Today: cost, sessions, messages, tokens
   - All time: lifetime cost, active days, model breakdown

### Verification
- If `~/.claude/projects/` has JSONL files: stats show non-zero numbers
- If empty: shows zero gracefully
- Opening Stats twice reuses cached data

---

## Phase 6: Setup, Uninstall, Build

**Goal:** One-command install on a fresh Windows machine.

### Tasks

**`setup.ps1`**
1. Check Python 3.11+ installed
2. `pip install -r requirements.txt`
3. Install hooks into `~\.claude\settings.json`:
   ```json
   {
     "hooks": {
       "PreToolUse":       [{"hooks": [{"type": "command", "command": "python C:\\...\\pre_tool_use.py"}]}],
       "PermissionRequest":[{"hooks": [{"type": "command", "command": "python C:\\...\\permission_request.py"}]}],
       "SessionStart":     [{"hooks": [{"type": "command", "command": "python C:\\...\\session_lifecycle.py"}]}],
       "SessionEnd":       [{"hooks": [{"type": "command", "command": "python C:\\...\\session_lifecycle.py"}]}],
       "Notification":     [{"hooks": [{"type": "command", "command": "python C:\\...\\notification.py"}]}],
       "Stop":             [{"hooks": [{"type": "command", "command": "python C:\\...\\stop.py"}]}]
     }
   }
   ```
   Merge into existing file (don't clobber other settings).
4. Copy default config to `%APPDATA%\pester\pester.config.json` if not exists
5. Add `pester.exe` (or `python pester.py`) to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
6. Launch pester

**`uninstall.ps1`**
1. Kill running pester process
2. Remove hooks from `~\.claude\settings.json`
3. Remove Run registry key
4. Offer to delete `%APPDATA%\pester\`

**`build.bat`**
```bat
@echo off
pip install pyinstaller
pyinstaller --onefile --windowed --icon=assets\icon.ico --name pester --add-data "assets;assets" --add-data "pester.config.json;." src\pester.py
echo Built: dist\pester.exe
```

### Verification
- Run `setup.ps1` on clean machine → `claude` sessions now route through pester
- Run `uninstall.ps1` → hooks removed, tray gone
- `build.bat` → `dist/pester.exe` launches and shows tray icon without Python installed

---

## Phase 7: End-to-End Verification

1. Start `pester.exe` (or `python src/pester.py`)
2. Open Claude Code, run a command that triggers `Bash` tool
3. Approval popup appears above Claude Code window
4. Press Y → Claude Code proceeds
5. Press Esc → Claude Code receives deny with message
6. Trigger `Bash` twice with same command after clicking Always Allow → second time auto-approved, no popup
7. Check `%APPDATA%\pester\pester.config.json` → `Bash` added to `auto_approve`
8. Right-click tray → Stats → window shows token/cost data
9. Kill pester → Claude Code hooks fall through cleanly (no error, no hang)
10. Re-run `setup.ps1` → idempotent (no duplicate hook entries)

---

## Open Questions / Stretch Goals

- **Pixel art mascot**: Pillow-drawn sprite in the popup corner (like Guardian's cat/robot)
- **Per-session tracking**: show which session each popup belongs to
- **Dark mode**: detect Windows dark mode via registry and theme tkinter accordingly
- **Toast notifications**: use `windows-toasts` package for the Stop hook instead of MessageBox
- **Multi-monitor**: position popup on the monitor where Claude Code's window lives
