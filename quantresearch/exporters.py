from pathlib import Path
import shutil
from typing import Iterable, Optional

import pandas as pd

from .constants import DEFAULT_DATASET_NAME, DEFAULT_DB_PATH, PARQUET_EXPORT_DIR, QLIB_CSV_EXPORT_DIR
from .database import MarketDataDB


def qlib_symbol(symbol: str, market: str) -> str:
    return f"{market.upper()}_{symbol.upper()}"


def export_symbol_for_qlib(
    symbol: str,
    market: str,
    asset_type: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Path:
    exported = export_dataset_for_qlib(
        dataset_name=dataset_name,
        symbols=[(symbol.upper(), market.upper(), asset_type.upper())],
        db_path=db_path,
        start=start,
        end=end,
    )
    return next(iter(exported))


def export_dataset_for_qlib(
    dataset_name: str = DEFAULT_DATASET_NAME,
    symbols: Optional[Iterable[tuple[str, str, str]]] = None,
    db_path: Path | str = DEFAULT_DB_PATH,
    start: Optional[str] = None,
    end: Optional[str] = None,
    clean: bool = False,
) -> list[Path]:
    db = MarketDataDB(db_path)
    export_dir = QLIB_CSV_EXPORT_DIR / dataset_name
    parquet_dir = PARQUET_EXPORT_DIR / dataset_name
    if clean and symbols is None:
        shutil.rmtree(export_dir, ignore_errors=True)
        shutil.rmtree(parquet_dir, ignore_errors=True)
    export_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir.mkdir(parents=True, exist_ok=True)

    with db.connect() as conn:
        if symbols:
            clauses = []
            params = []
            for symbol, market, asset_type in symbols:
                clauses.append("(i.symbol = ? AND i.market = ? AND i.asset_type = ?)")
                params.extend([symbol, market, asset_type])
            instrument_filter = " AND (" + " OR ".join(clauses) + ")"
        else:
            instrument_filter = ""
            params = []

        if start:
            params.append(start)
            start_clause = " AND b.trade_date >= ?"
        else:
            start_clause = ""
        if end:
            params.append(end)
            end_clause = " AND b.trade_date <= ?"
        else:
            end_clause = ""

        df = pd.read_sql_query(
            f"""
            SELECT i.symbol, i.market, i.asset_type, i.has_real_factor, b.trade_date, b.open, b.high, b.low,
                   b.close, b.volume, b.amount, b.adj_close, b.factor
            FROM daily_bars b
            JOIN instruments i ON i.instrument_id = b.instrument_id
            WHERE 1 = 1
            {instrument_filter}
            {start_clause}
            {end_clause}
            ORDER BY i.market, i.symbol, b.trade_date
            """,
            conn,
            params=params,
        )

    if df.empty:
        return []

    exported_paths = []
    for (symbol, market, asset_type), group in df.groupby(["symbol", "market", "asset_type"]):
        out = group.copy()
        out["symbol"] = qlib_symbol(symbol, market)
        out["date"] = out["trade_date"]
        out["close"] = pd.to_numeric(out["close"], errors="coerce")
        for column in ("open", "high", "low"):
            out[column] = pd.to_numeric(out[column], errors="coerce").fillna(out["close"])
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)
        out["factor"] = out["factor"].fillna(1.0)
        out = out.dropna(subset=["close"])
        out = out[["date", "symbol", "open", "close", "high", "low", "volume", "factor"]]
        csv_path = export_dir / f"{qlib_symbol(symbol, market)}.csv"
        parquet_path = parquet_dir / f"{qlib_symbol(symbol, market)}.parquet"
        out.to_csv(csv_path, index=False)
        out.to_parquet(parquet_path, index=False)
        exported_paths.append(csv_path)
    return exported_paths
