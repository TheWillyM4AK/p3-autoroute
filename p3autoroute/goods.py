"""Catalog of goods (24) — port of scripts/repository/GoodRepository.gd.

The order 0..23 is the game's internal order and is used as the index into the
price/quantity arrays of the .rou format and in the pricing presets.
"""
from enum import IntEnum


class Good(IntEnum):
    GRAIN = 0
    MEAT = 1
    FISH = 2
    BEER = 3
    SALT = 4
    HONEY = 5
    SPICES = 6
    WINE = 7
    CLOTH = 8
    SKINS = 9
    OIL = 10
    TIMBER = 11
    IRON_GOODS = 12
    LEATHER = 13
    WOOL = 14
    PITCH = 15
    PIG_IRON = 16
    HEMP = 17
    POTTERY = 18
    BRICKS = 19
    SWORD = 20
    BOW = 21
    CROSSBOW = 22
    CARBINE = 23


# Internal load sizes (GoodRepository.Size). The .rou format multiplies the
# "on-screen" quantity by this factor.
BARREL = 200
BUNDLE = 2000
WEAPON = 10

NAMES = [
    "Grain", "Meat", "Fish", "Beer", "Salt", "Honey",
    "Spices", "Wine", "Cloth", "Skins", "Oil", "Timber",
    "Iron Goods", "Leather", "Wool", "Pitch", "Pig Iron", "Hemp",
    "Pottery", "Bricks", "Sword", "Bow", "Crossbow", "Carbine",
]

# The 4 weapons are not shown by default in the original UI.
VISIBILITY = [
    True, True, True, True, True, True,
    True, True, True, True, True, True,
    True, True, True, True, True, True,
    True, True, False, False, False, False,
]

SIZES = [
    BUNDLE, BUNDLE, BUNDLE, BARREL, BARREL, BARREL,
    BARREL, BARREL, BARREL, BARREL, BARREL, BUNDLE,
    BARREL, BARREL, BUNDLE, BARREL, BUNDLE, BUNDLE,
    BARREL, BUNDLE, WEAPON, WEAPON, WEAPON, WEAPON,
]

COUNT = 24
