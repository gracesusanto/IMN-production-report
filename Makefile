.PHONY: build start login logs dev-build dev-start dev-login dev-logs

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
