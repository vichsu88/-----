from dotenv import load_dotenv

load_dotenv()

from utils.task_queue import celery_app  # noqa: E402

if celery_app is None:
    raise RuntimeError("Set CELERY_BROKER_URL or REDIS_URL before starting a Celery worker.")
