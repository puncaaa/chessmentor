import os
from celery import Celery
from kombu import Queue
from app.core.config import settings

import socket

def is_redis_available(host="localhost", port=6379) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=0.3)
        sock.close()
        return True
    except Exception:
        return False

# Если Redis не задан или не запущен, для тестов поддерживается режим memory
custom_broker = os.getenv("CELERY_BROKER_URL")
if custom_broker:
    broker_url = custom_broker
    backend_url = os.getenv("CELERY_RESULT_BACKEND", custom_broker)
elif is_redis_available():
    broker_url = settings.REDIS_URL
    backend_url = settings.REDIS_URL
else:
    broker_url = "memory://"
    backend_url = "cache+memory://"

celery_app = Celery(
    "chess_tasks",
    broker=broker_url,
    backend=backend_url,
    include=["app.tasks.sync_tasks", "app.tasks.analysis_tasks"],
)

if broker_url.startswith("memory"):
    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )

# Очереди задач
celery_app.conf.task_queues = (
    Queue("sync", routing_key="sync.#"),
    Queue("engine", routing_key="engine.#"),
)

# Маршрутизация задач
celery_app.conf.task_routes = {
    "app.tasks.sync_tasks.*": {"queue": "sync"},
    "app.tasks.analysis_tasks.*": {"queue": "engine"},
}

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    
    # Защита CPU и ресурсов для воркеров Stockfish:
    worker_prefetch_multiplier=1,  # 1 задача на воркер
    task_acks_late=True,           # Подтверждение только после завершения
    task_time_limit=300,           # 5 минут жесткий таймаут на партию
    task_soft_time_limit=240,      # 4 минуты мягкий таймаут
)

# Расписание Celery Beat (Периодическая синхронизация)
celery_app.conf.beat_schedule = {
    "sync-active-students-every-2-hours": {
        "task": "app.tasks.sync_tasks.sync_all_active_students_task",
        "schedule": 7200.0,  # Каждые 2 часа (7200 секунд)
        "options": {"queue": "sync"},
    },
}
