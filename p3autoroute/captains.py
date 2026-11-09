"""Hireable tavern captains, read from the running game.

Reads the running ``Patrician3`` process **read-only** (the same ``ctypes``
plumbing as :mod:`prices`) and reports which towns' taverns currently hold a
captain the player can hire.

The model comes from P3Modding book PR #3 by stevenbg
(https://github.com/P3Modding/p3modding.github.io/pull/3). It was checked
against a live game of the 1.x GOG build before being wired into the app: a
predicted captain matched the tavern on all five figures shown (three skills,
age, wage), a town predicted empty was empty, and every record in the save was
either chained to a tavern or serving on a ship, never both. An earlier attempt
(shipped, then reverted) read ``town+0x82E`` as "the tavern's captain" and
produced false positives. That field is instead the **head of a linked list**:

- every town chains its *auto traders* through ``auto_trader+0x00`` (next index),
  starting at ``town+0x82E``; the chain ends at an out-of-range index
  (``0xFFFF`` = empty);
- the chain mixes two kinds of record, told apart by ``auto_trader+0x08``:
  ``<= 0x20`` is a captain, ``> 0x20`` is the tavern's *pirate* captain (the
  character you can hand a ship to);
- a tavern offers a captain for hire while its chain holds a captain record no
  merchant employs (``auto_trader+0x0F == 0xFF``), or one still tagged with the
  asking merchant's own index (a captain you just dismissed there).

Reading only the chain head therefore returns the pirate, or some other
captain, as often as the visible one — which is exactly what the old attempt
got wrong.

``python -m p3autoroute.captains`` prints every town's chain plus the model's
self-checks — the tool to reach for if the view ever disagrees with a tavern.
When re-verifying, check towns that should be **empty** as well as towns that
should have a captain; the reverted attempt passed the second kind only.

:func:`_collect` takes any object with ``read``/``u8``/``u16``/``u32``, which is
how the tests drive it from a fake memory image without the game.
"""
from __future__ import annotations

import struct
import sys

from .prices import (
    _Mem, _find_pid, _town_name, GAME_WORLD_PTR, PROCESS_NAMES,
    GW_DAY, GW_MONTH, GW_YEAR, GW_TOWNS_ARRAY, GW_TOWNS_COUNT,
    TOWN_STRIDE, TOWN_INDEX, TOWN_CITIZENS,
)
from .ships import (
    SHIPS_PTR, SHIPS_ARRAY, SHIPS_COUNT, SHIP_STRIDE, GW_GAME_TIME,
    OPERATIONS_PTR, OPS_PLAYER_MERCHANT,
)

# --- auto_trader array (captains, pirate captains and office administrators) --
# Lives on the same root as the ships array (SHIPS_PTR, a.k.a. CLASS6_PTR).
AUTO_TRADERS_ARRAY = 0x00       # ptr -> auto_trader array
AUTO_TRADERS_COUNT = 0xF2       # u16, number of records in the array

AT_STRIDE = 0x10
AT_NEXT = 0x00                  # u16, next record in the same town's chain
AT_BIRTH = 0x04                 # i32, birth stamp in game ticks
AT_KIND = 0x08                  # u8, <= 0x20 captain / > 0x20 pirate captain
AT_SAILING = 0x09               # u8, raw skill 0..255
AT_TRADE = 0x0A                 # u8
AT_FIGHTING = 0x0B              # u8
AT_WAGE = 0x0C                  # u16, daily wage as shown in the tavern
AT_RETIRING = 0x0E              # u8, set when the record is marked for retirement
AT_MERCHANT = 0x0F              # u8, employing merchant; 0xFF = nobody

PIRATE_KIND_ABOVE = 0x20        # AT_KIND above this marks a pirate captain
NO_MERCHANT = 0xFF

# --- other structs (only the fields this module needs) -----------------------
TOWN_CHAIN_HEAD = 0x82E         # u16, first auto_trader of the town's chain
SHIP_OWNER = 0x00               # u8, owning merchant; 0xFF = pirate / empty slot
SHIP_CAPTAIN = 0x42             # u16, auto_trader index of the ship's captain

TICKS_PER_YEAR = 93440          # 365 days * 256 ticks
MAX_TOWNS = 40                  # 24 Hanse towns + settlements founded in-game
MAX_RECORDS = 4096              # sanity bound; real saves hold a few hundred

# Raw skill -> displayed level 0..5. Confirmed in-game on the two readings that
# tell 50 apart from 51: raw 250 shows as 5 and raw 150 shows as 3.
SKILL_PER_LEVEL = 50


def _err(code: str, error: str) -> dict:
    return {"ok": False, "code": code, "error": error}


