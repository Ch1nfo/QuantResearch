from pathlib import Path
from typing import Optional

import pandas as pd

from .constants import DEFAULT_DB_PATH
from .database import MarketDataDB
from .etf_lookup import search_cn_etf_catalog
from .stock_lookup import search_cn_stock_catalog


def get_instrument_name(
    symbol: str,
    market: str,
    asset_type: str = "ETF",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Optional[str]:
    db = MarketDataDB(db_path)
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT name
            FROM instruments
            WHERE symbol = ? AND market = ? AND asset_type = ?
            """,
            (symbol.upper(), market.upper(), asset_type.upper()),
        ).fetchone()
    if row and row["name"]:
        return str(row["name"])

    if market.upper() == "CN" and asset_type.upper() == "ETF":
        try:
            matched = search_cn_etf_catalog(query=symbol, limit=1)
        except Exception:
            matched = pd.DataFrame()
        if not matched.empty and str(matched.iloc[0]["代码"]).zfill(6) == symbol.upper():
            return str(matched.iloc[0]["名称"])
    if market.upper() == "CN" and asset_type.upper() == "STOCK":
        try:
            matched = search_cn_stock_catalog(query=symbol, limit=1)
        except Exception:
            matched = pd.DataFrame()
        if not matched.empty and str(matched.iloc[0]["代码"]).zfill(6) == symbol.upper():
            return str(matched.iloc[0]["名称"])
    return None


def format_display_symbol(
    symbol: str,
    market: str,
    asset_type: str = "ETF",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> str:
    name = get_instrument_name(symbol, market, asset_type=asset_type, db_path=db_path)
    return f"{name}({symbol.upper()})" if name else symbol.upper()


def format_qlib_instrument(
    instrument: str,
    asset_type: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> str:
    if "_" not in instrument:
        return instrument
    market, symbol = instrument.split("_", 1)
    if asset_type is None:
        asset_type = infer_asset_type(symbol, market, db_path=db_path)
    return format_display_symbol(symbol, market, asset_type=asset_type, db_path=db_path)


def infer_asset_type(symbol: str, market: str, db_path: Path | str = DEFAULT_DB_PATH) -> str:
    db = MarketDataDB(db_path)
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT asset_type
            FROM instruments
            WHERE symbol = ? AND market = ?
            ORDER BY CASE asset_type
                WHEN 'INDEX' THEN 1
                WHEN 'ETF' THEN 2
                WHEN 'STOCK' THEN 3
                WHEN 'FUND' THEN 4
                ELSE 99
            END
            LIMIT 1
            """,
            (symbol.upper(), market.upper()),
        ).fetchone()
    return str(row["asset_type"]) if row else "INDEX"


def relabel_metric_columns(
    metrics: pd.DataFrame,
    market: str,
    asset_type: str = "ETF",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    renamed = {
        column: format_display_symbol(column, market, asset_type=asset_type, db_path=db_path)
        for column in metrics.columns
    }
    return metrics.rename(columns=renamed)


def relabel_rotation_picks(
    picks: pd.DataFrame,
    asset_type: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    if picks.empty:
        return picks
    relabeled = picks.copy()

    def _map_selected(text: str) -> str:
        if text == "CASH":
            return text
        return ",".join(format_qlib_instrument(item.strip(), asset_type=asset_type, db_path=db_path) for item in text.split(","))

    def _map_scores(text: str) -> str:
        if text == "no positive momentum":
            return text
        mapped_parts = []
        for part in text.split(", "):
            if ":" not in part:
                mapped_parts.append(part)
                continue
            instrument, score = part.split(":", 1)
            mapped_parts.append(f"{format_qlib_instrument(instrument, asset_type=asset_type, db_path=db_path)}:{score}")
        return ", ".join(mapped_parts)

    relabeled["selected"] = relabeled["selected"].map(_map_selected)
    relabeled["scores"] = relabeled["scores"].map(_map_scores)
    return relabeled
