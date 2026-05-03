import importlib.util
import logging
import os
import time
from contextlib import contextmanager
from typing import Optional

import akshare as ak
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ---- mootdx 可选依赖 ----
_MOOTDX_AVAILABLE = importlib.util.find_spec("mootdx") is not None
_MOOTDX_CLIENT = None  # 惰性单例，同进程复用


def _is_mootdx_available() -> bool:
    return _MOOTDX_AVAILABLE


def _get_mootdx_client():
    """惰性获取 mootdx Quotes 客户端（单例，不复用 bestip）。"""
    global _MOOTDX_CLIENT
    if not _MOOTDX_AVAILABLE:
        raise RuntimeError("mootdx 未安装，无法使用通达信数据源。")
    if _MOOTDX_CLIENT is None:
        from mootdx.quotes import Quotes as _MQ

        _MOOTDX_CLIENT = _MQ.factory(market="std", timeout=15)
    return _MOOTDX_CLIENT


def _reset_mootdx_client():
    """连接异常时重置客户端。"""
    global _MOOTDX_CLIENT
    _MOOTDX_CLIENT = None


PROXY_ENV_VARS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
    "NO_PROXY",
    "no_proxy",
)


def _retry_akshare(fn, max_retries=3, backoff=2.0):
    """带重试的 AKShare 调用，应对东方财富临时维护或网络抖动。"""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                wait = backoff * (2 ** attempt)
                logger.warning("AKShare 调用失败 (第 %d/%d 次)，%s 秒后重试: %s", attempt + 1, max_retries, wait, exc)
                time.sleep(wait)
    raise last_exc


def _merge_raw_and_adjusted(raw_df: pd.DataFrame, adj_df: pd.DataFrame) -> pd.DataFrame:
    """合并 不复权 和 前复权/已调整 两份数据，计算出真实的 factor 和 adj_close。

    raw_df / adj_df 都是已 normalized 的 DataFrame，包含列：
    trade_date, open, high, low, close, volume, amount, adj_close, factor

    返回合并后的 DataFrame：
    - open/high/low/close/volume/amount 来自 raw_df（不复权原始值）
    - adj_close 来自 adj_df（复权后价格）
    - factor = adj_close / close（累积复权因子）
    """
    base_cols = ["trade_date", "open", "high", "low", "close", "volume", "amount"]
    result = raw_df[base_cols].copy()
    adj_close_df = adj_df[["trade_date", "close"]].rename(columns={"close": "_adj_close"})
    result = result.merge(adj_close_df, on="trade_date", how="inner")
    # 避免除零
    result["factor"] = (result["_adj_close"] / result["close"].replace(0, pd.NA)).fillna(1.0)
    result["adj_close"] = result["_adj_close"]
    result.drop(columns=["_adj_close"], inplace=True)
    return result[base_cols + ["adj_close", "factor"]]

US_INDEX_TICKER_MAP = {
    "NDX": "^NDX",
    "GSPC": "^GSPC",
}

CN_INDEX_TICKER_MAP = {
    "000300": "csi000300",
    "000510": "csi000510",
}

CN_INDEX_SINA_TICKER_MAP = {
    "000300": "sh000300",
    "000510": "sh000510",
}


@contextmanager
def _without_proxy_for_current_process():
    old_values = {name: os.environ.get(name) for name in PROXY_ENV_VARS}
    try:
        # 清空所有代理环境变量
        for proxy_var in PROXY_ENV_VARS:
            os.environ.pop(proxy_var, None)
        for extra in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
            os.environ.pop(extra, None)
        os.environ["http_proxy"] = ""
        os.environ["https_proxy"] = ""
        os.environ["HTTP_PROXY"] = ""
        os.environ["HTTPS_PROXY"] = ""

        # macOS 上 requests 会读系统代理设置（System Preferences → Network → Proxies），
        # 必须通过 trust_env=False 强制跳过。
        import requests as _requests
        _original_init = _requests.Session.__init__

        def _patched_init(self):
            _original_init(self)
            self.trust_env = False

        _requests.Session.__init__ = _patched_init
        yield
    finally:
        for name, value in old_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _requests.Session.__init__ = _original_init


