"""Core tests: compressor and .rou serialization (round-trip).

Run directly:  python tests/test_roundtrip.py
Or with pytest: pytest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from p3autoroute import compressor, goods, rou  # noqa: E402
from p3autoroute.models import (  # noqa: E402
    Route, Rule, RuleMode, StopMode, TradeStop, default_rules,
)


def test_compressor_literal_roundtrip():
    for sample in (b"", b"\x00", b"hello world", bytes(range(256)),
                   b"\xff" * 500, os.urandom(1000)):
        assert compressor.decode(compressor.encode(sample)) == sample


def _sample_stop() -> TradeStop:
    rules = default_rules()  # 24 rules in order 0..23
    rules[goods.Good.GRAIN] = Rule(goods.Good.GRAIN, RuleMode.BUY, 5, 130)
    rules[goods.Good.BEER] = Rule(goods.Good.BEER, RuleMode.SELL, -1, 55)
    rules[goods.Good.SALT] = Rule(goods.Good.SALT, RuleMode.WITHDRAW, 3, 0)
    rules[goods.Good.WINE] = Rule(goods.Good.WINE, RuleMode.DEPOSIT, 2, 0)
    rules[goods.Good.TIMBER] = Rule(goods.Good.TIMBER, RuleMode.WITHDRAW, -1, 0)
    # Reorder to check that the goods order is preserved.
    beer = rules.pop(goods.Good.BEER)
    rules.insert(0, beer)
    return TradeStop(town=2, mode=StopMode.DOCK, rules=rules)


def test_route_roundtrip_preserves_everything():
    route = Route(name="Test", trade_stops=[
        _sample_stop(),
        TradeStop(town=9, mode=StopMode.REPAIR, rules=default_rules()),
        TradeStop(town=10, mode=StopMode.SKIP, rules=default_rules()),
    ])
    parsed = rou.parse_route(rou.serialize_route(route), "Test")

    assert len(parsed.trade_stops) == 3
    for original, got in zip(route.trade_stops, parsed.trade_stops):
        assert got.town == original.town
        assert int(got.mode) == int(original.mode)
        assert len(got.rules) == 24
        for r_orig, r_got in zip(original.rules, got.rules):
            assert r_got.good == r_orig.good, "goods order changed"
            assert int(r_got.mode) == int(r_orig.mode)
            assert r_got.quantity == r_orig.quantity
            assert r_got.price == r_orig.price


def test_empty_route():
    parsed = rou.parse_route(rou.serialize_route(Route("Empty", [])), "Empty")
    assert parsed.trade_stops == []


def test_max_quantity_sentinel():
    rules = default_rules()
    rules[0] = Rule(0, RuleMode.BUY, -1, 100)  # -1 => maximum
    route = Route("Max", [TradeStop(0, StopMode.DOCK, rules)])
    parsed = rou.parse_route(rou.serialize_route(route), "Max")
    assert parsed.trade_stops[0].rules[0].quantity == -1


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests OK")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
