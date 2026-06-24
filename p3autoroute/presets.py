"""Sorting and Pricing presets — port of ui/Sorting/* and ui/Pricing/*.

- Sorting: a permutation of the 24 goods (display/processing order).
- Pricing: a buying and a selling price per good (24 + 24).

Persistence: the original used a folder of .tres resources; here presets are
stored as JSON (one list per type). Same semantics: a list of presets, one of
them the default, with seeds loaded only if the user has no presets of their own.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List

from . import goods
from .models import RuleMode, TradeStop
from .paths import data_dir

# --------------------------------------------------------------------------- #
# Seeds (from assets/pricings/*.tres and assets/sortings/*.tres)
# --------------------------------------------------------------------------- #
DEFAULT_BUYING = [130, 1000, 500, 50, 25, 120, 200, 250, 280, 900, 100, 70,
                  350, 280, 1000, 60, 900, 450, 220, 80, 1, 1, 1, 1]
DEFAULT_SELLING = [140, 1200, 550, 55, 30, 130, 400, 360, 360, 1150, 140, 80,
                   440, 330, 1200, 65, 1100, 600, 260, 90, 1000, 1000, 1000, 1000]

_SORT_ENGLISH = [3, 19, 8, 2, 0, 17, 5, 12, 13, 1, 10, 16, 15, 18, 4, 9, 6, 11, 7, 14, 20, 21, 22, 23]
_SORT_INTERNAL = list(range(goods.COUNT))
_SORT_ITALIANO = [3, 17, 1, 18, 13, 16, 0, 14, 11, 19, 5, 10, 15, 9, 2, 4, 6, 8, 12, 7, 20, 21, 22, 23]


# --------------------------------------------------------------------------- #
# Import coercion helpers — keep hand-edited / foreign files from producing
# presets that would later break apply_pricing / apply_sorting.
# --------------------------------------------------------------------------- #
def _coerce_int_list(values, default: List[int], count: int) -> List[int]:
    """Exactly `count` ints, taking `default[i]` whenever an entry is missing
    or not an int (so buying/selling are always indexable by good id)."""
    out = []
    for i in range(count):
        try:
            out.append(int(values[i]))
        except (IndexError, KeyError, TypeError, ValueError):
            out.append(int(default[i]))
    return out


def _coerce_permutation(values, count: int) -> List[int]:
    """A full permutation of 0..count-1: the valid, unique, in-range ids the
    file provided, then any missing ones appended in natural order."""
    seen = []
    for v in (values or []):
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if 0 <= iv < count and iv not in seen:
            seen.append(iv)
    for i in range(count):
        if i not in seen:
            seen.append(i)
    return seen


@dataclass
class Pricing:
    id: str
    is_default: bool = False
    buying: List[int] = field(default_factory=lambda: list(DEFAULT_BUYING))
    selling: List[int] = field(default_factory=lambda: list(DEFAULT_SELLING))

    def to_dict(self) -> dict:
        return {"id": self.id, "is_default": self.is_default,
                "buying": list(self.buying), "selling": list(self.selling)}

    @staticmethod
    def from_dict(d: dict) -> "Pricing":
        return Pricing(d["id"], bool(d.get("is_default", False)),
                       list(d.get("buying", DEFAULT_BUYING)),
                       list(d.get("selling", DEFAULT_SELLING)))

    @staticmethod
    def coerce(d: dict) -> "Pricing | None":
        """Build a valid Pricing from an untrusted (imported) dict, or None."""
        if not isinstance(d, dict):
            return None
        return Pricing(
            id=str(d.get("id") or "imported"),
            is_default=False,
            buying=_coerce_int_list(d.get("buying"), DEFAULT_BUYING, goods.COUNT),
            selling=_coerce_int_list(d.get("selling"), DEFAULT_SELLING, goods.COUNT),
        )


@dataclass
class Sorting:
    id: str
    is_default: bool = False
    goods: List[int] = field(default_factory=lambda: list(_SORT_INTERNAL))

    def to_dict(self) -> dict:
        return {"id": self.id, "is_default": self.is_default, "goods": list(self.goods)}

    @staticmethod
    def from_dict(d: dict) -> "Sorting":
        order = d.get("goods") or list(_SORT_INTERNAL)
        return Sorting(d["id"], bool(d.get("is_default", False)), list(order))

    @staticmethod
    def coerce(d: dict) -> "Sorting | None":
        """Build a valid Sorting from an untrusted (imported) dict, or None.

        The order is repaired into a full 24-good permutation so apply_sorting
        never raises on a partial or out-of-range list."""
        if not isinstance(d, dict):
            return None
        return Sorting(
            id=str(d.get("id") or "imported"),
            is_default=False,
            goods=_coerce_permutation(d.get("goods"), goods.COUNT),
        )


EXPORT_TYPE = "p3autoroute-presets"
EXPORT_VERSION = 1


def _content(item) -> dict:
    """The preset's data minus its identity, for duplicate detection."""
    d = item.to_dict()
    d.pop("id", None)
    d.pop("is_default", None)
    return d


def _unique_id(base: str, taken) -> str:
    """`base`, or `base (2)`, `base (3)`, … — the first id not already taken."""
    if base not in taken:
        return base
    i = 2
    while f"{base} ({i})" in taken:
        i += 1
    return f"{base} ({i})"


