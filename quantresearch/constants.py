from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXPORT_DIR = DATA_DIR / "exports"
PARQUET_EXPORT_DIR = EXPORT_DIR / "parquet"
QLIB_CSV_EXPORT_DIR = EXPORT_DIR / "qlib_csv"
QLIB_DATA_DIR = DATA_DIR / "qlib_data"
QLIB_RECORDS_DIR = DATA_DIR / "qlib_records"
REFERENCE_DIR = DATA_DIR / "reference"
REPORTS_DIR = PROJECT_ROOT / "reports"
SIGNALS_DIR = REPORTS_DIR / "signals"
DECISIONS_DIR = REPORTS_DIR / "decisions"
AGENT_PLAYBOOKS_DIR = PROJECT_ROOT / "agent_playbooks"
DEFAULT_DB_PATH = DATA_DIR / "market_data.sqlite3"
DEFAULT_DATASET_NAME = "mixed_etf_stock_fund_day"
CN_ETF_CATALOG_PATH = REFERENCE_DIR / "cn_etf_catalog.csv"
EXPERIMENT_LOG_PATH = QLIB_RECORDS_DIR / "experiments.jsonl"

SUPPORTED_MARKETS = {"CN", "US", "HK"}
SUPPORTED_ASSET_TYPES = {"ETF", "STOCK", "FUND", "INDEX"}
