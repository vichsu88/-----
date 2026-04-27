import logging
import os


logger = logging.getLogger(__name__)

try:
    from celery import Celery
except ImportError:  # pragma: no cover - depends on deployment extras
    Celery = None


def _env_enabled(name, default=True):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


broker_url = os.environ.get("CELERY_BROKER_URL") or os.environ.get("REDIS_URL")
result_backend = os.environ.get("CELERY_RESULT_BACKEND") or broker_url
celery_app = None

if Celery is not None and broker_url:
    celery_app = Celery(
        "chentien_temple",
        broker=broker_url,
        backend=result_backend,
        include=["utils.email"],
    )
    celery_app.conf.update(
        accept_content=["json"],
        task_serializer="json",
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_ignore_result=True,
    )
elif broker_url and Celery is None:
    logger.warning(
        "CELERY_BROKER_URL is configured but celery is not installed",
        extra={"event": "task_queue_missing_dependency"},
    )


def queue_available():
    return celery_app is not None and _env_enabled("ASYNC_TASK_QUEUE_ENABLED", True)
