"""Live view of the player's ships and convoys, read from the running game.

Reads the running ``Patrician3`` process **read-only** (Windows-only, via
``kernel32`` through ``ctypes`` — the same plumbing as :mod:`prices`) and reports,
for every ship the player owns: its hold (capacity / used / free), the goods it
is carrying (loads + the average price they were bought at), and where it is
heading. Polling this repeatedly is how the frontend animates a ship filling and
emptying as the game runs.

The fixed absolute addresses are virtual addresses of the 1.x GOG/retail build
(image base ``0x400000``, no ASLR); a date sanity check guards against reading
garbage from an unexpected build. The struct offsets are the ones documented by
the P3Modding ``p3-api`` project and verified live against this build. Every
Windows API touch is done lazily inside :func:`read` so the module imports
cleanly on any platform (the test suite never calls it).
"""
from __future__ import annotations

import struct
import sys

from . import goods, towns
# Reuse the exact process-finding and read-only memory window from prices.py so
# there is a single implementation of the ctypes plumbing.
from .prices import _Mem, _find_pid, GAME_WORLD_PTR, PROCESS_NAMES

# --- static addresses (P3Modding p3-api, verified live) -------------------
SHIPS_PTR = 0x006DD7A0          # ShipsPtr root (a.k.a. CLASS6_PTR)
OPERATIONS_PTR = 0x006DF2F0     # OperationsPtr; holds the local player's id

# GameWorld layout (only the bits this module needs)
GW_DAY = 0x00                   # u8
GW_MONTH = 0x01                 # u8
GW_YEAR = 0x02                  # u16
GW_GAME_TIME = 0x14             # u32, game clock in ticks (TICKS_PER_DAY = 256)
GW_MERCHANTS_ARRAY = 0x78       # ptr -> merchants array

# The game clock advances 256 ticks per in-game day (P3Modding game_world.rs:
# TICKS_PER_YEAR 93440 == 365*256). Used to turn a ship's arrival timestamp into
# days remaining.
TICKS_PER_DAY = 256

# ShipsPtr root layout
SHIPS_ARRAY = 0x04              # ptr -> ships array
SHIPS_COUNT = 0xF4             # u16
CONVOYS_ARRAY = 0x08           # ptr -> convoys array
CONVOYS_COUNT = 0xF6           # u16

# Operations layout
OPS_PLAYER_MERCHANT = 0x0924    # i32, index of the local player's merchant

# Merchant struct (stride 0x650)
MERCHANT_STRIDE = 0x650
MERCH_FIRST_SHIP = 0x0E         # u16, head of this merchant's ship linked list

# Ship struct (stride 0x180)
SHIP_STRIDE = 0x180
SHIP_NEXT_OF_MERCHANT = 0x04    # u16, next ship of the same merchant (0xFFFF=end)
SHIP_CONVOY_ID = 0x08           # u16, 0xFFFF when the ship is not in a convoy
SHIP_TYPE = 0x0E                # u16, ShipType
SHIP_CAPACITY = 0x10            # u32, total hold in internal units
SHIP_MAX_HEALTH = 0x14          # u32
SHIP_CUR_HEALTH = 0x18          # u32
SHIP_DEST_TOWN = 0x38           # u8, town index it is sailing to
SHIP_LAST_TOWN = 0x39           # u8, current town when docked, 0xFF at sea
SHIP_ARRIVAL_TS = 0x48          # i32, game-tick the ship reaches its destination
SHIP_WARES = 0x54               # [i32; 24] cargo, internal units (loads*size)
SHIP_AVG_PRICE = 0xB4           # [f32; 24] average purchase price, per unit
SHIP_PAYLOAD_COST = 0x114       # i32, total gold paid for the cargo (game-computed)
SHIP_STATUS = 0x134             # u16
SHIP_NAME = 0x160               # char[32], latin1, NUL-terminated (per P3Modding book)

# Convoy struct (stride 0x3C)
CONVOY_STRIDE = 0x3C
CONVOY_STATUS = 0x12            # u16
CONVOY_TOWN = 0x39              # u16, current town index

