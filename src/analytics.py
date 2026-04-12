"""
Pester analytics.
Reads ~/.claude/projects/**/*.jsonl to compute token/cost stats.
Results cached for 60 seconds to avoid re-reading on every menu open.
"""

import glob
import json
import os
import time
from datetime import date, datetime
from pathlib import Path

_cache: dict = {}
_cache_time: float = 0.0
_CACHE_TTL = 60.0

# Pricing per token (USD). Covers known Claude model families.
# Cache read is cheap; cache creation costs ~25% more than input.
_MODEL_PRICING = {
    # claude-sonnet-4-x
    "claude-sonnet-4":  {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    # claude-opus-4-x
    "claude-opus-4":    {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    # claude-haiku-4-x / 3-5
    "claude-haiku":     {"input": 0.80, "output": 4.0,  "cache_write": 1.0,   "cache_read": 0.08},
    # claude-3-5-sonnet
    "claude-3-5-sonnet":{"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    # claude-3-opus
    "claude-3-opus":    {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
}
_DEFAULT_PRICING = {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30}


def _get_pricing(model: str) -> dict:
    for prefix, pricing in _MODEL_PRICING.items():
        if model.startswith(prefix):
            return pricing
    return _DEFAULT_PRICING


def _find_jsonl_files() -> list[str]:
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return []
    return glob.glob(str(claude_dir / "**" / "*.jsonl"), recursive=True)


def _parse_entry(line: str) -> dict | None:
    """Parse one JSONL line. Return None if not a usable assistant message."""
    try:
        data = json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return None

    # Only care about entries that have a nested assistant message with usage
    msg = data.get("message")
    if not isinstance(msg, dict):
        return None
    if msg.get("role") != "assistant":
        return None
    if not isinstance(msg.get("usage"), dict):
        return None

    return data


def _load_all() -> list[dict]:
    """Read, parse, and deduplicate all JSONL entries by message ID."""
    seen_ids: set[str] = set()
    entries = []
    for filepath in _find_jsonl_files():
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    entry = _parse_entry(line)
                    if entry is None:
                        continue
                    msg_id = entry.get("message", {}).get("id", "")
                    if msg_id and msg_id in seen_ids:
                        continue
                    if msg_id:
                        seen_ids.add(msg_id)
                    entries.append(entry)
        except OSError:
            pass
    return entries


def _get_all_cached() -> list[dict]:
    global _cache, _cache_time
    now = time.time()
    if now - _cache_time < _CACHE_TTL and _cache:
        return _cache.get("entries", [])
    entries = _load_all()
    _cache = {"entries": entries}
    _cache_time = now
    return entries


def _extract_tokens(entry: dict) -> tuple[int, int, int, int]:
    """Return (input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens)."""
    usage = entry.get("message", {}).get("usage", {})
    inp = int(usage.get("input_tokens", 0) or 0)
    out = int(usage.get("output_tokens", 0) or 0)
    cache_create = int(usage.get("cache_creation_input_tokens", 0) or 0)
    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
    return inp, out, cache_create, cache_read


def _extract_cost(entry: dict) -> float:
    """Calculate cost from token counts × model pricing."""
    model = entry.get("message", {}).get("model", "")
    pricing = _get_pricing(model)
    inp, out, cc, cr = _extract_tokens(entry)
    cost = (
        inp * pricing["input"] +
        out * pricing["output"] +
        cc  * pricing["cache_write"] +
        cr  * pricing["cache_read"]
    ) / 1_000_000
    return cost


def _extract_timestamp(entry: dict) -> datetime | None:
    ts = entry.get("timestamp") or entry.get("ts")
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts)
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None


def _extract_model(entry: dict) -> str:
    return entry.get("message", {}).get("model", "") or ""


def get_today_stats() -> dict:
    today = date.today()
    entries = _get_all_cached()

    cost = 0.0
    input_tokens = 0
    output_tokens = 0
    cache_creation_tokens = 0
    cache_read_tokens = 0
    messages = 0
    sessions: set = set()

    for entry in entries:
        ts = _extract_timestamp(entry)
        if ts is None or ts.date() != today:
            continue
        cost += _extract_cost(entry)
        i, o, cc, cr = _extract_tokens(entry)
        input_tokens += i
        output_tokens += o
        cache_creation_tokens += cc
        cache_read_tokens += cr
        messages += 1
        sid = entry.get("sessionId") or entry.get("session_id")
        if sid:
            sessions.add(sid)

    return {
        "cost_usd": round(cost, 4),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
        "total_tokens": input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens,
        "messages": messages,
        "sessions": len(sessions),
    }


def get_alltime_stats() -> dict:
    entries = _get_all_cached()

    cost = 0.0
    input_tokens = 0
    output_tokens = 0
    cache_creation_tokens = 0
    cache_read_tokens = 0
    active_days: set = set()
    models: dict[str, int] = {}

    for entry in entries:
        cost += _extract_cost(entry)
        i, o, cc, cr = _extract_tokens(entry)
        input_tokens += i
        output_tokens += o
        cache_creation_tokens += cc
        cache_read_tokens += cr
        ts = _extract_timestamp(entry)
        if ts:
            active_days.add(ts.date())
        model = _extract_model(entry)
        if model:
            models[model] = models.get(model, 0) + 1

    return {
        "cost_usd": round(cost, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
        "total_tokens": input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens,
        "active_days": len(active_days),
        "models": models,
    }


def invalidate_cache() -> None:
    """Force next call to re-read all files (e.g. after a file-system change)."""
    global _cache, _cache_time
    _cache = {}
    _cache_time = 0.0
