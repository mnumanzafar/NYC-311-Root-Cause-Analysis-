"""Pull NYC 311 Service Requests from the Socrata API into data/raw/."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import requests

from ..utils.config_loader import ROOT, load_config, setup_logging

log = logging.getLogger(__name__)

FIELDS = [
    "unique_key", "created_date", "closed_date", "agency", "complaint_type",
    "descriptor", "borough", "incident_zip", "status", "open_data_channel_type",
    "latitude", "longitude",
]


def fetch_page(domain: str, dataset: str, limit: int, offset: int,
               where: str, token: str | None = None) -> list[dict]:
    resp = requests.get(
        f"https://{domain}/resource/{dataset}.json",
        params={"$select": ",".join(FIELDS), "$where": where,
                "$limit": limit, "$offset": offset, "$order": "created_date"},
        headers={"X-App-Token": token} if token else {},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def extract(out_path: Path | None = None) -> Path:
    cfg = load_config()
    src, an = cfg["source"], cfg["analysis"]
    where = (f"created_date >= '{an['date_start']}T00:00:00' "
             f"AND created_date < '{an['date_end']}T00:00:00'")
    out_path = out_path or ROOT / "data" / "raw" / "nyc311_raw.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    frames, offset = [], 0
    while True:
        rows = fetch_page(src["socrata_domain"], src["dataset_id"],
                          src["page_size"], offset, where)
        if not rows:
            break
        frames.append(pd.DataFrame(rows))
        offset += src["page_size"]
        log.info("fetched %s rows (offset=%s)", len(rows), offset)

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FIELDS)
    df.to_parquet(out_path, index=False)
    log.info("wrote %s rows -> %s", len(df), out_path)
    return out_path


if __name__ == "__main__":
    setup_logging()
    extract()
