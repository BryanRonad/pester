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
    "auto_deny_on_timeout": True,
    "auto_approve": ["Read", "Glob", "Grep", "LS"],
    "always_block": [],
}

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
            return {**DEFAULTS, **data}
        except (json.JSONDecodeError, OSError):
            pass

    # Try bundled config
    bundled = get_bundled_config_path()
    if bundled.exists():
        try:
            with open(bundled, "r") as f:
                data = json.load(f)
            merged = {**DEFAULTS, **data}
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
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(config_path)

def get_server_url() -> str:
    config = load_config()
    port = config.get("port", 9001)
    return f"http://localhost:{port}"
