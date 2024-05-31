# Stage 1: Build the FastAPI application
FROM python:3.11-slim as builder

WORKDIR /usr/src/app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev build-essential postgresql-client

# Upgrade pip and install Python dependencies including Alembic
COPY ./services/web/requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt --target=/usr/src/app/dependencies

# Copy application code
COPY ./services/web/ .

# Stage 2: Setup Nginx and FastAPI
FROM tiangolo/uvicorn-gunicorn-fastapi:python3.11-slim

# Install Nginx
RUN apt-get update && apt-get install -y nginx libpq5 && \
    if [ -f /etc/nginx/conf.d/default.conf ]; then rm /etc/nginx/conf.d/default.conf; fi

# Setup environment for the application
WORKDIR /home/app

# Copy built Python dependencies
COPY --from=builder /usr/src/app/dependencies /usr/local/lib/python3.11/site-packages
# Ensure the Python environment recognizes these packages
ENV PYTHONPATH=/usr/local/lib/python3.11/site-packages

# Copy application code
COPY --from=builder /usr/src/app /home/app

COPY ./services/nginx/nginx.conf /etc/nginx/nginx.conf

# Configure Nginx to forward requests to FastAPI
COPY ./services/nginx/nginx.conf /etc/nginx/nginx.conf

# Expose the port Nginx is listening on
EXPOSE 80

# Start Nginx and FastAPI using a custom script
COPY ./start.sh /home/app/start.sh
CMD ["/home/app/start.sh"]
