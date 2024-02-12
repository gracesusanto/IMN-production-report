import csv
import os
from datetime import datetime
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
import app.database as database
from app.model.models import (
    Mesin,
    Tooling,
    Operator,
)  # Adjust the import path as needed
import json

# Create a session
session = sessionmaker(autocommit=False, autoflush=False, bind=database.get_engine())()

backup_folder = "data/db/backup"
models = [Mesin, Tooling, Operator]


def ensure_folder_exists(folder):
    if not os.path.exists(folder):
        os.makedirs(folder)


# Filename to store the last backup timestamps
last_backup_timestamps_file = "app/cmd/backup_csv/last_backup_timestamps.json"


def load_last_backup_timestamps():
    try:
        with open(last_backup_timestamps_file, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}


def save_last_backup_timestamp(model, timestamp):
    timestamps = load_last_backup_timestamps()
    timestamps[model.__name__] = timestamp
    with open(last_backup_timestamps_file, "w") as file:
        json.dump(timestamps, file)


def dump_table_to_csv(model, filename):
    last_backup_timestamps = load_last_backup_timestamps()
    model_name = model.__name__
    last_backup_timestamp = last_backup_timestamps.get(
        model_name, datetime.min.strftime("%Y-%m-%d %H:%M:%S.%f")
    )
    last_backup_datetime = datetime.strptime(
        last_backup_timestamp, "%Y-%m-%d %H:%M:%S.%f"
    )

    query = session.query(model).filter(
        sa.or_(
            model.time_created > last_backup_datetime,
            sa.and_(
                model.time_updated != None, model.time_updated > last_backup_datetime
            ),
        )
    )

    records = query.all()
    if records:
        mode = "a" if os.path.exists(filename) else "w"
        with open(filename, mode, newline="") as csvfile:
            writer = csv.writer(csvfile)
            if mode == "w":  # Write headers only if the file is being created
                writer.writerow(records[0].__table__.columns.keys())
            for record in records:
                writer.writerow(
                    [
                        getattr(record, column.name)
                        for column in record.__table__.columns
                    ]
                )

        latest_timestamp = max(
            [
                getattr(record, "time_updated") or getattr(record, "time_created")
                for record in records
            ]
        )
        save_last_backup_timestamp(
            model, latest_timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
        )
        print(f"Appended records to {filename} for {model_name}.")
    else:
        print(f"No new records to append for {model_name}.")


def backup_to_csv():
    ensure_folder_exists(backup_folder)
    for model in models:
        filename = f"{backup_folder}/{model.__name__}.csv"
        dump_table_to_csv(model, filename)
    print("Data dumped to CSV files successfully.")


def parse_datetime_or_none(value):
    try:
        # Directly parse the ISO 8601 datetime string, including timezone
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def insert_from_csv(model, filename):
    with open(filename, "r") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            # Convert string timestamps to datetime objects, handling None
            row["time_created"] = parse_datetime_or_none(row.get("time_created"))
            row["time_updated"] = parse_datetime_or_none(row.get("time_updated"))

            # Retrieve the existing record, if any
            existing_record = session.query(model).filter_by(id=row["id"]).first()
            if existing_record:
                # Determine which record is newer
                existing_updated_at = (
                    existing_record.time_updated or existing_record.time_created
                )
                file_updated_at = row["time_updated"] or row["time_created"]
                if existing_record.id == "MC-MEJAPACK-GRACE":
                    print(file_updated_at)

                if file_updated_at and file_updated_at > existing_updated_at:
                    print("FOUND ONE: " + existing_record.id)
                    # File record is newer; update existing database record
                    for key, value in row.items():
                        setattr(existing_record, key, value)
                    print(
                        f"Updated record with ID {row['id']} from file for {model.__name__}."
                    )
                # else:
                #     # Database record is newer; skip update
                #     print(
                #         f"Skipping update for ID {row['id']} as database record is newer for {model.__name__}."
                #     )
                continue

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
    ensure_folder_exists(backup_folder)
    for model in models:
        filename = f"{backup_folder}/{model.__name__}.csv"
        insert_from_csv(model, filename)
    print("Data inserted from CSV files successfully.")
