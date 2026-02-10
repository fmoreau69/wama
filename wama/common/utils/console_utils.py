"""
WAMA Unified Console Logging

Structured log messages stored in Redis with level/app metadata.
Also written to logs/wama-console.log via RotatingFileHandler.

Usage:
    push_console_line(user_id, "Processing started", level='info', app='anonymizer')
    lines = get_console_lines(user_id, levels=['info', 'warning'], app='anonymizer')
"""

import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Optional

from django.conf import settings
from django.core.cache import cache

try:
    from django_redis import get_redis_connection  # type: ignore
except Exception:  # pragma: no cover
    get_redis_connection = None  # type: ignore

# ---------------------------------------------------------------------------
# File logger (RotatingFileHandler → logs/wama-console.log)
# ---------------------------------------------------------------------------
_file_logger = logging.getLogger("wama.console.file")
_file_logger.setLevel(logging.DEBUG)
_file_logger.propagate = False

_log_dir = Path(settings.BASE_DIR) / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_log_file = _log_dir / "wama-console.log"

if not _file_logger.handlers:
    _handler = RotatingFileHandler(
        str(_log_file), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _file_logger.addHandler(_handler)

# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

def _redis():
    if get_redis_connection is None:
        return None
    try:
        return get_redis_connection("default")
    except Exception:
        return None


def _key(user_id: int) -> str:
    return f"console:{user_id}"


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------

def push_console_line(
    user_id: int,
    line: str,
    level: str = "info",
    app: str = "system",
    maxlen: int = 500,
) -> None:
    """
    Append a structured log line to the user's console buffer.

    Args:
        user_id: Target user
        line: Log message text
        level: 'info' | 'warning' | 'error' | 'debug'
        app: Application name (anonymizer, imager, enhancer, ...)
        maxlen: Max buffer size in Redis
    """
    ts = datetime.now().strftime("%H:%M:%S")
    entry = json.dumps(
        {"ts": ts, "level": level, "app": app, "msg": line},
        ensure_ascii=False,
    )

    # Write to Redis
    r = _redis()
    if r is not None:
        try:
            r.lpush(_key(user_id), entry)
            r.ltrim(_key(user_id), 0, maxlen - 1)
        except Exception:
            # Fallback below
            r = None

    if r is None:
        # Fallback to Django cache
        key = _key(user_id)
        buf = cache.get(key) or []
        buf.insert(0, entry)
        if len(buf) > maxlen:
            buf = buf[:maxlen]
        cache.set(key, buf, timeout=3600)

    # Write to file log
    full_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _file_logger.info(
        "%s [%s] [%s] user=%s %s",
        full_ts, level.upper(), app, user_id, line,
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_console_lines(
    user_id: int,
    levels: Optional[List[str]] = None,
    app: Optional[str] = None,
    limit: int = 200,
) -> List[dict]:
    """
    Retrieve structured console lines for a user.

    Args:
        user_id: Target user
        levels: Filter by log levels (e.g. ['info', 'warning']). None = all.
        app: Filter by app name. None or 'all' = no filter.
        limit: Max lines to return

    Returns:
        List of dicts: [{"ts": "14:32:05", "level": "info", "app": "anonymizer", "msg": "..."}]
    """
    raw_lines = _get_raw_lines(user_id, limit=limit * 2)  # over-fetch to allow filtering

    result = []
    for raw in raw_lines:
        entry = _parse_line(raw)

        # Filter by level
        if levels and entry["level"] not in levels:
            continue

        # Filter by app
        if app and app != "all" and entry["app"] != app:
            continue

        result.append(entry)
        if len(result) >= limit:
            break

    # Redis returns newest-first; reverse to chronological order (oldest first)
    result.reverse()
    return result


def _get_raw_lines(user_id: int, limit: int = 400) -> List[str]:
    """Retrieve raw string lines from Redis or cache."""
    r = _redis()
    if r is not None:
        try:
            items = r.lrange(_key(user_id), 0, limit - 1)
            return [
                i.decode("utf-8", errors="ignore")
                if isinstance(i, (bytes, bytearray))
                else str(i)
                for i in items
            ]
        except Exception:
            pass

    key = _key(user_id)
    buf = cache.get(key) or []
    return buf[:limit]


def _parse_line(raw: str) -> dict:
    """
    Parse a raw line into a structured dict.
    Handles both new JSON format and legacy plain-text format.
    """
    try:
        entry = json.loads(raw)
        if isinstance(entry, dict) and "msg" in entry:
            return {
                "ts": entry.get("ts", ""),
                "level": entry.get("level", "info"),
                "app": entry.get("app", "system"),
                "msg": entry.get("msg", ""),
            }
    except (json.JSONDecodeError, TypeError):
        pass

    # Legacy plain-text line → treat as info/system
    return {
        "ts": "",
        "level": "info",
        "app": "system",
        "msg": raw,
    }
