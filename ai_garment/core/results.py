"""Structured, JSON-serialisable results returned by every public call."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .errors import GarmentError, Issue


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if isinstance(value, float) and value != value:  # NaN
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


@dataclass
class Result:
    ok: bool = True
    action: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    operations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[Issue] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    dry_run: bool = False

    def __bool__(self) -> bool:
        return self.ok

    # builders -------------------------------------------------------------
    def add_error(self, code: str, message: str, suggestions: Optional[Iterable[str]] = None,
                  path: Optional[str] = None) -> "Result":
        self.errors.append(Issue(code, message, "error", path, list(suggestions or [])))
        self.ok = False
        return self

    def add_issue(self, issue: Issue) -> "Result":
        if issue.severity == "error":
            self.errors.append(issue)
            self.ok = False
        else:
            self.warn(issue.message)
        return self

    def warn(self, message: str) -> "Result":
        if message and message not in self.warnings:
            self.warnings.append(message)
        return self

    def log(self, message: str) -> "Result":
        self.logs.append(message)
        return self

    def step(self, description: str) -> "Result":
        self.operations.append(description)
        return self

    def merge(self, other: "Result", data_key: Optional[str] = None) -> "Result":
        self.ok = self.ok and other.ok
        self.operations.extend(other.operations)
        for w in other.warnings:
            self.warn(w)
        self.errors.extend(other.errors)
        self.logs.extend(other.logs)
        if data_key:
            self.data[data_key] = other.data
        return self

    @classmethod
    def failure(cls, action: str, code: str, message: str, suggestions: Optional[Iterable[str]] = None) -> "Result":
        return cls(action=action).add_error(code, message, suggestions)

    @classmethod
    def from_error(cls, action: str, error: GarmentError) -> "Result":
        r = cls(action=action)
        r.errors.append(error.to_issue())
        r.ok = False
        if error.details:
            r.data["details"] = error.details
        return r

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable({
            "ok": self.ok,
            "valid": self.data.get("valid", self.ok),
            "action": self.action,
            "dry_run": self.dry_run,
            "operations": list(self.operations),
            "warnings": list(self.warnings),
            "errors": [e.to_dict() for e in self.errors],
            "data": self.data,
            "logs": list(self.logs),
        })
