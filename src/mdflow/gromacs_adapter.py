"""GROMACS Adapter.

All GROMACS-specific knowledge lives here: mapping of engine-independent
:class:`~mdflow.simulation_spec.SimulationSpec` values onto MDP template
variables, MDP parsing and consistency checks, and generation of the Bash
run script. The parameter-space engine and the simulation specification do
not depend on this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .errors import Issue, MdflowError
from .simulation_spec import SimulationSpec, StageKind, StageSpec, fmt_decimal
from .template_renderer import check_variables, read_template, render

#: Output MDP file name for each stage, in execution order.
STAGE_MDP = {"em": "em.mdp", "nvt": "nvt.mdp", "npt": "npt.mdp", "production": "production.mdp"}
STAGE_ORDER = tuple(STAGE_MDP)

#: Variables an MDP template may reference, per stage. EM gets no thermodynamic
#: state; NVT gets no pressure.
ALLOWED_VARS = {
    "em": {"nsteps"},
    "nvt": {"nsteps", "dt_ps", "temperature_K", "random_seed"},
    "npt": {"nsteps", "dt_ps", "temperature_K", "pressure_bar", "random_seed"},
    "production": {"nsteps", "dt_ps", "temperature_K", "pressure_bar", "random_seed"},
}
#: Variables a template MUST reference (otherwise a scanned value would be
#: silently ignored). Pressure in production is checked after rendering,
#: because whether it is needed depends on the base project's ensemble.
REQUIRED_VARS = {
    "em": {"nsteps"},
    "nvt": {"nsteps", "dt_ps", "temperature_K"},
    "npt": {"nsteps", "dt_ps", "temperature_K", "pressure_bar"},
    "production": {"nsteps", "dt_ps", "temperature_K"},
}

EM_INTEGRATORS = {"steep", "cg", "l-bfgs"}
MD_INTEGRATORS = {"md", "md-vv", "md-vv-avek", "sd", "bd"}
STOCHASTIC_INTEGRATORS = {"sd", "bd"}
STOCHASTIC_TCOUPL = {"v-rescale", "andersen", "andersen-massive"}
STOCHASTIC_PCOUPL = {"c-rescale"}
SEED_KEYS = ("gen-seed", "ld-seed")


# --------------------------------------------------------------------------- #
# MDP parsing                                                                  #
# --------------------------------------------------------------------------- #
def normalize_key(key: str) -> str:
    """GROMACS treats '-' and '_' in MDP keys as equivalent and is case-insensitive."""
    return key.strip().lower().replace("_", "-")


def parse_mdp(text: str, where: str = "") -> dict[str, str]:
    params: dict[str, str] = {}
    issues = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            issues.append(Issue("MDP_SYNTAX_ERROR", f"line {lineno}: expected 'key = value'", where))
            continue
        key, value = line.split("=", 1)
        nkey = normalize_key(key)
        if not nkey:
            issues.append(Issue("MDP_SYNTAX_ERROR", f"line {lineno}: empty key", where))
            continue
        if nkey in params:
            issues.append(Issue("MDP_DUPLICATE_KEY", f"line {lineno}: '{nkey}' set more than once", where))
            continue
        params[nkey] = value.strip()
    if issues:
        raise MdflowError(issues)
    return params


def _lower(params: dict[str, str], key: str, default: str = "") -> str:
    return params.get(key, default).strip().lower()


def _decimals(value: str) -> list[Decimal] | None:
    try:
        return [Decimal(v) for v in value.split()]
    except InvalidOperation:
        return None


# --------------------------------------------------------------------------- #
# Topology / structure files                                                   #
# --------------------------------------------------------------------------- #
_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+(.*?)\s*$')

#: Files mdflow writes into a job directory, and files GROMACS writes while
#: running run.sh. Packaged base-project files must not use these names.
GENERATED_NAMES = frozenset(set(STAGE_MDP.values()) | {"run.sh", "job.json"})
RUNTIME_NAMES = frozenset(
    f"{stage}{ext}"
    for stage in STAGE_ORDER
    for ext in (".tpr", ".gro", ".cpt", ".edr", ".log", ".trr", ".xtc", "_prev.cpt", "_mdout.mdp")
)


def resolve_topology_includes(root: Path, topology: str) -> tuple[list[str], list[Issue]]:
    """Return the topology plus every file it ``#include``s, as posix paths
    relative to ``root``.

    Mirrors the GROMACS preprocessor (gmxcpp.cpp): a quoted include is looked
    up relative to the directory of the file that contains it. GROMACS would
    then fall back to ``-I`` paths and the installed library (GMXLIB /
    share/top); mdflow deliberately does *not*, because a job package must be
    self-contained. Includes inside ``#ifdef`` blocks are treated as required
    (conservative: the active branch is only known at grompp time).
    """
    root = root.resolve()
    issues: list[Issue] = []
    ordered: list[str] = []
    seen: set[Path] = set()

    def visit(path: Path, origin: str) -> None:
        path = path.resolve()
        if path in seen:
            return
        try:
            rel = path.relative_to(root)
        except ValueError:
            issues.append(Issue("DEPENDENCY_OUTSIDE_BASE", f"{path} is outside the base project", origin))
            return
        if not path.is_file():
            issues.append(
                Issue(
                    "DEPENDENCY_MISSING",
                    f"'{rel.as_posix()}' not found in the base project (GROMACS would fall back "
                    "to its installed library; job packages must be self-contained)",
                    origin,
                )
            )
            return
        seen.add(path)
        ordered.append(rel.as_posix())
        try:
            lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(Issue("DEPENDENCY_UNREADABLE", f"cannot read {rel}: {exc}", origin))
            return
        for lineno, line in enumerate(lines, start=1):
            m = _INCLUDE_RE.match(line.split(";", 1)[0])
            if not m:
                continue
            where = f"{rel.as_posix()}:{lineno}"
            arg = m.group(1)
            if not (len(arg) >= 2 and arg[0] == '"' and arg[-1] == '"'):
                issues.append(Issue("DEPENDENCY_UNSUPPORTED", f"unsupported include syntax: {arg}", where))
                continue
            target = arg[1:-1]
            if Path(target).is_absolute():
                issues.append(Issue("DEPENDENCY_ABSOLUTE", f"absolute include path '{target}'", where))
                continue
            visit(path.parent / target, where)

    visit(root / topology, "base_project.yaml:topology")
    return ordered, issues


def check_gro(path: Path) -> list[Issue]:
    """Minimal structural check of a .gro coordinate file."""
    where = path.name
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [Issue("STRUCTURE_UNREADABLE", str(exc), where)]
    try:
        natoms = int(lines[1].strip())
    except (IndexError, ValueError):
        return [Issue("STRUCTURE_INVALID", "line 2 must hold the atom count", where)]
    if len(lines) != natoms + 3:
        return [Issue("STRUCTURE_INVALID", f"atom count {natoms} does not match {len(lines) - 3} atom lines", where)]
    box = lines[-1].split()
    if len(box) not in (3, 9) or _decimals(lines[-1]) is None:
        return [Issue("STRUCTURE_INVALID", "last line must be the box vector (3 or 9 numbers)", where)]
    return []


# --------------------------------------------------------------------------- #
# Template context                                                             #
# --------------------------------------------------------------------------- #
def stage_context(spec: SimulationSpec, stage: StageSpec) -> dict:
    """Values offered to the template of ``stage`` (only its allowed subset)."""
    full = {
        "nsteps": stage.steps,
        "dt_ps": fmt_decimal(spec.protocol.timestep_ps),
        "temperature_K": fmt_decimal(spec.temperature_K),
        "pressure_bar": fmt_decimal(spec.pressure_bar),
        "random_seed": spec.random_seed,
    }
    return {k: v for k, v in full.items() if k in ALLOWED_VARS[stage.name]}


def check_template_sources(templates: dict[str, Path]) -> list[Issue]:
    """Static check of the base project's templates (existence + variables)."""
    issues: list[Issue] = []
    for stage in STAGE_ORDER:
        where = f"template:{stage}"
        try:
            src = read_template(templates[stage], where)
            issues += check_variables(
                src, allowed=ALLOWED_VARS[stage], required=REQUIRED_VARS[stage], where=where
            )
        except MdflowError as exc:
            issues += exc.issues
    return issues


