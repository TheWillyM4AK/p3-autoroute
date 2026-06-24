"""Static production / demand map for the 24 Patrician III towns.

The ``.rou`` format carries no economic data, so this table records which town
produces each good. It was rebuilt from the **running game's own data**: the
per-town daily-production array (``town+0xC4`` — the same field
:mod:`p3autoroute.prices` reads) was sampled live and a town is listed as a
producer of a good when it makes a non-trivial amount of it.

Two things learned from that live read shape the table:

- The base map has a clear **two-tier** production: a primary tier and a
  secondary tier at ~75% of it. Both are genuine producers, so both are listed.
  The older "Effective production towns by good" Steam guide
  (``steamcommunity.com/sharedfiles/filedetails/?id=567242601``) only named the
  primary tier, which is why this table used to miss producers such as
  Luebeck/Grain and mark them as sell targets.
- A town's daily production falls to ~zero while its **warehouse for that good
  is full**, so a single low reading does not mean "does not produce". Producers
  are therefore never dropped on the strength of one snapshot (e.g. Reval/Grain
  and Torun/Timber read near zero when caught with full storage but are real
  producers).

The SELL side follows town demand: a good is "demanded" wherever it is
consumable and not produced locally — exactly the towns you would import it
into, i.e. sell to.

The model the "Trade a good" feature uses is therefore:

- a town is a **BUY** target for good ``g`` if it produces ``g``
  (``g in PRODUCERS`` -> ``produces()``);
- a town is a **SELL** target for good ``g`` if ``g`` is consumable and the
  town does *not* produce it (``demands()``).

Spices (good 6) is produced nowhere in the game; the towns listed for it are the
import hubs where it can actually be bought (kept so the feature treats them as
BUY rather than SELL). The 4 weapons (good ids 20..23) are player/military goods
with no town population demand and no fixed producer, so they are left empty and
marked non-consumable; the feature simply never touches them.

Town and good ids follow :mod:`p3autoroute.towns` and :mod:`p3autoroute.goods`.
This data describes the base map only; it is intentionally easy to amend if a
town's set looks off for a given playthrough.
"""
from __future__ import annotations

from typing import List

from . import goods

# Producing towns for each good id 0..23 (empty = not produced on the map).
# Rebuilt from the running game's per-town daily-production array; the trailing
# comment names the towns for readability.
PRODUCERS: List[List[int]] = [
    [2, 3, 4, 5, 6, 8, 9, 10, 16, 17, 18, 19, 21, 22],  # 0  Grain      London, Burges, Groningen, Cologne, Bremen, Hamburg, Luebeck, Rostock, Visby, Stettin, Gdansk, Torun, Reval, Ladoga
    [0, 1, 2, 5, 7, 10, 11, 13, 14, 15, 18, 19, 21, 23],  # 1  Meat       Edinburgh, Scarborough, London, Cologne, Ripen, Rostock, Bergen, Aalborg, Malmo, Stockholm, Gdansk, Torun, Reval, Novgorod
    [0, 7, 8, 9, 11, 12, 13, 15, 17, 20, 22],  # 2  Fish       Edinburgh, Ripen, Hamburg, Luebeck, Bergen, Oslo, Aalborg, Stockholm, Stettin, Riga, Ladoga
    [1, 2, 6, 8, 17, 18, 23],         # 3  Beer       Scarborough, London, Bremen, Hamburg, Stettin, Gdansk, Novgorod
    [3, 7, 10, 17, 20, 21],           # 4  Salt       Burges, Ripen, Rostock, Stettin, Riga, Reval
    [3, 5, 10, 14, 16, 19, 20, 22, 23],  # 5  Honey      Burges, Cologne, Rostock, Malmo, Visby, Torun, Riga, Ladoga, Novgorod
    [2, 3, 4, 5, 6, 8],               # 6  Spices     London, Burges, Groningen, Cologne, Bremen, Hamburg (import hubs)
    [3, 4, 5],                        # 7  Wine       Burges, Groningen, Cologne
    [0, 1, 2, 6, 14, 16],             # 8  Cloth      Edinburgh, Scarborough, London, Bremen, Malmo, Visby
    [12, 19, 20, 21, 22, 23],         # 9  Skins      Oslo, Torun, Riga, Reval, Ladoga, Novgorod
    [7, 11, 12, 13, 15],              # 10 Oil        Ripen, Bergen, Oslo, Aalborg, Stockholm
    [0, 1, 4, 5, 7, 8, 9, 11, 12, 13, 14, 15, 17, 19, 20, 22, 23],  # 11 Timber     Edinburgh, Scarborough, Groningen, Cologne, Ripen, Hamburg, Luebeck, Bergen, Oslo, Aalborg, Malmo, Stockholm, Stettin, Torun, Riga, Ladoga, Novgorod
    [0, 1, 6, 9, 11, 15, 21],         # 12 Iron Goods Edinburgh, Scarborough, Bremen, Luebeck, Bergen, Stockholm, Reval
    [0, 1, 2, 5, 7, 10, 11, 13, 14, 15, 18, 19, 21, 23],  # 13 Leather    Edinburgh, Scarborough, London, Cologne, Ripen, Rostock, Bergen, Aalborg, Malmo, Stockholm, Gdansk, Torun, Reval, Novgorod
    [0, 1, 2, 3, 5, 6, 14, 16, 18, 19, 22],  # 14 Wool       Edinburgh, Scarborough, London, Burges, Cologne, Bremen, Malmo, Visby, Gdansk, Torun, Ladoga
    [9, 11, 12, 18, 20, 23],          # 15 Pitch      Luebeck, Bergen, Oslo, Gdansk, Riga, Novgorod
    [0, 2, 6, 7, 11, 12, 13, 14, 15, 22, 23],  # 16 Pig Iron   Edinburgh, London, Bremen, Ripen, Bergen, Oslo, Aalborg, Malmo, Stockholm, Ladoga, Novgorod
    [3, 4, 8, 9, 10, 16, 17, 18, 22],  # 17 Hemp       Burges, Groningen, Hamburg, Luebeck, Rostock, Visby, Stettin, Gdansk, Ladoga
    [3, 4, 5, 7, 8, 10, 13, 15, 16, 19],  # 18 Pottery    Burges, Groningen, Cologne, Ripen, Hamburg, Rostock, Aalborg, Stockholm, Visby, Torun
    [1, 3, 4, 6, 7, 9, 10, 12, 13, 14, 16, 23],  # 19 Bricks     Scarborough, Burges, Groningen, Bremen, Ripen, Luebeck, Rostock, Oslo, Aalborg, Malmo, Visby, Novgorod
    [],                               # 20 Sword
    [],                               # 21 Bow
    [],                               # 22 Crossbow
    [],                               # 23 Carbine
]

# Goods with town population demand (the SELL side). The 4 weapons have none.
CONSUMABLE: List[bool] = [g not in (20, 21, 22, 23) for g in range(goods.COUNT)]

# Fast membership lookup mirroring PRODUCERS.
_PRODUCER_SETS = [set(towns) for towns in PRODUCERS]


def produces(town: int, good: int) -> bool:
    """Whether ``town`` produces ``good`` (a BUY candidate)."""
    return 0 <= good < goods.COUNT and town in _PRODUCER_SETS[good]


def demands(town: int, good: int) -> bool:
    """Whether ``town`` demands ``good`` (a SELL candidate).

    A consumable good is demanded by every town that does not produce it.
    """
    return (0 <= good < goods.COUNT and CONSUMABLE[good]
            and town not in _PRODUCER_SETS[good])
