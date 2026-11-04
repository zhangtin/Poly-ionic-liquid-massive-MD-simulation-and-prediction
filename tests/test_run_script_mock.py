"""Exercise generated run.sh files against a *mock* ``gmx`` executable.

The mock checks that every input file passed to grompp/mdrun exists and
writes the outputs the real programs would write, so the stage chaining,
working-directory handling and error propagation of run.sh are tested
without GROMACS. This is NOT a GROMACS validation: no physics is computed and
no MDP option is interpreted.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

from mdflow.package_writer import build
from mdflow.plan import make_plan

MOCK = r'''#!/usr/bin/env python3
import os, sys
from pathlib import Path
log = Path(os.environ["MOCK_LOG"])
args = sys.argv[1:]
with log.open("a") as fh:
    fh.write(os.getcwd() + " :: " + " ".join(args) + "\n")
if args == ["--version"]:
    print("                 :-) GROMACS - gmx, %s (-:\n" % os.environ.get("MOCK_VERSION", "2025.5"))
    print("GROMACS version:    %s" % os.environ.get("MOCK_VERSION", "2025.5"))
    sys.exit(0)
cmd, opts = args[0], args[1:]
def opt(flag):
    return opts[opts.index(flag) + 1] if flag in opts else None
if cmd == "grompp":
    for flag in ("-f", "-c", "-p", "-t"):
        f = opt(flag)
        if f is not None and not Path(f).is_file():
            sys.stderr.write("grompp: missing input %s %s\n" % (flag, f)); sys.exit(2)
    if os.environ.get("MOCK_FAIL") == opt("-f"):
        sys.stderr.write("Fatal error (mock)\n"); sys.exit(3)
    Path(opt("-o")).write_text("tpr")
    Path(opt("-po")).write_text("mdout")
elif cmd == "mdrun":
    name = opt("-deffnm")
    if not Path(name + ".tpr").is_file():
        sys.stderr.write("mdrun: no tpr\n"); sys.exit(2)
    for ext in (".gro", ".cpt", ".log", ".edr"):
        Path(name + ext).write_text(ext)
else:
    sys.exit(64)
'''


@pytest.fixture
def built(write_config, tmp_path):
    cfg = write_config(scan={"temperature_K": [300], "pressure_bar": [1], "replicas": 2})
    plan = make_plan(cfg, for_build=True)
    build(plan)
    mock = tmp_path / "bin" / "gmx"
    mock.parent.mkdir()
    mock.write_text(MOCK)
    mock.chmod(mock.stat().st_mode | stat.S_IEXEC)
    return tmp_path / "out", mock


def _run(job_dir: Path, mock: Path, log: Path, **env):
    e = dict(os.environ, GMX=str(mock), MOCK_LOG=str(log), **env)
    # run from an unrelated working directory: run.sh must cd to its own dir
    return subprocess.run(["bash", str(job_dir / "run.sh")], cwd="/", env=e, capture_output=True, text=True)


def test_stage_chain_with_mock(built, tmp_path):
    out, mock = built
    job = out / "job_0001"
    log = tmp_path / "log.txt"
    res = _run(job, mock, log, MDRUN_ARGS="-nt 2 -pin on")
    assert res.returncode == 0, res.stderr
    calls = [l.split(" :: ")[1] for l in log.read_text().splitlines()]
    cwds = {l.split(" :: ")[0] for l in log.read_text().splitlines()}
    assert cwds == {str(job.resolve())}
    assert calls == [
        "--version",
        "grompp -f em.mdp -c conf.gro -p topol.top -po em_mdout.mdp -o em.tpr",
        "mdrun -deffnm em -nt 2 -pin on",
        "grompp -f nvt.mdp -c em.gro -p topol.top -po nvt_mdout.mdp -o nvt.tpr",
        "mdrun -deffnm nvt -nt 2 -pin on",
        "grompp -f npt.mdp -c nvt.gro -t nvt.cpt -p topol.top -po npt_mdout.mdp -o npt.tpr",
        "mdrun -deffnm npt -nt 2 -pin on",
        "grompp -f production.mdp -c npt.gro -t npt.cpt -p topol.top -po production_mdout.mdp -o production.tpr",
        "mdrun -deffnm production -nt 2 -pin on",
    ]


def test_empty_mdrun_args(built, tmp_path):
    out, mock = built
    log = tmp_path / "log.txt"
    res = _run(out / "job_0002", mock, log)
    assert res.returncode == 0, res.stderr
    assert "mdrun -deffnm em\n" in log.read_text()


def test_error_exit_code_propagates(built, tmp_path):
    out, mock = built
    log = tmp_path / "log.txt"
    res = _run(out / "job_0001", mock, log, MOCK_FAIL="npt.mdp")
    assert res.returncode == 3
    assert "production" not in log.read_text()


def test_old_gromacs_rejected(built, tmp_path):
    out, mock = built
    res = _run(out / "job_0001", mock, tmp_path / "log.txt", MOCK_VERSION="2020.7")
    assert res.returncode == 1
    assert "GROMACS >= 2021 required" in res.stderr


def test_missing_gmx(built, tmp_path):
    out, _ = built
    res = _run(out / "job_0001", Path("/nonexistent/gmx"), tmp_path / "log.txt")
    assert res.returncode == 127
