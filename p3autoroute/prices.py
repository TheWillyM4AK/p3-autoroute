"""Live town buy/sell prices, read from the running game.

Reads the running ``Patrician3`` process **read-only** (Windows-only, via
``kernel32`` through ``ctypes``) and, with the pure price engine in
:mod:`pricing`, turns each town's live ware **stock** (``town+0x04``) and live
per-ware **price thresholds** (``town+0x4F0`` — read straight from the game, so
there is no need to reproduce the threshold formula) into the exact current buy
and sell price of one load (barrel/bundle).

The result is grouped per good with one quote per town, so the frontend can show,
for a chosen good, the buy and sell price *in each town*. Each quote also carries
the town's weeks of supply and whether it produces the good, which is what
explains the price (a producer/oversupplied town is cheap to buy from; a starved
consumer town pays a lot when you sell to it).

The fixed absolute addresses are the virtual addresses of the 1.x GOG/retail
build, which loads at image base ``0x400000`` with no ASLR; a date sanity check
guards against reading garbage from an unexpected build. Every Windows API touch
is done lazily inside functions so the module imports cleanly on any platform
(the test suite is standard-library only and never calls :func:`read`).
"""
from __future__ import annotations

import statistics
import struct
import sys

from . import goods, pricing, towns

# --- static addresses (P3Modding RE project) -----------------------------
GAME_WORLD_PTR = 0x006DE4A0     # GameWorld struct base
TOWN_NAMES_PTR = 0x006DDA00     # table of name pointers, indexed by town_index

# GameWorld layout
GW_DAY = 0x00                   # u8
GW_MONTH = 0x01                 # u8
GW_YEAR = 0x02                  # u16
GW_TOWNS_COUNT = 0x10           # u16, number of active towns in the array
GW_TOWNS_ARRAY = 0x68           # ptr -> towns array

# Town struct (stride 0x9F8). Storage fields overlap the town base.
TOWN_STRIDE = 0x9F8
TOWN_STOCK = 0x04               # [i32; 24] current ware stock
TOWN_CONS_BUSINESS = 0x64       # [i32; 24] daily business consumption
TOWN_PRODUCTION = 0xC4          # [i32; 24] daily production
TOWN_INDEX = 0x2C0              # u8, 0..23 (matches towns.NAMES order)
TOWN_CITIZENS = 0x2D4           # u32, used as an "is this a real town" sanity bound
TOWN_CONS_CITIZENS = 0x310      # [i32; 24] daily citizen consumption
TOWN_THRESHOLDS = 0x4F0         # [[i32; 4]; 24] live price thresholds t0..t3

PROCESS_NAMES = ("patrician3", "patrician 3")  # matches Patrician3.exe & the modloader

# Windows constants
_PROCESS_VM_READ = 0x0010
_PROCESS_QUERY_INFORMATION = 0x0400
_TH32CS_SNAPPROCESS = 0x00000002

# Only the 20 real trade goods have a base price; weapons (20..23) are skipped.
TRADE_GOODS = [g for g in range(goods.COUNT) if pricing.BASE_PRICES[g] is not None]


def _err(code: str, error: str) -> dict:
    return {"ok": False, "code": code, "error": error}


def _median(values) -> int | None:
    """Rounded median of a list of prices, or ``None`` when the list is empty."""
    return round(statistics.median(values)) if values else None


def _find_pid(names):
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap == wintypes.HANDLE(-1).value:
        return None
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not k32.Process32First(snap, ctypes.byref(entry)):
            return None
        while True:
            exe = entry.szExeFile.decode("latin1", "ignore").lower()
            if any(n in exe for n in names):
                return entry.th32ProcessID
            if not k32.Process32Next(snap, ctypes.byref(entry)):
                return None
    finally:
        k32.CloseHandle(snap)


class _Mem:
    """Minimal read-only window into another process's address space."""

    def __init__(self, pid):
        import ctypes
        self._ctypes = ctypes
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.h = self._k32.OpenProcess(
            _PROCESS_VM_READ | _PROCESS_QUERY_INFORMATION, False, pid)
        if not self.h:
            raise PermissionError(ctypes.get_last_error())

    def close(self):
        if self.h:
            self._k32.CloseHandle(self.h)
            self.h = None

    def read(self, addr, size):
        ctypes = self._ctypes
        buf = (ctypes.c_char * size)()
        n = ctypes.c_size_t(0)
        ok = self._k32.ReadProcessMemory(
            self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n))
        if not ok or n.value != size:
            raise OSError(f"ReadProcessMemory @0x{addr:08x} ({size}B) failed")
        return bytes(buf[:n.value])

    def u8(self, a):
        return self.read(a, 1)[0]

    def u16(self, a):
        return struct.unpack("<H", self.read(a, 2))[0]

    def u32(self, a):
        return struct.unpack("<I", self.read(a, 4))[0]


