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

# Icon file per good (relative to the web/ root), indexed by good id. These are
# the game's own trade-good symbols, sourced from the Patrician III wiki. The 4
# weapons have no trade-good icon (and are hidden by default), so they are "".
ICONS = [
    "assets/goods/grain.png", "assets/goods/meat.png", "assets/goods/fish.png",
    "assets/goods/beer.png", "assets/goods/salt.png", "assets/goods/honey.png",
    "assets/goods/spices.png", "assets/goods/wine.png", "assets/goods/cloth.png",
    "assets/goods/skins.png", "assets/goods/oil.png", "assets/goods/timber.png",
    "assets/goods/iron_goods.png", "assets/goods/leather.png", "assets/goods/wool.png",
    "assets/goods/pitch.png", "assets/goods/pig_iron.png", "assets/goods/hemp.png",
    "assets/goods/pottery.png", "assets/goods/bricks.png",
    "", "", "", "",
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