# --------------------------------------------------------------------------- #
# Rendered-MDP consistency                                                     #
# --------------------------------------------------------------------------- #
def check_rendered_mdp(stage: StageSpec, params: dict[str, str], spec: SimulationSpec, where: str) -> list[Issue]:
    """Verify that the scan values actually landed on the right MDP keys.

    This is the mapping check between the engine-independent spec and GROMACS.
    """
    issues: list[Issue] = []

    def err(code: str, msg: str) -> None:
        issues.append(Issue(code, msg, where))

    def expect_number(key: str, expected: Decimal, label: str) -> None:
        if key not in params:
            err("MDP_MISSING_KEY", f"'{key}' is not set; {label} would not be applied")
            return
        vals = _decimals(params[key])
        if vals is None:
            err("MDP_BAD_VALUE", f"'{key} = {params[key]}' is not numeric")
        elif len(vals) != 1:
            err("MDP_UNSUPPORTED", f"'{key}' has {len(vals)} values; V0.1 supports a single group only")
        elif vals[0] != expected:
            err("MDP_MAPPING_MISMATCH", f"'{key} = {params[key]}' but {label} is {fmt_decimal(expected)}")

    integrator = _lower(params, "integrator", "md")
    expect_number("nsteps", Decimal(stage.steps), "the stage step count")

    if stage.kind is StageKind.MINIMIZATION:
        if integrator not in EM_INTEGRATORS:
            err("MDP_WRONG_INTEGRATOR", f"EM stage uses integrator '{integrator}'")
        return issues

    if integrator not in MD_INTEGRATORS:
        err("MDP_WRONG_INTEGRATOR", f"dynamics stage uses integrator '{integrator}'")
    expect_number("dt", spec.protocol.timestep_ps, "the timestep (ps)")

    # --- temperature coupling -------------------------------------------------
    tcoupl = _lower(params, "tcoupl", "no")
    if integrator in STOCHASTIC_INTEGRATORS:
        expect_number("ref-t", spec.temperature_K, "the scan temperature")
    elif tcoupl == "no":
        err("MDP_NO_THERMOSTAT", "dynamics stage has tcoupl = no; the scan temperature is not applied")
    else:
        expect_number("ref-t", spec.temperature_K, "the scan temperature")
    if len(params.get("tc-grps", "System").split()) != 1:
        err("MDP_UNSUPPORTED", "V0.1 supports exactly one temperature-coupling group")

    # --- pressure coupling ------------------------------------------------------
    pcoupl = _lower(params, "pcoupl", "no")
    if stage.ensemble == "NVT" and pcoupl != "no":
        err("MDP_ENSEMBLE_MISMATCH", f"NVT stage has pcoupl = {pcoupl}")
    if stage.ensemble == "NPT" and pcoupl == "no":
        err("MDP_ENSEMBLE_MISMATCH", "NPT stage has pcoupl = no")
    if pcoupl != "no":
        if _lower(params, "pcoupltype", "isotropic") != "isotropic":
            err("MDP_UNSUPPORTED", "V0.1 supports isotropic pressure coupling only")
        expect_number("ref-p", spec.pressure_bar, "the scan pressure")

    # --- velocities and seeds ---------------------------------------------------
    gen_vel = _lower(params, "gen-vel", "no") == "yes"
    if stage.name in ("npt", "production") and gen_vel:
        err(
            "MDP_DISCARDS_STATE",
            "gen-vel = yes in a stage continued from a checkpoint would discard the velocities",
        )
    if gen_vel:
        expect_number("gen-temp", spec.temperature_K, "the scan temperature")
    stochastic = (
        integrator in STOCHASTIC_INTEGRATORS or tcoupl in STOCHASTIC_TCOUPL or pcoupl in STOCHASTIC_PCOUPL
    )
    if gen_vel and "gen-seed" not in params:
        err("MDP_UNSEEDED", "gen-vel = yes but gen-seed is not set (GROMACS would pick a random seed)")
    if stochastic and "ld-seed" not in params:
        err(
            "MDP_UNSEEDED",
            "stochastic coupling/integrator in use but ld-seed is not set "
            "(GROMACS would pick a random seed; results not reproducible)",
        )
    for key in SEED_KEYS:
        if key in params:
            expect_number(key, Decimal(spec.random_seed), "the job random seed")
    return issues


