"""Live town buy/sell prices, read from the running game.

Combines the read-only memory layer from :mod:`captains` (find the process,
walk the town array, decode town names) with the pure price engine in
:mod:`pricing`. For every town it reads the live ware **stock** (``town+0x04``)
and the per-ware **price thresholds** (``town+0x4F0`` — read straight from the
game, so there is no need to reproduce the threshold formula) and prices one
load (barrel/bundle) for both buying and selling.

The result is grouped per good with one quote per town, so the frontend can show,
for a chosen good, the buy and sell price *in each town* — the live answer to
"at what price should I buy/sell this good here?". Each quote also carries the
town's weeks of supply and whether it produces the good, which is what explains
the price (a producer/oversupplied town is cheap to buy from; a starved consumer
town pays a lot when you sell to it).

Read-only and Windows-only, exactly like :mod:`captains`; all the Windows API
plumbing is reused from there so this module adds no new platform code.
"""
from __future__ import annotations

import struct
import sys

from . import captains, goods, pricing, towns

# GameWorld / town-struct offsets (the struct base, stride and index live in `captains`).
GW_TOWNS_COUNT = 0x10      # u16, number of active towns in the array
TOWN_STOCK = 0x04          # [i32; 24] current ware stock (storage overlaps the town base)
TOWN_PRODUCTION = 0xC4     # [i32; 24] daily production
TOWN_THRESHOLDS = 0x4F0    # [[i32; 4]; 24] live price thresholds t0..t3

# Only the 20 real trade goods have a base price; weapons (20..23) are skipped.
TRADE_GOODS = [g for g in range(goods.COUNT) if pricing.BASE_PRICES[g] is not None]


def read(params=None) -> dict:
    """Live buy/sell prices per good across all towns.

    ``params`` may carry ``{"difficulty": 0|1|2}`` (low/normal/high); it only
    affects sell prices in the starved regime. On success::

        {"ok": True, "date": {...}, "difficulty": int,
         "goods": [{"good": int, "name": str, "size": int, "basePerBarrel": float,
                    "towns": [{"townIndex", "town", "stock", "buy", "sell"}]}]}

    ``buy`` is ``None`` when the town has less than one load in stock. On failure
    it returns the same ``{"ok": False, "code", "error"}`` shape as
    :func:`captains.locate` (codes ``unsupported_os``/``not_running``/
    ``no_access``/``unknown_version``).
    """
    params = params or {}
    difficulty = int(params.get("difficulty", pricing.DIFFICULTY_NORMAL))
    if difficulty not in (0, 1, 2):
        difficulty = pricing.DIFFICULTY_NORMAL

    if sys.platform != "win32":
        return captains._err("unsupported_os",
                             "Reading the game's memory is only supported on Windows.")
    try:
        pid = captains._find_pid(captains.PROCESS_NAMES)
    except OSError:
        pid = None
    if not pid:
        return captains._err("not_running",
                             "Patrician III isn't running. Start the game and load a "
                             "savegame, then press the button again.")
    try:
        mem = captains._Mem(pid)
    except PermissionError:
        return captains._err("no_access",
                             "Couldn't access the game's memory. Try running this app "
                             "as administrator.")

    try:
        day = mem.u8(captains.GAME_WORLD_PTR + captains.GW_DAY)
        month = mem.u8(captains.GAME_WORLD_PTR + captains.GW_MONTH)
        year = mem.u16(captains.GAME_WORLD_PTR + captains.GW_YEAR)
        if not (1 <= day <= 31 and 1 <= month <= 12 and 1000 <= year <= 2000):
            return captains._err("unknown_version",
                                 "This game build isn't recognised (its internal "
                                 "addresses don't match). Tested with the 1.x "
                                 "GOG/retail edition.")

        towns_ptr = mem.u32(captains.GAME_WORLD_PTR + captains.GW_TOWNS_ARRAY)
        town_count = min(mem.u16(captains.GAME_WORLD_PTR + GW_TOWNS_COUNT), 40)

        # good id -> list of per-town quotes
        quotes: dict[int, list] = {g: [] for g in TRADE_GOODS}
        for t in range(town_count):
            base = towns_ptr + captains.TOWN_STRIDE * t
            try:
                town_index = mem.u8(base + captains.TOWN_INDEX)
                citizens = mem.u32(base + captains.TOWN_CITIZENS)
            except OSError:
                break
            if not (town_index < towns.COUNT and citizens < 1_000_000):
                continue
            name = captains._town_name(mem, town_index)
            stock = struct.unpack("<24i", mem.read(base + TOWN_STOCK, 96))
            thr = struct.unpack("<96i", mem.read(base + TOWN_THRESHOLDS, 384))
            prod = struct.unpack("<24i", mem.read(base + TOWN_PRODUCTION, 96))
            for g in TRADE_GOODS:
                size = goods.SIZES[g]
                base_price = pricing.BASE_PRICES[g]
                t4 = list(thr[g * 4:g * 4 + 4])
                # Real towns always have strictly-increasing positive thresholds;
                # anything else is uninitialised/garbage, so skip that quote.
                if not (0 < t4[0] < t4[1] < t4[2] < t4[3]):
                    continue
                s = stock[g]
                sell = pricing.unit_sell_price(s, t4, base_price, size, difficulty)
                buy = pricing.unit_buy_price(s, t4, base_price, size) if s >= size else None
                # "Weeks of supply" measured against the price thresholds so it
                # tracks the price exactly (no cross-town inversions): t1 is the
                # ~3-week level where the price equals base, so 3*stock/t1 is the
                # weeks-equivalent — literal weeks for staples, and "3 weeks"
                # always means the base price.
                weeks = round(3 * s / t4[1], 1)
                quotes[g].append({
                    "townIndex": town_index,
                    "town": name,
                    "stock": round(s / size),
                    "weeks": weeks,
                    "produces": prod[g] > 0,
                    "buy": None if buy is None else round(buy),
                    "sell": round(sell),
                })

        out = []
        for g in TRADE_GOODS:
            per = pricing.BASE_PRICES[g] * goods.SIZES[g]
            out.append({
                "good": g,
                "name": goods.NAMES[g],
                "size": goods.SIZES[g],
                "base": round(per),
                "floor": round(per * pricing.BUY_FLOOR),
                "ceiling": round(per * pricing.SELL_DIFFICULTY[difficulty]),
                "basePerBarrel": round(per, 1),
                "towns": sorted(quotes[g], key=lambda q: q["townIndex"]),
            })

        return {
            "ok": True,
            "date": {"day": day, "month": month, "year": year},
            "difficulty": difficulty,
            "goods": out,
        }
    finally:
        mem.close()