def _sina_symbol(symbol: str) -> str:
    if symbol.startswith(("5", "6", "9")):
        return f"sh{symbol}"
    return f"sz{symbol}"


def _normalize_yfinance_columns(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        if symbol in df.columns.get_level_values(-1):
            df = df.xs(symbol, axis=1, level=-1)
        else:
            df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    df = df.rename(
        columns={
            "Date": "trade_date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Adj Close": "adj_close",
        }
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"]
    df["amount"] = pd.NA
    df["factor"] = 1.0
    return df[["trade_date", "open", "high", "low", "close", "volume", "amount", "adj_close", "factor"]]


def _normalize_index_em_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(
        columns={
            "date": "trade_date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "latest": "close",
            "volume": "volume",
            "amount": "amount",
        }
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    if "volume" not in df.columns:
        df["volume"] = pd.NA
    if "amount" not in df.columns:
        df["amount"] = pd.NA
    df["adj_close"] = df["close"]
    df["factor"] = 1.0
    return df[["trade_date", "open", "high", "low", "close", "volume", "amount", "adj_close", "factor"]]


def _normalize_cn_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(
        columns={
            "date": "trade_date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
            "日期": "trade_date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    df["adj_close"] = df["close"]
    df["factor"] = 1.0
    for column in ("amount", "volume"):
        if column not in df.columns:
            df[column] = pd.NA
    return df[["trade_date", "open", "high", "low", "close", "volume", "amount", "adj_close", "factor"]]


def _normalize_cn_stock_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(
        columns={
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "date": "trade_date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "volume": "volume",
            "amount": "amount",
        }
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    df["adj_close"] = df["close"]
    df["factor"] = 1.0
    for column in ("amount", "volume"):
        if column not in df.columns:
            df[column] = pd.NA
    return df[["trade_date", "open", "high", "low", "close", "volume", "amount", "adj_close", "factor"]]


def _normalize_mootdx_bars(df: pd.DataFrame) -> pd.DataFrame:
    """将 mootdx bars() 输出规范化为统一格式。

    mootdx bars() 列名: open/close/high/low/vol/amount，datetime 索引。
    bars() 同时在列中也包含 datetime/year/month/day/hour/minute（冗余列），
    需要先清理再 reset_index 避免列名冲突。
    不包含 adj_close 和 factor，由调用方后续合并。
    """
    # 清理冗余/冲突列：
    # - datetime 既是索引又是列，reset_index 会冲突
    # - year/month/day/hour/minute 是从 datetime 拆出来的冗余列
    # - volume 和 vol 同时存在，保留 vol（原始成交量），删除 volume（衍生列）
    extra_cols = ["datetime", "year", "month", "day", "hour", "minute", "volume"]
    for col in extra_cols:
        if col in df.columns:
            df = df.drop(columns=[col])
    df = df.reset_index().rename(
        columns={
            "datetime": "trade_date",
            "vol": "volume",
        }
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    for column in ("open", "high", "low", "close"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["volume"] = pd.to_numeric(df.get("volume", pd.NA), errors="coerce").fillna(0.0)
    df["amount"] = pd.to_numeric(df.get("amount", pd.NA), errors="coerce").fillna(pd.NA)
    df["adj_close"] = df["close"]
    df["factor"] = 1.0
    return df[["trade_date", "open", "high", "low", "close", "volume", "amount", "adj_close", "factor"]]


def _normalize_mootdx_qfq(df: pd.DataFrame) -> pd.DataFrame:
    """将 mootdx get_k_data(adjust='qfq') 输出规范化为统一格式。

    get_k_data 列名: open/close/high/low/volume/amount/date/code。
    date 同时作为索引（index name 可能为空字符串或 'date'）。
    返回的 close 是前复权价，作为 adj_close 使用。
    """
    # 清理可能冲突的列
    for col in ("date", "code"):
        if col in df.columns:
            df = df.drop(columns=[col])
    df = df.reset_index().rename(
        columns={
            "date": "trade_date",
            "vol": "volume",
        }
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    for column in ("open", "high", "low", "close"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["volume"] = pd.to_numeric(df.get("volume", pd.NA), errors="coerce").fillna(0.0)
    df["amount"] = pd.to_numeric(df.get("amount", pd.NA), errors="coerce").fillna(pd.NA)
    df["adj_close"] = df["close"]
    df["factor"] = 1.0
    return df[["trade_date", "open", "high", "low", "close", "volume", "amount", "adj_close", "factor"]]


def _collect_cn_stock_via_mootdx(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 mootdx 采集 A 股个股日线，同时获取不复权和前复权数据并计算真实 factor。

    等价于 akshare 的 CN STOCK 采集逻辑：
    - bars(frequency=4) → 不复权 raw
    - get_k_data(adjust='qfq') → 前复权
    - _merge_raw_and_adjusted → 最终 DataFrame
    """
    client = _get_mootdx_client()
    start_fmt = pd.to_datetime(start).strftime("%Y-%m-%d")
    end_fmt = pd.to_datetime(end).strftime("%Y-%m-%d")

    # 不复权日线
    df_raw = client.bars(symbol=symbol, frequency=4, offset=5000)
    raw_normalized = _normalize_mootdx_bars(df_raw)
    raw_normalized = raw_normalized[
        (raw_normalized["trade_date"] >= start_fmt) & (raw_normalized["trade_date"] <= end_fmt)
    ].copy()

    time.sleep(1.0)

    # 前复权日线
    df_qfq = client.get_k_data(symbol, start_date=start_fmt, end_date=end_fmt)
    qfq_normalized = _normalize_mootdx_qfq(df_qfq)

    merged = _merge_raw_and_adjusted(raw_normalized, qfq_normalized)
    logger.info(
        "CN STOCK %s (mootdx): merged %d raw + %d qfq rows → %d rows, factor range [%.4f, %.4f]",
        symbol,
        len(raw_normalized),
        len(qfq_normalized),
        len(merged),
        merged["factor"].min(),
        merged["factor"].max(),
    )
    return merged


def _collect_cn_index_via_mootdx(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 mootdx 采集 A 股指数日线。指数无需复权，factor=1.0。"""
    client = _get_mootdx_client()
    start_fmt = pd.to_datetime(start).strftime("%Y-%m-%d")
    end_fmt = pd.to_datetime(end).strftime("%Y-%m-%d")

    df = client.index(symbol=symbol, frequency=4, offset=5000)
    normalized = _normalize_mootdx_bars(df)
    normalized = normalized[
        (normalized["trade_date"] >= start_fmt) & (normalized["trade_date"] <= end_fmt)
    ].copy()
    logger.info("CN INDEX %s (mootdx): %d rows", symbol, len(normalized))
    return normalized


def _collect_cn_etf_via_mootdx(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 mootdx 采集 A 股 ETF 日线。ETF 用 bars 接口，factor=1.0。"""
    client = _get_mootdx_client()
    start_fmt = pd.to_datetime(start).strftime("%Y-%m-%d")
    end_fmt = pd.to_datetime(end).strftime("%Y-%m-%d")

    df = client.bars(symbol=symbol, frequency=4, offset=5000)
    normalized = _normalize_mootdx_bars(df)
    normalized = normalized[
        (normalized["trade_date"] >= start_fmt) & (normalized["trade_date"] <= end_fmt)
    ].copy()
    logger.info("CN ETF %s (mootdx): %d rows", symbol, len(normalized))
    return normalized


def collect_history(symbol: str, market: str, asset_type: str, start: str, end: str) -> pd.DataFrame:
    market = market.upper()
    asset_type = asset_type.upper()

    if market == "US" and asset_type == "INDEX":
        ticker = US_INDEX_TICKER_MAP.get(symbol.upper(), symbol.upper())
        df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        return _normalize_yfinance_columns(df, ticker)

    if market == "US":
        # yfinance is a pragmatic first collector for US ETFs and stocks.
        # 同时拉取 raw（auto_adjust=False）和 adjusted（auto_adjust=True），计算真实 factor。
        ticker = yf.Ticker(symbol)
        df_raw = ticker.history(start=start, end=end, auto_adjust=False)
        df_adj = ticker.history(start=start, end=end, auto_adjust=True)
        raw_normalized = _normalize_yfinance_columns(df_raw, symbol)
        adj_normalized = _normalize_yfinance_columns(df_adj, symbol)
        merged = _merge_raw_and_adjusted(raw_normalized, adj_normalized)
        logger.info(
            "US %s %s: merged %d raw + %d adj rows → %d rows, factor range [%.4f, %.4f]",
            asset_type,
            symbol,
            len(raw_normalized),
            len(adj_normalized),
            len(merged),
            merged["factor"].min(),
            merged["factor"].max(),
        )
        return merged

    if market == "CN" and asset_type == "INDEX":
        # 主采集器：akshare（东方财富 / 新浪）。失败时降级到 mootdx。
        try:
            with _without_proxy_for_current_process():
                try:
                    df = ak.stock_zh_index_daily_em(
                        symbol=CN_INDEX_TICKER_MAP.get(symbol.upper(), symbol.lower()),
                        start_date=pd.to_datetime(start).strftime("%Y%m%d"),
                        end_date=pd.to_datetime(end).strftime("%Y%m%d"),
                    )
                except Exception:
                    df = ak.stock_zh_index_daily(symbol=CN_INDEX_SINA_TICKER_MAP.get(symbol.upper(), f"sh{symbol}"))
            return _normalize_index_em_columns(df)
        except Exception as exc:
            if not _is_mootdx_available():
                raise
            logger.warning("CN INDEX %s: akshare 采集失败 (%s)，降级到 mootdx", symbol, exc)
            try:
                return _collect_cn_index_via_mootdx(symbol, start, end)
            except Exception as mdx_exc:
                _reset_mootdx_client()
                raise RuntimeError(
                    f"CN INDEX {symbol}: akshare 和 mootdx 均采集失败。"
                    f"akshare: {exc}; mootdx: {mdx_exc}"
                ) from mdx_exc

    if market == "HK" and asset_type == "INDEX":
        with _without_proxy_for_current_process():
            try:
                df = ak.stock_hk_index_daily_em(symbol=symbol.upper())
            except Exception:
                df = ak.stock_hk_index_daily_sina(symbol=symbol.upper())
        normalized = _normalize_index_em_columns(df)
        start_date = pd.to_datetime(start).strftime("%Y-%m-%d")
        end_date = pd.to_datetime(end).strftime("%Y-%m-%d")
        return normalized[
            (normalized["trade_date"] >= start_date) & (normalized["trade_date"] <= end_date)
        ].copy()

    if market == "CN" and asset_type in {"ETF", "FUND"}:
        # 主采集器：akshare（新浪 ETF 接口）。失败时降级到 mootdx。
        try:
            with _without_proxy_for_current_process():
                df = ak.fund_etf_hist_sina(symbol=_sina_symbol(symbol))
            start_date = pd.to_datetime(start).strftime("%Y-%m-%d")
            end_date = pd.to_datetime(end).strftime("%Y-%m-%d")
            normalized = _normalize_cn_columns(df)
            return normalized[
                (normalized["trade_date"] >= start_date) & (normalized["trade_date"] <= end_date)
            ].copy()
        except Exception as exc:
            if not _is_mootdx_available():
                raise
            logger.warning("CN ETF/FUND %s: akshare 采集失败 (%s)，降级到 mootdx", symbol, exc)
            try:
                return _collect_cn_etf_via_mootdx(symbol, start, end)
            except Exception as mdx_exc:
                _reset_mootdx_client()
                raise RuntimeError(
                    f"CN ETF/FUND {symbol}: akshare 和 mootdx 均采集失败。"
                    f"akshare: {exc}; mootdx: {mdx_exc}"
                ) from mdx_exc

    if market == "CN" and asset_type == "STOCK":
        # 主采集器：akshare（新浪接口）。失败时降级到 mootdx。
        try:
            sina_sym = _sina_symbol(symbol)
            with _without_proxy_for_current_process():
                start_fmt = pd.to_datetime(start).strftime("%Y%m%d")
                end_fmt = pd.to_datetime(end).strftime("%Y%m%d")

                def _fetch_raw():
                    return ak.stock_zh_a_daily(
                        symbol=sina_sym,
                        start_date=start_fmt, end_date=end_fmt,
                        adjust="",  # 不复权
                    )

                def _fetch_qfq():
                    return ak.stock_zh_a_daily(
                        symbol=sina_sym,
                        start_date=start_fmt, end_date=end_fmt,
                        adjust="qfq",  # 前复权
                    )

                df_raw = _retry_akshare(_fetch_raw)
                time.sleep(1.5)
                df_qfq = _retry_akshare(_fetch_qfq)
            raw_normalized = _normalize_cn_stock_columns(df_raw)
            qfq_normalized = _normalize_cn_stock_columns(df_qfq)
            merged = _merge_raw_and_adjusted(raw_normalized, qfq_normalized)
            logger.info(
                "CN STOCK %s: merged %d raw + %d qfq rows → %d rows, factor range [%.4f, %.4f]",
                symbol,
                len(raw_normalized),
                len(qfq_normalized),
                len(merged),
                merged["factor"].min(),
                merged["factor"].max(),
            )
            return merged
        except Exception as exc:
            if not _is_mootdx_available():
                raise
            logger.warning("CN STOCK %s: akshare 采集失败 (%s)，降级到 mootdx", symbol, exc)
            try:
                return _collect_cn_stock_via_mootdx(symbol, start, end)
            except Exception as mdx_exc:
                _reset_mootdx_client()
                raise RuntimeError(
                    f"CN STOCK {symbol}: akshare 和 mootdx 均采集失败。"
                    f"akshare: {exc}; mootdx: {mdx_exc}"
                ) from mdx_exc

    raise NotImplementedError(
        f"Collector not implemented for market={market}, asset_type={asset_type}. "
        "Current version supports CN/HK/US indexes and CN ETF/FUND/STOCK plus US ETF/STOCK/FUND."
    )


def collect_index_constituents(index_symbol: str) -> list[dict]:
    """获取指数成分股列表（当前时点）。返回 [{symbol, name, market}, ...]。"""
    with _without_proxy_for_current_process():
        try:
            df = ak.index_stock_cons(symbol=index_symbol)
        except Exception:
            # 部分指数用新浪接口
            df = ak.index_stock_cons_sina(symbol=index_symbol)

    # 列名在不同版本可能不同，统一处理
    col_map = {
        "品种代码": "symbol", "品种名称": "name",
        "code": "symbol", "name": "name",
        "stock_code": "symbol", "stock_name": "name",
        "成分券代码": "symbol", "成分券名称": "name",
        "constituent_code": "symbol", "constituent_name": "name",
    }
    existing = set(df.columns)
    rename = {k: v for k, v in col_map.items() if k in existing}
    df = df.rename(columns=rename)

    result = []
    for _, row in df.iterrows():
        sym = str(row.get("symbol", "")).strip()
        if not sym:
            continue
        result.append({
            "symbol": sym,
            "name": str(row.get("name", "")).strip() if row.get("name") and str(row.get("name")).strip() else None,
            "market": "CN",
            "asset_type": "STOCK",
        })
    logger.info("指数 %s 成分股: %d 只", index_symbol, len(result))
    return result


def collect_stock_meta(symbol: str) -> dict:
    """采集单只 A 股的基本面元数据（市值、PE、PB、行业），走雪球/巨潮接口。"""
    xq_symbol = _sina_symbol(symbol).upper()  # sh000001 → SH000001
    meta: dict = {}

    # 1. 雪球行情：PE / PB / 市值
    with _without_proxy_for_current_process():
        spot_df = ak.stock_individual_spot_xq(symbol=xq_symbol)
    if isinstance(spot_df, pd.DataFrame) and "item" in spot_df.columns:
        spot = dict(zip(spot_df["item"].astype(str), spot_df["value"]))
    else:
        spot = {}

    if spot:
        meta["pe_ttm"] = _safe_float(spot.get("市盈率(TTM)", spot.get("市盈率(动)")))
        meta["pb"] = _safe_float(spot.get("市净率"))
        meta["circulating_market_cap"] = _safe_float(spot.get("流通值"))
        meta["total_market_cap"] = _safe_float(spot.get("资产净值/总市值"))
        meta["circulating_shares"] = _safe_float(spot.get("流通股"))

    # 2. 雪球基本信息：行业分类
    with _without_proxy_for_current_process():
        time.sleep(0.3)
        info_df = ak.stock_individual_basic_info_xq(symbol=xq_symbol)
    if isinstance(info_df, pd.DataFrame) and "item" in info_df.columns:
        info = dict(zip(info_df["item"].astype(str), info_df["value"]))
    else:
        info = {}

    if info:
        industry = info.get("affiliate_industry")
        if isinstance(industry, dict):
            meta["industry_sw"] = str(industry.get("ind_name", "")).strip()

    return meta


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# 财务指标中文名 → 数据库列名的映射
_FINANCIAL_INDICATOR_MAP = {
    "营业总收入":           "revenue",
    "归母净利润":           "net_profit",
    "扣非净利润":           "net_profit_deducted",
    "股东权益合计(净资产)":    "total_equity",
    "经营现金流量净额":       "operating_cash_flow",
    "基本每股收益":         "eps",
    "每股净资产":           "bvps",
    "净资产收益率(ROE)":     "roe",
    "总资产报酬率(ROA)":     "roa",
    "毛利率":              "gross_margin",
    "销售净利率":            "net_margin",
    "资产负债率":            "debt_ratio",
}


def collect_financials(symbol: str) -> list[dict]:
    """采集单只 A 股的财报数据（巨潮），返回 [{report_period, ...}, ...]。"""
    with _without_proxy_for_current_process():
        df = ak.stock_financial_abstract(symbol=symbol)

    # df 结构: 选项, 指标, 20250331, 20241231, ...
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []

    period_cols = [c for c in df.columns if str(c).isdigit() and len(str(c)) == 8]
    if not period_cols:
        return []

    # 按报告期整理
    records_by_period: dict[str, dict] = {}
    for period in period_cols:
        records_by_period[str(period)] = {"report_period": str(period)}

    for _, row in df.iterrows():
        indicator = str(row.get("指标", "")).strip()
        col = _FINANCIAL_INDICATOR_MAP.get(indicator)
        if col is None:
            continue
        for period in period_cols:
            val = row.get(period)
            if val is not None and str(val).strip() not in ("", "--"):
                records_by_period[str(period)][col] = _safe_float(val)

    return list(records_by_period.values())


def collect_dividends(symbol: str) -> list[dict]:
    """采集单只 A 股的分红记录（巨潮）。返回 [{ex_date, cash_dividend, ...}, ...]。"""
    with _without_proxy_for_current_process():
        df = ak.stock_dividend_cninfo(symbol=symbol)

    if not isinstance(df, pd.DataFrame) or df.empty:
        return []

    records = []
    for _, row in df.iterrows():
        ex_date = str(row.get("除权日", "")).strip()
        if not ex_date or ex_date == "NaT":
            continue

        def _per10share(val):
            # 巨潮返回的是 "每10股" 的值
            v = _safe_float(val)
            return v / 10.0 if v else None  # 转为每股

        records.append({
            "ex_date": ex_date[:10] if len(ex_date) >= 10 else ex_date,
            "record_date": str(row.get("股权登记日", "")).strip()[:10],
            "pay_date": str(row.get("派息日", "")).strip()[:10] if str(row.get("派息日")).strip() != "NaT" else "",
            "cash_dividend": _per10share(row.get("派息比例")),
            "stock_dividend": _per10share(row.get("送股比例")),
            "transfer_ratio": _per10share(row.get("转增比例")),
            "announce_date": str(row.get("实施方案公告日期", "")).strip()[:10],
            "notes": str(row.get("分红类型", "")).strip() + " " + str(row.get("实施方案分红说明", "")).strip(),
        })
    return records


def collect_trading_calendar() -> list[str]:
    """获取 A 股交易日历列表。"""
    with _without_proxy_for_current_process():
        df = ak.tool_trade_date_hist_sina()
    if isinstance(df, pd.DataFrame) and not df.empty:
        col = df.columns[0]
        return sorted(df[col].astype(str).str.slice(0, 10).tolist())  # YYYY-MM-DD
    return []
