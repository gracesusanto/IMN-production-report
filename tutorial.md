# Tutorial

pip install fastapi fastapi-sqlalchemy pydantic alembic psycopg2 uvicorn python-dotenv

docker-compose run app alembic revision --autogenerate -m "dbinit"
docker-compose run app alembic upgrade head

docker-compose build
docker-compose up

docker-compose run app python3 db_ingestion.py
docker-compose run app python3 generate_report.py

docker exec -it app /bin/bash
cd app/cmd
python3 -m app.cmd.db_ingestion
python3 -m app.cmd.generate_report
python3 db_ingestion.py
python3 generate_report.py

### Cara Memasukan Database
1. Taruh data tooling di `data_all.csv` dengan format 
```['M/C','Tonase','Customer','Part No.','Part Name','Child Part Name','Kode Tooling','Common Tooling Name','Proses','STD Jam (Pcs)','Operator']```
1. Taruh data operator di `db_operator.csv` dan data mesin di `db_mesin.csv`



sa_enum_operator_status = sa.Enum(name="operator_status_enum")
    sa_enum_operator_status.drop(op.get_bind(), checkfirst=True)

    sa_enum_status = sa.Enum(name="status")
    sa_enum_status.drop(op.get_bind(), checkfirst=True)

    sa_enum_displayed_status = sa.Enum(name="displayed_status")
    sa_enum_displayed_status.drop(op.get_bind(), checkfirst=True)