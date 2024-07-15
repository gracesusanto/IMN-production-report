import csv
import os
from datetime import datetime, timedelta
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
import app.database as database
from app.model.models import (
    Mesin,
    Tooling,
    Operator,
    MesinLog,
    ActivityMesin,
)  # Adjust the import path as needed
import json

# Create a session
session = sessionmaker(autocommit=False, autoflush=False, bind=database.get_engine())()

backup_folder = "backup/csv"
models = [Mesin, Tooling, Operator, MesinLog, ActivityMesin]


def ensure_folder_exists():
    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)

def dump_table_to_csv(model, filename):
    ensure_folder_exists()
    with open(filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter=";")
        records = session.query(model).all()
        if records:
            writer.writerow(records[0].__table__.columns.keys())  # column headers
            for record in records:
                # Add single quote to string columns
                row = []
                for column in record.__table__.columns:
                    value = getattr(record, column.name)
                    if isinstance(value, str):
                        value = f'="{value}"'
                    row.append(value)
                writer.writerow(row)
        print(f"Data dumped to {filename} for {model.__name__}.")

def backup_to_csv():
    ensure_folder_exists()
    for model in models:
        filename = f"{backup_folder}/{model.__name__}.csv"
        dump_table_to_csv(model, filename)
    print("Data dumped to CSV files successfully.")


def parse_datetime_or_none(value):
    if value is None or value == "":
        return None
    try:
        # Directly parse the ISO 8601 datetime string, including timezone
        return datetime.fromisoformat(value)
    except ValueError:
        # Return None or a default datetime if the format is not correct
        return None



def insert_from_csv(model, filename):
    with open(filename, "r") as csvfile:
        reader = csv.DictReader(csvfile, delimiter=";")
        for row in reader:
            # Remove leading single quote from string values
            for key, value in row.items():
                if isinstance(value, str) and value.startswith('="') and value.endswith('"'):
                    row[key] = value[2:-1]

            # Convert string timestamps to datetime objects, handling None
            row["time_created"] = parse_datetime_or_none(row.get("time_created"))
            row["time_updated"] = parse_datetime_or_none(row.get("time_updated"))

            # Retrieve the existing record, if any
            existing_record = session.query(model).filter_by(id=row["id"]).first()
            if existing_record:
                 # If there's an existing record, check which one is more recent
                existing_last_time = existing_record.time_updated or existing_record.time_created
                csv_last_time = row["time_updated"] or row["time_created"]
                if (csv_last_time and existing_last_time) and (csv_last_time > existing_last_time):
                    for key, value in row.items():
                        setattr(existing_record, key, value)
                    print(f"Updated record with ID {row['id']} from {filename} for {model.__name__}.")
                continue  # Skip to the next row if the database record is more recent or updated


            # If there's no existing record, insert new
            obj = model(**row)
            session.add(obj)

        try:
            session.commit()
            print(f"Data successfully inserted/updated from {filename}.")
        except IntegrityError as e:
            session.rollback()
            print(f"Error encountered. Rolling back changes. Error: {e}")


def backup_from_csv():
    ensure_folder_exists()
    for model in models:
        filename = f"{backup_folder}/{model.__name__}.csv"
        insert_from_csv(model, filename)
    print("Data inserted from CSV files successfully.")

def delete_old_data(model):
    expired_date = datetime.now() - timedelta(days=90)
    delete_query = session.query(model).filter(model.time_created < expired_date)
    deleted_count = delete_query.delete(synchronize_session=False)
    session.commit()
    print(f"Deleted {deleted_count} records of {model.__name__}.")
