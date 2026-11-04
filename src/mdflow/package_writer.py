"""Job Package Builder.

Creates one self-contained directory per job, writes ``job.json``, the global
``manifest.csv`` and ``build_report.json``, and validates everything before
the result becomes visible.

Safety properties
-----------------
* The build is assembled in a hidden staging directory next to the output and
  only moved into place after every job passed static validation. A failed
  build leaves no partial output behind.
* An existing non-empty output directory is never touched unless
  ``overwrite=True`` *and* it is a previous mdflow build.
* The base project is hashed before and after the build; any change aborts.
"""
from __future__ import annotations

import csv
import io
import json
import os
import platform
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import Issue, MdflowError
from .gromacs_adapter import STAGE_MDP, SEED_KEYS, parse_mdp, render_run_script, render_stages
from .plan import Plan, PlannedJob
from .simulation_spec import fmt_decimal, json_number
from .validator import (
    BUILD_REPORT_NAME,
    MANIFEST_COLUMNS,
    MANIFEST_NAME,
    ValidationStatus,
    check_job_dir,
    check_job_metadata,
    check_manifest,
    sha256_file,
)

JOB_SCHEMA_VERSION = 1
GENERATION_COMPLETE = "COMPLETE"


@dataclass(frozen=True)
class BuildResult:
    output_dir: Path
    n_jobs: int
    manifest: Path
    report: Path


def snapshot_tree(root: Path) -> dict[str, str]:
    """sha256 of every regular file under ``root`` (used to prove it is untouched)."""
    return {
        p.relative_to(root).as_posix(): sha256_file(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def manifest_row(job: PlannedJob, status: str) -> dict[str, str]:
    i = job.identity
    return {
        "sequence_id": i.sequence_id,
        "job_id": i.job_id,
        "temperature_K": fmt_decimal(job.spec.temperature_K),
        "pressure_bar": fmt_decimal(job.spec.pressure_bar),
        "replica": str(job.spec.replica),
        "random_seed": str(job.spec.random_seed),
        "directory": i.sequence_id,
        "generation_status": GENERATION_COMPLETE,
        "validation_status": status,
    }


def _metadata(plan: Plan, job: PlannedJob, rendered, files: dict[str, str]) -> dict:
    spec, ident = job.spec, job.identity
    d = plan.base.descriptor
    seed_usage = {}
    for r in rendered:
        keys = [k for k in SEED_KEYS if k in parse_mdp(r.text)]
        if keys:
            seed_usage[r.filename] = keys
    return {
        "schema_version": JOB_SCHEMA_VERSION,
        "job_id": ident.job_id,
        "sequence_id": ident.sequence_id,
        "experiment_id": plan.config.data.project,
        "builder_version": plan.builder_version,
        "parameters": {
            "temperature_K": json_number(spec.temperature_K),
            "pressure_bar": json_number(spec.pressure_bar),
            "replica": spec.replica,
        },
        "random_seed": spec.random_seed,
        "seed_usage": seed_usage,
        "protocol": {
            "timestep_fs": json_number(plan.protocol.timestep_fs),
            "stages": [
                {
                    "name": r.stage.name,
                    "mdp": r.filename,
                    "kind": r.stage.kind.value,
                    "ensemble": r.ensemble,
                    "steps": r.stage.steps,
                    "duration_ns": None if r.stage.duration_ns is None else json_number(r.stage.duration_ns),
                }
                for r in rendered
            ],
        },
        "base_project": {"name": d.name, "sha256": plan.base_sha256},
        "gromacs": {"min_version": d.gromacs.min_version, "developed_against": d.gromacs.developed_against},
        "identity": json.loads(ident.identity_document),
        "files": files,
        "generation_status": GENERATION_COMPLETE,
        "validation_status": ValidationStatus.STATIC_VALIDATED.value,
    }


def _dump_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=True) + "\n"


def write_job(plan: Plan, job: PlannedJob, job_dir: Path, forbidden: list[str]) -> dict:
    """Write and validate one job package. Returns its metadata dict."""
    base = plan.base
    d = base.descriptor
    job_dir.mkdir()

    # 1. scientific inputs copied verbatim from the base project
    for rel in plan.packaged_files:
        dst = job_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base.root / rel, dst)

    # 2. stage MDP files rendered from the base templates
    rendered = render_stages(job.spec, base.template_paths())
    for r in rendered:
        (job_dir / r.filename).write_text(r.text, encoding="utf-8")

    # 3. run script
    script = render_run_script(
        sequence_id=job.identity.sequence_id,
        job_id=job.identity.job_id,
        spec=job.spec,
        structure=d.structure,
        topology=d.topology,
        gmx_min_version=d.gromacs.min_version,
        gmx_developed_against=d.gromacs.developed_against,
        builder_version=plan.builder_version,
    )
    run_sh = job_dir / "run.sh"
    run_sh.write_text(script, encoding="utf-8")
    run_sh.chmod(0o755)

    # 4. static validation of the package
    expected = [*plan.packaged_files, *STAGE_MDP.values(), "run.sh"]
    issues = check_job_dir(job_dir, spec=job.spec, expected_files=expected, forbidden_strings=forbidden)
    if issues:
        raise MdflowError(issues)

    # 5. metadata (written last; carries the validation status)
    files = {rel: sha256_file(job_dir / rel) for rel in sorted(expected)}
    meta = _metadata(plan, job, rendered, files)
    (job_dir / "job.json").write_text(_dump_json(meta), encoding="utf-8")
    issues = check_job_metadata(
        job_dir,
        expect={"job_id": job.identity.job_id, "random_seed": job.spec.random_seed},
    )
    if issues:
        raise MdflowError(issues)
    return meta


