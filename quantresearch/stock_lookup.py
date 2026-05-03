from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd

from .constants import REFERENCE_DIR


CN_STOCK_CATALOG_PATH = REFERENCE_DIR / "cn_stock_catalog.csv"
CATALOG_COLUMNS = ["代码", "名称", "最新价", "涨跌幅", "成交额", "换手率", "总市值", "流通市值"]


def fetch_cn_stock_catalog() -> pd.DataFrame:
    df = ak.stock_zh_a_spot_em()
    if "代码" not in df.columns or "名称" not in df.columns:
        raise ValueError("Unexpected stock catalog shape from akshare.stock_zh_a_spot_em()")
    df = df.copy()
    df["代码"] = df["代码"].astype(str).str.zfill(6)
    keep_cols = [column for column in CATALOG_COLUMNS if column in df.columns]
    return df[keep_cols].sort_values(["代码", "名称"]).reset_index(drop=True)


def save_cn_stock_catalog(df: pd.DataFrame, path: Path | str = CN_STOCK_CATALOG_PATH) -> Path:
    output = Path(path)
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    return output


def load_cn_stock_catalog(path: Path | str = CN_STOCK_CATALOG_PATH) -> pd.DataFrame:
    catalog_path = Path(path)
    if not catalog_path.exists():
        raise FileNotFoundError(f"Stock catalog cache not found: {catalog_path}")
    df = pd.read_csv(catalog_path, dtype={"代码": str})
    df["代码"] = df["代码"].astype(str).str.zfill(6)
    return df


def get_cn_stock_catalog(refresh: bool = False, path: Path | str = CN_STOCK_CATALOG_PATH) -> pd.DataFrame:
    if refresh:
        df = fetch_cn_stock_catalog()
        save_cn_stock_catalog(df, path=path)
        return df
    try:
        return load_cn_stock_catalog(path=path)
    except FileNotFoundError:
        df = fetch_cn_stock_catalog()
        save_cn_stock_catalog(df, path=path)
        return df


def search_cn_stock_catalog(
    query: Optional[str] = None,
    *,
    refresh: bool = False,
    limit: Optional[int] = 20,
    path: Path | str = CN_STOCK_CATALOG_PATH,
) -> pd.DataFrame:
    df = get_cn_stock_catalog(refresh=refresh, path=path)
    if query:
        keyword = str(query).strip()
        code_mask = df["代码"].str.contains(keyword, regex=False, na=False)
        name_mask = df["名称"].astype(str).str.contains(keyword, regex=False, na=False)
        df = df[code_mask | name_mask].copy()
    if limit is not None:
        df = df.head(limit).copy()
    return df.reset_index(drop=True)
