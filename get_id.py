import os
import pandas
import sqlalchemy as sa

import database
import models

engine = database.get_engine()
session = sa.orm.sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def get_directory():
    directory = f"data/IDs/"
    if not os.path.exists(directory):
        os.makedirs(directory)
    return directory


def get_id_query(model):
    return session.query(model).with_entities(model.id).statement


def get_csv(model, category):
    query = get_id_query(model)
    df = pandas.read_sql(sql=query, con=engine)
    filepath = f"{get_directory()}/{category}_ids.csv"
    df.to_csv(filepath, index=False)


if __name__ == "__main__":
    get_csv(models.Tooling, "tooling")
    get_csv(models.Mesin, "mesin")
    get_csv(models.Operator, "operator")
