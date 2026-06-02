import logging
import time

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging
from celery.signals import task_failure, task_postrun, task_prerun

from src.core.config import settings
from src.core.logging import setup_logging

logger = logging.getLogger("worker.celery")


# 1. Initialize Celery App
celery_app = Celery(
    "worker",
    broker=settings.RABBITMQ_URL,
    backend=settings.REDIS_URL,
    include=["src.worker.tasks"],
)

# 2. Celery Configurations
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        "cleanup-expired-tokens-every-6-hours": {
            "task": "tasks.cleanup_expired_tokens",
            "schedule": 21600.0,  # 6 hours in seconds
        },
    },
)


# 3. Route Celery logs to our custom colored masking logger
@celery_setup_logging.connect
def on_celery_setup_logging(**kwargs):
    setup_logging()
    logger.info("Celery logging configured with colored masking formatter.")


# 4. Task Metrics & Logging signals
task_start_times = {}


@task_prerun.connect
def task_prerun_handler(task_id, task, args, kwargs, **info):
    task_start_times[task_id] = time.perf_counter()
    logger.info(
        f"Celery Task Start | Task Name: {task.name} | Task ID: {task_id} | "
        f"Args: {args} | Kwargs: {kwargs}"
    )


@task_postrun.connect
def task_postrun_handler(task_id, task, args, kwargs, retval, state, **info):
    start_time = task_start_times.pop(task_id, None)
    duration = time.perf_counter() - start_time if start_time else 0.0
    logger.info(
        f"Celery Task End | Task Name: {task.name} | Task ID: {task_id} | "
        f"State: {state} | Duration: {duration:.4f}s | Result: {retval}"
    )


@task_failure.connect
def task_failure_handler(task_id, exception, args, kwargs, traceback, einfo, **info):
    start_time = task_start_times.pop(task_id, None)
    duration = time.perf_counter() - start_time if start_time else 0.0
    logger.error(
        f"Celery Task Failed | Task ID: {task_id} | Duration: {duration:.4f}s | "
        f"Exception: {str(exception)}"
    )
