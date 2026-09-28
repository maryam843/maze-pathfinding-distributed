"""Celery application. Broker and result backend come from the environment.

    CELERY_BROKER_URL      default pyamqp://guest@localhost//  (RabbitMQ's local default user)
    CELERY_RESULT_BACKEND  default rpc://  (results come back over the broker)

Start a worker with:
    celery -A maze_runner.backends.celery_app worker -c 4 --loglevel=info
"""

from __future__ import annotations

import os

from celery import Celery

DEFAULT_BROKER_URL = "pyamqp://guest@localhost//"
BROKER_URL = os.environ.get("CELERY_BROKER_URL", DEFAULT_BROKER_URL)
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "rpc://")

# A task nobody picked up within this many seconds is dropped by the worker instead of running
# later for a client that already gave up (2025 bug B49).
TASK_EXPIRES_S = int(os.environ.get("MAZE_TASK_EXPIRES_S", "60"))

app = Celery(
    "maze_runner",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["maze_runner.backends.celery_tasks"],
)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    result_expires=3600,
)
