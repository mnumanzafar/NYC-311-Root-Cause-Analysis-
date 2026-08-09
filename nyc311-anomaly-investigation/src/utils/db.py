"""Postgres connection helpers (SQLAlchemy engine, reused across ETL and analysis)."""
from __future__ import annotations

import functools

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config_loader import env


def connection_url() -> str:
    return (
        f"postgresql+psycopg2://{env('PGUSER')}:{env('PGPASSWORD')}"
        f"@{env('PGHOST')}:{env('PGPORT', '5432')}/{env('PGDATABASE')}"
    )


@functools.lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(connection_url(), pool_pre_ping=True, future=True)


def read_sql(query: str, **params) -> pd.DataFrame:
    return pd.read_sql(text(query), get_engine(), params=params or None)


def execute_script(sql: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(sql))
