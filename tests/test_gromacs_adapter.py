"""GROMACS parameter mapping, template checks, topology dependencies, run script."""
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from mdflow.errors import MdflowError
from mdflow.gromacs_adapter import (
    check_rendered_mdp,
    parse_mdp,
    render_run_script,
    render_stages,
    resolve_topology_includes,
    stage_context,
)
from mdflow.plan import make_plan
from mdflow.schemas import SimulationConfig
from mdflow.simulation_spec import Protocol, SimulationSpec


@pytest.fixture
def spec():
    proto = Protocol.from_config(
        SimulationConfig(timestep_fs=2.0, em_steps=50000, nvt_ns=1.0, npt_ns=5.0, production_ns=20.0)
    )
    return SimulationSpec(Decimal("300"), Decimal("10"), 2, 123456789, proto)


def _templates(base_dir: Path):
    return {s: base_dir / "mdp" / f"{s}.mdp.j2" for s in ("em", "nvt", "npt", "production")}


# --- parameter mapping -------------------------------------------------------
def test_stage_context_units_and_scoping(spec):
    em, nvt, npt, prod = spec.stages
    assert stage_context(spec, em) == {"nsteps": 50000}  # no T/P in EM
    assert stage_context(spec, nvt) == {
        "nsteps": 500_000, "dt_ps": "0.002", "temperature_K": "300", "random_seed": 123456789,
    }  # no pressure in NVT
    assert stage_context(spec, npt)["pressure_bar"] == "10"
    assert stage_context(spec, prod)["nsteps"] == 10_000_000


def test_rendered_mdps_carry_scan_values(spec, base_dir):
    rendered = {r.stage.name: parse_mdp(r.text) for r in render_stages(spec, _templates(base_dir))}
    em, nvt, npt, prod = (rendered[k] for k in ("em", "nvt", "npt", "production"))
    assert em["integrator"] == "steep" and em["nsteps"] == "50000"
    assert "ref-t" not in em and "ref-p" not in em
    assert nvt["dt"] == "0.002" and nvt["nsteps"] == "500000"
    assert nvt["ref-t"] == nvt["gen-temp"] == "300"
    assert nvt["gen-vel"] == "yes" and nvt["gen-seed"] == nvt["ld-seed"] == "123456789"
    assert nvt["pcoupl"] == "no"
    assert npt["pcoupl"] == "C-rescale" and npt["ref-p"] == "10" and npt["nsteps"] == "2500000"
    assert npt["gen-vel"] == "no" and npt["continuation"] == "yes"
    assert prod["nsteps"] == "10000000" and prod["ref-p"] == "10" and prod["ld-seed"] == "123456789"


def test_production_ensemble_inherited_from_base(spec, base_dir):
    prod = [r for r in render_stages(spec, _templates(base_dir)) if r.stage.name == "production"][0]
    assert prod.ensemble == "NPT"


def test_parse_mdp_normalizes_and_detects_duplicates():
    assert parse_mdp("Ref_T = 300 ; comment\n\n; x\nnsteps=5")["ref-t"] == "300"
    with pytest.raises(MdflowError) as exc:
        parse_mdp("ref_t = 300\nref-t = 310\n")
    assert exc.value.codes == {"MDP_DUPLICATE_KEY"}


# --- mapping consistency checks on broken templates ---------------------------
def _edit(base_dir, stage, old, new):
    p = base_dir / "mdp" / f"{stage}.mdp.j2"
    text = p.read_text()
    assert old in text
    p.write_text(text.replace(old, new))


