# Tutorial

pip install fastapi fastapi-sqlalchemy pydantic alembic psycopg2 uvicorn python-dotenv

docker-compose run app alembic revision --autogenerate -m "dbinit"
docker-compose run app alembic upgrade head

docker-compose build
docker-compose up

docker-compose run app python3 db_ingestion.py
docker-compose run app python3 generate_report.py

docker exec -it app /bin/bash
python3 db_ingestion.py