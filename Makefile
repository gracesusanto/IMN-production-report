.PHONY: build up shell logs

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
