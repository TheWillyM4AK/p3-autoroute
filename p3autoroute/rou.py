"""Reading/writing .rou files — port of scripts/mapper/RouteBinaryMapper.gd.

Layout of each stop (220 bytes):
    0x00..0x01  u16   padding (0)
    0x02        u8    town index
    0x03        u8    mode (DOCK=0, REPAIR=1, SKIP=9; when reading: & 0xB)
    0x04..0x1B  24xu8 goods ORDER array (position j -> good id)
    0x1C..0x7B  24xs32 prices, indexed by good id
    0x7C..0xDB  24xs32 quantities, indexed by good id
"""
from __future__ import annotations

import os
import struct
from typing import List

from . import compressor, goods
from .models import Route, Rule, RuleMode, StopMode, TradeStop

STOP_SIZE = 220
MAX_AMOUNT = 1_000_000_000

# Mode byte written for each StopMode (REPAIR=1, SKIP=9 as in the original).
_STOP_MODE_BYTE = {StopMode.DOCK: 0, StopMode.REPAIR: 1, StopMode.SKIP: 9}


def serialize_route(route: Route) -> bytes:
    """Route -> compressed bytes ready to write to a .rou."""
    raw = bytearray(len(route.trade_stops) * STOP_SIZE)
    for i, stop in enumerate(route.trade_stops):
        base = i * STOP_SIZE
        raw[base + 0x2] = int(stop.town) & 0xFF
        raw[base + 0x3] = _STOP_MODE_BYTE.get(StopMode(int(stop.mode)), 0)
        for j, rule in enumerate(stop.rules):
            good = int(rule.good)
            size = goods.SIZES[good]
            price = 0
            quantity = 0
            mode = RuleMode(int(rule.mode))
            if mode == RuleMode.BUY:
                quantity = rule.quantity * size if rule.quantity != -1 else MAX_AMOUNT
                price = -rule.price
            elif mode == RuleMode.SELL:
                quantity = rule.quantity * size if rule.quantity != -1 else MAX_AMOUNT
                price = rule.price
            elif mode == RuleMode.WITHDRAW:
                quantity = rule.quantity * size if rule.quantity != -1 else MAX_AMOUNT
            elif mode == RuleMode.DEPOSIT:
                quantity = -rule.quantity * size if rule.quantity != -1 else -MAX_AMOUNT
            # NONE -> price=0, quantity=0
            raw[base + 0x4 + j] = good & 0xFF
            struct.pack_into("<i", raw, base + 0x1C + good * 4, price)
            struct.pack_into("<i", raw, base + 0x7C + good * 4, quantity)
    return compressor.encode(bytes(raw))


def parse_route(data: bytes, name: str) -> Route:
    """compressed bytes of a .rou -> Route."""
    decompressed = compressor.decode(data)
    stop_count = len(decompressed) // STOP_SIZE
    route = Route(name=name)
    for i in range(stop_count):
        base = i * STOP_SIZE
        town = decompressed[base + 0x2]
        mode_byte = decompressed[base + 0x3] & 0xB
        if mode_byte == 0:
            stop_mode = StopMode.DOCK
        elif mode_byte == 1:
            stop_mode = StopMode.REPAIR
        else:
            stop_mode = StopMode.SKIP

        order = list(decompressed[base + 0x4: base + 0x4 + 24])
        prices = list(struct.unpack_from("<24i", decompressed, base + 0x1C))
        quantities = list(struct.unpack_from("<24i", decompressed, base + 0x7C))

        stop = TradeStop(town=town, mode=stop_mode, rules=[])
        for j in range(24):
            good = order[j]
            q = quantities[good]
            p = prices[good]
            if q == 0:
                mode = RuleMode.NONE
            elif p == 0 and q < 0:
                mode = RuleMode.DEPOSIT
            elif p == 0 and q > 0:
                mode = RuleMode.WITHDRAW
            elif p < 0:
                mode = RuleMode.BUY
            else:
                mode = RuleMode.SELL
            quantity = abs(q) // goods.SIZES[good]
            if abs(q) == MAX_AMOUNT:
                quantity = -1
            stop.rules.append(Rule(good=good, mode=mode, quantity=quantity, price=abs(p)))
        route.trade_stops.append(stop)
    return route


def _strip_name(name: str) -> str:
    return name[:-4] if name.lower().endswith(".rou") else name


class RouteRepository:
    """CRUD of .rou files in a folder (the game's Save/AutoRoute)."""

    def __init__(self, path: str) -> None:
        self.path = path

    def _file(self, name: str) -> str:
        return os.path.join(self.path, _strip_name(name) + ".rou")

    def create(self, route: Route) -> None:
        route.name = _strip_name(route.name)
        with open(self._file(route.name), "wb") as f:
            f.write(serialize_route(route))

    def read(self, name: str) -> Route:
        name = _strip_name(name)
        with open(self._file(name), "rb") as f:
            data = f.read()
        return parse_route(data, name)

    def delete(self, name: str) -> None:
        path = self._file(name)
        if os.path.exists(path):
            os.remove(path)

    def list_names(self) -> List[str]:
        if not os.path.isdir(self.path):
            return []
        names = [os.path.splitext(fn)[0] for fn in os.listdir(self.path)
                 if fn.lower().endswith(".rou")]
        return sorted(names, key=str.lower)

    def search(self) -> List[Route]:
        return [self.read(n) for n in self.list_names()]
