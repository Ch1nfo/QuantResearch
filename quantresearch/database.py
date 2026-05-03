import sqlite3
from dataclasses import dataclass
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _timezone

    UTC = _timezone.utc
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from .constants import DATA_DIR, DEFAULT_DB_PATH


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass
class Instrument:
    symbol: str
    market: str
    asset_type: str
    name: Optional[str] = None
    currency: Optional[str] = None
    exchange: Optional[str] = None
    list_date: Optional[str] = None
    delist_date: Optional[str] = None
    status: str = "ACTIVE"
    has_real_factor: int = 0


class MarketDataDB:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_db(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    name TEXT,
                    currency TEXT,
                    exchange TEXT,
                    list_date TEXT,
                    delist_date TEXT,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    has_real_factor INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(symbol, market, asset_type)
                );

                CREATE TABLE IF NOT EXISTS data_sources (
                    source_name TEXT PRIMARY KEY,
                    api_name TEXT NOT NULL,
                    market_scope TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS instrument_source_map (
                    instrument_id INTEGER NOT NULL,
                    source_name TEXT NOT NULL,
                    source_symbol TEXT NOT NULL,
                    source_market TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (instrument_id, source_name),
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id),
                    FOREIGN KEY (source_name) REFERENCES data_sources(source_name)
                );

                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_name TEXT NOT NULL,
                    source_name TEXT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS daily_bars (
                    instrument_id INTEGER NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    amount REAL,
                    adj_close REAL,
                    factor REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (instrument_id, trade_date),
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                );

                CREATE TABLE IF NOT EXISTS weekly_bars (
                    instrument_id INTEGER NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    amount REAL,
                    adj_close REAL,
                    factor REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (instrument_id, trade_date),
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                );

                CREATE INDEX IF NOT EXISTS idx_daily_bars_date ON daily_bars(trade_date);
                CREATE INDEX IF NOT EXISTS idx_weekly_bars_date ON weekly_bars(trade_date);

                CREATE TABLE IF NOT EXISTS index_constituents (
                    index_id INTEGER NOT NULL,
                    constituent_id INTEGER NOT NULL,
                    include_date TEXT NOT NULL,
                    exclude_date TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (index_id, constituent_id),
                    FOREIGN KEY (index_id) REFERENCES instruments(instrument_id),
                    FOREIGN KEY (constituent_id) REFERENCES instruments(instrument_id)
                );

                CREATE TABLE IF NOT EXISTS batch_sync_checkpoint (
                    job_name TEXT PRIMARY KEY,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    completed_count INTEGER NOT NULL DEFAULT 0,
                    last_instrument_id INTEGER,
                    last_symbol TEXT,
                    status TEXT NOT NULL DEFAULT 'RUNNING',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS instrument_meta (
                    instrument_id INTEGER PRIMARY KEY,
                    total_market_cap REAL,
                    circulating_market_cap REAL,
                    pe_ttm REAL,
                    pb REAL,
                    industry_sw TEXT,
                    total_shares REAL,
                    circulating_shares REAL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                );

                CREATE TABLE IF NOT EXISTS financials (
                    instrument_id INTEGER NOT NULL,
                    report_period TEXT NOT NULL,
                    revenue REAL,
                    net_profit REAL,
                    net_profit_deducted REAL,
                    total_equity REAL,
                    operating_cash_flow REAL,
                    eps REAL,
                    bvps REAL,
                    roe REAL,
                    roa REAL,
                    gross_margin REAL,
                    net_margin REAL,
                    debt_ratio REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (instrument_id, report_period),
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                );

                CREATE TABLE IF NOT EXISTS corporate_actions (
                    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    ex_date TEXT NOT NULL,
                    record_date TEXT,
                    pay_date TEXT,
                    cash_dividend REAL,
                    stock_dividend REAL,
                    transfer_ratio REAL,
                    announce_date TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                );

                CREATE TABLE IF NOT EXISTS trading_calendar (
                    trade_date TEXT PRIMARY KEY,
                    is_open INTEGER NOT NULL DEFAULT 1,
                    market TEXT NOT NULL DEFAULT 'CN'
                );

                CREATE TABLE IF NOT EXISTS suspension_log (
                    instrument_id INTEGER NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    gap_days INTEGER NOT NULL DEFAULT 0,
                    detected_at TEXT NOT NULL,
                    PRIMARY KEY (instrument_id, start_date),
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                );

                CREATE TABLE IF NOT EXISTS positions (
                    position_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id INTEGER NOT NULL,
                    entry_date TEXT NOT NULL,
                    entry_price REAL,
                    quantity REAL NOT NULL DEFAULT 0,
                    current_value REAL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    exit_date TEXT,
                    exit_price REAL,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                );
                """
            )
            # 迁移:老表可能缺 current_value 列
            try:
                conn.execute("ALTER TABLE positions ADD COLUMN current_value REAL")
            except sqlite3.OperationalError:
                pass
            # 迁移:老表可能缺 last_symbol 列
            try:
                conn.execute("ALTER TABLE batch_sync_checkpoint ADD COLUMN last_symbol TEXT")
            except sqlite3.OperationalError:
                pass

    def seed_default_sources(self) -> None:
        now = _utc_now()
        rows = [
            ("akshare", "akshare", "CN/HK", "CN ETF/FUND/STOCK/INDEX and HK INDEX collector"),
            ("yfinance", "yfinance", "US", "US ETF/STOCK/FUND/INDEX collector"),
        ]
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO data_sources(source_name, api_name, market_scope, notes, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    api_name=excluded.api_name,
                    market_scope=excluded.market_scope,
                    notes=excluded.notes
                """,
                [(source_name, api_name, market_scope, notes, now) for source_name, api_name, market_scope, notes in rows],
            )

    def upsert_instrument(self, instrument: Instrument) -> int:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO instruments(
                    symbol, market, asset_type, name, currency, exchange, list_date, delist_date,
                    status, has_real_factor, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market, asset_type) DO UPDATE SET
                    name=excluded.name,
                    currency=excluded.currency,
                    exchange=excluded.exchange,
                    list_date=excluded.list_date,
                    delist_date=excluded.delist_date,
                    status=excluded.status,
                    has_real_factor=excluded.has_real_factor,
                    updated_at=excluded.updated_at
                """,
                (
                    instrument.symbol,
                    instrument.market,
                    instrument.asset_type,
                    instrument.name,
                    instrument.currency,
                    instrument.exchange,
                    instrument.list_date,
                    instrument.delist_date,
                    instrument.status,
                    instrument.has_real_factor,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT instrument_id
                FROM instruments
                WHERE symbol = ? AND market = ? AND asset_type = ?
                """,
                (instrument.symbol, instrument.market, instrument.asset_type),
            ).fetchone()
            return int(row["instrument_id"])

    def get_instrument(self, symbol: str, market: str, asset_type: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT *
                FROM instruments
                WHERE symbol = ? AND market = ? AND asset_type = ?
                """,
                (symbol.upper(), market.upper(), asset_type.upper()),
            ).fetchone()

    def delete_instrument(self, symbol: str, market: str, asset_type: str) -> int:
        instrument = self.get_instrument(symbol, market, asset_type)
        if instrument is None:
            return 0
        instrument_id = int(instrument["instrument_id"])
        with self.connect() as conn:
            conn.execute("DELETE FROM daily_bars WHERE instrument_id = ?", (instrument_id,))
            conn.execute("DELETE FROM weekly_bars WHERE instrument_id = ?", (instrument_id,))
            conn.execute("DELETE FROM instrument_source_map WHERE instrument_id = ?", (instrument_id,))
            conn.execute("DELETE FROM instruments WHERE instrument_id = ?", (instrument_id,))
        return 1

    def ensure_instrument(self, symbol: str, market: str, asset_type: str) -> int:
        existing = self.get_instrument(symbol, market, asset_type)
        if existing is not None:
            return int(existing["instrument_id"])
        return self.upsert_instrument(
            Instrument(
                symbol=symbol.upper(),
                market=market.upper(),
                asset_type=asset_type.upper(),
            )
        )

    def seed_instruments_from_csv(self, csv_path: Path | str) -> int:
        df = pd.read_csv(csv_path)
        inserted = 0
        for record in df.fillna(value=pd.NA).to_dict("records"):
            instrument = Instrument(
                symbol=str(record["symbol"]).upper(),
                market=str(record["market"]).upper(),
                asset_type=str(record["asset_type"]).upper(),
                name=_normalize_nullable(record.get("name")),
                currency=_normalize_nullable(record.get("currency")),
                exchange=_normalize_nullable(record.get("exchange")),
                list_date=_normalize_nullable(record.get("list_date")),
                delist_date=_normalize_nullable(record.get("delist_date")),
                status=str(record.get("status") or "ACTIVE").upper(),
                has_real_factor=int(record.get("has_real_factor") or 0),
            )
            self.upsert_instrument(instrument)
            inserted += 1
        return inserted

    def upsert_source_mapping(
        self,
        instrument_id: int,
        source_name: str,
        source_symbol: str,
        source_market: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO instrument_source_map(
                    instrument_id, source_name, source_symbol, source_market, notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id, source_name) DO UPDATE SET
                    source_symbol=excluded.source_symbol,
                    source_market=excluded.source_market,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (instrument_id, source_name, source_symbol, source_market, notes, now, now),
            )

    def create_ingestion_run(self, job_name: str, source_name: Optional[str]) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ingestion_runs(job_name, source_name, started_at, status, row_count)
                VALUES (?, ?, ?, 'RUNNING', 0)
                """,
                (job_name, source_name, _utc_now()),
            )
            return int(cursor.lastrowid)

    def finalize_ingestion_run(
        self, run_id: int, status: str, row_count: int, error_message: Optional[str] = None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_runs
                SET ended_at = ?, status = ?, row_count = ?, error_message = ?
                WHERE run_id = ?
                """,
                (_utc_now(), status, row_count, error_message, run_id),
            )

    def upsert_daily_bars(self, instrument_id: int, frame: pd.DataFrame) -> int:
        now = _utc_now()
        rows = []
        for record in frame.to_dict("records"):
            rows.append(
                (
                    instrument_id,
                    record["trade_date"],
                    _normalize_number(record.get("open")),
                    _normalize_number(record.get("high")),
                    _normalize_number(record.get("low")),
                    _normalize_number(record.get("close")),
                    _normalize_number(record.get("volume")),
                    _normalize_number(record.get("amount")),
                    _normalize_number(record.get("adj_close")),
                    _normalize_number(record.get("factor"), default=1.0),
                    now,
                    now,
                )
            )
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO daily_bars(
                    instrument_id, trade_date, open, high, low, close, volume, amount,
                    adj_close, factor, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id, trade_date) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    amount=excluded.amount,
                    adj_close=excluded.adj_close,
                    factor=excluded.factor,
                    updated_at=excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def set_has_real_factor(self, instrument_id: int, value: int = 1) -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE instruments SET has_real_factor = ?, updated_at = ? WHERE instrument_id = ?",
                (value, now, instrument_id),
            )

    def get_instruments_needing_factor_repair(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM instruments
                WHERE has_real_factor = 0 AND asset_type IN ('STOCK', 'ETF', 'FUND')
                AND status = 'ACTIVE'
                """
            ).fetchall()

    def get_daily_bar_coverage(self, instrument_id: int) -> dict[str, Optional[str] | int]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT MIN(trade_date) AS min_trade_date,
                       MAX(trade_date) AS max_trade_date,
                       COUNT(*) AS row_count
                FROM daily_bars
                WHERE instrument_id = ?
                """,
                (instrument_id,),
            ).fetchone()
        return {
            "min_trade_date": row["min_trade_date"],
            "max_trade_date": row["max_trade_date"],
            "row_count": int(row["row_count"] or 0),
        }

    def rebuild_weekly_bars(self, instrument_ids: Optional[Iterable[int]] = None) -> int:
        predicate = ""
        params: list[int] = []
        if instrument_ids:
            placeholders = ",".join("?" for _ in instrument_ids)
            predicate = f"WHERE instrument_id IN ({placeholders})"
            params = list(instrument_ids)

        query = f"""
            SELECT instrument_id, trade_date, open, high, low, close, volume, amount, adj_close, factor
            FROM daily_bars
            {predicate}
            ORDER BY instrument_id, trade_date
        """
        with self.connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if df.empty:
            return 0

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        output_frames = []
        for instrument_id, group in df.groupby("instrument_id"):
            weekly = (
                group.set_index("trade_date")
                .resample("W-FRI")
                .agg(
                    {
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum",
                        "amount": "sum",
                        "adj_close": "last",
                        "factor": "last",
                    }
                )
                .dropna(subset=["close"])
                .reset_index()
            )
            weekly["instrument_id"] = instrument_id
            weekly["trade_date"] = weekly["trade_date"].dt.strftime("%Y-%m-%d")
            output_frames.append(weekly)

        weekly_df = pd.concat(output_frames, ignore_index=True)
        now = _utc_now()
        rows = [
            (
                int(record["instrument_id"]),
                record["trade_date"],
                _normalize_number(record.get("open")),
                _normalize_number(record.get("high")),
                _normalize_number(record.get("low")),
                _normalize_number(record.get("close")),
                _normalize_number(record.get("volume")),
                _normalize_number(record.get("amount")),
                _normalize_number(record.get("adj_close")),
                _normalize_number(record.get("factor"), default=1.0),
                now,
                now,
            )
            for record in weekly_df.to_dict("records")
        ]
        with self.connect() as conn:
            if instrument_ids:
                placeholders = ",".join("?" for _ in instrument_ids)
                conn.execute(f"DELETE FROM weekly_bars WHERE instrument_id IN ({placeholders})", list(instrument_ids))
            else:
                conn.execute("DELETE FROM weekly_bars")
            conn.executemany(
                """
                INSERT INTO weekly_bars(
                    instrument_id, trade_date, open, high, low, close, volume, amount,
                    adj_close, factor, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    # -- index_constituents --------------------------------------------

    def upsert_constituents(self, index_symbol: str, index_market: str, constituent_list: list[dict]) -> int:
        """批量写入指数成分股关联 (单连接避免锁冲突)."""
        now = _utc_now()
        count = 0
        with self.connect() as conn:
            # 先拿到 index_id
            row = conn.execute(
                "SELECT instrument_id FROM instruments WHERE symbol=? AND market=? AND asset_type=?",
                (index_symbol.upper(), index_market.upper(), "INDEX"),
            ).fetchone()
            if row is None:
                raise ValueError(f"指数 {index_symbol}/{index_market} 不在 instruments 表中")
            index_id = int(row["instrument_id"])

            for item in constituent_list:
                sym = item["symbol"]
                mkt = item.get("market", "CN")
                atype = item.get("asset_type", "STOCK")
                name = item.get("name")

                # 单连接内 upsert instrument
                conn.execute(
                    """
                    INSERT INTO instruments(symbol, market, asset_type, name, status, has_real_factor, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'ACTIVE', 0, ?, ?)
                    ON CONFLICT(symbol, market, asset_type) DO UPDATE SET
                        name=COALESCE(excluded.name, instruments.name),
                        updated_at=excluded.updated_at
                    """,
                    (sym.upper(), mkt.upper(), atype.upper(), name, now, now),
                )
                cid_row = conn.execute(
                    "SELECT instrument_id FROM instruments WHERE symbol=? AND market=? AND asset_type=?",
                    (sym.upper(), mkt.upper(), atype.upper()),
                ).fetchone()
                cid = int(cid_row["instrument_id"])

                conn.execute(
                    """
                    INSERT INTO index_constituents(index_id, constituent_id, include_date, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(index_id, constituent_id) DO NOTHING
                    """,
                    (index_id, cid, "2000-01-01", now, now),
                )
                count += 1
        return count

    def get_constituent_ids(self, index_symbol: str, index_market: str) -> list[int]:
        """获取某指数当前所有成分股的 instrument_id 列表."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.constituent_id
                FROM index_constituents c
                JOIN instruments i ON c.index_id = i.instrument_id
                WHERE i.symbol = ? AND i.market = ?
                AND c.exclude_date IS NULL
                """,
                (index_symbol.upper(), index_market.upper()),
            ).fetchall()
        return [int(r["constituent_id"]) for r in rows]

    def get_constituents_without_data(self, index_symbol: str, index_market: str) -> list[sqlite3.Row]:
        """获取某指数中尚未采集日线数据的成分股."""
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT i.* FROM instruments i
                JOIN index_constituents c ON i.instrument_id = c.constituent_id
                JOIN instruments idx ON c.index_id = idx.instrument_id
                WHERE idx.symbol = ? AND idx.market = ?
                AND c.exclude_date IS NULL
                AND i.instrument_id NOT IN (
                    SELECT DISTINCT instrument_id FROM daily_bars WHERE instrument_id IS NOT NULL
                )
                ORDER BY i.symbol
                """,
                (index_symbol.upper(), index_market.upper()),
            ).fetchall()

    # -- batch_sync_checkpoint -----------------------------------------

    def create_checkpoint(self, job_name: str, total: int) -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO batch_sync_checkpoint(job_name, total_count, completed_count, status, created_at, updated_at)
                VALUES (?, ?, 0, 'RUNNING', ?, ?)
                """,
                (job_name, total, now, now),
            )

    def update_checkpoint(self, job_name: str, instrument_id: int, last_symbol: str = "") -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE batch_sync_checkpoint
                SET completed_count = completed_count + 1,
                    last_instrument_id = ?,
                    updated_at = ?
                WHERE job_name = ?
                """,
                (instrument_id, now, job_name),
            )
            if last_symbol:
                try:
                    conn.execute(
                        "UPDATE batch_sync_checkpoint SET last_symbol = ? WHERE job_name = ?",
                        (last_symbol, job_name),
                    )
                except sqlite3.OperationalError:
                    # 老表可能没有 last_symbol 列,忽略
                    pass

    def finish_checkpoint(self, job_name: str) -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE batch_sync_checkpoint SET status = 'DONE', updated_at = ? WHERE job_name = ?",
                (now, job_name),
            )

    def get_checkpoint(self, job_name: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM batch_sync_checkpoint WHERE job_name = ?", (job_name,)
            ).fetchone()

    # -- instrument_meta ------------------------------------------------

    def upsert_meta(self, instrument_id: int, meta: dict) -> None:
        """写入/更新标的基本面元数据(最新快照)."""
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO instrument_meta(
                    instrument_id, total_market_cap, circulating_market_cap,
                    pe_ttm, pb, industry_sw, total_shares, circulating_shares, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id) DO UPDATE SET
                    total_market_cap=excluded.total_market_cap,
                    circulating_market_cap=excluded.circulating_market_cap,
                    pe_ttm=excluded.pe_ttm,
                    pb=excluded.pb,
                    industry_sw=excluded.industry_sw,
                    total_shares=excluded.total_shares,
                    circulating_shares=excluded.circulating_shares,
                    updated_at=excluded.updated_at
                """,
                (
                    instrument_id,
                    meta.get("total_market_cap"),
                    meta.get("circulating_market_cap"),
                    meta.get("pe_ttm"),
                    meta.get("pb"),
                    meta.get("industry_sw"),
                    meta.get("total_shares"),
                    meta.get("circulating_shares"),
                    now,
                ),
            )

    def get_stocks_without_meta(self) -> list[sqlite3.Row]:
        """返回缺少元数据的 A 股个股."""
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT i.* FROM instruments i
                WHERE i.market = 'CN' AND i.asset_type = 'STOCK' AND i.status = 'ACTIVE'
                AND i.instrument_id NOT IN (SELECT instrument_id FROM instrument_meta)
                ORDER BY i.symbol
                """
            ).fetchall()

    # -- financials -----------------------------------------------------

    def upsert_financials(self, instrument_id: int, records: list[dict]) -> int:
        """批量写入财报数据.records 每项含 report_period 及各项财务指标."""
        now = _utc_now()
        cols = ["revenue", "net_profit", "net_profit_deducted", "total_equity",
                "operating_cash_flow", "eps", "bvps", "roe", "roa",
                "gross_margin", "net_margin", "debt_ratio"]
        rows = []
        for rec in records:
            vals = [instrument_id, str(rec["report_period"])]
            vals.extend([_safe_db_float(rec.get(c)) for c in cols])
            vals.extend([now, now])
            rows.append(tuple(vals))
        with self.connect() as conn:
            conn.executemany(
                f"""
                INSERT INTO financials(instrument_id, report_period,
                    {','.join(cols)}, created_at, updated_at)
                VALUES ({','.join('?'* (2+len(cols)+2))})
                ON CONFLICT(instrument_id, report_period) DO UPDATE SET
                    {', '.join(f'{c}=excluded.{c}' for c in cols)},
                    updated_at=excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def get_stocks_without_financials(self, limit: Optional[int] = None) -> list[sqlite3.Row]:
        """返回缺少财报数据的 A 股个股(按元数据已采集的优先)."""
        with self.connect() as conn:
            sql = """
                SELECT i.* FROM instruments i
                JOIN instrument_meta m ON i.instrument_id = m.instrument_id
                WHERE i.market = 'CN' AND i.asset_type = 'STOCK' AND i.status = 'ACTIVE'
                AND i.instrument_id NOT IN (SELECT DISTINCT instrument_id FROM financials)
                ORDER BY i.symbol
            """
            if limit:
                sql += f" LIMIT {int(limit)}"
            return conn.execute(sql).fetchall()

    # -- corporate_actions -----------------------------------------------

    def upsert_dividends(self, instrument_id: int, records: list[dict]) -> int:
        """批量写入分红记录."""
        now = _utc_now()
        rows = [
            (
                instrument_id, "DIVIDEND",
                str(r.get("ex_date", "")), str(r.get("record_date", "")),
                str(r.get("pay_date", "")),
                _safe_db_float(r.get("cash_dividend")),
                _safe_db_float(r.get("stock_dividend")),
                _safe_db_float(r.get("transfer_ratio")),
                str(r.get("announce_date", "")), str(r.get("notes", "")),
                now,
            )
            for r in records
        ]
        with self.connect() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO corporate_actions(
                    instrument_id, action_type, ex_date, record_date, pay_date,
                    cash_dividend, stock_dividend, transfer_ratio, announce_date, notes, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        return len(rows)

    # -- trading_calendar ------------------------------------------------

    def seed_trading_calendar(self, dates: list[str]) -> int:
        """写入 A 股交易日历."""
        now = _utc_now()
        rows = [(d, 1, "CN") for d in dates]
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO trading_calendar(trade_date, is_open, market) VALUES (?,?,?)",
                rows,
            )
        return len(rows)

    def get_trading_dates(self, start: str, end: str) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT trade_date FROM trading_calendar WHERE trade_date BETWEEN ? AND ?",
                (start, end),
            ).fetchall()
        return {r["trade_date"] for r in rows}

    def get_stocks_without_dividends(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT i.* FROM instruments i
                WHERE i.market = 'CN' AND i.asset_type = 'STOCK' AND i.status = 'ACTIVE'
                AND i.instrument_id NOT IN (SELECT DISTINCT instrument_id FROM corporate_actions)
                ORDER BY i.symbol
                """
            ).fetchall()

    # -- suspension_log --------------------------------------------------

    def upsert_suspensions(self, records: list[dict]) -> int:
        """写入停牌记录.records: [{instrument_id, start_date, end_date, gap_days}, ...]"""
        now = _utc_now()
        rows = [
            (int(r["instrument_id"]), r["start_date"], r["end_date"],
             int(r.get("gap_days", 0)), now)
            for r in records
        ]
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO suspension_log(instrument_id, start_date, end_date, gap_days, detected_at) VALUES (?,?,?,?,?)",
                rows,
            )
        return len(rows)

    # -- positions -------------------------------------------------------

    def add_position(
        self, symbol: str, market: str, entry_date: str,
        entry_price: float, quantity: float,
        current_value: float = 0, notes: str = "",
    ) -> int:
        """新增一条持仓记录.返回 position_id."""
        inst = self.get_instrument(symbol, market, "STOCK")
        if inst is None:
            inst = self.get_instrument(symbol, market, "ETF")
        if inst is None:
            inst = self.get_instrument(symbol, market, "INDEX")
        if inst is None:
            raise ValueError(f"标的 {symbol}/{market} 不在 instruments 表中")
        now = _utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO positions(instrument_id, entry_date, entry_price, quantity,
                   current_value, status, notes, created_at, updated_at)
                VALUES (?,?,?,?,?,'OPEN',?,?,?)""",
                (int(inst["instrument_id"]), entry_date, entry_price, quantity,
                 current_value or 0, notes or "", now, now),
            )
            return cur.lastrowid

    def list_positions(self, status: str = "OPEN") -> list[dict]:
        """列出持仓.返回 [{position_id, symbol, name, entry_date, entry_price, quantity, current_value, cost, pnl, pnl_pct}, ...]"""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*, i.symbol, i.name, i.market, i.asset_type
                FROM positions p
                JOIN instruments i ON p.instrument_id = i.instrument_id
                WHERE (? = 'ALL' OR p.status = ?)
                ORDER BY p.entry_date DESC
                """,
                (status, status),
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            cost = (d.get("entry_price") or 0) * (d.get("quantity") or 0)
            cur_val = d.get("current_value") or 0
            pnl = cur_val - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0
            d["cost"] = cost
            d["pnl"] = pnl
            d["pnl_pct"] = pnl_pct
            d["alloc_pct"] = 0  # 下面算
            result.append(d)
        # 算占比
        total_val = sum(r["current_value"] or 0 for r in result)
        if total_val > 0:
            for r in result:
                r["alloc_pct"] = ((r["current_value"] or 0) / total_val * 100)
        return result

    def close_position(self, position_id: int, exit_date: str, exit_price: float = 0) -> None:
        """平仓:标记持仓为 CLOSED,记录出场价."""
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """UPDATE positions SET status='CLOSED', exit_date=?, exit_price=?, updated_at=?
                WHERE position_id=?""",
                (exit_date, exit_price if exit_price > 0 else None, now, position_id),
            )


def _safe_db_float(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _normalize_nullable(value):
    if value is None or value is pd.NA:
        return None
    if pd.isna(value):
        return None
    return str(value)


def _normalize_number(value, default=None):
    if value is None or value is pd.NA:
        return default
    if pd.isna(value):
        return default
    return float(value)
