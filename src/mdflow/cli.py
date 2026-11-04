"""Command-line interface: ``mdflow plan | build | validate``.

Exit codes: 0 success, 1 validation/build errors, 2 usage errors.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .errors import MdflowError
from .gromacs_adapter import render_run_script, render_stages
from .package_writer import build, verify_output
from .plan import Plan, make_plan
from .simulation_spec import fmt_decimal
from .validator import BUILD_REPORT_NAME, ValidationStatus


def _print_issues(err: MdflowError) -> None:
    print(f"ERROR: {len(err.issues)} problem(s) found:", file=sys.stderr)
    for issue in err.issues:
        print(f"  - {issue}", file=sys.stderr)


def _summary(plan: Plan) -> None:
    cfg = plan.config.data
    d = plan.base.descriptor
    n_t, n_p, n_r = len(cfg.scan.temperature_K), len(cfg.scan.pressure_bar), cfg.scan.replicas
    print(f"project       : {cfg.project}")
    print(f"config        : {plan.config.path}")
    print(f"base project  : {d.name}  ({plan.base.root})")
    print(f"base sha256   : {plan.base_sha256}")
    print(f"output        : {plan.config.output_dir}")
    print(f"scan          : {n_t} temperature(s) x {n_p} pressure(s) x {n_r} replica(s) = {len(plan.jobs)} jobs")
    print(f"timestep      : {fmt_decimal(plan.protocol.timestep_fs)} fs")
    for s in plan.protocol.stages():
        dur = "max steps" if s.duration_ns is None else f"{fmt_decimal(s.duration_ns)} ns"
        print(f"  stage {s.name:<11s}: {s.steps:>12,d} steps  ({dur})")


def _jobs_table(plan: Plan, limit: int | None) -> None:
    print(f"\n{'seq':<10s} {'job_id':<17s} {'T/K':>8s} {'P/bar':>8s} {'rep':>4s} {'seed':>11s}")
    jobs = plan.jobs if limit is None else plan.jobs[:limit]
    for j in jobs:
        print(
            f"{j.identity.sequence_id:<10s} {j.identity.job_id:<17s} "
            f"{fmt_decimal(j.spec.temperature_K):>8s} {fmt_decimal(j.spec.pressure_bar):>8s} "
            f"{j.spec.replica:>4d} {j.spec.random_seed:>11d}"
        )
    if limit is not None and len(plan.jobs) > limit:
        print(f"... {len(plan.jobs) - limit} more (use --list to show all)")


def cmd_plan(args) -> int:
    plan = make_plan(args.config)
    _summary(plan)
    _jobs_table(plan, None if args.list else 5)
    print(f"\nstatus: {ValidationStatus.CONFIG_VALIDATED.value} (no files written)")
    return 0


def cmd_build(args) -> int:
    plan = make_plan(args.config, for_build=True, overwrite=args.overwrite)
    _summary(plan)
    result = build(plan, overwrite=args.overwrite)
    print(f"\nwrote {result.n_jobs} job packages to {result.output_dir}")
    print(f"manifest: {result.manifest}")
    print(f"report  : {result.report}")
    print(f"status  : {ValidationStatus.STATIC_VALIDATED.value} (GROMACS was not run)")
    return 0


def cmd_validate(args) -> int:
    plan = make_plan(args.config)
    _summary(plan)
    # dry-run rendering of every job (templates, mapping checks, run script)
    d = plan.base.descriptor
    for job in plan.jobs:
        render_stages(job.spec, plan.base.template_paths())
        render_run_script(
            sequence_id=job.identity.sequence_id,
            job_id=job.identity.job_id,
            spec=job.spec,
            structure=d.structure,
            topology=d.topology,
            gmx_min_version=d.gromacs.min_version,
            gmx_developed_against=d.gromacs.developed_against,
            builder_version=plan.builder_version,
        )
    print(f"\nconfiguration, base project, templates and dependencies: "
          f"{ValidationStatus.CONFIG_VALIDATED.value}")
    print(f"dry-run rendering of {len(plan.jobs)} jobs: OK")
    out = plan.config.output_dir
    if (out / BUILD_REPORT_NAME).is_file():
        issues = verify_output(plan)
        if issues:
            raise MdflowError(issues)
        print(f"existing build in {out}: {ValidationStatus.STATIC_VALIDATED.value} "
              f"({len(plan.jobs)} packages re-checked)")
    elif out.exists():
        print(f"note: {out} exists but is not an mdflow build")
    else:
        print("no existing build found (run `mdflow build` to generate packages)")
    return 0


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mdflow", description="MD Automation Platform V0.1 - GROMACS Script Builder")
    p.add_argument("--version", action="version", version=f"mdflow {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("plan", help="validate the configuration and list the jobs (writes nothing)")
    sp.add_argument("config")
    sp.add_argument("--list", action="store_true", help="show every job instead of the first five")
    sp.set_defaults(func=cmd_plan)

    sb = sub.add_parser("build", help="generate all job packages, manifest.csv and build_report.json")
    sb.add_argument("config")
    sb.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output directory, but only if it is a previous mdflow build",
    )
    sb.set_defaults(func=cmd_build)

    sv = sub.add_parser("validate", help="check config, base project, templates, dependencies (and an existing build)")
    sv.add_argument("config")
    sv.set_defaults(func=cmd_validate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        return args.func(args)
    except MdflowError as err:
        _print_issues(err)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
