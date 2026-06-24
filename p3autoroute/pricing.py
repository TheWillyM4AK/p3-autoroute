"""Patrician III town price model — pure, stdlib-only engine.

This is a faithful port of the P3Modding reverse-engineering project's reference
implementations (`p3modding.github.io/src/towns/ware-prices/{buying,selling}-price.py`,
game functions `get_buy_price` @ ``0x0052E430`` and `get_sell_price` @ ``0x0052E1D0``).

A town's price for a ware is **piecewise-linear in the warehouse stock**, split
into 5 intervals by 4 thresholds ``t0<t1<t2<t3`` (read live from the town struct,
see :mod:`p3autoroute.live`). For a transaction of ``amount`` units the engine
integrates the per-unit *factor* over the stock range the transaction sweeps
(buying lowers the stock, selling raises it), so the marginal price moves along
the curve as you trade:

    price = sum over intervals of  base_price * units_in_interval * factor

where ``factor`` is evaluated at the midpoint of the swept range within each
interval. ``base_price`` is the global per-unit price from ``ware_base_prices``
(@ ``0x00673A18``); multiply by the good's load size (:data:`goods.SIZES`) for a
per-barrel/bundle price.

The module is dependency-free and is validated against P3Modding's own numeric
test vectors in ``tests/test_pricing.py``.
"""
from __future__ import annotations

# --- per-unit base prices, indexed by goods.Good (0..23) ---------------------
# Verbatim from p3modding.github.io ware_base_prices @ 0x00673A18 (20 wares; the
# 4 militia weapons are not normal trade goods and have no base price).
BASE_PRICES = [
    0.055000003,  # Grain
    0.47855002,   # Meat
    0.22005001,   # Fish
    0.17399999,   # Beer
    0.1425,       # Salt
    0.55000001,   # Honey
    1.4,          # Spices
    1.1,          # Wine
    1.034,        # Cloth
    3.3824999,    # Skins
    0.41249999,   # Oil (WhaleOil)
    0.027500002,  # Timber
    1.278,        # Iron Goods
    1.12,         # Leather
    0.44000003,   # Wool
    0.278,        # Pitch
    0.44000003,   # Pig Iron
    0.22000001,   # Hemp
    0.85499996,   # Pottery
    0.039900005,  # Bricks
    None, None, None, None,  # Sword, Bow, Crossbow, Carbine
]

# --- factor tables (P3Modding) ----------------------------------------------
# Buying: f_i = BUY_M[i] - BUY_V[i] * midpoint/width ; interval 4 is a flat 0.6.
BUY_M = (4.0, 1.5, 1.0, 0.8)
BUY_V = (2.5, 0.5, 0.2, 0.2)
BUY_FLOOR = 0.6

# Selling: like buying, but interval 0 swaps m_0 for a difficulty constant and
# interval 4 is a flat 0.5.
SELL_M = (None, 1.4, 1.0, 0.7)        # m_0 is unused (difficulty is used instead)
SELL_V = (1.4, 0.4, 0.3, 0.2)
SELL_FLOOR = 0.5
SELL_DIFFICULTY = (2.2, 2.0, 1.8)     # low / normal / high
DIFFICULTY_NORMAL = 1


def _buy_factor(interval, w_relative_stock, w_relative_remain, width):
    if interval == 4:
        return BUY_FLOOR
    if width <= 0:  # degenerate (empty) interval — it contributes zero units anyway
        return 0.0
    midpoint = (w_relative_stock + w_relative_remain) / 2
    return BUY_M[interval] - BUY_V[interval] * midpoint / width


def _sell_factor(interval, w_relative_stock, w_relative_new_stock, width, difficulty):
    if interval == 4:
        return SELL_FLOOR
    if width <= 0:  # degenerate (empty) interval — it contributes zero units anyway
        return 0.0
    midpoint = (w_relative_stock + w_relative_new_stock) / 2
    if interval == 0:
        d = SELL_DIFFICULTY[difficulty]
        f_max, f_var = d, d - SELL_V[0]
    else:
        f_max, f_var = SELL_M[interval], SELL_V[interval]
    return f_max - f_var * midpoint / width


