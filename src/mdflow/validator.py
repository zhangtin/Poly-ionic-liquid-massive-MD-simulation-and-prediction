"""Static validation.

Checks are pure functions returning lists of :class:`~mdflow.errors.Issue`.
Nothing here runs GROMACS: a ``STATIC_VALIDATED`` job has consistent,
complete inputs, which says nothing about whether ``grompp`` accepts them or
whether the physics is right.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
from enum import Enum
from pathlib import Path

from .config import BASE_DESCRIPTOR_NAME, BaseProject, LoadedConfig
from .errors import Issue
from .gromacs_adapter import (
    GENERATED_NAMES,
    RUNTIME_NAMES,
    STAGE_MDP,
    check_gro,
    check_rendered_mdp,
    check_template_sources,
    parse_mdp,
    resolve_topology_includes,
)
from .simulation_spec import SimulationSpec, fmt_decimal, to_decimal

SHA256SUMS_NAME = "SHA256SUMS"
BUILD_REPORT_NAME = "build_report.json"
MANIFEST_NAME = "manifest.csv"
MANIFEST_COLUMNS = [
    "sequence_id",
    "job_id",
    "temperature_K",
    "pressure_bar",
    "replica",
    "random_seed",
    "directory",
    "generation_status",
    "validation_status",
]


class ValidationStatus(str, Enum):
    """Validation levels. V0.1 code only ever assigns the first two."""

    CONFIG_VALIDATED = "CONFIG_VALIDATED"  # config + base project + templates checked
    STATIC_VALIDATED = "STATIC_VALIDATED"  # generated package checked without GROMACS
    GROMPP_VALIDATED = "GROMPP_VALIDATED"  # gmx grompp accepted every stage (not done by V0.1)
    RUN_VALIDATED = "RUN_VALIDATED"  # short mdrun succeeded (not done by V0.1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Base project                                                                 #
# --------------------------------------------------------------------------- #
def base_project_files(base: BaseProject) -> tuple[list[str], list[Issue]]:
    """Files that define the base project scientifically (relative paths).

    = descriptor + structure + topology include closure + MDP templates.
    """
    d = base.descriptor
    issues: list[Issue] = []
    structure = base.root / d.structure
    if not structure.is_file():
        issues.append(Issue("STRUCTURE_MISSING", f"structure file not found: {d.structure}", "base_project.yaml:structure"))
    topo_files, topo_issues = resolve_topology_includes(base.root, d.topology)
    issues += topo_issues
    files = [BASE_DESCRIPTOR_NAME, d.structure, *topo_files]
    for stage, p in base.template_paths().items():
        rel = p.resolve()
        try:
            files.append(rel.relative_to(base.root).as_posix())
        except ValueError:
            issues.append(Issue("TEMPLATE_OUTSIDE_BASE", f"template for {stage} is outside the base project", f"template:{stage}"))
    # de-duplicate while keeping order
    seen: set[str] = set()
    files = [f for f in files if not (f in seen or seen.add(f))]
    return files, issues


def base_project_sha256(base: BaseProject, files: list[str]) -> str:
    listing = [[f, sha256_file(base.root / f)] for f in sorted(files)]
    return hashlib.sha256(json.dumps(listing, separators=(",", ":")).encode()).hexdigest()


def check_base_project(base: BaseProject) -> tuple[list[str], list[str], list[Issue]]:
    """Returns (all identity files, packaged files, issues)."""
    d = base.descriptor
    files, issues = base_project_files(base)
    structure = base.root / d.structure
    if structure.is_file():
        if structure.suffix != ".gro":
            issues.append(Issue("STRUCTURE_UNSUPPORTED", "V0.1 supports .gro structures only", d.structure))
        else:
            issues += check_gro(structure)
    issues += check_template_sources(base.template_paths())

    template_files = {p.resolve().relative_to(base.root).as_posix() for p in base.template_paths().values()
                      if p.resolve().is_relative_to(base.root)}
    packaged = [f for f in files if f != BASE_DESCRIPTOR_NAME and f not in template_files]
    for f in packaged:
        top = f.split("/", 1)[0]
        if top in GENERATED_NAMES or top in RUNTIME_NAMES:
            issues.append(Issue("FILENAME_CONFLICT", f"base project file '{f}' clashes with a file mdflow or GROMACS writes", f))

    # Optional integrity reference shipped with the base project.
    sums = base.root / SHA256SUMS_NAME
    if sums.is_file():
        for lineno, line in enumerate(sums.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            m = re.fullmatch(r"([0-9a-f]{64})\s+\*?(.+)", line.strip())
            if not m:
                issues.append(Issue("SHA256SUMS_INVALID", f"line {lineno} malformed", SHA256SUMS_NAME))
                continue
            p = base.root / m.group(2)
            if not p.is_file():
                issues.append(Issue("BASE_PROJECT_MODIFIED", f"listed file missing: {m.group(2)}", SHA256SUMS_NAME))
            elif sha256_file(p) != m.group(1):
                issues.append(Issue("BASE_PROJECT_MODIFIED", f"checksum mismatch: {m.group(2)}", SHA256SUMS_NAME))
    return files, packaged, issues


# --------------------------------------------------------------------------- #
# Scan configuration vs. base project limits                                   #
# --------------------------------------------------------------------------- #
def check_scan_limits(cfg: LoadedConfig, base: BaseProject) -> list[Issue]:
    lim = base.descriptor.limits
    issues: list[Issue] = []
    lo_t, hi_t = (to_decimal(v) for v in lim.temperature_K)
    lo_p, hi_p = (to_decimal(v) for v in lim.pressure_bar)
    for t in cfg.data.scan.temperature_K:
        if not lo_t <= to_decimal(t) <= hi_t:
            issues.append(Issue(
                "TEMPERATURE_OUT_OF_RANGE",
                f"{t} K outside the base project's limits [{fmt_decimal(lo_t)}, {fmt_decimal(hi_t)}] K",
                "scan.temperature_K",
            ))
    for p in cfg.data.scan.pressure_bar:
        if not lo_p <= to_decimal(p) <= hi_p:
            issues.append(Issue(
                "PRESSURE_OUT_OF_RANGE",
                f"{p} bar outside the base project's limits [{fmt_decimal(lo_p)}, {fmt_decimal(hi_p)}] bar",
                "scan.pressure_bar",
            ))
    if to_decimal(cfg.data.simulation.timestep_fs) > to_decimal(lim.max_timestep_fs):
        issues.append(Issue(
            "TIMESTEP_TOO_LARGE",
            f"{cfg.data.simulation.timestep_fs} fs exceeds the base project's maximum {lim.max_timestep_fs} fs",
            "simulation.timestep_fs",
        ))
    return issues


def _is_within(child: Path, parent: Path) -> bool:
    return child == parent or child.is_relative_to(parent)


def check_output_path(cfg: LoadedConfig, base: BaseProject, *, for_build: bool, overwrite: bool = False) -> list[Issue]:
    out = cfg.output_dir
    issues: list[Issue] = []
    where = "output.directory"
    if _is_within(out, base.root) or _is_within(base.root, out):
        issues.append(Issue("OUTPUT_PATH_INVALID", f"output {out} overlaps the base project {base.root}", where))
    if _is_within(cfg.path.parent, out):
        issues.append(Issue("OUTPUT_PATH_INVALID", f"output {out} would contain the configuration file", where))
    if out.exists() and not out.is_dir():
        issues.append(Issue("OUTPUT_PATH_INVALID", f"output path exists and is not a directory: {out}", where))
    # nearest existing ancestor must be a writable directory
    anc = out
    while not anc.exists():
        anc = anc.parent
    if not anc.is_dir():
        issues.append(Issue("OUTPUT_PATH_INVALID", f"{anc} is not a directory", where))
    elif not os.access(anc, os.W_OK):
        issues.append(Issue("OUTPUT_PATH_INVALID", f"no write permission in {anc}", where))
    if for_build and out.is_dir() and any(out.iterdir()):
        if not overwrite:
            issues.append(Issue(
                "OUTPUT_EXISTS",
                f"output directory {out} already exists and is not empty; choose another "
                "directory or pass --overwrite to replace a previous mdflow build",
                where,
            ))
        elif not _is_mdflow_output(out):
            issues.append(Issue(
                "OUTPUT_NOT_MDFLOW",
                f"--overwrite refused: {out} does not look like an mdflow build (no {BUILD_REPORT_NAME})",
                where,
            ))
    return issues


def _is_mdflow_output(out: Path) -> bool:
    try:
        return json.loads((out / BUILD_REPORT_NAME).read_text()).get("tool") == "mdflow"
    except (OSError, ValueError, AttributeError):
        return False


# --------------------------------------------------------------------------- #
# Generated job packages                                                       #
# --------------------------------------------------------------------------- #
def check_run_script(path: Path, forbidden_strings: list[str]) -> list[Issue]:
    where = f"{path.parent.name}/{path.name}"
    issues: list[Issue] = []
    text = path.read_text()
    if not text.startswith("#!/usr/bin/env bash\n"):
        issues.append(Issue("SCRIPT_INVALID", "missing '#!/usr/bin/env bash' shebang", where))
    if "set -euo pipefail" not in text:
        issues.append(Issue("SCRIPT_INVALID", "missing 'set -euo pipefail'", where))
    if "-maxwarn" in text:
        issues.append(Issue("SCRIPT_INVALID", "script uses -maxwarn", where))
    for s in forbidden_strings:
        if len(s) > 1 and s in text:
            issues.append(Issue("SCRIPT_ABSOLUTE_PATH", f"script contains build-host path '{s}'", where))
    if not os.access(path, os.X_OK):
        issues.append(Issue("SCRIPT_INVALID", "script is not executable", where))
    for stage, mdp in STAGE_MDP.items():
        if f"-f {mdp}" not in text:
            issues.append(Issue("SCRIPT_INVALID", f"no grompp call for {mdp}", where))
    bash = shutil.which("bash")
    if bash:
        res = subprocess.run([bash, "-n", str(path)], capture_output=True, text=True)
        if res.returncode != 0:
            issues.append(Issue("SCRIPT_SYNTAX_ERROR", res.stderr.strip(), where))
    return issues


def check_job_dir(
    job_dir: Path,
    *,
    spec: SimulationSpec,
    expected_files: list[str],
    forbidden_strings: list[str],
) -> list[Issue]:
    """Completeness + consistency of one job package (job.json excluded)."""
    issues: list[Issue] = []
    name = job_dir.name
    for rel in expected_files:
        if not (job_dir / rel).is_file():
            issues.append(Issue("PACKAGE_INCOMPLETE", f"missing file {rel}", name))
    if issues:
        return issues
    for stage in spec.stages:
        mdp = job_dir / STAGE_MDP[stage.name]
        try:
            params = parse_mdp(mdp.read_text(), f"{name}/{mdp.name}")
        except Exception as exc:  # MdflowError
            issues += getattr(exc, "issues", [Issue("MDP_SYNTAX_ERROR", str(exc), mdp.name)])
            continue
        issues += check_rendered_mdp(stage, params, spec, f"{name}/{mdp.name}")
    issues += check_run_script(job_dir / "run.sh", forbidden_strings)
    return issues


def check_job_metadata(job_dir: Path, *, expect: dict) -> list[Issue]:
    """job.json exists, parses, agrees with ``expect`` and with file hashes."""
    where = f"{job_dir.name}/job.json"
    try:
        meta = json.loads((job_dir / "job.json").read_text())
    except (OSError, ValueError) as exc:
        return [Issue("METADATA_INVALID", f"cannot read job.json: {exc}", where)]
    issues = []
    for key, value in expect.items():
        if meta.get(key) != value:
            issues.append(Issue("METADATA_MISMATCH", f"{key}: expected {value!r}, found {meta.get(key)!r}", where))
    for rel, digest in (meta.get("files") or {}).items():
        p = job_dir / rel
        if not p.is_file():
            issues.append(Issue("PACKAGE_INCOMPLETE", f"file listed in job.json missing: {rel}", where))
        elif sha256_file(p) != digest:
            issues.append(Issue("PACKAGE_MODIFIED", f"checksum mismatch: {rel}", where))
    return issues


def read_manifest(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def check_manifest(out_dir: Path, *, expected_rows: list[dict]) -> list[Issue]:
    where = MANIFEST_NAME
    path = out_dir / MANIFEST_NAME
    if not path.is_file():
        return [Issue("MANIFEST_MISSING", "manifest.csv not found", where)]
    rows = read_manifest(path)
    issues: list[Issue] = []
    if rows and list(rows[0].keys()) != MANIFEST_COLUMNS:
        issues.append(Issue("MANIFEST_INVALID", f"unexpected columns {list(rows[0].keys())}", where))
    if len(rows) != len(expected_rows):
        issues.append(Issue("MANIFEST_MISMATCH", f"{len(rows)} rows, expected {len(expected_rows)}", where))
    for col in ("job_id", "random_seed", "directory"):
        vals = [r.get(col) for r in rows]
        if len(set(vals)) != len(vals):
            issues.append(Issue("MANIFEST_INVALID", f"duplicate values in column {col}", where))
    for row, exp in zip(rows, expected_rows):
        if row != exp:
            diff = {k: (row.get(k), v) for k, v in exp.items() if row.get(k) != v}
            issues.append(Issue("MANIFEST_MISMATCH", f"row {exp['sequence_id']}: {diff}", where))
        jd = out_dir / row.get("directory", "")
        if not (jd / "job.json").is_file():
            issues.append(Issue("MANIFEST_MISMATCH", f"directory {row.get('directory')} has no job.json", where))
            continue
        meta = json.loads((jd / "job.json").read_text())
        p = meta.get("parameters", {})
        if (
            meta.get("job_id") != row.get("job_id")
            or str(meta.get("random_seed")) != row.get("random_seed")
            or str(p.get("replica")) != row.get("replica")
        ):
            issues.append(Issue("MANIFEST_MISMATCH", f"row {row.get('sequence_id')} disagrees with job.json", where))
    return issues
