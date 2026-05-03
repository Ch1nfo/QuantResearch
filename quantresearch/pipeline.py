import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

import pandas as pd

from .collectors import collect_history
from .constants import DEFAULT_DATASET_NAME, DEFAULT_DB_PATH
from .database import Instrument, MarketDataDB
from .exporters import export_dataset_for_qlib
from .qlib_support import build_qlib_bin


@dataclass
class SyncResult:
    instrument_id: int
    symbol: str
    market: str
    asset_type: str
    row_count: int


def ensure_history_coverage(
    *,
    symbol: str,
    market: str,
    asset_type: str,
    db_path: Path | str = DEFAULT_DB_PATH,
    target_years: int = 20,
    end: Optional[str] = None,
    refresh_recent_days: int = 14,
) -> SyncResult:
    db = MarketDataDB(db_path)
    db.init_db()
    db.seed_default_sources()
    instrument_id = db.ensure_instrument(symbol=symbol, market=market, asset_type=asset_type)
    target_end = _parse_iso_date(end) if end else date.today()
    target_start = _subtract_years(target_end, target_years)
    coverage = db.get_daily_bar_coverage(instrument_id)
    requested_ranges = _build_missing_ranges(
        target_start=target_start,
        target_end=target_end,
        coverage_start=coverage["min_trade_date"],
        coverage_end=coverage["max_trade_date"],
        refresh_recent_days=refresh_recent_days,
    )
    synced_rows = 0
    touched = False
    source_name = "akshare" if market.upper() == "CN" else "yfinance"
    run_id = db.create_ingestion_run(job_name="ensure-history", source_name=source_name)
    try:
        for range_start, range_end in requested_ranges:
            frame = collect_history(
                symbol=symbol,
                market=market,
                asset_type=asset_type,
                start=range_start.isoformat(),
                end=range_end.isoformat(),
            )
            if frame.empty:
                continue
            synced_rows += db.upsert_daily_bars(instrument_id=instrument_id, frame=frame)
            touched = True
        db.upsert_source_mapping(
            instrument_id=instrument_id,
            source_name=source_name,
            source_symbol=symbol.upper(),
            source_market=market.upper(),
        )
        if touched:
            db.rebuild_weekly_bars([instrument_id])
        db.finalize_ingestion_run(run_id, status="SUCCESS", row_count=synced_rows)
    except Exception as exc:
        db.finalize_ingestion_run(run_id, status="FAILED", row_count=synced_rows, error_message=str(exc))
        raise
    return SyncResult(
        instrument_id=instrument_id,
        symbol=symbol.upper(),
        market=market.upper(),
        asset_type=asset_type.upper(),
        row_count=synced_rows,
    )


def ensure_history_for_targets(
    db_path: Path | str = DEFAULT_DB_PATH,
    symbol: Optional[str] = None,
    market: Optional[str] = None,
    asset_type: Optional[str] = None,
    target_years: int = 20,
    end: Optional[str] = None,
    refresh_recent_days: int = 14,
) -> list[SyncResult]:
    db = MarketDataDB(db_path)
    db.init_db()
    db.seed_default_sources()
    targets = _load_target_instruments(db, symbol, market, asset_type)
    results = []
    for record in targets.to_dict("records"):
        results.append(
            ensure_history_coverage(
                symbol=record["symbol"],
                market=record["market"],
                asset_type=record["asset_type"],
                db_path=db_path,
                target_years=target_years,
                end=end,
                refresh_recent_days=refresh_recent_days,
            )
        )
    return results


def backfill_history(
    db_path: Path | str = DEFAULT_DB_PATH,
    start: str = "2000-01-01",
    end: Optional[str] = None,
    symbol: Optional[str] = None,
    market: Optional[str] = None,
    asset_type: Optional[str] = None,
) -> list[SyncResult]:
    end = end or date.today().isoformat()
    db = MarketDataDB(db_path)
    return _sync_history(db, "backfill-history", start, end, symbol, market, asset_type)