# capacity@0x10 is the hold figure the game itself shows (verified live on an
# unarmed Snaikka: 30000/200 == the 150 the in-game ship sheet reports), so we
# convert it straight to the game's uniform hold unit (a barrel = 1, a bundle =
# 10) without subtracting anything. The in-game hold figure shrinks as you mount
# weapons / take shipyard extensions (per the P3Modding/wiki notes), and this
# field IS that figure, so it already reflects armament — no separate weapon term
# is needed. The old fixed -10000 "reserve" was the placeholder p3-lib's
# calc_free_capacity carries behind a `TODO weapons, sailors`; it simply shaved
# 50 barrels off every ship (showing 100 for a 150-hold ship).
HOLD_UNIT = goods.BARREL        # 200

SHIP_TYPE_NAMES = ["Snaikka", "Craier", "Cog", "Hulk"]
NONE_TOWN = 0xFF
NONE_ID = 0xFFFF


def _err(code: str, error: str) -> dict:
    return {"ok": False, "code": code, "error": error}


def _town_name(idx: int):
    return towns.NAMES[idx] if 0 <= idx < towns.COUNT else None


def _read_ship(mem, addr: int, game_time: int) -> dict:
    """Decode one ship struct at absolute address ``addr``.

    ``game_time`` is the current game clock (ticks) so a ship at sea can report
    how many days remain until it reaches its destination.
    """
    raw = mem.read(addr, SHIP_STRIDE)
    u8 = lambda o: raw[o]
    u16 = lambda o: struct.unpack_from("<H", raw, o)[0]
    u32 = lambda o: struct.unpack_from("<I", raw, o)[0]
    i32 = lambda o: struct.unpack_from("<i", raw, o)[0]
    name = raw[SHIP_NAME:SHIP_NAME + 32].split(b"\x00", 1)[0].decode("latin1", "ignore")

    wares = struct.unpack_from("<24i", raw, SHIP_WARES)
    prices = struct.unpack_from("<24f", raw, SHIP_AVG_PRICE)
    cargo = []
    for g in range(goods.COUNT):
        if wares[g] <= 0:
            continue
        size = goods.SIZES[g]
        unit_price = prices[g] if prices[g] > 0 else 0.0
        cargo.append({
            "good": g,
            "name": goods.NAMES[g],
            "loads": round(wares[g] / size, 1),
            # Average purchase price per load (per-unit price * load size); the
            # gold the player paid, which the in-game cargo window also shows.
            "avgPrice": round(unit_price * size) if unit_price else None,
            # Total gold tied up in this cargo line.
            "value": round(wares[g] * unit_price) if unit_price else None,
        })

    capacity = u32(SHIP_CAPACITY)
    used = sum(w for w in wares if w > 0)
    max_h = u32(SHIP_MAX_HEALTH)
    cur_h = u32(SHIP_CUR_HEALTH)

    last_town = u8(SHIP_LAST_TOWN)
    dest_town = u8(SHIP_DEST_TOWN)
    convoy_id = u16(SHIP_CONVOY_ID)
    ship_type = u16(SHIP_TYPE)

    # Days until arrival: the ship's arrival timestamp minus the game clock, in
    # days. The game sets it as soon as a trip is ordered (even while the ship is
    # still leaving its current port), so report it whenever it is in the future;
    # a ship parked with no pending trip has it in the past -> None.
    at_sea = last_town == NONE_TOWN
    arrival = i32(SHIP_ARRIVAL_TS)
    eta_ticks = arrival - game_time
    eta_days = round(eta_ticks / TICKS_PER_DAY, 1) if eta_ticks > 0 else None

    return {
        "name": name or "(unnamed)",
        "type": SHIP_TYPE_NAMES[ship_type] if ship_type < len(SHIP_TYPE_NAMES) else f"#{ship_type}",
        "convoyId": None if convoy_id == NONE_ID else convoy_id,
        # Hold figures in the game's uniform unit (barrel = 1, bundle = 10).
        "holdUsed": round(used / HOLD_UNIT),
        "holdTotal": round(capacity / HOLD_UNIT),
        "holdFree": round((capacity - used) / HOLD_UNIT),
        "holdPct": round(100 * used / capacity) if capacity > 0 else 0,
        "townIndex": None if last_town == NONE_TOWN else last_town,
        "town": _town_name(last_town),
        "destIndex": None if dest_town == NONE_TOWN else dest_town,
        "dest": _town_name(dest_town),
        "atSea": at_sea,
        "etaDays": eta_days,
        # Total gold paid for everything aboard, as the game itself tracks it
        # (the per-line "value" entries sum to ~this, give or take rounding).
        "cargoValue": i32(SHIP_PAYLOAD_COST) or None,
        "health": round(100 * cur_h / max_h) if max_h > 0 else None,
        "status": u16(SHIP_STATUS),
        "cargo": cargo,
    }


