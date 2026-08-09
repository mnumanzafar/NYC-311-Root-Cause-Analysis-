"""Load the raw extract into Postgres (raw.nyc311_requests)."""
from __future__ import annotations

import logging

import pandas as pd

from ..utils.config_loader import ROOT, load_config, setup_logging
from ..utils.db import execute_script, get_engine

log = logging.getLogger(__name__)
CHUNK = 50_000


def load(table: str = "nyc311_requests") -> int:
    cfg = load_config()
    schema = cfg["database"]["schema_raw"]
    execute_script(f"CREATE SCHEMA IF NOT EXISTS {schema};")

    df = pd.read_parquet(ROOT / "data" / "raw" / "nyc311_raw.parquet")
    df.to_sql(table, get_engine(), schema=schema, if_exists="replace",
              index=False, chunksize=CHUNK, method="multi")
    log.info("loaded %s rows into %s.%s", len(df), schema, table)
    return len(df)


if __name__ == "__main__":
    setup_logging()
    load()
