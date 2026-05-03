import os
from pathlib import Path
from typing import Optional

import pandas as pd
import pywencai


DEFAULT_COOKIE_ENV = "WENCAI_COOKIE"


def resolve_wencai_cookie(cookie: Optional[str] = None, cookie_env: str = DEFAULT_COOKIE_ENV) -> str:
    if cookie:
        return cookie
    env_cookie = os.environ.get(cookie_env, "").strip()
    if env_cookie:
        return env_cookie
    raise ValueError(
        "Missing iWenCai cookie. Set the WENCAI_COOKIE environment variable or pass cookie=... explicitly."
    )


def query_wencai(
    query: str,
    *,
    cookie: Optional[str] = None,
    cookie_env: str = DEFAULT_COOKIE_ENV,
    sort_key: Optional[str] = None,
    sort_order: str = "desc",
    perpage: int = 100,
    loop: bool | int = False,
) -> pd.DataFrame:
    resolved_cookie = resolve_wencai_cookie(cookie=cookie, cookie_env=cookie_env)
    kwargs = {
        "query": query,
        "cookie": resolved_cookie,
        "perpage": perpage,
        "loop": loop,
    }
    if sort_key:
        kwargs["sort_key"] = sort_key
        kwargs["sort_order"] = sort_order
    result = pywencai.get(**kwargs)
    if result is None:
        return pd.DataFrame()
    if isinstance(result, pd.DataFrame):
        return result
    return pd.DataFrame(result)


def save_wencai_result(df: pd.DataFrame, output_path: Path | str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)
    return path


def standardize_wencai_etf_result(df: pd.DataFrame, source_query: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["symbol", "name", "market", "asset_type", "exchange", "source_query"])

    code_col = _pick_first_existing(df, ["基金代码", "证券代码", "股票代码", "code", "代码"])
    name_col = _pick_first_existing(df, ["基金简称", "证券简称", "股票简称", "name", "名称"])
    if code_col is None or name_col is None:
        raise ValueError("Could not find ETF code/name columns in iWenCai result.")

    standardized = pd.DataFrame()
    standardized["symbol"] = df[code_col].astype(str).str.extract(r"(\d{6})", expand=False).fillna(df[code_col].astype(str))
    standardized["symbol"] = standardized["symbol"].str.zfill(6)
    standardized["name"] = df[name_col].astype(str)
    standardized["market"] = standardized["symbol"].map(_infer_cn_market)
    standardized["asset_type"] = "ETF"
    standardized["exchange"] = standardized["market"].map({"CN": None})
    standardized.loc[standardized["symbol"].str.startswith(("5", "6", "9")), "exchange"] = "SH"
    standardized.loc[standardized["symbol"].str.startswith(("0", "1", "2", "3")), "exchange"] = "SZ"
    standardized["source_query"] = source_query
    standardized = standardized.drop_duplicates(subset=["symbol", "name"]).reset_index(drop=True)
    return standardized


def _pick_first_existing(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _infer_cn_market(symbol: str) -> str:
    return "CN"