def update_daily(
    db_path: Path | str = DEFAULT_DB_PATH,
    window_days: int = 14,
    symbol: Optional[str] = None,
    market: Optional[str] = None,
    asset_type: Optional[str] = None,
) -> list[SyncResult]:
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=window_days)).isoformat()
    db = MarketDataDB(db_path)
    return _sync_history(db, "update-daily", start, end, symbol, market, asset_type)


def refresh_qlib(
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
    qlib_repo: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Path:
    export_dataset_for_qlib(dataset_name=dataset_name, db_path=db_path, start=start, end=end, clean=True)
    return build_qlib_bin(dataset_name=dataset_name, qlib_repo=qlib_repo, output_dir=output_dir, clean=True)


def _sync_history(
    db: MarketDataDB,
    job_name: str,
    start: str,
    end: str,
    symbol: Optional[str],
    market: Optional[str],
    asset_type: Optional[str],
) -> list[SyncResult]:
    run_id = db.create_ingestion_run(job_name=job_name, source_name=None)
    try:
        instrument_df = _load_target_instruments(db, symbol, market, asset_type)
        results = []
        for record in instrument_df.to_dict("records"):
            frame = collect_history(
                symbol=record["symbol"],
                market=record["market"],
                asset_type=record["asset_type"],
                start=start,
                end=end,
            )
            if frame.empty:
                continue
            instrument_id = int(record["instrument_id"])
            inserted = db.upsert_daily_bars(instrument_id=instrument_id, frame=frame)
            source_name = "akshare" if record["market"] == "CN" else "yfinance"
            db.upsert_source_mapping(
                instrument_id=instrument_id,
                source_name=source_name,
                source_symbol=record["symbol"],
                source_market=record["market"],
            )
            results.append(
                SyncResult(
                    instrument_id=instrument_id,
                    symbol=record["symbol"],
                    market=record["market"],
                    asset_type=record["asset_type"],
                    row_count=inserted,
                )
            )

        touched_ids = [result.instrument_id for result in results]
        if touched_ids:
            db.rebuild_weekly_bars(touched_ids)
        db.finalize_ingestion_run(run_id, status="SUCCESS", row_count=sum(item.row_count for item in results))
        return results
    except Exception as exc:
        db.finalize_ingestion_run(run_id, status="FAILED", row_count=0, error_message=str(exc))
        raise


def _load_target_instruments(
    db: MarketDataDB,
    symbol: Optional[str],
    market: Optional[str],
    asset_type: Optional[str],
) -> pd.DataFrame:
    clauses = []
    params = []
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    if market:
        clauses.append("market = ?")
        params.append(market.upper())
    if asset_type:
        clauses.append("asset_type = ?")
        params.append(asset_type.upper())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db.connect() as conn:
        return pd.read_sql_query(
            f"SELECT instrument_id, symbol, market, asset_type FROM instruments {where} ORDER BY market, symbol",
            conn,
            params=params,
        )


def seed_default_universe(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    db = MarketDataDB(db_path)
    db.seed_default_sources()
    default_rows = [
        Instrument(symbol="HSTECH", market="HK", asset_type="INDEX", name="恒生科技指数", currency="HKD", exchange="HK"),
        Instrument(symbol="000300", market="CN", asset_type="INDEX", name="沪深300指数", currency="CNY", exchange="CSI"),
        Instrument(symbol="000510", market="CN", asset_type="INDEX", name="中证A500指数", currency="CNY", exchange="CSI"),
        Instrument(symbol="NDX", market="US", asset_type="INDEX", name="纳斯达克100指数", currency="USD", exchange="INDEX"),
        Instrument(symbol="GSPC", market="US", asset_type="INDEX", name="标普500指数", currency="USD", exchange="INDEX"),
    ]
    for instrument in default_rows:
        db.upsert_instrument(instrument)
    return len(default_rows)


def replace_index_proxy_universe(
    db_path: Path | str = DEFAULT_DB_PATH,
    *,
    target_years: int = 20,
    end: Optional[str] = None,
    refresh_recent_days: int = 14,
) -> list[SyncResult]:
    db = MarketDataDB(db_path)
    db.init_db()
    db.seed_default_sources()

    proxy_rows = [
        ("520570", "CN", "ETF"),
        ("159352", "CN", "ETF"),
        ("510300", "CN", "ETF"),
        ("QQQ", "US", "ETF"),
        ("SPY", "US", "ETF"),
        ("513130", "CN", "ETF"),
    ]
    for symbol, market, asset_type in proxy_rows:
        db.delete_instrument(symbol, market, asset_type)

    index_rows = [
        Instrument(symbol="HSTECH", market="HK", asset_type="INDEX", name="恒生科技指数", currency="HKD", exchange="HK"),
        Instrument(symbol="000510", market="CN", asset_type="INDEX", name="中证A500指数", currency="CNY", exchange="CSI"),
        Instrument(symbol="000300", market="CN", asset_type="INDEX", name="沪深300指数", currency="CNY", exchange="CSI"),
        Instrument(symbol="NDX", market="US", asset_type="INDEX", name="纳斯达克100指数", currency="USD", exchange="INDEX"),
        Instrument(symbol="GSPC", market="US", asset_type="INDEX", name="标普500指数", currency="USD", exchange="INDEX"),
    ]
    for instrument in index_rows:
        db.upsert_instrument(instrument)

    results = []
    for instrument in index_rows:
        results.append(
            ensure_history_coverage(
                symbol=instrument.symbol,
                market=instrument.market,
                asset_type=instrument.asset_type,
                db_path=db_path,
                target_years=target_years,
                end=end,
                refresh_recent_days=refresh_recent_days,
            )
        )
    return results


def _build_missing_ranges(
    *,
    target_start: date,
    target_end: date,
    coverage_start: Optional[str],
    coverage_end: Optional[str],
    refresh_recent_days: int,
) -> list[tuple[date, date]]:
    ranges: list[tuple[date, date]] = []
    existing_start = _parse_iso_date(coverage_start) if coverage_start else None
    existing_end = _parse_iso_date(coverage_end) if coverage_end else None

    if existing_start is None or existing_end is None:
        return [(target_start, target_end)]

    if existing_start > target_start:
        earlier_end = min(existing_start - timedelta(days=1), target_end)
        if target_start <= earlier_end:
            ranges.append((target_start, earlier_end))

    if existing_end < target_end:
        later_start = max(existing_end + timedelta(days=1), target_start)
        if later_start <= target_end:
            ranges.append((later_start, target_end))
    elif refresh_recent_days > 0:
        refresh_start = max(target_start, target_end - timedelta(days=refresh_recent_days))
        if refresh_start <= target_end:
            ranges.append((refresh_start, target_end))

    return ranges


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def _subtract_years(base_date: date, years: int) -> date:
    try:
        return base_date.replace(year=base_date.year - years)
    except ValueError:
        return base_date.replace(month=2, day=28, year=base_date.year - years)


def repair_factors(
    db_path: Path | str = DEFAULT_DB_PATH,
    *,
    target_years: int = 20,
    end: Optional[str] = None,
) -> list[SyncResult]:
    """修复所有非 INDEX 标的的复权因子和 adj_close。

    找到 has_real_factor=0 的 STOCK / ETF / FUND 标的，
    用修复后的 collector 全量重拉数据（同时获取不复权+复权数据，计算真实 factor），
    最后标记 has_real_factor=1。
    """
    db = MarketDataDB(db_path)
    db.init_db()
    db.seed_default_sources()

    instruments = db.get_instruments_needing_factor_repair()
    if not instruments:
        return []

    target_end = _parse_iso_date(end) if end else date.today()
    target_start = _subtract_years(target_end, target_years)

    results: list[SyncResult] = []
    for inst in instruments:
        try:
            frame = collect_history(
                symbol=inst["symbol"],
                market=inst["market"],
                asset_type=inst["asset_type"],
                start=target_start.isoformat(),
                end=target_end.isoformat(),
            )
            if frame.empty:
                continue
            instrument_id = int(inst["instrument_id"])
            row_count = db.upsert_daily_bars(instrument_id=instrument_id, frame=frame)
            db.rebuild_weekly_bars([instrument_id])
            db.set_has_real_factor(instrument_id, value=1)
            results.append(
                SyncResult(
                    instrument_id=instrument_id,
                    symbol=inst["symbol"],
                    market=inst["market"],
                    asset_type=inst["asset_type"],
                    row_count=row_count,
                )
            )
        except Exception as exc:
            logger.warning("repair_factors 跳过 %s (%s/%s): %s", inst["symbol"], inst["market"], inst["asset_type"], exc)
            continue

    return results


def seed_index_constituents(
    index_symbol: str,
    index_market: str = "CN",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    """抓取指数成分股列表并写入数据库。返回写入的标的数量。"""
    from .collectors import collect_index_constituents

    db = MarketDataDB(db_path)
    db.init_db()
    db.seed_default_sources()

    constituents = collect_index_constituents(index_symbol)
    if not constituents:
        return 0

    return db.upsert_constituents(index_symbol, index_market, constituents)


def batch_ensure_history(
    index_symbol: str,
    index_market: str = "CN",
    db_path: Path | str = DEFAULT_DB_PATH,
    *,
    target_years: int = 20,
    end: Optional[str] = None,
    refresh_recent_days: int = 14,
) -> list[SyncResult]:
    """批量采集指数成分股的历史数据，支持断点续传。"""
    import time as _time

    db = MarketDataDB(db_path)
    db.init_db()
    db.seed_default_sources()

    job_name = f"batch-{index_symbol}"
    all_constituents = db.get_constituents_without_data(index_symbol, index_market)
    if not all_constituents:
        checkpoint = db.get_checkpoint(job_name)
        if checkpoint and checkpoint["status"] == "DONE":
            print(f"batch-{index_symbol}: 全部已完成 ✓")
        return []

    # 检查断点：按代码字母序跳过已完成的
    checkpoint = db.get_checkpoint(job_name)
    total = len(all_constituents)
    if checkpoint:
        done_before = checkpoint["completed_count"]
        last_sym = checkpoint["last_symbol"] if checkpoint["last_symbol"] else ""
        if last_sym:
            remaining = [c for c in all_constituents if c["symbol"] > last_sym]
        else:
            # 老 checkpoint 没有 last_symbol，从已完成数估算
            remaining = all_constituents[done_before:]
        print(f"batch-{index_symbol}: 断点续传，已完成 {done_before}/{total}，剩余 {len(remaining)}")
    else:
        done_before = 0
        remaining = all_constituents
        db.create_checkpoint(job_name, total)
        print(f"batch-{index_symbol}: 开始采集，共 {total} 只标的")

    if not remaining:
        db.finish_checkpoint(job_name)
        return []

    results: list[SyncResult] = []
    ok_count = 0
    err_count = 0
    batch_start = _time.time()

    def _bar(current, tot, width=24):
        filled = int(width * current / tot) if tot > 0 else 0
        return "[" + "█" * filled + "░" * (width - filled) + "]"

    for i, inst in enumerate(remaining):
        try:
            t0 = _time.time()
            result = ensure_history_coverage(
                symbol=inst["symbol"],
                market=inst["market"],
                asset_type=inst["asset_type"],
                db_path=db_path,
                target_years=target_years,
                end=end,
                refresh_recent_days=refresh_recent_days,
            )
            results.append(result)
            db.update_checkpoint(job_name, int(inst["instrument_id"]), last_symbol=inst["symbol"])
            ok_count += 1
            elapsed = _time.time() - t0
        except Exception as exc:
            logger.warning("batch %s: 跳过 %s: %s", index_symbol, inst["symbol"], exc)
            err_count += 1
            elapsed = 0

        current = done_before + i + 1

        # 每 10 只或最后一只输出进度行
        if (current % 10 == 0) or (current == total):
            elapsed_total = _time.time() - batch_start
            processed = ok_count + err_count
            avg = elapsed_total / processed if processed > 0 else 0
            eta = avg * (total - current) if current < total else 0
            print(
                f"  {_bar(current, total)} "
                f"{current:4d}/{total} "
                f"{'✓' + str(ok_count):>5s}  "
                f"{'✗' + str(err_count):>5s}  "
                f"⌀{avg:.1f}s  "
                f"ETA {eta/60:.0f}m{eta%60:02.0f}s"
            )

    # 全部完成
    elapsed_total = _time.time() - batch_start
    print(f"\nbatch-{index_symbol}: 完成！成功 {ok_count} 只，失败 {err_count} 只，耗时 {elapsed_total/60:.1f} 分钟")

    remaining_check = db.get_constituents_without_data(index_symbol, index_market)
    if not remaining_check:
        db.finish_checkpoint(job_name)
        constituent_ids = db.get_constituent_ids(index_symbol, index_market)
        if constituent_ids:
            print(f"  正在重建周线数据（{len(constituent_ids)} 标的）...")
            db.rebuild_weekly_bars(constituent_ids)
            print(f"  周线已重建。可以运行 refresh-qlib 重建 qlib 数据")
    else:
        print(f"  仍有 {len(remaining_check)} 只未完成，可重新运行继续")

    return results


def update_stock_meta(
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    """批量更新所有 A 股个股的基本面元数据（市值/PE/PB/行业）。"""
    import time as _time
    from .collectors import collect_stock_meta

    db = MarketDataDB(db_path)
    db.init_db()
    db.seed_default_sources()

    stocks = db.get_stocks_without_meta()
    if not stocks:
        print("所有个股元数据已是最新 ✓")
        return 0

    total = len(stocks)
    print(f"开始采集元数据，共 {total} 只个股")
    ok = 0
    fail = 0
    t0 = _time.time()

    for i, inst in enumerate(stocks):
        try:
            meta = collect_stock_meta(inst["symbol"])
            if meta:
                db.upsert_meta(int(inst["instrument_id"]), meta)
                ok += 1
                status = "✓"
            else:
                fail += 1
                status = "✗(空)"
        except Exception:
            fail += 1
            status = "✗"

        if (i + 1) % 20 == 0 or (i + 1) == total:
            elapsed = _time.time() - t0
            avg = elapsed / (i + 1)
            eta = avg * (total - i - 1)
            print(f"  [{i+1:4d}/{total}] ✓{ok} ✗{fail}  ⌀{avg:.2f}s  ETA {eta/60:.0f}m{eta%60:02.0f}s")

        _time.sleep(0.3)

    print(f"\n元数据采集完成：成功 {ok} 只，失败 {fail} 只，耗时 {(_time.time()-t0)/60:.1f} 分钟")
    return ok


def update_financials(
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    """批量采集所有 A 股个股的财报数据（巨潮）。"""
    import time as _time
    from .collectors import collect_financials

    db = MarketDataDB(db_path)
    db.init_db()
    db.seed_default_sources()

    stocks = db.get_stocks_without_financials()
    if not stocks:
        print("所有个股财报已采集 ✓")
        return 0

    total = len(stocks)
    print(f"开始采集财报数据，共 {total} 只个股")
    ok = 0
    fail = 0
    t0 = _time.time()

    for i, inst in enumerate(stocks):
        try:
            records = collect_financials(inst["symbol"])
            if records:
                db.upsert_financials(int(inst["instrument_id"]), records)
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1

        if (i + 1) % 20 == 0 or (i + 1) == total:
            elapsed = _time.time() - t0
            avg = elapsed / (i + 1)
            eta = avg * (total - i - 1)
            print(f"  [{i+1:4d}/{total}] ✓{ok} ✗{fail}  ⌀{avg:.1f}s  ETA {eta/60:.0f}m{eta%60:02.0f}s")

        _time.sleep(0.5)

    print(f"\n财报采集完成：成功 {ok} 只，失败 {fail} 只，耗时 {(_time.time()-t0)/60:.1f} 分钟")
    return ok


def update_dividends(
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    """批量采集所有 A 股分红记录。"""
    import time as _time
    from .collectors import collect_dividends

    db = MarketDataDB(db_path)
    db.init_db()

    stocks = db.get_stocks_without_dividends()
    if not stocks:
        print("所有个股分红数据已采集 ✓")
        return 0

    total = len(stocks)
    print(f"开始采集中分红数据，共 {total} 只")
    ok = 0
    fail = 0
    total_records = 0
    t0 = _time.time()

    for i, inst in enumerate(stocks):
        try:
            records = collect_dividends(inst["symbol"])
            if records:
                n = db.upsert_dividends(int(inst["instrument_id"]), records)
                total_records += n
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1

        if (i + 1) % 30 == 0 or (i + 1) == total:
            elapsed = _time.time() - t0
            avg = elapsed / (i + 1)
            eta = avg * (total - i - 1)
            print(f"  [{i+1:4d}/{total}] ✓{ok} ✗{fail}  累计{total_records}条分红  ⌀{avg:.1f}s  ETA {eta/60:.0f}m{eta%60:02.0f}s")

        _time.sleep(0.3)

    print(f"\n分红采集完成：成功 {ok} 只，共 {total_records} 条记录，耗时 {(_time.time()-t0)/60:.1f} 分钟")
    return ok


def seed_trading_calendar(
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    """写入 A 股交易日历。"""
    from .collectors import collect_trading_calendar

    db = MarketDataDB(db_path)
    db.init_db()
    dates = collect_trading_calendar()
    if dates:
        n = db.seed_trading_calendar(dates)
        print(f"交易日历已写入：{n} 个交易日 ({dates[0]} ~ {dates[-1]})")
        return n
    return 0


def detect_suspensions(
    db_path: Path | str = DEFAULT_DB_PATH,
    min_gap: int = 3,
) -> int:
    """检测所有 A 股个股的停牌期（连续缺失交易日 >= min_gap 天视为停牌）。"""
    import time as _time

    db = MarketDataDB(db_path)
    db.init_db()

    # 加载交易日历
    all_dates = sorted(db.get_trading_dates("1990-01-01", "2030-12-31"))
    if not all_dates:
        print("错误：交易日历为空，请先运行 seed-trading-calendar")
        return 0
    date_set = set(all_dates)

    with db.connect() as conn:
        stocks = conn.execute(
            "SELECT i.* FROM instruments i JOIN instrument_meta m ON i.instrument_id=m.instrument_id"
        ).fetchall()

    total = len(stocks)
    print(f"检测停牌中，共 {total} 只个股 (最小连续缺失 {min_gap} 天)...")
    all_suspensions = []
    t0 = _time.time()

    for i, inst in enumerate(stocks):
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT trade_date FROM daily_bars WHERE instrument_id=? ORDER BY trade_date",
                (int(inst["instrument_id"]),)
            ).fetchall()
        existing = {r["trade_date"] for r in rows}
        if not existing:
            continue

        sym_dates = sorted(existing)
        first, last = sym_dates[0], sym_dates[-1]
        trading_dates = sorted(d for d in date_set if first <= d <= last)

        gaps = []
        gap_start = None
        prev = None
        for d in trading_dates:
            if d not in existing:
                if gap_start is None:
                    gap_start = d
            else:
                if gap_start is not None and prev is not None:
                    gap_len = (pd.to_datetime(d) - pd.to_datetime(gap_start)).days
                    if gap_len >= min_gap:
                        gaps.append((gap_start, prev, gap_len))
                gap_start = None
            prev = d

        for start, end, days in gaps:
            all_suspensions.append({
                "instrument_id": int(inst["instrument_id"]),
                "start_date": start,
                "end_date": end,
                "gap_days": days,
            })

        if (i + 1) % 100 == 0:
            elapsed = _time.time() - t0
            print(f"  [{i+1:4d}/{total}] 已处理，已发现 {len(all_suspensions)} 段停牌")

    if all_suspensions:
        db.upsert_suspensions(all_suspensions)
    elapsed = _time.time() - t0
    print(f"\n停牌检测完成：发现 {len(all_suspensions)} 段停牌，耗时 {elapsed:.1f} 秒")
    return len(all_suspensions)
