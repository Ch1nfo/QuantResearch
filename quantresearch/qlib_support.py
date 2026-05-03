import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .constants import DEFAULT_DATASET_NAME, PROJECT_ROOT, QLIB_CSV_EXPORT_DIR, QLIB_DATA_DIR


DEFAULT_QLIB_REPO_CANDIDATES = [
    PROJECT_ROOT / "vendor" / "qlib",
    PROJECT_ROOT.parent / "qlib",
]


def resolve_dump_bin_script(qlib_repo: Optional[Path | str] = None) -> Path:
    if qlib_repo:
        script = Path(qlib_repo) / "scripts" / "dump_bin.py"
        if script.exists():
            return script
        raise FileNotFoundError(f"dump_bin.py not found under qlib repo: {script}")

    env_repo = os.environ.get("QLIB_REPO")
    if env_repo:
        script = Path(env_repo) / "scripts" / "dump_bin.py"
        if script.exists():
            return script

    spec = importlib.util.find_spec("qlib")
    if spec is None or spec.origin is None:
        return _resolve_dump_bin_from_known_locations()

    site_pkg = Path(spec.origin).resolve().parent.parent
    candidate = site_pkg / "scripts" / "dump_bin.py"
    if candidate.exists():
        return candidate

    return _resolve_dump_bin_from_known_locations()


def build_qlib_bin(
    dataset_name: str = DEFAULT_DATASET_NAME,
    qlib_repo: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    clean: bool = False,
    mode: str = "all",
) -> Path:
    """构建 qlib .bin 数据集。

    mode:
      - "all":    全量重建（默认），对应 dump_bin.py dump_all
      - "fix":    增量修复，只添加新标的，对应 dump_bin.py dump_fix
      - "update": 增量更新，为已有标的追加新日期数据，对应 dump_bin.py dump_update
    """
    if mode not in ("all", "fix", "update"):
        raise ValueError(f"不支持的模式：{mode}，可选 all / fix / update")

    script = resolve_dump_bin_script(qlib_repo)
    csv_dir = QLIB_CSV_EXPORT_DIR / dataset_name
    qlib_dir = Path(output_dir) if output_dir else (QLIB_DATA_DIR / dataset_name)

    if mode == "all" and clean:
        shutil.rmtree(qlib_dir, ignore_errors=True)
    qlib_dir.mkdir(parents=True, exist_ok=True)

    fire_command = {"all": "dump_all", "fix": "dump_fix", "update": "dump_update"}[mode]

    subprocess.run(
        [
            sys.executable,
            str(script),
            fire_command,
            "--data_path",
            str(csv_dir),
            "--qlib_dir",
            str(qlib_dir),
            "--freq",
            "day",
            "--max_workers",
            "1",
            "--include_fields",
            "open,close,high,low,volume,factor",
            "--date_field_name",
            "date",
            "--symbol_field_name",
            "symbol",
        ],
        check=True,
    )
    return qlib_dir


def _resolve_dump_bin_from_known_locations() -> Path:
    for repo in DEFAULT_QLIB_REPO_CANDIDATES:
        script = repo / "scripts" / "dump_bin.py"
        if script.exists():
            return script
    searched = ", ".join(str(path) for path in DEFAULT_QLIB_REPO_CANDIDATES)
    raise RuntimeError(
        "没有找到 qlib 的 scripts/dump_bin.py。"
        "可以通过 --qlib-repo 指定官方 qlib 仓库，"
        "或者设置环境变量 QLIB_REPO。"
        f"已搜索路径：{searched}"
    )
