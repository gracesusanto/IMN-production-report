# Tutorial

pip install fastapi fastapi-sqlalchemy pydantic alembic psycopg2 uvicorn python-dotenv

docker-compose run app alembic revision --autogenerate -m "dbinit"
docker-compose run app alembic upgrade head

docker-compose build
docker-compose up

docker-compose run app python3 db_ingestion.py
docker-compose run app python3 generate_report.py

docker-compose -f docker-compose.prod.yml build
docker-compose -f docker-compose.prod.yml up

docker exec -it imn-production-app-prod /bin/bash
docker exec -it app /bin/bash
python3 db_ingestion.py

docker logs --follow app

docker-compose up --force-recreate

docker-compose rm -f
docker-compose pull
docker-compose up --build -d