"""Selection filters shared by the CLI, the nightly job and the Power BI export button.

Power BI cannot call Python directly, so the report page writes the *current*
slicer state to a small JSON file (see ``powerbi/report_spec.md``, Page 6 export
button) and the exporter reads it back:

    {"boroughs": ["BROOKLYN", "QUEENS"],
     "complaint_types": ["Noise - Residential"],
     "date_from": "2024-06-01", "date_to": "2024-06-30",
     "source": "Power BI cohort page"}

Any key may be omitted or null, which means "no filter on that field".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ALL_TOKENS = {"", "all", "(all)", "*", "any", "all boroughs", "all categories"}


def _clean(values) -> list[str]:
    """Normalise a slicer selection to a de-duplicated, upper-cased-safe list."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [v for v in re.split(r"\s*[,|;]\s*", values) if v.strip()]
    out: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text.lower() in ALL_TOKENS:
            continue
        if text not in out:
            out.append(text)
    return out


@dataclass
class CohortFilter:
    """Borough / complaint-category / date selection carried through an export run."""

    boroughs: list[str] = field(default_factory=list)
    complaint_types: list[str] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    source: str | None = None

    # ------------------------------------------------------------------ inputs
    @classmethod
    def from_dict(cls, data: dict | None) -> "CohortFilter":
        data = data or {}
        return cls(
            boroughs=_clean(data.get("boroughs") or data.get("borough")),
            complaint_types=_clean(data.get("complaint_types")
                                   or data.get("complaint_type")
                                   or data.get("categories")),
            date_from=(data.get("date_from") or None),
            date_to=(data.get("date_to") or None),
            source=(data.get("source") or None),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "CohortFilter":
        payload = json.loads(Path(path).read_text())
        return cls.from_dict(payload)

    # ------------------------------------------------------------------ state
    @property
    def is_empty(self) -> bool:
        return not (self.boroughs or self.complaint_types
                    or self.date_from or self.date_to)

    def label(self) -> str:
        """Human-readable description printed on the PDF / Excel / e-mail."""
        if self.is_empty:
            return "All boroughs, all complaint categories"
        parts = []
        parts.append(", ".join(self.boroughs) if self.boroughs else "All boroughs")
        parts.append(", ".join(self.complaint_types) if self.complaint_types
                     else "All complaint categories")
        if self.date_from or self.date_to:
            parts.append(f"{self.date_from or '…'} → {self.date_to or '…'}")
        return " | ".join(parts)

    def slug(self) -> str:
        """Filename-safe fragment so filtered exports never overwrite full ones."""
        if self.is_empty:
            return "all"
        bits = self.boroughs[:2] + self.complaint_types[:2]
        text = "_".join(bits) or "filtered"
        return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()[:60]

    def to_dict(self) -> dict:
        return {"boroughs": self.boroughs, "complaint_types": self.complaint_types,
                "date_from": self.date_from, "date_to": self.date_to,
                "source": self.source}

    # ------------------------------------------------------------------ apply
    def _mask(self, df: pd.DataFrame, with_dates: bool) -> pd.Series:
        mask = pd.Series(True, index=df.index)
        if self.boroughs and "borough" in df:
            mask &= df["borough"].astype(str).str.upper().isin(
                [b.upper() for b in self.boroughs])
        if self.complaint_types and "complaint_type" in df:
            mask &= df["complaint_type"].astype(str).str.upper().isin(
                [c.upper() for c in self.complaint_types])
        if with_dates and "date_day" in df:
            days = pd.to_datetime(df["date_day"])
            if self.date_from:
                mask &= days >= pd.Timestamp(self.date_from)
            if self.date_to:
                mask &= days <= pd.Timestamp(self.date_to)
        return mask

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter a comparison (no dates) or daily (dated) cohort frame."""
        if df is None or not len(df) or self.is_empty:
            return df
        return df.loc[self._mask(df, with_dates=True)].reset_index(drop=True)


def recompute_contribution(df: pd.DataFrame) -> pd.DataFrame:
    """Re-base contribution % to the filtered selection.

    Without this, a Brooklyn-only export would still show each row's share of the
    *citywide* change and the column would not sum to 100%.
    """
    if df is None or not len(df) or "abs_change" not in df:
        return df
    out = df.copy()
    total = float(out["abs_change"].sum(skipna=True))
    out["contribution_pct"] = (100.0 * out["abs_change"] / total
                               if total else np.nan)
    return out
