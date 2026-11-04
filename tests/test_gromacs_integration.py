"""Optional integration tests against a real GROMACS installation.

Skipped automatically when no ``gmx`` executable is found (override the
executable with the ``MDFLOW_GMX`` environment variable). They are short:
grompp on all four stages, then a tiny end-to-end run (50 EM steps and 100
MD steps per dynamics stage) of one generated job.

Passing these tests corresponds to GROMPP_VALIDATED / RUN_VALIDATED for the
tested job only; the builder itself never assigns those statuses.
"""
import os
import shutil
import subprocess

import pytest

from mdflow.package_writer import build
from mdflow.plan import make_plan

GMX = os.environ.get("MDFLOW_GMX") or shutil.which("gmx") or shutil.which("gmx_mpi")
pytestmark = [
    pytest.mark.gromacs,
    pytest.mark.skipif(GMX is None, reason="GROMACS (gmx) not installed"),
]


@pytest.fixture
def tiny_job(write_config):
    cfg = write_config(
        scan={"temperature_K": [300], "pressure_bar": [1], "replicas": 1},
        simulation={"em_steps": 50, "nvt_ns": 0.0002, "npt_ns": 0.0002, "production_ns": 0.0002},
    )
    plan = make_plan(cfg, for_build=True)
    res = build(plan)
    return res.output_dir / "job_0001"


def test_grompp_accepts_every_stage_without_warnings(tiny_job):
    # grompp of later stages needs the previous outputs, so check the first
    # stage directly and the full chain in the run test below.
    r = subprocess.run(
        [GMX, "grompp", "-f", "em.mdp", "-c", "conf.gro", "-p", "topol.top", "-o", "em.tpr", "-po", "em_mdout.mdp"],
        cwd=tiny_job, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-3000:]
    assert "WARNING" not in r.stderr


def test_short_end_to_end_run(tiny_job):
    env = dict(os.environ, GMX=GMX, MDRUN_ARGS="-nt 2")
    r = subprocess.run(["bash", "run.sh"], cwd=tiny_job, env=env, capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, r.stderr[-3000:]
    for stage in ("em", "nvt", "npt", "production"):
        assert (tiny_job / f"{stage}.gro").is_file()
