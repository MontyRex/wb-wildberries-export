from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


XLSX_COLUMNS: list[str] = [
    "product_url",
    "article",
    "name",
    "price",
    "description",
    "image_urls",
    "characteristics_json",
    "seller_name",
    "seller_url",
    "sizes",
    "stocks_total",
    "rating",
    "reviews_count",
]


def write_xlsx(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    # фиксируем порядок колонок и добавляем отсутствующие
    for col in XLSX_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[XLSX_COLUMNS]

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="catalog")
        ws = writer.sheets["catalog"]
        ws.freeze_panes = "A2"

