"""Tavern-captain locator tests, driven from a fake memory image.

These pin the chain walk and the struct offsets as coded. They cannot tell
whether the model matches the real game — that was checked by hand against a
live save (see the module docstring of ``p3autoroute.captains``).

Run directly:  python tests/test_captains.py
Or with pytest: pytest
"""
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Constructing Api must not touch the real ~/.p3autoroute.
os.environ["P3AUTOROUTE_DATA"] = tempfile.mkdtemp()

from p3autoroute import captains as c  # noqa: E402
from p3autoroute.api import PUBLIC_METHODS, Api  # noqa: E402
from p3autoroute.prices import (  # noqa: E402
    GAME_WORLD_PTR, GW_TOWNS_ARRAY, GW_TOWNS_COUNT, TOWN_CITIZENS, TOWN_INDEX,
    TOWN_STRIDE,
)
from p3autoroute.ships import (  # noqa: E402
    GW_GAME_TIME, OPERATIONS_PTR, OPS_PLAYER_MERCHANT, SHIP_STRIDE, SHIPS_ARRAY,
    SHIPS_COUNT, SHIPS_PTR,
)

GAME_TIME = 5_000_000
PLAYER = 36
END = 0xFFFF
TOWNS_AT, RECS_AT, SHIPS_AT = 0x10000000, 0x20000000, 0x30000000
HAMBURG, LUEBECK, TORUN = 8, 9, 19


class FakeMem:
    """Sparse stand-in for ``prices._Mem``: reads outside a region raise OSError."""

    def __init__(self):
        self.regions = {}

    def region(self, base, size):
        self.regions[base] = bytearray(size)
        return self.regions[base]

    def read(self, addr, size):
        for base, buf in self.regions.items():
            if base <= addr and addr + size <= base + len(buf):
                return bytes(buf[addr - base:addr - base + size])
        raise OSError(f"unmapped 0x{addr:08x}")

    def u8(self, a):
        return self.read(a, 1)[0]

    def u16(self, a):
        return struct.unpack("<H", self.read(a, 2))[0]

    def u32(self, a):
        return struct.unpack("<I", self.read(a, 4))[0]


def _record(next_, kind, sailing, trade, fighting, wage, merchant, age_years=30.0):
    birth = GAME_TIME - int(age_years * c.TICKS_PER_YEAR)
    return struct.pack("<HhiBBBBHBB", next_, 0, birth, kind, sailing, trade,
                       fighting, wage, 0, merchant)


def _build(records, town_heads, ships):
    """A game image with the given auto-trader records, (town, chain head) pairs
    and (owner, captain index) ships."""
    mem = FakeMem()
    gw = mem.region(GAME_WORLD_PTR, 0x100)
    gw[0], gw[1] = 12, 4
    struct.pack_into("<H", gw, 2, 1304)
    struct.pack_into("<H", gw, GW_TOWNS_COUNT, len(town_heads))
    struct.pack_into("<I", gw, GW_GAME_TIME, GAME_TIME)
    struct.pack_into("<I", gw, GW_TOWNS_ARRAY, TOWNS_AT)
    ops = mem.region(OPERATIONS_PTR, 0x1000)
    struct.pack_into("<i", ops, OPS_PLAYER_MERCHANT, PLAYER)
    root = mem.region(SHIPS_PTR, 0x100)
    struct.pack_into("<I", root, c.AUTO_TRADERS_ARRAY, RECS_AT)
    struct.pack_into("<I", root, SHIPS_ARRAY, SHIPS_AT)
    struct.pack_into("<H", root, c.AUTO_TRADERS_COUNT, len(records))
    struct.pack_into("<H", root, SHIPS_COUNT, len(ships))
    mem.region(RECS_AT, len(records) * c.AT_STRIDE)[:] = b"".join(records)
    tw = mem.region(TOWNS_AT, TOWN_STRIDE * len(town_heads))
    for t, (town_index, head) in enumerate(town_heads):
        tw[t * TOWN_STRIDE + TOWN_INDEX] = town_index
        struct.pack_into("<I", tw, t * TOWN_STRIDE + TOWN_CITIZENS, 5000)
        struct.pack_into("<H", tw, t * TOWN_STRIDE + c.TOWN_CHAIN_HEAD, head)
    sh = mem.region(SHIPS_AT, max(1, len(ships)) * SHIP_STRIDE)
    for s, (owner, cap) in enumerate(ships):
        sh[s * SHIP_STRIDE + c.SHIP_OWNER] = owner
        struct.pack_into("<H", sh, s * SHIP_STRIDE + c.SHIP_CAPTAIN, cap)
    return mem