@pytest.mark.parametrize(
    "stage, old, new, code",
    [
        ("nvt", "ref-t                   = {{ temperature_K }}", "ref-t = 310\n; {{ temperature_K }}", "MDP_MAPPING_MISMATCH"),
        ("nvt", "pcoupl                  = no", "pcoupl = C-rescale", "MDP_ENSEMBLE_MISMATCH"),
        ("npt", "pcoupl                  = C-rescale", "pcoupl = no", "MDP_ENSEMBLE_MISMATCH"),
        ("npt", "gen-vel                 = no", "gen-vel = yes\ngen-seed = {{ random_seed }}", "MDP_DISCARDS_STATE"),
        ("npt", "ld-seed                 = {{ random_seed }}", "; no seed", "MDP_UNSEEDED"),
        ("production", "ld-seed                 = {{ random_seed }}", "ld-seed = 42", "MDP_MAPPING_MISMATCH"),
        ("nvt", "tcoupl                  = V-rescale", "tcoupl = no", "MDP_NO_THERMOSTAT"),
        ("npt", "pcoupltype              = isotropic", "pcoupltype = semiisotropic", "MDP_UNSUPPORTED"),
        ("em", "integrator              = steep", "integrator = md", "MDP_WRONG_INTEGRATOR"),
    ],
)
def test_broken_templates_detected(spec, base_dir, stage, old, new, code):
    _edit(base_dir, stage, old, new)
    with pytest.raises(MdflowError) as exc:
        render_stages(spec, _templates(base_dir))
    assert code in exc.value.codes


def test_template_unknown_variable(spec, base_dir):
    _edit(base_dir, "em", "emtol                   = 1000.0", "emtol = {{ tolerance }}")
    with pytest.raises(MdflowError) as exc:
        render_stages(spec, _templates(base_dir))
    assert "TEMPLATE_UNKNOWN_VARIABLE" in exc.value.codes


def test_em_template_may_not_use_temperature(spec, base_dir):
    _edit(base_dir, "em", "emtol                   = 1000.0", "emtol = 1000.0\nref-t = {{ temperature_K }}")
    with pytest.raises(MdflowError) as exc:
        render_stages(spec, _templates(base_dir))
    assert "TEMPLATE_UNKNOWN_VARIABLE" in exc.value.codes


def test_template_missing_required_variable(spec, base_dir):
    _edit(base_dir, "npt", "ref-p                   = {{ pressure_bar }}", "ref-p = 1.0")
    with pytest.raises(MdflowError) as exc:
        render_stages(spec, _templates(base_dir))
    assert "TEMPLATE_MISSING_VARIABLE" in exc.value.codes


def test_template_syntax_error(spec, base_dir):
    _edit(base_dir, "em", "nsteps                  = {{ nsteps }}", "nsteps = {{ nsteps ")
    with pytest.raises(MdflowError) as exc:
        render_stages(spec, _templates(base_dir))
    assert "TEMPLATE_SYNTAX_ERROR" in exc.value.codes


def test_unrendered_markup_detected(spec, base_dir):
    _edit(base_dir, "em", "emtol                   = 1000.0", "emtol = {{ '{{' }} 1000")
    with pytest.raises(MdflowError) as exc:
        render_stages(spec, _templates(base_dir))
    assert "TEMPLATE_UNRENDERED" in exc.value.codes


def test_missing_template(spec, base_dir):
    (base_dir / "mdp" / "npt.mdp.j2").unlink()
    with pytest.raises(MdflowError) as exc:
        render_stages(spec, _templates(base_dir))
    assert exc.value.codes == {"TEMPLATE_MISSING"}


def test_check_rendered_mdp_rejects_wrong_nsteps(spec):
    nvt = spec.stages[1]
    params = {"integrator": "md", "dt": "0.002", "nsteps": "499999", "tcoupl": "berendsen", "ref-t": "300"}
    issues = check_rendered_mdp(nvt, params, spec, "x")
    assert [i.code for i in issues] == ["MDP_MAPPING_MISMATCH"]


# --- topology dependencies -----------------------------------------------------
def test_topology_dependency_closure(base_dir):
    files, issues = resolve_topology_includes(base_dir, "topol.top")
    assert issues == []
    assert files == [
        "topol.top",
        "oplsaa.ff/forcefield.itp",
        "oplsaa.ff/ffnonbonded.itp",  # resolved relative to forcefield.itp, like grompp
        "oplsaa.ff/ffbonded.itp",
        "oplsaa.ff/spce.itp",
    ]


