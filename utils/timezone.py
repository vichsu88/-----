from datetime import datetime, timezone
from zoneinfo import ZoneInfo


UTC = timezone.utc
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def utc_now():
    """Return a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def ensure_aware_utc(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_taipei(value):
    if value is None:
        return None
    aware = ensure_aware_utc(value)
    if not isinstance(aware, datetime):
        return aware
    return aware.astimezone(TAIPEI_TZ)


def format_taipei(value, fmt="%Y-%m-%d %H:%M"):
    if not value:
        return ""
    try:
        converted = to_taipei(value)
        if isinstance(converted, datetime):
            return converted.strftime(fmt)
    except Exception:
        pass
    return str(value)


def taipei_now():
    return utc_now().astimezone(TAIPEI_TZ)