RECORDS = [
    _record(END, 0x80, 200, 200, 200, 31, 0xFF),            # 0 Hamburg's pirate (chain head)
    _record(2, 0xFB, 237, 251, 112, 31, 0xFF),              # 1 Torun's pirate (chain head)
    _record(3, 6, 137, 236, 60, 22, 0xFF, age_years=38.3),  # 2 Torun: free captain
    _record(5, 3, 100, 100, 100, 16, 5),                    # 3 Torun: held by merchant 5
    _record(END, 2, 90, 90, 90, 15, 0xFF),                  # 4 unchained: serving on a ship
    _record(END, 9, 250, 150, 49, 18, PLAYER),              # 5 Torun: dismissed by the player
]
TOWNS = [(HAMBURG, 0), (TORUN, 1), (LUEBECK, END)]
SHIPS = [(PLAYER, 4), (0xFF, 2)]                            # a real ship; an empty slot


def _world():
    out = c._collect(_build(RECORDS, TOWNS, SHIPS))
    assert out["ok"], out
    return out, {row["town"]: row for row in out["towns"]}


def test_pirate_at_chain_head_is_not_a_captain():
    # The reverted first attempt read only the head record, i.e. this pirate.
    _, towns = _world()
    assert towns["Hamburg"]["captains"] == []
    assert [p["index"] for p in towns["Hamburg"]["pirates"]] == [0]


def test_empty_chain_has_nobody():
    _, towns = _world()
    assert towns["Luebeck"]["captains"] == [] and towns["Luebeck"]["pirates"] == []


def test_captain_is_found_past_the_pirate():
    out, towns = _world()
    assert [(r["index"], r["status"]) for r in towns["Torun"]["captains"]] == [
        (2, "free"), (3, "taken"), (5, "yours")]
    # Only the free one and the player's own dismissed one are on offer, best first.
    assert [(h["town"], h["index"]) for h in out["hireable"]] == [("Torun", 5), ("Torun", 2)]


def test_record_fields_as_the_tavern_shows_them():
    out, _ = _world()
    free = next(h for h in out["hireable"] if h["index"] == 2)
    assert (free["trade"], free["sailing"], free["fighting"]) == (4, 2, 1)
    assert (free["wage"], free["age"], free["townIndex"]) == (22, 38, TORUN)
    assert free["raw"] == {"trade": 236, "sailing": 137, "fighting": 60}


def test_skill_levels_are_fifty_points_each():
    # The two in-game readings that separate a divisor of 50 from 51.
    assert c._level(250) == 5 and c._level(150) == 3
    assert c._level(49) == 0 and c._level(255) == 5


def test_on_ship_captain_never_listed_and_empty_slots_ignored():
    out, _ = _world()
    listed = [r["index"] for row in out["towns"] for r in row["captains"] + row["pirates"]]
    assert 4 not in listed
    # Ship slot 1 has no owner; its stale captain index must not raise a conflict.
    assert out["checks"] == {"chainedOnShip": [], "chainedTwice": [], "loopingChains": []}


def test_self_checks_fire_when_data_contradicts_the_model():
    bad = c._collect(_build(RECORDS, [(HAMBURG, 2), (TORUN, 1)], [(PLAYER, 2)]))
    assert [d["index"] for d in bad["checks"]["chainedTwice"]] == [2, 3, 5]
    assert {d["index"] for d in bad["checks"]["chainedOnShip"]} == {2}


def test_looping_chain_terminates_and_is_reported():
    loop = [_record(1, 5, 1, 1, 1, 10, 0xFF), _record(0, 5, 1, 1, 1, 10, 0xFF)]
    assert c.walk_chain(b"".join(loop), 2, 0) == ([0, 1], False)
    assert c._collect(_build(loop, [(HAMBURG, 0)], []))["checks"]["loopingChains"] == ["Hamburg"]


def test_unrecognised_build_is_rejected():
    mem = _build(RECORDS, TOWNS, SHIPS)
    mem.regions[GAME_WORLD_PTR][0] = 0                       # day 0: not a real date
    assert c._collect(mem)["code"] == "unknown_version"


def test_report_is_plain_ascii():
    out, _ = _world()
    report = c.format_report(out)
    report.encode("ascii")                                   # safe on any console codepage
    assert "HIREABLE CAPTAINS: 2" in report and "Torun" in report
    assert c.format_report({"ok": False, "code": "not_running", "error": "x"}) == "[not_running] x"


def test_api_exposes_the_endpoint():
    # Missing from PUBLIC_METHODS it would work over the bridge but 404 in web mode.
    assert "captains_live" in PUBLIC_METHODS
    res = Api().captains_live({})
    # Whatever the machine (no game, other OS, game running) it answers in shape.
    assert isinstance(res.get("ok"), bool)
    assert res["ok"] or res["code"] in (
        "unsupported_os", "not_running", "no_access", "unknown_version")


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
