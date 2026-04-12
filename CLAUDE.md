# Pester — CLAUDE.md

Windows-native Claude Code permission guardian. Python port of
[Claude Guardian](https://github.com/anshaneja5/Claude-Guardian) (macOS/Swift).

---

## Architecture

```
Claude Code (hook fires)
        │  stdin JSON
        ▼
  hooks/pre_tool_use.py        ──POST /request──►  pester.exe (localhost:9001)
  hooks/permission_request.py                      │
        │  GET /decision/{id}                      ├─ HTTP server thread (server.py)
        │  (polls, blocks)                         ├─ Popup worker thread (popup.py)
        ▼                                          ├─ System tray — main thread (tray.py)
  JSON decision → Claude Code                      └─ Analytics reader (analytics.py)
```

**Single process, three threads:**
- `main` → pystray tray icon (owns the Win32 message loop — must stay on main thread)
- `server` → `http.server` on localhost:9001 (daemon)
- `popup` → tkinter popup queue, one dialog at a time (daemon)

**Config:** `%APPDATA%\pester\pester.config.json` (user). Falls back to `pester.config.json`
next to `src/` (bundled default).

---

## File Layout

```
pester/
  src/
    pester.py             Entry point: wires server + popup + tray
    server.py             HTTP server, in-memory request store
    popup.py              tkinter approval dialog + queue
    tray.py               pystray tray icon + Stats/Config menu
    analytics.py          ~/.claude/ JSONL reader for cost/token stats
    config.py             load_config() / save_config() / get_config_path()
    hooks/
      pre_tool_use.py         Intercepts allowed tools (Claude's own allowlist path)
      permission_request.py   Intercepts tools requiring Claude Code's permission prompt
      session_lifecycle.py    SessionStart/SessionEnd → spawn/remove mascot
      notification.py         Forwards Claude notifications to tray bubble
      stop.py                 Fires when Claude finishes; launches pester if not running
  assets/
    icon.png              64×64 tray icon
  pester.config.json      Bundled default config
  setup.ps1               Installs hooks into ~/.claude/settings.json + startup reg key
  uninstall.ps1           Removes hooks + reg key; optionally deletes %APPDATA%\pester\
  build.bat               PyInstaller one-liner → dist/pester.exe
  requirements.txt
```

---

## HTTP API

| Endpoint | Method | Body | Response |
|---|---|---|---|
| `/health` | GET | — | `200 ok` |
| `/request` | POST | `{tool_name, tool_input, session_id, timestamp}` | `{request_id}` |
| `/decision/{id}` | GET | — | `{status, message}` |
| `/session` | POST | `{event, session_id, ...}` | `{ok: true}` |

**Decision statuses:** `pending` / `approved` / `denied` / `timeout` / `passthrough`

`passthrough` = mascot hidden; hook exits 0 with no output so Claude Code shows its own prompt.

---

## Hook Decision Logic

### `pre_tool_use.py`
Fires for **every** tool call. Only acts as a Pester gatekeeper when the tool is already
in Claude Code's own allow list (because `permission_request` will NOT fire for those).

Flow:
1. Send cost update if available
2. `notify_only` or `--dangerously-skip-permissions` → silent passthrough
3. Tool is in Claude Code's allow list?
   - No → only enforce `always_block`; let `permission_request` handle the popup
   - Yes → check `auto_approve`, `always_block`, then show Pester popup
4. Pester not running → fall through to Claude Code default

### `permission_request.py`
Fires when Claude Code would show its own Yes/No prompt (tool NOT in allowlist).

Flow:
1. Check `auto_approve` → silent allow
2. Check `always_block` → silent deny
3. Pester not running → fall through (Claude Code shows its own prompt)
4. Send request → poll for decision → return allow/deny/passthrough

### `session_lifecycle.py`
- `SessionStart` → send terminal PID + app name so pester can manage mascot per session
- `SessionEnd` → notify pester to remove mascot
- Skips entirely if `--dangerously-skip-permissions` detected (bypass mode)

### `stop.py`
- Fires when Claude finishes a response
- Launches pester if not running, waits up to 5s, then sends "Claude finished coding! ✓"
- Falls back to `ctypes.MessageBoxW` if pester fails to start

### `notification.py`
- Forwards Claude Code notification events to `/session`
- Skips `idle` type (already handled by `stop.py`)

---

## Config Schema

`%APPDATA%\pester\pester.config.json`

```json
{
  "port": 9001,
  "timeout_seconds": 60,
  "notify_only": false,
  "auto_deny_on_timeout": true,
  "auto_approve": ["Read", "Glob", "Grep", "LS"],
  "always_block": []
}
```

| Key | Type | Description |
|---|---|---|
| `port` | int | HTTP server port |
| `timeout_seconds` | int | Seconds before popup auto-resolves |
| `notify_only` | bool | Skip all permission prompts; pester is observer only |
| `auto_deny_on_timeout` | bool | `true` = deny on timeout; `false` = passthrough to Claude Code |
| `auto_approve` | list[str] | Tool names silently allowed without popup |
| `always_block` | list[str] | Tool names silently denied without popup |

**"Always Allow" button** in popup appends the tool name to `auto_approve` and saves config atomically.

---

## Popup UI

- Topmost tkinter window, bottom-right corner
- Shows: tool name, first meaningful arg (command/file_path/path/query/pattern), session ID prefix
- Countdown progress bar (decrements every second)
- Buttons + keyboard shortcuts:
  - Allow / `Y` / `Enter`
  - Always / `A` (persists to `auto_approve`)
  - Deny / `N` / `Escape`
- One popup at a time; extras queue in `_popup_queue`
- If popup crashes → auto-deny

---

## Tray Menu

Right-click the tray icon:
- **Stats** — today's cost/sessions/tokens + all-time totals (reads `~/.claude/projects/**/*.jsonl`, cached 60s)
- **Open Config** — `os.startfile` on `%APPDATA%\pester\pester.config.json`
- **Quit** — `icon.stop()` + `sys.exit(0)`

---

## Setup / Install

```powershell
# Install (from repo root)
powershell -ExecutionPolicy Bypass -File setup.ps1
```

`setup.ps1` does:
1. Checks Python 3.11+
2. `pip install -r requirements.txt`
3. Copies default config to `%APPDATA%\pester\` if not present
4. Writes hook commands into `~\.claude\settings.json` (merges, doesn't clobber)
5. Adds pester to `HKCU\...\Run` for startup
6. Launches pester if not already running

**Windows path fix:** Hook commands are written using Unix-style paths
(`/c/Users/...`) because Claude Code runs hooks via bash.

```powershell
# Uninstall
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

---

## Build (PyInstaller)

```bat
build.bat
```

Produces `dist/pester.exe` — single-file Windows executable, no Python required.
`stop.py` checks for `dist/pester.exe` first when auto-launching.

---

## Running from Source

```bash
python src/pester.py
```

Requires: `pystray`, `Pillow`, `psutil` (see `requirements.txt`). `tkinter` ships with Python on Windows.

Port conflict → process prints message and exits immediately (single-instance guard).

---

## Analytics

`analytics.py` reads `~/.claude/projects/**/*.jsonl`. Each line is a JSON record.
Extracts: `costUSD`/`cost_usd`, `usage.input_tokens`, `usage.output_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`, `timestamp`/`ts`, `model`.

Results cached for 60 seconds. Call `invalidate_cache()` to force reload.

---

## Key Conventions

- Config load always merges file over `DEFAULTS` (missing keys get defaults)
- Config save is atomic: write `.tmp` → `replace()`
- All hook scripts are standalone (no imports from `src/`) — they find config via `_find_config_path()` which checks `%APPDATA%\pester\` then bundled sibling
- Hooks exit `sys.exit(0)` with no output to pass through; print JSON to stdout to signal a decision
- If pester is not running, hooks always fall through cleanly — no hard dependency on the app being alive