def production_ensemble(params: dict[str, str]) -> str:
    return "NVT" if _lower(params, "pcoupl", "no") == "no" else "NPT"


@dataclass(frozen=True)
class RenderedStage:
    stage: StageSpec
    filename: str
    text: str
    ensemble: str | None


def render_stages(spec: SimulationSpec, templates: dict[str, Path]) -> list[RenderedStage]:
    out: list[RenderedStage] = []
    issues: list[Issue] = []
    for stage in spec.stages:
        where = f"template:{stage.name}"
        try:
            src = read_template(templates[stage.name], where)
            text = render(
                src,
                stage_context(spec, stage),
                allowed=ALLOWED_VARS[stage.name],
                required=REQUIRED_VARS[stage.name],
                where=where,
            )
            params = parse_mdp(text, where)
        except MdflowError as exc:
            issues += exc.issues
            continue
        issues += check_rendered_mdp(stage, params, spec, where)
        ensemble = stage.ensemble
        if stage.name == "production":
            ensemble = production_ensemble(params)
        out.append(RenderedStage(stage, STAGE_MDP[stage.name], text, ensemble))
    if issues:
        raise MdflowError(issues)
    return out


# --------------------------------------------------------------------------- #
# Run script                                                                   #
# --------------------------------------------------------------------------- #
_VERSION_RE = re.compile(r"^\d{4}(\.\d+)*$")


