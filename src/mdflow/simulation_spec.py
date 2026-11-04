"""Engine-independent simulation definition.

Everything here is expressed in explicit physical units (the unit is part of
every field name) and uses :class:`decimal.Decimal` so that unit conversions
are exact. Nothing in this module knows about GROMACS file formats or keys.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .errors import Issue, MdflowError
from .schemas import SimulationConfig

FS_PER_NS = Decimal(1_000_000)
FS_PER_PS = Decimal(1_000)


def to_decimal(value: float | int) -> Decimal:
    """Exact decimal for a YAML number.

    ``repr(float)`` is the shortest string that round-trips, so ``0.1`` becomes
    ``Decimal('0.1')`` rather than the binary expansion of 0.1.
    """
    if isinstance(value, bool):  # bool is an int subclass; never a quantity
        raise TypeError("boolean is not a number")
    return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)


def fmt_decimal(value: Decimal) -> str:
    """Plain (non-scientific) canonical string: 300.0 -> '300', 0.0020 -> '0.002'."""
    s = format(value.normalize(), "f")
    return s


def json_number(value: Decimal) -> int | float:
    """Number for JSON/CSV output: integral values as int, otherwise float."""
    return int(value) if value == value.to_integral_value() else float(value)


def steps_from_duration(duration_ns: Decimal, timestep_fs: Decimal) -> int:
    """Number of integration steps covering ``duration_ns`` exactly.

    Raises ``ValueError`` if the duration is not an integer multiple of the
    timestep -- rounding would silently change the simulated time.
    """
    if duration_ns <= 0 or timestep_fs <= 0:
        raise ValueError("duration and timestep must be positive")
    steps = duration_ns * FS_PER_NS / timestep_fs
    if steps != steps.to_integral_value():
        raise ValueError(
            f"{fmt_decimal(duration_ns)} ns is not an integer multiple of "
            f"{fmt_decimal(timestep_fs)} fs ({steps} steps)"
        )
    return int(steps)


class StageKind(str, Enum):
    MINIMIZATION = "minimization"
    DYNAMICS = "dynamics"


@dataclass(frozen=True)
class StageSpec:
    """One stage of the protocol.

    ``ensemble`` is ``None`` for minimization and for the production stage,
    whose ensemble is inherited from the base project (it is determined by the
    production template, not by mdflow).
    """

    name: str
    kind: StageKind
    ensemble: str | None
    steps: int
    duration_ns: Decimal | None  # None for minimization (step-limited)


@dataclass(frozen=True)
class Protocol:
    """The four-stage protocol shared by every job of a scan."""

    timestep_fs: Decimal
    em_max_steps: int
    nvt_ns: Decimal
    npt_ns: Decimal
    production_ns: Decimal

    @classmethod
    def from_config(cls, sim: SimulationConfig) -> "Protocol":
        proto = cls(
            timestep_fs=to_decimal(sim.timestep_fs),
            em_max_steps=sim.em_steps,
            nvt_ns=to_decimal(sim.nvt_ns),
            npt_ns=to_decimal(sim.npt_ns),
            production_ns=to_decimal(sim.production_ns),
        )
        proto.stages()  # raises MdflowError on non-integral step counts
        return proto

    @property
    def timestep_ps(self) -> Decimal:
        return self.timestep_fs / FS_PER_PS

    def stages(self) -> tuple[StageSpec, ...]:
        issues: list[Issue] = []
        steps: dict[str, int] = {}
        for name, dur in (("nvt", self.nvt_ns), ("npt", self.npt_ns), ("production", self.production_ns)):
            try:
                steps[name] = steps_from_duration(dur, self.timestep_fs)
            except ValueError as exc:
                issues.append(Issue("NON_INTEGER_STEPS", str(exc), f"simulation.{name}_ns"))
        if issues:
            raise MdflowError(issues)
        return (
            StageSpec("em", StageKind.MINIMIZATION, None, self.em_max_steps, None),
            StageSpec("nvt", StageKind.DYNAMICS, "NVT", steps["nvt"], self.nvt_ns),
            StageSpec("npt", StageKind.DYNAMICS, "NPT", steps["npt"], self.npt_ns),
            StageSpec("production", StageKind.DYNAMICS, None, steps["production"], self.production_ns),
        )

    def fingerprint(self) -> dict:
        """Canonical, JSON-serialisable description used in job identity."""
        return {
            "timestep_fs": fmt_decimal(self.timestep_fs),
            "stages": [
                {
                    "name": s.name,
                    "kind": s.kind.value,
                    "steps": s.steps,
                }
                for s in self.stages()
            ],
        }


@dataclass(frozen=True)
class SimulationSpec:
    """Complete, engine-independent definition of one job."""

    temperature_K: Decimal
    pressure_bar: Decimal
    replica: int
    random_seed: int
    protocol: Protocol

    @property
    def stages(self) -> tuple[StageSpec, ...]:
        return self.protocol.stages()
