from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc
API_DATETIME_FORMAT = "%Y-%m-%d %H:%M"
API_DATE_FORMAT = "%Y-%m-%d"

try:
    TAIPEI_TZ = ZoneInfo("Asia/Taipei")
except ZoneInfoNotFoundError:
    TAIPEI_TZ = timezone(timedelta(hours=8), "Asia/Taipei")


def utc_now():
    """取得 UTC aware datetime；寫入 MongoDB 時一律使用這個時間基準。"""
    return datetime.now(UTC)


def ensure_aware_utc(value):
    """將 datetime 正規化為 UTC aware，legacy naive datetime 視為 UTC。"""
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_db_datetime(value=None):
    """轉成適合寫入 DB 的 UTC aware datetime；未傳入時回傳目前 UTC 時間。"""
    if value is None:
        return utc_now()
    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime instance")
    return ensure_aware_utc(value)


def to_taipei(value):
    """將 DB 取出的 UTC datetime 轉成台北時區 datetime。"""
    if value is None:
        return None
    aware = ensure_aware_utc(value)
    if not isinstance(aware, datetime):
        return aware
    return aware.astimezone(TAIPEI_TZ)


def format_for_api(value, fmt=API_DATETIME_FORMAT):
    """回傳給前端前統一轉成台北時間字串。"""
    if not value:
        return ""
    try:
        converted = to_taipei(value)
        if isinstance(converted, datetime):
            return converted.strftime(fmt)
    except Exception:
        pass
    return str(value)


def format_taipei(value, fmt=API_DATETIME_FORMAT):
    """向下相容既有呼叫；新程式可優先使用 format_for_api。"""
    return format_for_api(value, fmt)


def taipei_now():
    return utc_now().astimezone(TAIPEI_TZ)


def _parse_taipei_date(value, field_name="date"):
    """解析前端傳入的台北日期字串（YYYY-MM-DD）。"""
    if isinstance(value, datetime):
        return to_taipei(value).date()
    if isinstance(value, date):
        return value

    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    try:
        return datetime.strptime(text, API_DATE_FORMAT).date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def taipei_day_range_to_utc(value):
    """將單一天台北日期轉成 MongoDB 可查詢的 UTC 半開區間。"""
    day = _parse_taipei_date(value)
    start_local = datetime.combine(day, time.min, tzinfo=TAIPEI_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def taipei_date_range_to_utc(start_date, end_date=None):
    """將前端台北日期區間轉成 UTC aware range，end_date 以含當日計算。"""
    start_day = _parse_taipei_date(start_date, "start_date")
    end_day = _parse_taipei_date(end_date or start_date, "end_date")
    if end_day < start_day:
        raise ValueError("end_date must be greater than or equal to start_date")

    start_local = datetime.combine(start_day, time.min, tzinfo=TAIPEI_TZ)
    end_local = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=TAIPEI_TZ)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def taipei_date_range_query(start_date, end_date=None):
    """產生 MongoDB 日期查詢條件：前端台北日期輸入，DB 以 UTC 查詢。"""
    start_utc, end_utc = taipei_date_range_to_utc(start_date, end_date)
    return {"$gte": start_utc, "$lt": end_utc}
