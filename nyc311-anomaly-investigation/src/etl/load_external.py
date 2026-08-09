"""Load external enrichment extracts into Postgres (raw.weather_daily, raw.holidays_daily)."""
from __future__ import annotations

import logging

import pandas as pd

from ..utils.config_loader import ROOT, load_config, setup_logging
from ..utils.db import execute_script, get_engine

log = logging.getLogger(__name__)

SOURCES = {
    "weather_daily": "weather_daily.parquet",
    "holidays_daily": "holidays_daily.parquet",
}


def load_external() -> dict[str, int]:
    cfg = load_config()
    schema = cfg["database"]["schema_raw"]
    execute_script(f"CREATE SCHEMA IF NOT EXISTS {schema};")

    counts = {}
    for table, filename in SOURCES.items():
        path = ROOT / "data" / "raw" / filename
        if not path.exists():
            raise FileNotFoundError(
                f"{path} missing — run `python -m src.etl.extract_external` first."
            )
        df = pd.read_parquet(path)
        df.to_sql(table, get_engine(), schema=schema, if_exists="replace",
                  index=False, chunksize=50_000, method="multi")
        counts[table] = len(df)
        log.info("loaded %s rows into %s.%s", len(df), schema, table)
    return counts


if __name__ == "__main__":
    setup_logging()
    load_external()
