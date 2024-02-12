import csv
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
import app.database as database
from app.model.models import (
    Mesin,
    Tooling,
    Operator,
)  # Adjust the import path as needed

# Create a session
session = sessionmaker(autocommit=False, autoflush=False, bind=database.get_engine())()

models = [Mesin, Tooling, Operator]


def dump_table_to_csv(model, filename):
    with open(filename, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        records = session.query(model).all()
        if records:
            writer.writerow(records[0].__table__.columns.keys())
            for record in records:
                writer.writerow(
                    [
                        getattr(record, column.name)
                        for column in record.__table__.columns
                    ]
                )


def backup_to_csv():
    for model in models:
        filename = f"data/db/backup/{model.__name__}.csv"
        dump_table_to_csv(model, filename)
    print("Data dumped to CSV files successfully.")


def insert_from_csv(model, filename):
    with open(filename, "r") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            for timestamp_field in ["time_created", "time_updated"]:
                if timestamp_field in row and row[timestamp_field] == "":
                    row[timestamp_field] = None
            obj = model(**row)
            try:
                session.add(obj)
                session.commit()
            except IntegrityError:
                session.rollback()
                print(f"Duplicate found and skipped: {row}")


def backup_from_csv():
    for model in models:
        filename = f"data/db/backup/{model.__name__}.csv"
        insert_from_csv(model, filename)
    print("Data inserted from CSV files successfully.")
