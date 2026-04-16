"""
Pester config loader/saver.
Config lives at %APPDATA%/pester/pester.config.json
"""
import json
import os
from pathlib import Path

DEFAULTS = {
    "port": 9001,
    "timeout_seconds": 60,
    "notify_only": False,
    "steal_focus": True,
    "timeout_behavior": "deny",
    "auto_approve": ["Read", "Glob", "Grep", "LS"],
    "always_block": [],
}


def normalize_timeout_behavior(data: dict | None) -> str:
    """Normalize timeout behavior, including legacy boolean config."""
    env_behavior = os.environ.get("PESTER_TIMEOUT_BEHAVIOR", "").strip().lower()
    if env_behavior in {"deny", "dismiss", "allow"}:
        return env_behavior

    if not isinstance(data, dict):
        return DEFAULTS["timeout_behavior"]

    behavior = data.get("timeout_behavior")
    if behavior in {"deny", "dismiss", "allow"}:
        return behavior

    legacy = data.get("auto_deny_on_timeout")
    if isinstance(legacy, bool):
        return "deny" if legacy else "dismiss"

    return DEFAULTS["timeout_behavior"]


def _merge_config(data: dict | None) -> dict:
    merged = {**DEFAULTS, **(data or {})}
    merged["timeout_behavior"] = normalize_timeout_behavior(data)
    merged.pop("auto_deny_on_timeout", None)
    return merged

def get_config_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "pester"

def get_config_path() -> Path:
    return get_config_dir() / "pester.config.json"

def get_bundled_config_path() -> Path:
    """Fallback: config bundled next to the src/ directory."""
    return Path(__file__).parent.parent / "pester.config.json"

def load_config() -> dict:
    """Load config, creating it from defaults if missing."""
    config_path = get_config_path()
    config_dir = get_config_dir()

    # Try user config first
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            return _merge_config(data)
        except (json.JSONDecodeError, OSError):
            pass

    # Try bundled config
    bundled = get_bundled_config_path()
    if bundled.exists():
        try:
            with open(bundled, "r") as f:
                data = json.load(f)
            merged = _merge_config(data)
            # Write to user location for next time
            config_dir.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w") as f:
                json.dump(merged, f, indent=2)
            return merged
        except (json.JSONDecodeError, OSError):
            pass

    # Create default config
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(DEFAULTS, f, indent=2)
    return dict(DEFAULTS)

def save_config(data: dict) -> None:
    """Atomically save config."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_suffix(".tmp")
    normalized = _merge_config(data)
    with open(tmp, "w") as f:
        json.dump(normalized, f, indent=2)
    tmp.replace(config_path)

def get_server_url() -> str:
    config = load_config()
    port = config.get("port", 9001)
    return f"http://localhost:{port}"