def _town_name(mem, town_index):
    """In-app name (towns.NAMES) when known, else the game's own string."""
    if 0 <= town_index < towns.COUNT:
        return towns.NAMES[town_index]
    try:
        ptr = mem.u32(TOWN_NAMES_PTR + town_index * 4)
        raw = mem.read(ptr, 40)
        return raw.split(b"\x00", 1)[0].decode("latin1") or f"Town #{town_index}"
    except OSError:
        return f"Town #{town_index}"


def read(params=None) -> dict:
    """Live buy/sell prices per good across all towns.

    ``params`` may carry ``{"difficulty": 0|1|2}`` (low/normal/high); it only
    affects sell prices in the starved regime. On success::

        {"ok": True, "date": {...}, "difficulty": int,
         "goods": [{"good", "name", "size", "base", "floor", "ceiling",
                    "basePerBarrel",
                    "towns": [{"townIndex", "town", "stock", "weeks",
                               "produces", "buy", "sell"}]}]}

    ``buy`` is ``None`` when the town has less than one load in stock. On failure
    it returns ``{"ok": False, "code", "error"}`` where *code* is one of
    ``unsupported_os``/``not_running``/``no_access``/``unknown_version``.
    """
    params = params or {}
    difficulty = int(params.get("difficulty", pricing.DIFFICULTY_NORMAL))
    if difficulty not in (0, 1, 2):
        difficulty = pricing.DIFFICULTY_NORMAL

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

        towns_ptr = mem.u32(GAME_WORLD_PTR + GW_TOWNS_ARRAY)
        town_count = min(mem.u16(GAME_WORLD_PTR + GW_TOWNS_COUNT), 40)

        # good id -> list of per-town quotes
        quotes: dict[int, list] = {g: [] for g in TRADE_GOODS}
        # good id -> {key: [per-town price at a reference weeks-of-supply]}; the
        # universal table's live columns are the median of these across towns.
        ref: dict[int, dict] = {g: {"sell1": [], "sell1_5": [], "sell2": [], "buy2": [], "buy2_5": [], "buy3": []} for g in TRADE_GOODS}
        for t in range(town_count):
            base = towns_ptr + TOWN_STRIDE * t
            try:
                town_index = mem.u8(base + TOWN_INDEX)
                citizens = mem.u32(base + TOWN_CITIZENS)
            except OSError:
                break
            if not (town_index < towns.COUNT and citizens < 1_000_000):
                continue
            name = _town_name(mem, town_index)
            stock = struct.unpack("<24i", mem.read(base + TOWN_STOCK, 96))
            thr = struct.unpack("<96i", mem.read(base + TOWN_THRESHOLDS, 384))
            prod = struct.unpack("<24i", mem.read(base + TOWN_PRODUCTION, 96))
            cons_cit = struct.unpack("<24i", mem.read(base + TOWN_CONS_CITIZENS, 96))
            cons_biz = struct.unpack("<24i", mem.read(base + TOWN_CONS_BUSINESS, 96))
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
                # Literal weeks of supply = stock / weekly consumption, matching
                # the figure the game shows (gross citizen+business consumption,
                # production excluded). ``None`` (∞) when the town doesn't consume
                # the good. NB: this no longer tracks the price 1:1 — for building
                # materials the additive threshold bonus shifts the price up at a
                # given week count — but it is what the player reads in-game.
                weekly = (cons_cit[g] + cons_biz[g]) * 7
                weeks = round(s / weekly, 1) if weekly > 0 else None
                # Reference prices computed at fixed weeks-of-supply using THIS
                # town's real thresholds (robust: no extrapolation from observed
                # stock, so towns far from the target week still contribute).
                if weekly > 0:
                    s2, s25, s3 = round(2 * weekly), round(2.5 * weekly), round(3 * weekly)
                    ref[g]["sell1"].append(
                        pricing.unit_sell_price(round(weekly), t4, base_price, size, difficulty))
                    ref[g]["sell1_5"].append(
                        pricing.unit_sell_price(round(1.5 * weekly), t4, base_price, size, difficulty))
                    ref[g]["sell2"].append(
                        pricing.unit_sell_price(s2, t4, base_price, size, difficulty))
                    if s2 >= size:
                        ref[g]["buy2"].append(pricing.unit_buy_price(s2, t4, base_price, size))
                    if s25 >= size:
                        ref[g]["buy2_5"].append(pricing.unit_buy_price(s25, t4, base_price, size))
                    if s3 >= size:
                        ref[g]["buy3"].append(pricing.unit_buy_price(s3, t4, base_price, size))
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
                # Real-world counterparts to the universal columns: median across
                # towns of the price at 1/2/3 weeks of supply. ``None`` when no
                # town gives a usable figure (e.g. a good held in huge bulk like
                # bricks never sits near 2–3 weeks).
                "sell1wk": _median(ref[g]["sell1"]),
                "sell1_5wk": _median(ref[g]["sell1_5"]),
                "sell2wk": _median(ref[g]["sell2"]),
                "buy2wk": _median(ref[g]["buy2"]),
                "buy2_5wk": _median(ref[g]["buy2_5"]),
                "buy3wk": _median(ref[g]["buy3"]),
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