def test_missing_topology_dependency(base_dir):
    (base_dir / "oplsaa.ff" / "ffbonded.itp").unlink()
    _, issues = resolve_topology_includes(base_dir, "topol.top")
    assert [i.code for i in issues] == ["DEPENDENCY_MISSING"]
    assert issues[0].where == "oplsaa.ff/forcefield.itp:23"


@pytest.mark.parametrize(
    "line, code",
    [
        ('#include "/usr/share/gromacs/top/ions.itp"', "DEPENDENCY_ABSOLUTE"),
        ('#include "../outside.itp"', "DEPENDENCY_OUTSIDE_BASE"),
        ("#include <ions.itp>", "DEPENDENCY_UNSUPPORTED"),
        ('#include "amber99.ff/ions.itp"', "DEPENDENCY_MISSING"),  # would come from GMXLIB
    ],
)
def test_bad_includes(base_dir, line, code):
    (base_dir.parent / "outside.itp").write_text("; outside\n")
    top = base_dir / "topol.top"
    top.write_text(top.read_text().replace('#include "oplsaa.ff/spce.itp"', f'#include "oplsaa.ff/spce.itp"\n{line}'))
    _, issues = resolve_topology_includes(base_dir, "topol.top")
    assert [i.code for i in issues] == [code]


def test_include_cycle_terminates(base_dir):
    a = base_dir / "a.itp"
    a.write_text('#include "topol.top"\n')
    top = base_dir / "topol.top"
    top.write_text('#include "a.itp"\n' + top.read_text())
    files, issues = resolve_topology_includes(base_dir, "topol.top")
    assert issues == [] and files[:2] == ["topol.top", "a.itp"]


# --- run script ----------------------------------------------------------------------
def _script(spec, **kw):
    args = dict(
        sequence_id="job_0007", job_id="0123456789abcdef", spec=spec, structure="conf.gro",
        topology="topol.top", gmx_min_version="2021", gmx_developed_against="2025.5", builder_version="0.1.0",
    )
    args.update(kw)
    return render_run_script(**args)


def test_run_script_structure(spec, tmp_path):
    s = _script(spec)
    assert s.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in s
    assert 'cd "$(dirname "${BASH_SOURCE[0]}")"' in s
    assert "-maxwarn" not in s
    order = [
        "grompp -f em.mdp -c conf.gro -p topol.top",
        "run_mdrun em",
        "grompp -f nvt.mdp -c em.gro -p topol.top",
        "run_mdrun nvt",
        "grompp -f npt.mdp -c nvt.gro -t nvt.cpt -p topol.top",
        "run_mdrun npt",
        "grompp -f production.mdp -c npt.gro -t npt.cpt -p topol.top",
        "run_mdrun production",
    ]
    positions = [s.index(x) for x in order]
    assert positions == sorted(positions)
    assert "GROMACS >= 2021" in s
    p = tmp_path / "run.sh"
    p.write_text(s)
    assert subprocess.run(["bash", "-n", str(p)]).returncode == 0


def test_run_script_rejects_unsafe_names(spec):
    with pytest.raises(MdflowError):
        _script(spec, structure="../conf.gro")
    with pytest.raises(MdflowError):
        _script(spec, topology="my topol.top")
    with pytest.raises(MdflowError):
        _script(spec, gmx_min_version="latest")


def test_run_script_deterministic(spec):
    assert _script(spec) == _script(spec)


def test_validate_uses_gromacs_mapping(write_config):
    """End-to-end mapping: every planned job renders and passes the MDP checks."""
    plan = make_plan(write_config())
    for job in plan.jobs:
        rendered = render_stages(job.spec, plan.base.template_paths())
        nvt = parse_mdp(rendered[1].text)
        assert Decimal(nvt["ref-t"]) == job.spec.temperature_K
        assert int(nvt["gen-seed"]) == job.spec.random_seed