def buy_price(stock, amount, thresholds, base_price):
    """Gold paid to buy ``amount`` units out of a town holding ``stock``.

    Buying lowers the stock from ``stock`` to ``stock - amount``; the per-unit
    price rises as the town empties. ``thresholds`` is ``[t0, t1, t2, t3]`` in
    raw (unscaled) units. Raises ``ValueError`` if ``amount > stock``.
    """
    if amount > stock:
        raise ValueError(f"buy amount {amount} exceeds stock {stock}")
    price = 0.0
    remaining = stock - amount
    for interval in range(4):
        if remaining < thresholds[interval]:
            start = 0 if interval == 0 else thresholds[interval - 1]
            end = thresholds[interval]
            width = end - start
            w_interval_stock = min(stock, end)
            w_relative_stock = w_interval_stock - start
            w_b = w_interval_stock - max(remaining, start)
            w_relative_remain = w_relative_stock - w_b
            f = _buy_factor(interval, w_relative_stock, w_relative_remain, width)
            price += base_price * w_b * f
            if stock <= end:
                break
    if remaining + amount > thresholds[3]:
        w_b = stock - max(remaining, thresholds[3])
        price += base_price * w_b * BUY_FLOOR
    return price


def sell_price(stock, amount, thresholds, base_price, difficulty=DIFFICULTY_NORMAL):
    """Gold received for selling ``amount`` units into a town holding ``stock``.

    Selling raises the stock from ``stock`` to ``stock + amount``; the per-unit
    price falls as the town fills. ``difficulty`` is 0/1/2 (low/normal/high) and
    only affects interval 0 (the starved, high-price regime).
    """
    price = 0.0
    new_stock = stock + amount
    pending = amount
    for interval in range(4):
        if stock < thresholds[interval]:
            start = 0 if interval == 0 else thresholds[interval - 1]
            end = thresholds[interval]
            width = end - start
            w_interval_stock = max(stock, start)
            w_relative_stock = w_interval_stock - start
            w_s = min(pending, width - w_relative_stock)
            w_relative_new_stock = w_relative_stock + w_s
            f = _sell_factor(interval, w_relative_stock, w_relative_new_stock, width, difficulty)
            price += base_price * w_s * f
            pending -= w_s
            if new_stock <= end:
                break
    if new_stock > thresholds[3]:
        w_s = new_stock - max(stock, thresholds[3])
        price += base_price * w_s * SELL_FLOOR
    return price


# Constant reference price points as multiples of the base price. Because the
# price at a given weeks-of-supply is universal, these are fixed per good and
# never change with the game state. They all sit in difficulty-independent parts
# of the curve (intervals 1–2, not the empty-town interval 0).
BASE_FACTOR = 1.0       # 3 weeks of supply — buy & sell meet here (the neutral price)
BUY_2WK_FACTOR = 1.25   # buy down to 2 weeks (the source's satisfaction floor; aggressive)
SELL_2WK_FACTOR = 1.2   # sell up to the 2-week satisfaction cap (the default)
SELL_1WK_FACTOR = 1.4   # sell only up to 1 week (premium / cream-skim)


def universal_table():
    """Constant per-good reference prices for setting route rules.

    Returns ``{"ok": True, "goods": [{"good", "name", "floor", "base", "sell2wk",
    "buy2wk", "sell1wk", "ceiling"}]}`` in gold per barrel/bundle — fixed
    multiples of each good's base price, so they never change with the game.
    Ordered cheapest → dearest, they trace the good's whole price range:

    - ``floor`` (0.6×): the cheapest you'll ever pay — a deep-glut town.
    - ``base`` (1.0×): the 3-week pivot where buy = sell = base.
    - ``sell2wk`` (1.2×): sell down to the 2-week satisfaction cap (the default).
    - ``buy2wk`` (1.25×): aggressive buy cap — drains a town to 2 weeks (below
      that you penalise its satisfaction).
    - ``sell1wk`` (1.4×): premium sell — only down to 1 week.
    - ``ceiling`` (2.0×, normal difficulty): the dearest you'll get — an empty town.
    """
    from . import goods
    out = []
    for g, base in enumerate(BASE_PRICES):
        if base is None:
            continue
        per = base * goods.SIZES[g]
        out.append({
            "good": g,
            "name": goods.NAMES[g],
            "floor": round(per * BUY_FLOOR),
            "base": round(per * BASE_FACTOR),
            "sell2wk": round(per * SELL_2WK_FACTOR),
            "buy2wk": round(per * BUY_2WK_FACTOR),
            "sell1wk": round(per * SELL_1WK_FACTOR),
            "ceiling": round(per * SELL_DIFFICULTY[DIFFICULTY_NORMAL]),
        })
    return {"ok": True, "goods": out}


def unit_buy_price(stock, thresholds, base_price, size=1):
    """Per-barrel/bundle price to buy one load (``size`` units) right now."""
    return buy_price(stock, size, thresholds, base_price)


def unit_sell_price(stock, thresholds, base_price, size=1, difficulty=DIFFICULTY_NORMAL):
    """Per-barrel/bundle price to sell one load (``size`` units) right now."""
    return sell_price(stock, size, thresholds, base_price, difficulty)
