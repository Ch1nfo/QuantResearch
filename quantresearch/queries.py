from pathlib import Path

import pandas as pd

from .constants import DEFAULT_DB_PATH
from .database import MarketDataDB
from .pipeline import ensure_history_coverage


def list_instruments(db_path: Path | str = DEFAULT_DB_PATH, market=None, asset_type=None) -> pd.DataFrame:
    db = MarketDataDB(db_path)
    clauses = []
    params = []
    if market:
        clauses.append("market = ?")
        params.append(str(market).upper())
    if asset_type:
        clauses.append("asset_type = ?")
        params.append(str(asset_type).upper())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db.connect() as conn:
        return pd.read_sql_query(
            f"SELECT * FROM instruments {where} ORDER BY market, asset_type, symbol",
            conn,
            params=params,
        )


def get_price_history(
    symbol: str,
    market: str,
    asset_type: str,
    start: str,
    end: str,
    freq: str = "daily",
    db_path: Path | str = DEFAULT_DB_PATH,
    auto_fetch: bool = False,
    target_years: int = 20,
) -> pd.DataFrame:
    table_name = "daily_bars" if freq == "daily" else "weekly_bars"
    if auto_fetch:
        ensure_history_coverage(
            symbol=symbol,
            market=market,
            asset_type=asset_type,
            db_path=db_path,
            target_years=target_years,
        )
    db = MarketDataDB(db_path)
    query = f"""
        SELECT i.symbol, i.market, i.asset_type, b.trade_date, b.open, b.high, b.low, b.close,
               b.volume, b.amount, b.adj_close, b.factor
        FROM {table_name} b
        JOIN instruments i ON i.instrument_id = b.instrument_id
        WHERE i.symbol = ?
          AND i.market = ?
          AND i.asset_type = ?
          AND b.trade_date >= ?
          AND b.trade_date <= ?
        ORDER BY b.trade_date
    """
    with db.connect() as conn:
        return pd.read_sql_query(
            query,
            conn,
            params=[symbol.upper(), market.upper(), asset_type.upper(), start, end],
        )


def get_close_series(
    symbol: str,
    market: str,
    asset_type: str,
    start: str,
    end: str,
    adjusted: bool = False,
    db_path: Path | str = DEFAULT_DB_PATH,
    auto_fetch: bool = False,
    target_years: int = 20,
) -> pd.Series:
    frame = get_price_history(
        symbol,
        market,
        asset_type,
        start,
        end,
        freq="daily",
        db_path=db_path,
        auto_fetch=auto_fetch,
        target_years=target_years,
    )
    if frame.empty:
        return pd.Series(dtype=float, name=symbol.upper())
    column = "adj_close" if adjusted else "close"
    series = frame.set_index("trade_date")[column]
    series.name = symbol.upper()
    return series
