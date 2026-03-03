.PHONY: build start login logs dev-build dev-start dev-login dev-logs test dev-test

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

# ======= Testing =======
# Run tests in production container
test:
	docker exec app python tests/run_tests.py

# Run tests in development container
dev-test:
	docker exec api_dev python tests/run_tests.py

# Run tests with coverage in development container
dev-test-coverage:
	docker exec api_dev python tests/run_tests.py -v

# Run specific test category in development container
dev-test-unit:
	docker exec api_dev python tests/run_tests.py unit

dev-test-integration:
	docker exec api_dev python tests/run_tests.py integration

# Run backfill validation script
dev-validate:
	docker exec api_dev python app/cmd/validate_reporting_pipeline.py

# Run CSV parity validation (feature flag ON vs OFF)
dev-validate-csv:
	docker exec -w /app -e PYTHONPATH=/app api_dev python app/cmd/validate_csv_parity.py

# Run CSV parity tests
dev-test-parity:
	docker exec api_dev python tests/run_tests.py parity

# Interactive login versions (for manual debugging)
dev-test-interactive:
	docker exec -it api_dev python tests/run_tests.py

dev-validate-interactive:
	docker exec -it api_dev python app/cmd/validate_reporting_pipeline.py
