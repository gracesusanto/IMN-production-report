from datetime import datetime, time

import pandas
import sqlalchemy as sa
from sqlalchemy.orm import aliased

import app.database as database
import app.model.models as models

engine = database.get_engine()
session = sa.orm.sessionmaker(autocommit=False, autoflush=False,
                                      bind=engine)()

def get_id_query(model):
    return session.query(model).with_entities(model.id).statement

def get_csv(model, category):
    query = get_id_query(model)
    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df.to_csv(f"data/IDs/{category}_ids.csv", index=False)

if __name__ == "__main__":
    get_csv(models.Tooling, "tooling")
    get_csv(models.Mesin, "mesin")
    get_csv(models.Operator, "operator")

