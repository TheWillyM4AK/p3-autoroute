"""Locate hireable captains by reading the *running* game's memory.

Patrician III stores, inside every town struct, an **"Unemployed Captain
Index"** at offset ``0x82e`` — the head of a linked list (chained through each
captain's *next* field) of the captains currently waiting to be hired in that
town's tavern. That offset is confirmed by the P3Modding Cheat Engine table
(`p3modding.github.io/src/Patrician3.CT`); the surrounding struct layout comes
from the same project's IDA scripts (`github.com/P3Modding/p3_ida_scripts`).

This module attaches **read-only** to the live ``Patrician3`` process and walks
those lists, returning which town has which hireable captain. It is
Windows-only (uses ``kernel32`` via ``ctypes``); every Windows API touch is done
lazily inside functions so the module imports cleanly on any platform (the test
suite is standard-library only and never calls :func:`locate`).

The fixed absolute addresses below are the virtual addresses of the 1.x
GOG/retail build, which loads at image base ``0x400000`` with no ASLR — so they
are valid verbatim in the process. A date sanity check guards against reading
garbage from an unexpected build.
"""
from __future__ import annotations

import struct
import sys

from . import towns

# --- static addresses (P3Modding RE project) -----------------------------
GAME_WORLD_PTR = 0x006DE4A0     # GameWorld struct base
CLASS6_PTR = 0x006DD7A0         # holds the captains/ships/convoys arrays
TOWN_NAMES_PTR = 0x006DDA00     # table of name pointers, indexed by town_index

# GameWorld layout
GW_DAY = 0x00                   # u8
GW_MONTH = 0x01                 # u8
GW_YEAR = 0x02                  # u16
GW_TOWNS_ARRAY = 0x68           # ptr -> towns array

# Town struct (stride 0x9F8)
TOWN_STRIDE = 0x9F8
TOWN_INDEX = 0x2C0              # u8, 0..23 (matches towns.NAMES order)
TOWN_CITIZENS = 0x2D4           # u32, used as a "is this a real town" sanity bound
TOWN_UNEMPLOYED_CAPTAIN = 0x82E  # u16, head index into the captains array (0xFFFF = none)

# class6: captains array
C6_CAPTAINS_ARRAY = 0x00        # ptr -> captains array
C6_CAPTAINS_COUNT = 0xF2        # u16

# Captain / auto_trader struct (stride 0x10)
CAPTAIN_STRIDE = 0x10
CAP_NEXT = 0x00                 # u16, next captain in the same town's list
CAP_SAILING = 0x09             # u8, raw 0..255  (P3 calls this "Sailing")
CAP_TRADE = 0x0A               # u8, raw 0..255
CAP_FIGHTING = 0x0B            # u8, raw 0..255  (P3 calls this "Fighting")
CAP_WAGE = 0x0C                 # u16, daily wage

# The game shows each skill on a 0..5 scale (Trade / Sailing / Fighting; see the
# Patrician III wiki). The raw byte is bucketed by integer division by 51
# (=255/5) — calibrated against an in-game reading of 236/137/160 -> 4/2/3.
SKILL_DIVISOR = 51


def _level(raw):
    return min(5, raw // SKILL_DIVISOR)

NONE_INDEX = 0xFFFF
PROCESS_NAMES = ("patrician3", "patrician 3")  # matches Patrician3.exe & the modloader

# Windows constants
_PROCESS_VM_READ = 0x0010
_PROCESS_QUERY_INFORMATION = 0x0400
_TH32CS_SNAPPROCESS = 0x00000002


def _err(code: str, error: str) -> dict:
    return {"ok": False, "code": code, "error": error}


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


def locate() -> dict:
    """Return the towns that currently have a hireable captain.

    On success::

        {"ok": True, "date": {...}, "totalCaptains": int,
         "townsWithCaptains": int,
         "towns": [{"townIndex": int, "town": str,
                    "captains": [{"index", "trade", "sailing",
                                  "fighting", "wage"}]}],  # skills 0..5
         "emptyTowns": [str, ...]}

    On failure: ``{"ok": False, "code": str, "error": str}`` where *code* is one
    of ``unsupported_os``, ``not_running``, ``no_access`` or ``unknown_version``.
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
        if not (1 <= day <= 31 and 1 <= month <= 12 and 1000 <= year <= 2000):
            return _err("unknown_version",
                        "This game build isn't recognised (its internal "
                        "addresses don't match). Tested with the 1.x GOG/retail "
                        "edition.")

        caps_ptr = mem.u32(CLASS6_PTR + C6_CAPTAINS_ARRAY)
        count = mem.u16(CLASS6_PTR + C6_CAPTAINS_COUNT)
        captains = [mem.read(caps_ptr + CAPTAIN_STRIDE * i, CAPTAIN_STRIDE)
                    for i in range(count)]

        def parse(i):
            r = captains[i]
            return {
                "index": i,
                "trade": _level(r[CAP_TRADE]),
                "sailing": _level(r[CAP_SAILING]),
                "fighting": _level(r[CAP_FIGHTING]),
                "wage": struct.unpack_from("<H", r, CAP_WAGE)[0],
            }

        def walk(head):
            out, seen, cur = [], set(), head
            while cur != NONE_INDEX and cur < count and cur not in seen and len(out) < 16:
                seen.add(cur)
                out.append(parse(cur))
                cur = struct.unpack_from("<H", captains[cur], CAP_NEXT)[0]
            return out

        towns_ptr = mem.u32(GAME_WORLD_PTR + GW_TOWNS_ARRAY)
        with_caps, empty = [], []
        for t in range(40):
            base = towns_ptr + TOWN_STRIDE * t
            try:
                blob = mem.read(base, TOWN_UNEMPLOYED_CAPTAIN + 2)
            except OSError:
                break
            town_index = blob[TOWN_INDEX]
            citizens = struct.unpack_from("<I", blob, TOWN_CITIZENS)[0]
            if not (town_index < 40 and citizens < 1_000_000):
                continue
            head = struct.unpack_from("<H", blob, TOWN_UNEMPLOYED_CAPTAIN)[0]
            name = _town_name(mem, town_index)
            chain = walk(head)
            if chain:
                with_caps.append({"townIndex": town_index, "town": name,
                                  "captains": chain})
            else:
                empty.append(name)

        with_caps.sort(key=lambda e: e["townIndex"])
        total = sum(len(e["captains"]) for e in with_caps)
        return {
            "ok": True,
            "date": {"day": day, "month": month, "year": year},
            "totalCaptains": total,
            "townsWithCaptains": len(with_caps),
            "towns": with_caps,
            "emptyTowns": empty,
        }
    finally:
        mem.close()
