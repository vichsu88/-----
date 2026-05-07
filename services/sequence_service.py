import logging

from pymongo.errors import DuplicateKeyError

from repositories.sequence_repository import next_counter_value
from utils.timezone import taipei_now


logger = logging.getLogger(__name__)
DEFAULT_RETRY_ATTEMPTS = 5
SEQUENCE_WIDTH = 6

ORDER_PREFIXES = {
    "shop": "ORD",
    "donation": "DON",
    "fund": "FND",
    "committee": "COM",
}


def _date_part():
    return taipei_now().strftime("%Y%m%d")


def _build_sequence_id(scope, prefix):
    date_part = _date_part()
    counter_key = f"{scope}:{prefix}:{date_part}"
    sequence = next_counter_value(
        counter_key,
        {
            "scope": scope,
            "prefix": prefix,
            "date": date_part,
        },
    )
    return f"{prefix}{date_part}{sequence:0{SEQUENCE_WIDTH}d}"


def generate_order_id(order_type):
    prefix = ORDER_PREFIXES.get(order_type, "ORD")
    return _build_sequence_id("orders", prefix)


def generate_feedback_id():
    return _build_sequence_id("feedback", "FB")


def write_with_unique_id_retry(generate_identifier, write_operation, *, label, max_attempts=DEFAULT_RETRY_ATTEMPTS):
    """遇到唯一索引碰撞時重新取號，避免高併發下因單號重複直接失敗。"""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        identifier = generate_identifier()
        try:
            return identifier, write_operation(identifier)
        except DuplicateKeyError as exc:
            last_error = exc
            logger.warning(
                "Duplicate generated identifier, retrying",
                extra={
                    "event": "mongodb_generated_id_duplicate",
                    "label": label,
                    "identifier": identifier,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                },
            )
    raise last_error
