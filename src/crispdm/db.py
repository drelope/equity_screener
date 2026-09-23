import pandas as pd
from sqlalchemy import create_engine, text
from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)

def execute(sql, params=None):
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {})

def read_df(sql, params=None):
    return pd.read_sql(text(sql), engine, params=params or {})
