"""Strict Jinja2 rendering.

Engine-agnostic: knows nothing about MDP semantics. Guarantees that

* every variable a template references is in the allowed set,
* every variable in the required set is actually referenced,
* rendering with a missing value raises (``StrictUndefined``), and
* no template markup survives in the output.
"""
from __future__ import annotations

import re
from pathlib import Path

import jinja2
from jinja2 import meta

from .errors import Issue, MdflowError

_ENV = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    keep_trailing_newline=True,
    autoescape=False,
    trim_blocks=False,
    lstrip_blocks=False,
)
_LEFTOVER = re.compile(r"\{\{|\}\}|\{%|%\}|\{#|#\}")


def read_template(path: Path, where: str) -> str:
    if not path.is_file():
        raise MdflowError(Issue("TEMPLATE_MISSING", f"template not found: {path}", where))
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise MdflowError(Issue("TEMPLATE_UNREADABLE", f"cannot read {path}: {exc}", where)) from exc


def referenced_variables(source: str, where: str = "") -> set[str]:
    try:
        ast = _ENV.parse(source)
    except jinja2.TemplateSyntaxError as exc:
        raise MdflowError(
            Issue("TEMPLATE_SYNTAX_ERROR", f"line {exc.lineno}: {exc.message}", where)
        ) from exc
    return set(meta.find_undeclared_variables(ast))


def check_variables(source: str, *, allowed: set[str], required: set[str], where: str) -> list[Issue]:
    used = referenced_variables(source, where)
    issues = []
    unknown = sorted(used - allowed)
    if unknown:
        issues.append(
            Issue(
                "TEMPLATE_UNKNOWN_VARIABLE",
                f"template uses variables mdflow does not provide: {unknown}; "
                f"allowed: {sorted(allowed)}",
                where,
            )
        )
    unused = sorted(required - used)
    if unused:
        issues.append(
            Issue(
                "TEMPLATE_MISSING_VARIABLE",
                f"template does not reference required variables {unused}; the scan "
                "value would be silently ignored",
                where,
            )
        )
    return issues


def render(source: str, context: dict, *, allowed: set[str], required: set[str], where: str) -> str:
    issues = check_variables(source, allowed=allowed, required=required, where=where)
    if issues:
        raise MdflowError(issues)
    try:
        out = _ENV.from_string(source).render(**context)
    except jinja2.UndefinedError as exc:
        raise MdflowError(Issue("TEMPLATE_UNDEFINED_VARIABLE", str(exc), where)) from exc
    m = _LEFTOVER.search(out)
    if m:
        line = out.count("\n", 0, m.start()) + 1
        raise MdflowError(
            Issue("TEMPLATE_UNRENDERED", f"template markup left in output at line {line}", where)
        )
    return out
