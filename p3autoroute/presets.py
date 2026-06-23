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


class _Store:
    """Generic CRUD for presets persisted as a JSON list."""

    filename = ""
    cls = None  # type: ignore

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


class PricingStore(_Store):
    filename = "pricings.json"
    cls = Pricing

    def _seed(self) -> list:
        return [Pricing("default", True, list(DEFAULT_BUYING), list(DEFAULT_SELLING))]


class SortingStore(_Store):
    filename = "sortings.json"
    cls = Sorting

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
