"""Shared fixtures.

Every test works on a private copy of the example base project inside
``tmp_path`` so tests may freely break it without touching the real one.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
EXAMPLE_BASE = REPO / "examples" / "base_gromacs"
EXAMPLE_CONFIG = REPO / "configs" / "scan.example.yaml"

ACCEPTANCE = {
    "project": "water_scan_001",
    "base_project": "base",
    "scan": {"temperature_K": [280, 300, 320, 340], "pressure_bar": [1, 10, 50], "replicas": 3},
    "simulation": {"timestep_fs": 2.0, "em_steps": 50000, "nvt_ns": 1.0, "npt_ns": 5.0, "production_ns": 20.0},
    "output": {"directory": "out"},
}


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    dst = tmp_path / "base"
    shutil.copytree(EXAMPLE_BASE, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


@pytest.fixture
def write_config(tmp_path: Path, base_dir: Path):
    """write_config(**overrides) -> path. Nested dicts are merged one level deep."""

    def _write(name: str = "scan.yaml", **overrides) -> Path:
        cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in ACCEPTANCE.items()}
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
        path = tmp_path / name
        path.write_text(yaml.safe_dump(cfg, sort_keys=False))
        return path

    return _write


def tree_digest(root: Path, exclude: set[str] = frozenset()) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.relative_to(root).as_posix() not in exclude
    }
