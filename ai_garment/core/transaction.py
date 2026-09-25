"""Undo journal used for transactional operations and rollback.

The Blender layer records an undo callable for every scene change it makes
(object created, modifier added, scene setting changed). ``rollback`` runs
them in reverse and reports failures instead of swallowing them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Tuple


@dataclass
class RollbackReport:
    ok: bool = True
    undone: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self):
        return {"ok": self.ok, "undone": list(self.undone), "errors": list(self.errors),
                "warnings": list(self.warnings)}


class Transaction:
    def __init__(self, name: str = "transaction"):
        self.name = name
        self._journal: List[Tuple[str, Callable[[], None]]] = []
        self.committed = False

    def record(self, description: str, undo: Callable[[], None]) -> None:
        self._journal.append((description, undo))

    def __len__(self) -> int:
        return len(self._journal)

    @property
    def entries(self) -> List[str]:
        return [d for d, _ in self._journal]

    def commit(self, keep: bool = False) -> "Transaction":
        """Finish the transaction. With ``keep=True`` return a new Transaction holding the
        journal so the caller can still roll the change back later (Garment.rollback)."""
        kept = Transaction(self.name)
        if keep:
            kept._journal = list(self._journal)
        self._journal = []
        self.committed = True
        return kept

    def rollback(self) -> RollbackReport:
        report = RollbackReport()
        if not self._journal:
            report.warnings.append(f"Nothing to roll back for '{self.name}'.")
            return report
        while self._journal:
            description, undo = self._journal.pop()
            try:
                undo()
                report.undone.append(description)
            except Exception as err:  # every failure is collected and reported
                report.ok = False
                report.errors.append(f"{description}: {err}")
        return report

    def __enter__(self) -> "Transaction":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.rollback()
        return False
