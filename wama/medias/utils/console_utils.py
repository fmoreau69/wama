from typing import List
from django.core.cache import cache

try:
    # Only available if django-redis is installed and cache is Redis
    from django_redis import get_redis_connection  # type: ignore
except Exception:  # pragma: no cover
    get_redis_connection = None  # type: ignore


def _redis():
    if get_redis_connection is None:
        return None
    try:
        return get_redis_connection("default")
    except Exception:
        return None


def _key(user_id: int) -> str:
    return f"console:{user_id}"


def push_console_line(user_id: int, line: str, maxlen: int = 500) -> None:
    """Append a log line to the user's console buffer."""
    r = _redis()
    if r is not None:
        try:
            r.lpush(_key(user_id), line)
            r.ltrim(_key(user_id), 0, maxlen - 1)
            return
        except Exception:
            pass

    # Fallback to Django cache (not atomic; best effort)
    key = _key(user_id)
    buf = cache.get(key) or []
    buf.insert(0, line)
    if len(buf) > maxlen:
        buf = buf[:maxlen]
    cache.set(key, buf, timeout=3600)


def get_console_lines(user_id: int, limit: int = 200) -> List[str]:
    r = _redis()
    if r is not None:
        try:
            items = r.lrange(_key(user_id), 0, limit - 1)
            # redis returns bytes
            return [i.decode("utf-8", errors="ignore") if isinstance(i, (bytes, bytearray)) else str(i) for i in items]
        except Exception:
            pass

    # Fallback
    key = _key(user_id)
    buf = cache.get(key) or []
    return buf[:limit]
