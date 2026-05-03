from __future__ import annotations

from pathlib import Path

import pandas as pd

from .constants import DEFAULT_DATASET_NAME, DEFAULT_DB_PATH, QLIB_CSV_EXPORT_DIR, QLIB_DATA_DIR
from .database import MarketDataDB


def check_qlib_consistency(
    *,
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
    qlib_dir: Path | str | None = None,
) -> dict:
    expected = sorted(sqlite_qlib_symbols(db_path=db_path))
    csv_symbols = sorted(qlib_csv_symbols(dataset_name=dataset_name))
    bin_symbols = sorted(qlib_bin_symbols(dataset_name=dataset_name, qlib_dir=qlib_dir))
    expected_set = set(expected)
    csv_set = set(csv_symbols)
    bin_set = set(bin_symbols)
    return {
        "ok": expected_set == csv_set == bin_set,
        "dataset_name": dataset_name,
        "sqlite_symbols": expected,
        "csv_symbols": csv_symbols,
        "bin_symbols": bin_symbols,
        "missing_in_csv": sorted(expected_set - csv_set),
        "extra_in_csv": sorted(csv_set - expected_set),
        "missing_in_bin": sorted(expected_set - bin_set),
        "extra_in_bin": sorted(bin_set - expected_set),
    }


def sqlite_qlib_symbols(db_path: Path | str = DEFAULT_DB_PATH) -> list[str]:
    db = MarketDataDB(db_path)
    with db.connect() as conn:
        frame = pd.read_sql_query(
            """
            SELECT DISTINCT i.market || '_' || i.symbol AS qlib_symbol
            FROM instruments i
            JOIN daily_bars b ON b.instrument_id = i.instrument_id
            WHERE i.status = 'ACTIVE'
            ORDER BY qlib_symbol
            """,
            conn,
        )
    if frame.empty:
        return []
    return [str(item).upper() for item in frame["qlib_symbol"].tolist()]


def qlib_csv_symbols(dataset_name: str = DEFAULT_DATASET_NAME) -> list[str]:
    csv_dir = QLIB_CSV_EXPORT_DIR / dataset_name
    if not csv_dir.exists():
        return []
    return sorted(path.stem.upper() for path in csv_dir.glob("*.csv"))


def qlib_bin_symbols(dataset_name: str = DEFAULT_DATASET_NAME, qlib_dir: Path | str | None = None) -> list[str]:
    dataset_dir = Path(qlib_dir) if qlib_dir else (QLIB_DATA_DIR / dataset_name)
    feature_dir = dataset_dir / "features"
    if not feature_dir.exists():
        return []
    return sorted(path.name.upper() for path in feature_dir.iterdir() if path.is_dir())


def format_consistency_report(result: dict) -> str:
    status = "通过" if result["ok"] else "失败"
    lines = [
        f"qlib 数据一致性检查：{status}",
        f"数据集：{result['dataset_name']}",
        f"SQLite 标的数：{len(result['sqlite_symbols'])}",
        f"CSV 标的数：{len(result['csv_symbols'])}",
        f"Bin 标的数：{len(result['bin_symbols'])}",
    ]
    for key, label in (
        ("missing_in_csv", "CSV 缺失"),
        ("extra_in_csv", "CSV 多余"),
        ("missing_in_bin", "Bin 缺失"),
        ("extra_in_bin", "Bin 多余"),
    ):
        values = result.get(key) or []
        lines.append(f"{label}：{', '.join(values) if values else '无'}")
    return "\n".join(lines)
