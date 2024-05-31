#!/bin/bash

alembic upgrade head

# Start Nginx in the background
nginx -g 'daemon off;' &

# Start FastAPI using Gunicorn
exec gunicorn app.main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8080