def _extract_items(parsed, kind: str, discriminator: str):
    """Pull the preset list out of an imported payload, tolerating shapes:
    the export wrapper ({"kind", "items"}), a `{kind: [...]}` map, a bare list,
    or a single bare preset (detected by `discriminator`). Returns
    (items, declared_kind) — declared_kind lets the caller reject a file that
    is explicitly tagged as the *other* preset type."""
    if isinstance(parsed, dict):
        declared = parsed.get("kind")
        if isinstance(parsed.get("items"), list):
            return parsed["items"], declared
        if isinstance(parsed.get(kind), list):
            return parsed[kind], declared
        if discriminator in parsed:
            return [parsed], declared
        return [], declared
    if isinstance(parsed, list):
        return parsed, None
    return [], None


class _Store:
    """Generic CRUD for presets persisted as a JSON list."""

    filename = ""
    cls = None  # type: ignore
    kind = ""          # payload tag, e.g. "pricings" — used by import/export
    discriminator = ""  # field that marks a bare preset of this kind

    def __init__(self) -> None:
        self.path = os.path.join(data_dir(), self.filename)
        self.items: list = []
        self._load()

    def _seed(self) -> list:  # pragma: no cover - overridden
        return []

    def _load(self) -> None:
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.items = [self.cls.from_dict(d) for d in raw]
        if not self.items:
            self.items = self._seed()
            self.save_all()

    def save_all(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([it.to_dict() for it in self.items], f, indent=2)

    def find(self, preset_id: str):
        return next((it for it in self.items if it.id == preset_id), None)

    def get_default(self):
        return next((it for it in self.items if it.is_default),
                    self.items[0] if self.items else None)

    def set_default(self, preset_id: str) -> None:
        for it in self.items:
            it.is_default = (it.id == preset_id)
        self.save_all()

    def upsert(self, preset) -> None:
        existing = self.find(preset.id)
        if existing:
            self.items[self.items.index(existing)] = preset
        else:
            self.items.append(preset)
        self.save_all()

    def rename(self, old_id: str, new_id: str) -> None:
        it = self.find(old_id)
        if it:
            it.id = new_id
            self.save_all()

    def delete(self, preset_id: str) -> None:
        it = self.find(preset_id)
        if it:
            self.items.remove(it)
            self.save_all()

    # ------------------------------------------------------------- import/export
    def export_payload(self, ids=None) -> dict:
        """A JSON-serializable wrapper with the chosen presets (all if `ids` is
        falsy). Tagged with `kind` so import can reject the wrong file type."""
        chosen = self.items if not ids else [it for it in self.items if it.id in set(ids)]
        return {"type": EXPORT_TYPE, "kind": self.kind, "version": EXPORT_VERSION,
                "items": [it.to_dict() for it in chosen]}

    def import_payload(self, parsed) -> dict:
        """Merge presets from a parsed payload into the store, non-destructively:
        an id clash with identical content is skipped; a clash with different
        content is imported under a fresh id; nothing is ever overwritten and
        imports never become the default. Returns {ok, imported, skipped}."""
        items, declared = _extract_items(parsed, self.kind, self.discriminator)
        if declared and declared != self.kind:
            return {"ok": False,
                    "error": f"This file holds '{declared}', not {self.kind}."}
        coerced = [c for c in (self.cls.coerce(d) for d in items) if c is not None]
        if not coerced:
            return {"ok": False, "error": f"No {self.kind} found in the file."}

        taken = {it.id for it in self.items}
        imported, skipped = [], []
        for preset in coerced:
            existing = self.find(preset.id)
            if existing is not None and _content(existing) == _content(preset):
                skipped.append(preset.id)
                continue
            preset.is_default = False
            preset.id = _unique_id(preset.id, taken)
            taken.add(preset.id)
            self.items.append(preset)
            imported.append(preset.id)
        if imported:
            self.save_all()
        return {"ok": True, "imported": imported, "skipped": skipped}


class PricingStore(_Store):
    filename = "pricings.json"
    cls = Pricing
    kind = "pricings"
    discriminator = "buying"

    def _seed(self) -> list:
        return [Pricing("default", True, list(DEFAULT_BUYING), list(DEFAULT_SELLING))]


class SortingStore(_Store):
    filename = "sortings.json"
    cls = Sorting
    kind = "sortings"
    discriminator = "goods"

    def _seed(self) -> list:
        return [
            Sorting("english", True, list(_SORT_ENGLISH)),
            Sorting("internal", False, list(_SORT_INTERNAL)),
            Sorting("italiano", False, list(_SORT_ITALIANO)),
        ]


# --------------------------------------------------------------------------- #
# Applying presets to a stop (port of RuleInfo.gd)
# --------------------------------------------------------------------------- #
def apply_sorting(stop: TradeStop, order: List[int]) -> None:
    """Reorders the stop's rules according to the goods order `order`."""
    stop.rules.sort(key=lambda r: order.index(int(r.good)))


def apply_pricing(stop: TradeStop, pricing: Pricing) -> None:
    """Sets each rule's price by its mode (BUY -> buying, SELL -> selling)."""
    for r in stop.rules:
        if r.mode == RuleMode.BUY:
            r.price = pricing.buying[int(r.good)]
        elif r.mode == RuleMode.SELL:
            r.price = pricing.selling[int(r.good)]
