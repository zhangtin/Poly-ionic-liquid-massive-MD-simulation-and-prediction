"""Error and issue types shared by all mdflow modules."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    """A single validation finding.

    ``code`` is a stable machine-readable identifier (used by tests and
    reports); ``where`` points at the offending config field or file.
    """

    code: str
    message: str
    where: str = ""

    def __str__(self) -> str:
        loc = f" [{self.where}]" if self.where else ""
        return f"{self.code}{loc}: {self.message}"


class MdflowError(Exception):
    """Raised when one or more validation issues block an operation."""

    def __init__(self, issues: list[Issue] | Issue):
        if isinstance(issues, Issue):
            issues = [issues]
        self.issues: list[Issue] = list(issues)
        super().__init__("\n".join(str(i) for i in self.issues))

    @property
    def codes(self) -> set[str]:
        return {i.code for i in self.issues}
