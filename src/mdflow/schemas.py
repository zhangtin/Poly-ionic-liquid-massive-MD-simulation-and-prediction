"""Pydantic schemas for the user scan configuration and the base-project descriptor.

The schemas only check *shape and types* (plus trivially invalid values such
as non-positive temperatures). Cross-field and file-system checks live in
:mod:`mdflow.validator`. Inputs are never silently corrected: unknown keys,
wrong types (including strings or booleans where numbers are expected) and
non-finite numbers are rejected.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

_STRICT = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

ProjectName = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
]
PositiveFloat = Annotated[float, Field(gt=0)]


# --------------------------------------------------------------------------- #
# User scan configuration (YAML)                                               #
# --------------------------------------------------------------------------- #
class ScanConfig(BaseModel):
    model_config = _STRICT

    #: Thermostat reference temperatures, kelvin.
    temperature_K: Annotated[list[PositiveFloat], Field(min_length=1)]
    #: Isotropic barostat reference pressures, bar.
    pressure_bar: Annotated[list[PositiveFloat], Field(min_length=1)]
    #: Number of independent replicas per (T, P) point.
    replicas: Annotated[int, Field(ge=1, le=1000)]


class SimulationConfig(BaseModel):
    model_config = _STRICT

    timestep_fs: PositiveFloat
    #: Maximum number of energy-minimization steps (not time-based).
    em_steps: Annotated[int, Field(ge=1)]
    nvt_ns: PositiveFloat
    npt_ns: PositiveFloat
    production_ns: PositiveFloat


class OutputConfig(BaseModel):
    model_config = _STRICT

    directory: Annotated[str, StringConstraints(min_length=1)]


class ScanFile(BaseModel):
    """Top-level structure of a scan YAML file."""

    model_config = _STRICT

    project: ProjectName
    base_project: Annotated[str, StringConstraints(min_length=1)]
    scan: ScanConfig
    simulation: SimulationConfig
    output: OutputConfig


# --------------------------------------------------------------------------- #
# Base-project descriptor (base_project.yaml)                                  #
# --------------------------------------------------------------------------- #
class TemplateSet(BaseModel):
    model_config = _STRICT

    em: str
    nvt: str
    npt: str
    production: str


class GromacsInfo(BaseModel):
    model_config = _STRICT

    min_version: str
    developed_against: str | None = None


class Limits(BaseModel):
    model_config = _STRICT

    temperature_K: Annotated[list[PositiveFloat], Field(min_length=2, max_length=2)]
    pressure_bar: Annotated[list[PositiveFloat], Field(min_length=2, max_length=2)]
    max_timestep_fs: PositiveFloat


class BaseProjectDescriptor(BaseModel):
    model_config = _STRICT

    name: ProjectName
    description: str = ""
    structure: str
    topology: str
    templates: TemplateSet
    gromacs: GromacsInfo
    limits: Limits
