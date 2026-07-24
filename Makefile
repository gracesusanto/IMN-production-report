.PHONY: build start login logs dev-build dev-start dev-login dev-logs \
        migrate dev-migrate db-revision dev-db-revision db-history dev-db-history db-downgrade dev-db-downgrade

# Build the Docker containers using docker-compose
build:
	docker-compose build

# Start the Docker containers using docker-compose
start:
	docker-compose up -d

# Open a shell inside the 'app' container
login:
	docker exec -it app /bin/bash

# Follow the logs of the 'app' container
logs:
	docker logs --follow app

# ======= Development Environment =======
# Build the development Docker containers using docker-compose.dev.yml
dev-build:
	docker-compose -f docker-compose.dev.yml build

# Start the development Docker containers using docker-compose.dev.yml
dev-start:
	docker-compose -f docker-compose.dev.yml up -d

dev-up:
	docker-compose -f docker-compose.dev.yml up --build -d

# Open a shell inside the 'api_dev' container
dev-login:
	docker exec -it api_dev /bin/bash

# Follow the logs of the 'api_dev' container
dev-logs:
	docker logs --follow api_dev

# Stop all containers
stop:
	docker-compose down
	docker-compose -f docker-compose.dev.yml down

# Restart all containers
restart: stop start

# Restart only development containers
dev-restart: stop dev-start

# Run tests in development environment
dev-test:
	docker exec api_dev bash -c "cd /app && python -m pytest -v"

# Run tests (alias for dev-test)
test: dev-test

# ======= Alembic / Database Migrations =======
# Apply all pending migrations (production container)
migrate:
	docker exec app bash -c "cd /app && alembic upgrade head"

# Apply all pending migrations (dev container)
dev-migrate:
	docker exec api_dev bash -c "cd /app && alembic upgrade head"

# Create a new migration revision — usage: make db-revision MSG="describe change"
db-revision:
	docker exec app bash -c "cd /app && alembic revision --autogenerate -m '$(MSG)'"

dev-db-revision:
	docker exec api_dev bash -c "cd /app && alembic revision --autogenerate -m '$(MSG)'"

# Show migration history
db-history:
	docker exec app bash -c "cd /app && alembic history --verbose"

dev-db-history:
	docker exec api_dev bash -c "cd /app && alembic history --verbose"

# Show current migration head
db-current:
	docker exec app bash -c "cd /app && alembic current"

dev-db-current:
	docker exec api_dev bash -c "cd /app && alembic current"

# Downgrade one revision — usage: make db-downgrade (steps down by 1)
db-downgrade:
	docker exec app bash -c "cd /app && alembic downgrade -1"

dev-db-downgrade:
	docker exec api_dev bash -c "cd /app && alembic downgrade -1"
