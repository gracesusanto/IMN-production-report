#!/bin/bash

# Start the cron service
service cron start

# Start your application
exec bash -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"