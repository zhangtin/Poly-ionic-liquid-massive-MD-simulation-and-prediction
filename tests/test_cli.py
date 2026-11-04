import subprocess
import sys

from mdflow.cli import main

from conftest import EXAMPLE_CONFIG, REPO


def test_plan_writes_nothing(write_config, tmp_path, capsys):
    assert main(["plan", str(write_config())]) == 0
    out = capsys.readouterr().out
    assert "= 36 jobs" in out and "CONFIG_VALIDATED" in out
    assert "10,000,000 steps" in out
    assert not (tmp_path / "out").exists()


def test_plan_list(write_config, capsys):
    assert main(["plan", "--list", str(write_config())]) == 0
    assert "job_0036" in capsys.readouterr().out


def test_build_then_validate_then_refuse_rebuild(write_config, tmp_path, capsys):
    cfg = str(write_config())
    assert main(["build", cfg]) == 0
    assert "wrote 36 job packages" in capsys.readouterr().out
    assert main(["validate", cfg]) == 0
    assert "existing build" in capsys.readouterr().out
    assert main(["build", cfg]) == 1
    assert "OUTPUT_EXISTS" in capsys.readouterr().err
    assert main(["build", "--overwrite", cfg]) == 0


def test_validate_reports_all_errors(write_config, base_dir, capsys):
    (base_dir / "SHA256SUMS").unlink()
    (base_dir / "oplsaa.ff" / "spce.itp").unlink()
    cfg = write_config(scan={"temperature_K": [300, 300]})
    assert main(["validate", str(cfg)]) == 1
    err = capsys.readouterr().err
    assert "DEPENDENCY_MISSING" in err and "DUPLICATE_VALUE" in err


def test_validate_detects_edited_build(write_config, tmp_path, capsys):
    cfg = str(write_config())
    assert main(["build", cfg]) == 0
    (tmp_path / "out" / "job_0003" / "run.sh").write_text("#!/usr/bin/env bash\n")
    assert main(["validate", cfg]) == 1
    assert "job_0003" in capsys.readouterr().err


def test_console_script_and_shipped_example_plan():
    # the shipped example configuration must always be plannable
    res = subprocess.run(
        [sys.executable, "-m", "mdflow.cli", "plan", str(EXAMPLE_CONFIG)],
        capture_output=True, text=True, cwd="/",
    )
    assert res.returncode == 0, res.stderr
    assert "= 36 jobs" in res.stdout


def test_usage_error_exit_code():
    res = subprocess.run([sys.executable, "-m", "mdflow.cli"], capture_output=True, text=True)
    assert res.returncode == 2
