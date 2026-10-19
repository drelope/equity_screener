import atexit

import pandas as pd
from sqlalchemy import create_engine, text

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)

# Close pooled connections before interpreter shutdown: otherwise the raw psycopg
# connections are garbage-collected while still open and psycopg emits a
# ResourceWarning ("deleted while still open").
atexit.register(engine.dispose)


def execute(sql, params=None):
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {})


def read_df(sql, params=None):
    return pd.read_sql(text(sql), engine, params=params or {})