def _write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


def build(plan: Plan, *, overwrite: bool = False) -> BuildResult:
    out = plan.config.output_dir
    base_root = plan.base.root
    before = snapshot_tree(base_root)

    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.mdflow-staging-", dir=out.parent))
    staging.chmod(0o755)  # mkdtemp creates 0700; the final output should be a normal directory
    forbidden = sorted(
        {str(base_root), str(plan.config.path.parent), str(out), str(staging), str(Path.home())},
        key=len,
        reverse=True,
    )
    try:
        rows = []
        for job in plan.jobs:
            write_job(plan, job, staging / job.identity.sequence_id, forbidden)
            rows.append(manifest_row(job, ValidationStatus.STATIC_VALIDATED.value))
        _write_manifest(staging / MANIFEST_NAME, rows)
        issues = check_manifest(staging, expected_rows=rows)

        after = snapshot_tree(base_root)
        if after != before:
            changed = sorted(set(before.items()) ^ set(after.items()))
            issues.append(Issue("BASE_PROJECT_MODIFIED", f"base project changed during build: {changed[:5]}"))
        if issues:
            raise MdflowError(issues)

        report = {
            "tool": "mdflow",
            "builder_version": plan.builder_version,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "host": {"python": platform.python_version(), "platform": platform.platform()},
            "project": plan.config.data.project,
            "config": {"path": str(plan.config.path), "sha256": plan.config.sha256},
            "base_project": {
                "path": str(base_root),
                "name": plan.base.descriptor.name,
                "sha256": plan.base_sha256,
                "unchanged_after_build": True,
            },
            "n_jobs": len(rows),
            "validation_status": ValidationStatus.STATIC_VALIDATED.value,
            "gromacs_validation": "NOT_PERFORMED (V0.1 performs static validation only)",
        }
        (staging / BUILD_REPORT_NAME).write_text(_dump_json(report), encoding="utf-8")

        # move into place
        if out.exists():
            if any(out.iterdir()):
                if not overwrite:  # re-checked: the directory may have appeared meanwhile
                    raise MdflowError(Issue("OUTPUT_EXISTS", f"{out} appeared during the build"))
                trash = Path(tempfile.mkdtemp(prefix=f".{out.name}.mdflow-old-", dir=out.parent))
                os.replace(out, trash / out.name)
                os.replace(staging, out)
                shutil.rmtree(trash)
            else:
                out.rmdir()
                os.replace(staging, out)
        else:
            os.replace(staging, out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return BuildResult(out, len(rows), out / MANIFEST_NAME, out / BUILD_REPORT_NAME)


def verify_output(plan: Plan) -> list[Issue]:
    """Re-check an existing build against the plan (used by ``mdflow validate``).

    Detects missing/edited files, manifest drift and builds made from a
    different configuration or base project.
    """
    out = plan.config.output_dir
    issues: list[Issue] = []
    rows = [manifest_row(j, ValidationStatus.STATIC_VALIDATED.value) for j in plan.jobs]
    issues += check_manifest(out, expected_rows=rows)
    expected = [*plan.packaged_files, *STAGE_MDP.values(), "run.sh", "job.json"]
    forbidden = [str(plan.base.root), str(plan.config.path.parent), str(out)]
    for job in plan.jobs:
        jd = out / job.identity.sequence_id
        if not jd.is_dir():
            issues.append(Issue("PACKAGE_MISSING", f"job directory missing: {jd.name}"))
            continue
        issues += check_job_dir(jd, spec=job.spec, expected_files=expected, forbidden_strings=forbidden)
        issues += check_job_metadata(
            jd,
            expect={
                "job_id": job.identity.job_id,
                "random_seed": job.spec.random_seed,
                "validation_status": ValidationStatus.STATIC_VALIDATED.value,
            },
        )
    return issues
