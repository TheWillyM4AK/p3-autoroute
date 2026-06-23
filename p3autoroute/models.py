"""Domain models — port of scripts/{Rule,TradeStop,Route}.gd.

A Route has stops (TradeStop); each stop has 24 rules (Rule), one per good,
whose ORDER within the stop is significant (it defines the "goods order" that
is saved in the .rou order array).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List

from . import goods


class RuleMode(IntEnum):
    NONE = 0
    BUY = 1
    SELL = 2
    WITHDRAW = 3
    DEPOSIT = 4


class StopMode(IntEnum):
    DOCK = 0
    REPAIR = 1
    SKIP = 2


@dataclass
class Rule:
    good: int
    mode: int = RuleMode.NONE
    quantity: int = 0  # -1 means "maximum" (1_000_000_000 in binary)
    price: int = 0

    def to_dict(self) -> dict:
        return {"good": int(self.good), "mode": int(self.mode),
                "quantity": int(self.quantity), "price": int(self.price)}

    @staticmethod
    def from_dict(d: dict) -> "Rule":
        return Rule(int(d["good"]), int(d.get("mode", 0)),
                    int(d.get("quantity", 0)), int(d.get("price", 0)))


@dataclass
class TradeStop:
    town: int = 0
    mode: int = StopMode.DOCK
    rules: List[Rule] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"town": int(self.town), "mode": int(self.mode),
                "rules": [r.to_dict() for r in self.rules]}

    @staticmethod
    def from_dict(d: dict) -> "TradeStop":
        return TradeStop(int(d.get("town", 0)), int(d.get("mode", 0)),
                         [Rule.from_dict(r) for r in d.get("rules", [])])


@dataclass
class Route:
    name: str = "My Auto Route"
    trade_stops: List[TradeStop] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name,
                "stops": [s.to_dict() for s in self.trade_stops]}

    @staticmethod
    def from_dict(d: dict) -> "Route":
        return Route(d.get("name", "My Auto Route"),
                     [TradeStop.from_dict(s) for s in d.get("stops", [])])


def default_rules() -> List[Rule]:
    """24 rules in internal order (0..23), all in NONE mode."""
    return [Rule(g) for g in range(goods.COUNT)]