def _level(raw: int) -> int:
    return min(5, raw // SKILL_PER_LEVEL)


def walk_chain(records: bytes, count: int, head: int):
    """Follow a town's auto-trader chain through the raw ``records`` blob.

    Returns ``(indices, clean)``; ``clean`` is False when the walk had to stop
    because the chain looped back on itself instead of ending out of range.
    """
    out, seen = [], set()
    idx = head
    while idx < count:
        if idx in seen:
            return out, False
        seen.add(idx)
        out.append(idx)
        idx = struct.unpack_from("<H", records, idx * AT_STRIDE + AT_NEXT)[0]
    return out, True


def decode_record(records: bytes, index: int, game_time: int, player: int) -> dict:
    """Decode auto_trader ``index`` out of the raw ``records`` blob."""
    raw = records[index * AT_STRIDE:(index + 1) * AT_STRIDE]
    kind = raw[AT_KIND]
    merchant = raw[AT_MERCHANT]
    if kind > PIRATE_KIND_ABOVE:
        status = "pirate"
    elif merchant == NO_MERCHANT:
        status = "free"             # anyone can hire him
    elif merchant == player:
        status = "yours"            # dismissed here by the player, still hireable
    else:
        status = "taken"            # held by another merchant
    age_ticks = game_time - struct.unpack_from("<i", raw, AT_BIRTH)[0]
    trade, sailing, fighting = raw[AT_TRADE], raw[AT_SAILING], raw[AT_FIGHTING]
    return {
        "index": index,
        "status": status,
        "hireable": status in ("free", "yours"),
        # Skills in the order the game shows them: Trade, Sailing, Fighting.
        "trade": _level(trade), "sailing": _level(sailing), "fighting": _level(fighting),
        "raw": {"trade": trade, "sailing": sailing, "fighting": fighting},
        "wage": struct.unpack_from("<H", raw, AT_WAGE)[0],
        "age": age_ticks // TICKS_PER_YEAR if 0 < age_ticks < 120 * TICKS_PER_YEAR else None,
        "kind": kind,
        "merchant": None if merchant == NO_MERCHANT else merchant,
        "retiring": bool(raw[AT_RETIRING]),
    }


def _collect(mem) -> dict:
    """Build the report from an open memory window (any object with read/u8/u16/u32)."""
    day = mem.u8(GAME_WORLD_PTR + GW_DAY)
    month = mem.u8(GAME_WORLD_PTR + GW_MONTH)
    year = mem.u16(GAME_WORLD_PTR + GW_YEAR)
    # The month is 0-indexed in memory (January = 0).
    if not (1 <= day <= 31 and 0 <= month <= 11 and 1000 <= year <= 2000):
        return _err("unknown_version",
                    "This game build isn't recognised (its internal addresses "
                    "don't match). Tested with the 1.x GOG/retail edition.")

    player = struct.unpack("<i", mem.read(OPERATIONS_PTR + OPS_PLAYER_MERCHANT, 4))[0]
    if player < 0:
        return _err("not_running", "No local player merchant — load a savegame first.")
    game_time = mem.u32(GAME_WORLD_PTR + GW_GAME_TIME)

    count = mem.u16(SHIPS_PTR + AUTO_TRADERS_COUNT)
    if count > MAX_RECORDS:
        return _err("unknown_version",
                    f"Implausible auto-trader count ({count}); wrong game build?")
    records = mem.read(mem.u32(SHIPS_PTR + AUTO_TRADERS_ARRAY), count * AT_STRIDE) if count else b""

    # Which records are serving on a ship. Only used as a self-check: a record
    # sitting in a tavern chain should never also be a ship's captain.
    on_ship = {}
    ships_base = mem.u32(SHIPS_PTR + SHIPS_ARRAY)
    for s in range(min(mem.u16(SHIPS_PTR + SHIPS_COUNT), 2000)):
        try:
            head = mem.read(ships_base + s * SHIP_STRIDE, SHIP_CAPTAIN + 2)
        except OSError:
            break
        cap = struct.unpack_from("<H", head, SHIP_CAPTAIN)[0]
        if cap < count and head[SHIP_OWNER] != NO_MERCHANT:
            on_ship[cap] = s

    towns_ptr = mem.u32(GAME_WORLD_PTR + GW_TOWNS_ARRAY)
    town_count = min(mem.u16(GAME_WORLD_PTR + GW_TOWNS_COUNT), MAX_TOWNS)
    town_rows, hireable = [], []
    chained_in = {}                 # record index -> first town that chained it
    conflicts, duplicates, loops = [], [], []
    for t in range(town_count):
        base = towns_ptr + TOWN_STRIDE * t
        try:
            town_index = mem.u8(base + TOWN_INDEX)
            citizens = mem.u32(base + TOWN_CITIZENS)
            head = mem.u16(base + TOWN_CHAIN_HEAD)
        except OSError:
            break
        if not (town_index < MAX_TOWNS and citizens < 1_000_000):
            continue
        name = _town_name(mem, town_index)
        indices, clean = walk_chain(records, count, head)
        if not clean:
            loops.append(name)
        captains, pirates = [], []
        for idx in indices:
            if idx in chained_in:
                duplicates.append({"index": idx, "towns": [chained_in[idx], name]})
            else:
                chained_in[idx] = name
            if idx in on_ship:
                conflicts.append({"index": idx, "town": name, "ship": on_ship[idx]})
            rec = decode_record(records, idx, game_time, player)
            (pirates if rec["status"] == "pirate" else captains).append(rec)
        for rec in captains:
            if rec["hireable"]:
                hireable.append({"townIndex": town_index, "town": name, **rec})
        town_rows.append({"townIndex": town_index, "town": name, "head": head,
                          "captains": captains, "pirates": pirates})

    town_rows.sort(key=lambda r: r["townIndex"])
    hireable.sort(key=lambda r: -(r["raw"]["trade"] + r["raw"]["sailing"] + r["raw"]["fighting"]))
    return {
        "ok": True,
        "date": {"day": day, "month": month, "year": year},
        "player": player,
        "records": count,
        "hireable": hireable,
        "towns": town_rows,
        # All three lists are expected to be empty if the chain model is right.
        "checks": {"chainedOnShip": conflicts, "chainedTwice": duplicates,
                   "loopingChains": loops},
    }


def read(params=None) -> dict:
    """Live snapshot of the tavern captains in every town.

    On success::

        {"ok": True, "date": {"day","month","year"}, "player": int, "records": int,
         "hireable": [{"townIndex","town", <record>}],
         "towns": [{"townIndex","town","head","captains":[<record>],"pirates":[<record>]}],
         "checks": {"chainedOnShip","chainedTwice","loopingChains"}}

    where ``<record>`` is ``{"index","status","hireable","trade","sailing",
    "fighting","raw":{...},"wage","age","kind","merchant","retiring"}`` and
    ``status`` is one of ``free``/``yours``/``taken``/``pirate``.

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
                    "savegame, then try again.")
    try:
        mem = _Mem(pid)
    except PermissionError:
        return _err("no_access",
                    "Couldn't access the game's memory. Try running this as "
                    "administrator.")
    try:
        return _collect(mem)
    except OSError as exc:
        return _err("unknown_version", f"Couldn't read the game's memory: {exc}")
    finally:
        mem.close()


def _skills(rec: dict) -> str:
    raw = rec["raw"]
    return (f"Trade {rec['trade']} ({raw['trade']:>3})  "
            f"Sailing {rec['sailing']} ({raw['sailing']:>3})  "
            f"Fighting {rec['fighting']} ({raw['fighting']:>3})")


def format_report(data: dict) -> str:
    """Plain-ASCII report of :func:`read`'s result, for checking against the game."""
    if not data.get("ok"):
        return f"[{data.get('code')}] {data.get('error')}"
    d = data["date"]
    lines = [
        f"Patrician III  {d['day']:02d}/{d['month'] + 1:02d}/{d['year']}   "
        f"player merchant #{data['player']}   {data['records']} auto-trader records",
        "",
        f"HIREABLE CAPTAINS: {len(data['hireable'])}",
    ]
    for rec in data["hireable"]:
        age = "?" if rec["age"] is None else rec["age"]
        lines.append(f"  {rec['town']:<13} #{rec['index']:<4} {_skills(rec)}  "
                     f"wage {rec['wage']:>3}  age {age}  [{rec['status']}]")
    lines += ["", "EVERY TOWN (chain headed at town+0x82E)"]
    for row in data["towns"]:
        caps = ", ".join(f"#{r['index']} {r['status']}" for r in row["captains"]) or "-"
        pirs = ", ".join(f"#{r['index']}" for r in row["pirates"]) or "-"
        lines.append(f"  {row['town']:<13} captain: {caps:<24} pirate: {pirs}")
    checks = data["checks"]
    free = sum(1 for r in data["hireable"] if r["status"] == "free")
    lines += [
        "",
        "SELF-CHECKS (all three lists should be empty if the chain model is right)",
        f"  chain records that are also a ship's captain: {checks['chainedOnShip'] or 'none'}",
        f"  records chained in two towns:                 {checks['chainedTwice'] or 'none'}",
        f"  chains that loop:                             {checks['loopingChains'] or 'none'}",
        f"  free captains world-wide: {free} (the game stops spawning them at 8)",
    ]
    return "\n".join(lines)


def main() -> int:
    data = read()
    print(format_report(data))
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
