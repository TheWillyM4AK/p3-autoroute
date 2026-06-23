"""Route generators (route presets) — port of ui/RouteModels/*.

Each generator returns a list of TradeStop. `good_data` is a list of 24 dicts
(in internal order 0..23) with the keys:
    good, enabled, quantity, buying_price, selling_price

The first stop is always a SKIP in the (town+1) town "to avoid notifications",
just like the original.
"""
from __future__ import annotations

from typing import Dict, List

from . import goods, towns
from .models import Rule, RuleMode, StopMode, TradeStop

MAX_STOPS = 20


def _empty_rules() -> List[Rule]:
    return [Rule(g, RuleMode.NONE, 0, 0) for g in range(goods.COUNT)]


def _skip_first_stop(town: int) -> TradeStop:
    return TradeStop(town=(town + 1) % towns.COUNT, mode=StopMode.SKIP,
                     rules=_empty_rules())


def day_trader(town: int, good_data: List[Dict]) -> List[TradeStop]:
    stops = [_skip_first_stop(town)]
    for i in range(MAX_STOPS - 1):
        good_counter = 0
        stop = TradeStop(town=town, mode=StopMode.DOCK, rules=[])
        for g in good_data:
            rule = Rule(g["good"], RuleMode.NONE, 0, 1)
            if g["enabled"]:
                if good_counter % 2 == i % 2:
                    rule.mode = RuleMode.BUY
                    rule.quantity = -1
                    rule.price = g["buying_price"]
                else:
                    rule.mode = RuleMode.SELL
                    rule.quantity = -1
                    rule.price = g["selling_price"]
                good_counter += 1
            stop.rules.append(rule)
        stops.append(stop)
    return stops


def seller(town: int, good_data: List[Dict]) -> List[TradeStop]:
    stops = [_skip_first_stop(town)]
    for i in range(MAX_STOPS - 1):
        good_counter = 0
        stop = TradeStop(town=town, mode=StopMode.DOCK, rules=[])
        for g in good_data:
            rule = Rule(g["good"], RuleMode.NONE, 0, 1)
            if g["enabled"]:
                if good_counter % 3 == i % 3:
                    rule.mode = RuleMode.WITHDRAW
                    rule.quantity = -1
                    rule.price = 1
                elif (good_counter + 1) % 3 == i % 3:
                    rule.mode = RuleMode.SELL
                    rule.quantity = -1
                    rule.price = g["selling_price"]
                else:
                    rule.mode = RuleMode.DEPOSIT
                    rule.quantity = -1
                    rule.price = 1
                good_counter += 1
            stop.rules.append(rule)
        stops.append(stop)
    return stops


def supplier(town: int, good_data: List[Dict]) -> List[TradeStop]:
    stops = [_skip_first_stop(town)]
    for _ in range(MAX_STOPS - 1):
        stop = TradeStop(town=town, mode=StopMode.DOCK, rules=[])
        for g in good_data:
            rule = Rule(g["good"], RuleMode.NONE, 0, 1)
            if g["enabled"]:
                rule.mode = RuleMode.BUY
                rule.quantity = -1
                rule.price = g["buying_price"]
            stop.rules.append(rule)
        stops.append(stop)
    return stops


def sucker(town: int, maximum_goods: int, good_data: List[Dict]) -> List[TradeStop]:
    stops = [_skip_first_stop(town)]
    last_bought_good = -1
    last_enabled_good = -1
    was_bought = [False] * goods.COUNT
    for _ in range(MAX_STOPS - 1):
        buying_goods = 0
        stop = TradeStop(town=town, mode=StopMode.DOCK, rules=[])
        for g in good_data:
            gid = g["good"]
            rule = Rule(gid, RuleMode.NONE, 0, 1)
            if g["enabled"]:
                if (buying_goods < maximum_goods and gid > last_bought_good
                        and not was_bought[gid]):
                    rule.mode = RuleMode.BUY
                    rule.quantity = -1
                    rule.price = g["buying_price"]
                    buying_goods += 1
                    last_bought_good = gid
                    was_bought[gid] = True
                else:
                    rule.mode = RuleMode.DEPOSIT
                    rule.quantity = -1
                    rule.price = 1
                    was_bought[gid] = False
                last_enabled_good = gid
            stop.rules.append(rule)
        if last_bought_good == last_enabled_good:
            last_bought_good = -1
        stops.append(stop)
    return stops


def sucker_to_warehouse(first_town: int, second_town: int,
                        first_data: List[Dict], second_data: List[Dict]) -> List[TradeStop]:
    stops: List[TradeStop] = []

    # 1) SKIP to avoid notifications.
    stops.append(TradeStop((first_town + 1) % towns.COUNT, StopMode.SKIP, _empty_rules()))

    # 2) Repairs in the first town.
    stops.append(TradeStop(first_town, StopMode.REPAIR, _empty_rules()))

    # 3) Deposit goods from both lists in the first town.
    stop = TradeStop(first_town, StopMode.DOCK, _empty_rules())
    for g in first_data + second_data:
        if g["enabled"]:
            stop.rules[g["good"]].mode = RuleMode.DEPOSIT
            stop.rules[g["good"]].quantity = -1
    stops.append(stop)

    # 4) Withdraw from the first town (specified quantity).
    stop = TradeStop(first_town, StopMode.DOCK, _empty_rules())
    for g in first_data:
        if g["enabled"]:
            stop.rules[g["good"]].mode = RuleMode.WITHDRAW
            stop.rules[g["good"]].quantity = g["quantity"]
    stops.append(stop)

    # 5) Withdraw surplus from the second town (maximum).
    stop = TradeStop(second_town, StopMode.DOCK, _empty_rules())
    for g in first_data:
        if g["enabled"]:
            stop.rules[g["good"]].mode = RuleMode.WITHDRAW
            stop.rules[g["good"]].quantity = -1
    stops.append(stop)

    # 6) Deposit in the second town (specified quantity).
    stop = TradeStop(second_town, StopMode.DOCK, _empty_rules())
    for g in first_data:
        if g["enabled"]:
            stop.rules[g["good"]].mode = RuleMode.DEPOSIT
            stop.rules[g["good"]].quantity = g["quantity"]
    stops.append(stop)

    # 7) Withdraw the second list from the second town.
    stop = TradeStop(second_town, StopMode.DOCK, _empty_rules())
    for g in second_data:
        if g["enabled"]:
            stop.rules[g["good"]].mode = RuleMode.WITHDRAW
            stop.rules[g["good"]].quantity = g["quantity"]
    stops.append(stop)

    return stops


GENERATORS = {
    "day_trader": day_trader,
    "seller": seller,
    "supplier": supplier,
    "sucker": sucker,
    "sucker_to_warehouse": sucker_to_warehouse,
}
