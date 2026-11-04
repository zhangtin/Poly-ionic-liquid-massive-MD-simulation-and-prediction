"""Loading of the scan YAML file and of the base-project descriptor.

Responsibilities: YAML parsing (with duplicate-key detection, which PyYAML
would otherwise silently resolve), schema validation via :mod:`mdflow.schemas`,
and resolution of relative paths. Relative paths inside a YAML file are
resolved against the directory containing that file, never against the
current working directory.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .errors import Issue, MdflowError
from .schemas import BaseProjectDescriptor, ScanFile

BASE_DESCRIPTOR_NAME = "base_project.yaml"


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def read_yaml(path: Path) -> Any:
    """Parse a YAML file, turning every failure into an :class:`MdflowError`."""
    if not path.exists():
        raise MdflowError(Issue("FILE_NOT_FOUND", f"file does not exist: {path}", str(path)))
    if not path.is_file():
        raise MdflowError(Issue("NOT_A_FILE", f"not a regular file: {path}", str(path)))
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise MdflowError(Issue("FILE_UNREADABLE", f"cannot read {path}: {exc}", str(path))) from exc
    try:
        return yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        code = "YAML_DUPLICATE_KEY" if "duplicate key" in str(exc) else "YAML_PARSE_ERROR"
        raise MdflowError(Issue(code, f"invalid YAML: {exc}", str(path))) from exc


def _pydantic_issues(exc: ValidationError, prefix: str) -> list[Issue]:
    issues = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        where = f"{prefix}{loc}" if loc else prefix.rstrip(".")
        issues.append(Issue("SCHEMA_ERROR", f"{err['msg']} (got {err.get('input')!r})", where))
    return issues


@dataclass(frozen=True)
class LoadedConfig:
    """A schema-valid scan configuration plus resolved paths."""

    path: Path
    sha256: str
    data: ScanFile
    base_project_dir: Path
    output_dir: Path


def load_config(path: str | Path) -> LoadedConfig:
    path = Path(path).resolve()
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise MdflowError(Issue("SCHEMA_ERROR", "top level of the scan file must be a mapping", str(path)))
    try:
        data = ScanFile.model_validate(raw)
    except ValidationError as exc:
        raise MdflowError(_pydantic_issues(exc, "")) from exc
    root = path.parent
    return LoadedConfig(
        path=path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        data=data,
        base_project_dir=(root / data.base_project).resolve(),
        output_dir=(root / data.output.directory).resolve(),
    )


@dataclass(frozen=True)
class BaseProject:
    """A schema-valid base-project descriptor with its directory."""

    root: Path
    descriptor: BaseProjectDescriptor

    @property
    def descriptor_path(self) -> Path:
        return self.root / BASE_DESCRIPTOR_NAME

    def template_paths(self) -> dict[str, Path]:
        t = self.descriptor.templates
        return {
            "em": self.root / t.em,
            "nvt": self.root / t.nvt,
            "npt": self.root / t.npt,
            "production": self.root / t.production,
        }


def load_base_project(root: str | Path) -> BaseProject:
    root = Path(root).resolve()
    if not root.exists():
        raise MdflowError(Issue("BASE_PROJECT_MISSING", f"base project directory does not exist: {root}", "base_project"))
    if not root.is_dir():
        raise MdflowError(Issue("BASE_PROJECT_MISSING", f"base project is not a directory: {root}", "base_project"))
    desc_path = root / BASE_DESCRIPTOR_NAME
    if not desc_path.is_file():
        raise MdflowError(
            Issue("BASE_DESCRIPTOR_MISSING", f"missing {BASE_DESCRIPTOR_NAME} in {root}", str(desc_path))
        )
    raw = read_yaml(desc_path)
    if not isinstance(raw, dict):
        raise MdflowError(Issue("SCHEMA_ERROR", "base project descriptor must be a mapping", str(desc_path)))
    try:
        desc = BaseProjectDescriptor.model_validate(raw)
    except ValidationError as exc:
        raise MdflowError(_pydantic_issues(exc, f"{BASE_DESCRIPTOR_NAME}:")) from exc
    return BaseProject(root=root, descriptor=desc)