def render_run_script(
    *,
    sequence_id: str,
    job_id: str,
    spec: SimulationSpec,
    structure: str,
    topology: str,
    gmx_min_version: str,
    gmx_developed_against: str | None,
    builder_version: str,
) -> str:
    if not _VERSION_RE.match(gmx_min_version):
        raise MdflowError(Issue("BAD_GMX_VERSION", f"unrecognised GROMACS version '{gmx_min_version}'"))
    min_major = int(gmx_min_version.split(".")[0])
    for name in (structure, topology):
        if "/" in name or name.startswith(".") or not re.fullmatch(r"[A-Za-z0-9_.+-]+", name):
            raise MdflowError(Issue("BAD_FILENAME", f"unsupported file name for run script: {name!r}"))
    dev = f" (developed against {gmx_developed_against})" if gmx_developed_against else ""
    T = fmt_decimal(spec.temperature_K)
    P = fmt_decimal(spec.pressure_bar)
    return f"""#!/usr/bin/env bash
# =============================================================================
# Generated by mdflow {builder_version} (GROMACS Script Builder). Do not edit by hand;
# regenerate from the scan configuration instead.
#
#   sequence id : {sequence_id}
#   job id      : {job_id}
#   parameters  : T = {T} K, P = {P} bar, replica {spec.replica}
#   random seed : {spec.random_seed}
#   GROMACS     : >= {gmx_min_version} required{dev}
#
# Stages: EM -> NVT -> NPT -> production. Each stage starts from the previous
# stage's output; NPT and production also read its checkpoint (.cpt) so that
# coordinates, velocities and coupling state are carried over exactly.
#
# Usage:   bash run.sh
# Options (environment variables):
#   GMX         GROMACS executable            (default: gmx)
#   MDRUN_ARGS  extra arguments for mdrun     (e.g. "-nt 8" or "-ntomp 4 -pin on")
# =============================================================================
set -euo pipefail
cd "$(dirname "${{BASH_SOURCE[0]}}")"

GMX="${{GMX:-gmx}}"
read -r -a MDRUN_ARGS <<< "${{MDRUN_ARGS:-}}"

if ! command -v "$GMX" > /dev/null 2>&1; then
    echo "ERROR: GROMACS executable '$GMX' not found (set GMX=...)" >&2
    exit 127
fi
gmx_version="$("$GMX" --version 2> /dev/null | awk -F': *' '/^GROMACS version/ {{print $2}}')" || gmx_version=""
gmx_major="${{gmx_version%%.*}}"
if [[ ! "$gmx_major" =~ ^[0-9]+$ ]] || (( gmx_major < {min_major} )); then
    echo "ERROR: GROMACS >= {gmx_min_version} required, found '${{gmx_version:-unknown}}'" >&2
    exit 1
fi
echo "Using GROMACS $gmx_version ($GMX)"

run_mdrun() {{
    "$GMX" mdrun -deffnm "$1" ${{MDRUN_ARGS[@]+"${{MDRUN_ARGS[@]}}"}}
}}

echo "==> [1/4] Energy minimization"
"$GMX" grompp -f em.mdp -c {structure} -p {topology} -po em_mdout.mdp -o em.tpr
run_mdrun em

echo "==> [2/4] NVT equilibration"
"$GMX" grompp -f nvt.mdp -c em.gro -p {topology} -po nvt_mdout.mdp -o nvt.tpr
run_mdrun nvt

echo "==> [3/4] NPT equilibration"
"$GMX" grompp -f npt.mdp -c nvt.gro -t nvt.cpt -p {topology} -po npt_mdout.mdp -o npt.tpr
run_mdrun npt

echo "==> [4/4] Production MD"
"$GMX" grompp -f production.mdp -c npt.gro -t npt.cpt -p {topology} -po production_mdout.mdp -o production.tpr
run_mdrun production

echo "Job {sequence_id} ({job_id}) finished."
"""
