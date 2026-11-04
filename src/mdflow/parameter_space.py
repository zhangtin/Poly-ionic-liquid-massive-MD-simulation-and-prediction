"""Parameter Space Engine.

Expands the scan into an ordered list of points, assigns replica numbers,
stable job identities and reproducible random seeds. This module never reads
or writes GROMACS files.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .errors import Issue, MdflowError
from .schemas import ScanConfig
from .simulation_spec import fmt_decimal, to_decimal

#: Seeds are drawn from [1, SEED_MAX]. GROMACS reads gen-seed as a 32-bit
#: int and ld-seed as int64, and treats -1 as "pick a random seed"; staying in
#: the positive signed 32-bit range is valid for both.
SEED_MIN = 1
SEED_MAX = 2**31 - 1

JOB_ID_HEX_CHARS = 16


@dataclass(frozen=True)
class ScanPoint:
    temperature_K: Decimal
    pressure_bar: Decimal
    replica: int  # 1-based


@dataclass(frozen=True)
class JobIdentity:
    sequence_id: str  # human-readable, e.g. job_0001 (NOT a scientific identity)
    job_id: str  # content hash, the scientific identity
    random_seed: int
    point: ScanPoint
    identity_document: str  # canonical JSON the job_id was hashed from


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _check_unique(values: list[Decimal], field: str) -> list[Issue]:
    seen: dict[Decimal, int] = {}
    issues = []
    for i, v in enumerate(values):
        if v in seen:
            issues.append(
                Issue(
                    "DUPLICATE_VALUE",
                    f"value {fmt_decimal(v)} appears more than once "
                    f"(positions {seen[v]} and {i}); remove the duplicate",
                    f"scan.{field}",
                )
            )
        else:
            seen[v] = i
    return issues


def expand(scan: ScanConfig) -> list[ScanPoint]:
    """Cartesian product temperature x pressure x replica (in that nesting order).

    Duplicate values are reported as errors instead of being silently
    dropped, so the job count always equals the product of the list lengths.
    """
    temps = [to_decimal(t) for t in scan.temperature_K]
    press = [to_decimal(p) for p in scan.pressure_bar]
    issues = _check_unique(temps, "temperature_K") + _check_unique(press, "pressure_bar")
    if issues:
        raise MdflowError(issues)
    points = [
        ScanPoint(t, p, r)
        for t, p, r in itertools.product(temps, press, range(1, scan.replicas + 1))
    ]
    # Invariant: by construction every combination is unique.
    assert len(set(points)) == len(points)
    return points


def identity_document(
    point: ScanPoint,
    *,
    base_project_sha256: str,
    protocol_fingerprint: dict,
    builder_version: str,
) -> str:
    """Canonical JSON describing everything that defines a job scientifically.

    The experiment/project name and output location are deliberately NOT part
    of the identity: renaming a scan must not change its jobs.
    """
    return canonical_json(
        {
            "builder_version": builder_version,
            "base_project_sha256": base_project_sha256,
            "protocol": protocol_fingerprint,
            "parameters": {
                "temperature_K": fmt_decimal(point.temperature_K),
                "pressure_bar": fmt_decimal(point.pressure_bar),
                "replica": point.replica,
            },
        }
    )


def job_id_from_document(doc: str) -> str:
    return hashlib.sha256(doc.encode("ascii")).hexdigest()[:JOB_ID_HEX_CHARS]


def seed_from_document(doc: str, attempt: int = 0) -> int:
    """Deterministic seed in [SEED_MIN, SEED_MAX] derived from the identity."""
    digest = hashlib.sha256(f"mdflow-seed-v1|{attempt}|{doc}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big") % (SEED_MAX - SEED_MIN + 1) + SEED_MIN


def assign_identities(
    points: list[ScanPoint],
    *,
    base_project_sha256: str,
    protocol_fingerprint: dict,
    builder_version: str,
) -> list[JobIdentity]:
    width = max(4, len(str(len(points))))
    out: list[JobIdentity] = []
    used_ids: set[str] = set()
    used_seeds: set[int] = set()
    for idx, point in enumerate(points, start=1):
        doc = identity_document(
            point,
            base_project_sha256=base_project_sha256,
            protocol_fingerprint=protocol_fingerprint,
            builder_version=builder_version,
        )
        job_id = job_id_from_document(doc)
        if job_id in used_ids:  # 64-bit prefix collision: astronomically unlikely
            raise MdflowError(Issue("JOB_ID_COLLISION", f"job id collision for {point}"))
        # Seeds must differ between all jobs. A collision (p ~ n^2 / 2^32) is
        # resolved deterministically by re-hashing with an attempt counter, so
        # the same input still always yields the same seeds.
        attempt = 0
        seed = seed_from_document(doc, attempt)
        while seed in used_seeds:
            attempt += 1
            seed = seed_from_document(doc, attempt)
        used_ids.add(job_id)
        used_seeds.add(seed)
        out.append(JobIdentity(f"job_{idx:0{width}d}", job_id, seed, point, doc))
    return out
