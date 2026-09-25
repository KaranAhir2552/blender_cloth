"""In-memory garment store (+ reconstruction from scene custom properties)."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from ..core.record import GarmentRecord
from ..core.vocabulary import normalize

__all__ = ["GarmentRecord", "GarmentStore"]


class GarmentStore:
    def __init__(self) -> None:
        self._records: Dict[str, GarmentRecord] = {}

    def add(self, record: GarmentRecord) -> None:
        self._records[record.id] = record

    def remove(self, gid: str) -> Optional[GarmentRecord]:
        return self._records.pop(gid, None)

    def get(self, key: str) -> Optional[GarmentRecord]:
        if key in self._records:
            return self._records[key]
        n = normalize(key)
        for r in self._records.values():
            if normalize(r.name) == n or (r.object_name and normalize(r.object_name) == n):
                return r
        return None

    def all(self) -> List[GarmentRecord]:
        return sorted(self._records.values(), key=lambda r: r.created)

    def clear(self) -> None:
        self._records.clear()

    def load_from_objects(self, objects) -> List[GarmentRecord]:
        """Rebuild records from objects carrying the ai_garment_record property."""
        loaded = []
        for obj in objects:
            raw = obj.get("ai_garment_record") if obj.get("ai_garment_role") == "garment" else None
            if not raw:
                continue
            rec = GarmentRecord.from_dict(json.loads(raw))
            rec.object_name = obj.name
            self._records[rec.id] = rec
            loaded.append(rec)
        return loaded
