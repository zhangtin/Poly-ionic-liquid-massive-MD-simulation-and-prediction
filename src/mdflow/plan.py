"""Glue: turn a scan YAML file into a fully validated, in-memory build plan.

Used by every CLI command. ``make_plan`` performs all configuration-level
checks (``CONFIG_VALIDATED``) and collects every issue it can find before
failing, so users see all problems at once.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import BUILDER_VERSION
from .config import BaseProject, LoadedConfig, load_base_project, load_config
from .errors import Issue, MdflowError
from .parameter_space import JobIdentity, assign_identities, expand
from .simulation_spec import Protocol, SimulationSpec
from .validator import base_project_sha256, check_base_project, check_output_path, check_scan_limits


@dataclass(frozen=True)
class PlannedJob:
    identity: JobIdentity
    spec: SimulationSpec


@dataclass(frozen=True)
class Plan:
    config: LoadedConfig
    base: BaseProject
    protocol: Protocol
    base_identity_files: list[str]  # files hashed into base_sha256
    packaged_files: list[str]  # base files copied into every job
    base_sha256: str
    jobs: list[PlannedJob]
    builder_version: str = BUILDER_VERSION


def make_plan(config_path, *, for_build: bool = False, overwrite: bool = False) -> Plan:
    cfg = load_config(config_path)
    base = load_base_project(cfg.base_project_dir)

    issues: list[Issue] = []
    identity_files, packaged, base_issues = check_base_project(base)
    issues += base_issues

    protocol = None
    try:
        protocol = Protocol.from_config(cfg.data.simulation)
    except MdflowError as exc:
        issues += exc.issues

    points = None
    try:
        points = expand(cfg.data.scan)
    except MdflowError as exc:
        issues += exc.issues

    issues += check_scan_limits(cfg, base)
    issues += check_output_path(cfg, base, for_build=for_build, overwrite=overwrite)
    if issues:
        raise MdflowError(issues)
    assert protocol is not None and points is not None

    base_sha = base_project_sha256(base, identity_files)
    identities = assign_identities(
        points,
        base_project_sha256=base_sha,
        protocol_fingerprint=protocol.fingerprint(),
        builder_version=BUILDER_VERSION,
    )
    jobs = [
        PlannedJob(
            ident,
            SimulationSpec(
                temperature_K=ident.point.temperature_K,
                pressure_bar=ident.point.pressure_bar,
                replica=ident.point.replica,
                random_seed=ident.random_seed,
                protocol=protocol,
            ),
        )
        for ident in identities
    ]
    return Plan(cfg, base, protocol, identity_files, packaged, base_sha, jobs)
