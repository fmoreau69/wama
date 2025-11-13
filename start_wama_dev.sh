#!/bin/bash
cd /mnt/d/WAMA/web-app-for-media-automation
source venv_linux/bin/activate

# Redis
redis-server > logs/redis.log 2>&1 &

# Celery worker
celery -A wama worker -l info -P solo > logs/celery_worker.log 2>&1 &

# Celery beat
celery -A wama beat -l info > logs/celery_beat.log 2>&1 &

# Django (en foreground)
python manage.py runserver 0.0.0.0:8000
