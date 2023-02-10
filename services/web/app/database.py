import logging
import os

import fastapi
import sqlalchemy
import sqlalchemy.orm

def get_engine() -> sqlalchemy.engine.Engine:
    logging.info("Connecting to %s", os.environ["DATABASE_URL"])
    return sqlalchemy.create_engine(os.environ["DATABASE_URL"])

SessionLocal = sqlalchemy.orm.sessionmaker(autocommit=False, autoflush=False)
_is_bound = False

# Helper function to get database session
def _get_session():
    global _is_bound  # pylint: disable=global-statement
    if not _is_bound:
        _is_bound = True
        SessionLocal.configure(bind=get_engine())
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


Sessioner = fastapi.Depends(_get_session)
