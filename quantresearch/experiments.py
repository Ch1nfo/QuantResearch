from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .constants import DEFAULT_DATASET_NAME, EXPERIMENT_LOG_PATH, QLIB_RECORDS_DIR
from .serialization import to_jsonable


def record_experiment(
    *,
    kind: str,
    payload: dict,
    dataset_name: str = DEFAULT_DATASET_NAME,
    markdown_path: Path | str | None = None,
    json_path: Path | str | None = None,
) -> dict:
    record = {
        "experiment_id": _new_experiment_id(kind),
        "kind": kind,
        "created_at": _utc_now(),
        "dataset_name": dataset_name,
        "markdown_path": str(markdown_path) if markdown_path else None,
        "json_path": str(json_path) if json_path else None,
        "payload": to_jsonable(payload),
        "recorder_status": "not_attempted",
        "recorder_error": None,
    }
    recorder_status, recorder_error = _try_record_with_qlib(record)
    record["recorder_status"] = recorder_status
    record["recorder_error"] = recorder_error
    _append_jsonl(record)
    return record


def list_experiments(kind: str | None = None, limit: int = 20) -> list[dict]:
    records = _read_jsonl()
    if kind:
        records = [record for record in records if record.get("kind") == kind]
    return records[-limit:][::-1]


def show_experiment(experiment_id: str) -> dict | None:
    for record in reversed(_read_jsonl()):
        if record.get("experiment_id") == experiment_id:
            return record
    return None


def _append_jsonl(record: dict) -> None:
    QLIB_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    with EXPERIMENT_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(to_jsonable(record), ensure_ascii=False) + "\n")


def _read_jsonl() -> list[dict]:
    if not EXPERIMENT_LOG_PATH.exists():
        return []
    records = []
    for line in EXPERIMENT_LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _try_record_with_qlib(record: dict) -> tuple[str, str | None]:
    try:
        from qlib.workflow import R
        from qlib.workflow.recorder import MLflowRecorder

        original_log_code = MLflowRecorder._log_uncommitted_code
        MLflowRecorder._log_uncommitted_code = lambda self: None
        recorder_uri = str((QLIB_RECORDS_DIR / "mlruns").resolve())
        QLIB_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=FutureWarning, module="mlflow.*")
                with R.start(
                    experiment_name=f"quantresearch_{record['kind']}",
                    recorder_name=record["experiment_id"],
                    uri=recorder_uri,
                ):
                    payload = record.get("payload", {})
                    params = {
                        "kind": record["kind"],
                        "dataset_name": record["dataset_name"],
                        "markdown_path": record.get("markdown_path"),
                        "json_path": record.get("json_path"),
                    }
                    for key in ("symbol", "market", "asset_type", "as_of", "start", "end", "strategies"):
                        if key in payload:
                            params[key] = str(payload[key])
                    R.log_params(**{key: value for key, value in params.items() if value is not None})
                    metrics = _extract_float_metrics(payload)
                    if metrics:
                        R.log_metrics(**metrics)
        finally:
            MLflowRecorder._log_uncommitted_code = original_log_code
        return "qlib_recorder", None
    except Exception as exc:
        return "jsonl_fallback", str(exc)


def _extract_float_metrics(payload: dict) -> dict[str, float]:
    metrics = {}
    raw_metrics = payload.get("metrics")
    if not isinstance(raw_metrics, dict):
        return metrics
    for strategy, values in raw_metrics.items():
        if not isinstance(values, dict):
            continue
        for metric_name, value in values.items():
            if isinstance(value, (int, float)) and value == value:
                safe_key = f"{strategy}_{metric_name}".replace(" ", "_").replace("/", "_")
                metrics[safe_key] = float(value)
    return metrics


def _new_experiment_id(kind: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_{kind}_{uuid4().hex[:8]}"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
