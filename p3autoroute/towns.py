"""Catalog of towns (24) — port of scripts/repository/TownRepository.gd."""
from enum import IntEnum


class Town(IntEnum):
    EDINBURGH = 0
    SCARBOROUGH = 1
    LONDON = 2
    BURGES = 3
    GRONINGEN = 4
    COLOGNE = 5
    BREMEN = 6
    RIPEN = 7
    HAMBURG = 8
    LUEBECK = 9
    ROSTOCK = 10
    BERGEN = 11
    OSLO = 12
    AALBORG = 13
    MALMO = 14
    STOCKHOLM = 15
    VISBY = 16
    STETTIN = 17
    GDANSK = 18
    TORUN = 19
    RIGA = 20
    REVAL = 21
    LADOGA = 22
    NOVGOROD = 23


NAMES = [
    "Edinburgh", "Scarborough", "London", "Burges", "Groningen", "Cologne",
    "Bremen", "Ripen", "Hamburg", "Luebeck", "Rostock", "Bergen",
    "Oslo", "Aalborg", "Malmo", "Stockholm", "Visby", "Stettin",
    "Gdansk", "Torun", "Riga", "Reval", "Ladoga", "Novgorod",
]

COUNT = 24