def read(params=None) -> dict:
    """Live snapshot of the player's ships, grouped data for the frontend.

    On success::

        {"ok": True, "date": {"day","month","year"},
         "ships": [{"name","type","convoyId","holdUsed","holdTotal","holdFree",
                    "holdPct","town","townIndex","dest","destIndex","atSea",
                    "etaDays","cargoValue","health","status",
                    "cargo":[{"good","name","loads","avgPrice","value"}]}]}

    ``etaDays`` is the days left until the ship reaches its destination (only
    while at sea; ``None`` when docked).

    On failure: ``{"ok": False, "code", "error"}`` with *code* one of
    ``unsupported_os``/``not_running``/``no_access``/``unknown_version``.
    """
    if sys.platform != "win32":
        return _err("unsupported_os",
                    "Reading the game's memory is only supported on Windows.")
    try:
        pid = _find_pid(PROCESS_NAMES)
    except OSError:
        pid = None
    if not pid:
        return _err("not_running",
                    "Patrician III isn't running. Start the game and load a "
                    "savegame, then press the button again.")
    try:
        mem = _Mem(pid)
    except PermissionError:
        return _err("no_access",
                    "Couldn't access the game's memory. Try running this app "
                    "as administrator.")

    try:
        day = mem.u8(GAME_WORLD_PTR + GW_DAY)
        month = mem.u8(GAME_WORLD_PTR + GW_MONTH)
        year = mem.u16(GAME_WORLD_PTR + GW_YEAR)
        # The game stores the month 0-indexed (January = 0), so a valid month is
        # 0..11 — the old `1 <= month` wrongly rejected January as "unknown build".
        if not (1 <= day <= 31 and 0 <= month <= 11 and 1000 <= year <= 2000):
            return _err("unknown_version",
                        "This game build isn't recognised (its internal "
                        "addresses don't match). Tested with the 1.x GOG/retail "
                        "edition.")

        player = struct.unpack("<i", mem.read(OPERATIONS_PTR + OPS_PLAYER_MERCHANT, 4))[0]
        if player < 0:
            return _err("not_running",
                        "No local player merchant — load a savegame first.")

        game_time = mem.u32(GAME_WORLD_PTR + GW_GAME_TIME)
        ships_base = mem.u32(SHIPS_PTR + SHIPS_ARRAY)
        ships_count = mem.u16(SHIPS_PTR + SHIPS_COUNT)
        merch_base = mem.u32(GAME_WORLD_PTR + GW_MERCHANTS_ARRAY)

        # Walk the player merchant's ship linked list (head at MERCH_FIRST_SHIP,
        # chained via SHIP_NEXT_OF_MERCHANT). Guard against cycles/garbage.
        first = mem.u16(merch_base + player * MERCHANT_STRIDE + MERCH_FIRST_SHIP)
        ships = []
        seen = set()
        idx = first
        while idx != NONE_ID and idx < ships_count and idx not in seen and len(ships) < 200:
            seen.add(idx)
            addr = ships_base + idx * SHIP_STRIDE
            try:
                ships.append(_read_ship(mem, addr, game_time))
            except OSError:
                break
            idx = mem.u16(addr + SHIP_NEXT_OF_MERCHANT)

        return {
            "ok": True,
            "date": {"day": day, "month": month, "year": year},
            "ships": ships,
        }
    finally:
        mem.close()
