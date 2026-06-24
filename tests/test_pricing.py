"""Price engine tests — validated against P3Modding's reference vectors.

The expected numbers are copied verbatim from the assertions in
``p3modding.github.io/src/towns/ware-prices/{buying,selling}-price.py`` (pig iron,
base price 0.44000003, thresholds [20000, 60000, 70000, 80000]).

Run directly:  python tests/test_pricing.py
Or with pytest: pytest
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from p3autoroute import goods, pricing  # noqa: E402

T = [20_000, 60_000, 70_000, 80_000]
PIG_IRON = 0.44000003


def _close(a, b):
    assert math.isclose(a, b, rel_tol=1e-6), f"{a} != {b}"


def test_buy_price_vectors():
    cases = [
        (2_000, 2_000, 3410.000212490559),
        (4_000, 2_000, 3190.00019878149),
        (18_000, 2_000, 1649.999995396131),
        (23_000, 2_000, 1298.000080883503),
        (23_000, 10_000, 7922.750493697822),
        (55_000, 2_000, 946.0000589489937),
        (65_000, 2_000, 809.6001041603122),
        (75_000, 2_000, 633.6000931930575),
        (110_000, 100_000, 46310.00288575888),
    ]
    for stock, amount, expected in cases:
        _close(pricing.buy_price(stock, amount, T, PIG_IRON), expected)


def test_sell_price_vectors():
    cases = [
        (0, 2_000, 0, 1900.80011844635),
        (0, 2_000, 1, 1733.600108027458),
        (0, 2_000, 2, 1566.400097608566),
        (0, 100_000, 0, 47740.00297486782),
        (0, 100_000, 1, 46860.00292003155),
        (0, 100_000, 2, 45980.00286519527),
        (17_000, 2_000, 1, 1284.800080060959),
        (19_000, 2_000, 1, 1236.400077044964),
        (21_000, 2_000, 1, 1214.400075674057),
        (55_000, 100_000, 2, 25135.00156626105),
        (57_000, 2_000, 1, 897.6000559329987),
        (77_000, 2_000, 1, 475.19997590064672),
        (85_000, 2_000, 1, 440.0),
    ]
    for stock, amount, diff, expected in cases:
        _close(pricing.sell_price(stock, amount, T, PIG_IRON, diff), expected)


def test_buy_amount_exceeding_stock_raises():
    try:
        pricing.buy_price(1_000, 2_000, T, PIG_IRON)
    except ValueError:
        return
    raise AssertionError("expected ValueError when buying more than stock")


def test_overstock_hits_floor():
    # Far above t3, the per-unit price collapses to the flat floors.
    _close(pricing.sell_price(85_000, 2_000, T, PIG_IRON, 1), PIG_IRON * 2_000 * 0.5)
    _close(pricing.buy_price(120_000, 2_000, T, PIG_IRON), PIG_IRON * 2_000 * 0.6)


def test_buy_unit_price_decreases_with_stock():
    # The marginal price you pay falls monotonically as the town's stock grows.
    prev = None
    for stock in range(4_000, 120_000, 4_000):
        p = pricing.unit_buy_price(stock, T, PIG_IRON, size=2_000)
        if prev is not None:
            assert p <= prev + 1e-6, f"price rose at stock={stock}"
        prev = p


def test_base_prices_table():
    assert len(pricing.BASE_PRICES) == goods.COUNT
    assert pricing.BASE_PRICES[goods.Good.GRAIN] == 0.055000003
    assert pricing.BASE_PRICES[goods.Good.SKINS] == 3.3824999
    # weapons have no trade base price
    for w in (goods.Good.SWORD, goods.Good.BOW, goods.Good.CROSSBOW, goods.Good.CARBINE):
        assert pricing.BASE_PRICES[w] is None


def test_universal_table():
    t = pricing.universal_table()
    assert t["ok"] and len(t["goods"]) == 20
    beer = next(x for x in t["goods"] if x["name"] == "Beer")
    per = 0.17399999 * goods.SIZES[goods.Good.BEER]
    assert beer["floor"] == round(per * 0.6)      # deep-glut floor (cheapest)
    assert beer["base"] == round(per)             # 3-week pivot: buy = sell = base
    assert beer["sell2wk"] == round(per * 1.2)    # 2-week satisfaction sell
    assert beer["buy2wk"] == round(per * 1.25)    # aggressive buy cap (2-week drain)
    assert beer["sell1wk"] == round(per * 1.4)    # 1-week premium sell
    assert beer["ceiling"] == round(per * 2.0)    # empty-town ceiling (dearest, normal)
    # the columns are ordered cheapest -> dearest
    assert beer["floor"] < beer["base"] < beer["sell2wk"] < beer["buy2wk"] < beer["sell1wk"] < beer["ceiling"]


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
