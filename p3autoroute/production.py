"""Static production / demand map for the 24 Patrician III towns.

The ``.rou`` format carries no economic data, so this table is curated from
community references for the base game's fixed map:

- The BUY side (``PRODUCERS``) — which towns produce each good — is transcribed
  from the "Effective production towns by good" Steam guide
  (``steamcommunity.com/sharedfiles/filedetails/?id=567242601``), cross-checked
  against the Patrician III wiki's business pages.
- The SELL side follows the manual's description of town demand: a town's
  population consumes essentially every *consumer* good it does not itself
  produce (consumption scales with the social classes present). So a good is
  considered "demanded" wherever it is consumable and not produced locally —
  exactly the towns you would import it into, i.e. sell to.

The model the "Trade a good" feature uses is therefore:

- a town is a **BUY** target for good ``g`` if it produces ``g``
  (``g in PRODUCERS`` -> ``produces()``);
- a town is a **SELL** target for good ``g`` if ``g`` is consumable and the
  town does *not* produce it (``demands()``).

The 4 weapons (good ids 20..23) are player/military goods with no town
population demand and no fixed producer on the map, so they are left empty and
marked non-consumable; the feature simply never touches them.

Town and good ids follow :mod:`p3autoroute.towns` and :mod:`p3autoroute.goods`.
This data describes the base map only; it is intentionally easy to amend if a
town's set looks off for a given playthrough.
"""
from __future__ import annotations

from typing import List

from . import goods

# Producing towns for each good id 0..23 (empty = not produced on the map).
# The trailing comment names the towns for readability.
PRODUCERS: List[List[int]] = [
    [4, 8, 10, 17, 18, 21, 22],       # 0  Grain      Groningen, Hamburg, Rostock, Stettin, Gdansk, Reval, Ladoga
    [2, 11, 13, 14, 18, 19, 23],      # 1  Meat       London, Bergen, Aalborg, Malmo, Gdansk, Torun, Novgorod
    [0, 8, 9, 17, 20, 22],            # 2  Fish       Edinburgh, Hamburg, Luebeck, Stettin, Riga, Ladoga
    [1, 2, 6, 8, 17, 18, 23],         # 3  Beer       Scarborough, London, Bremen, Hamburg, Stettin, Gdansk, Novgorod
    [3, 7, 10, 17, 20, 21],           # 4  Salt       Burges, Ripen, Rostock, Stettin, Riga, Reval
    [5, 10, 16, 19, 20],              # 5  Honey      Cologne, Rostock, Visby, Torun, Riga
    [2, 3, 4, 5, 6, 8],               # 6  Spices     London, Burges, Groningen, Cologne, Bremen, Hamburg (import hubs)
    [3, 5],                           # 7  Wine       Burges, Cologne
    [0, 1, 2, 6, 14, 16],             # 8  Cloth      Edinburgh, Scarborough, London, Bremen, Malmo, Visby
    [20, 21, 22, 23],                 # 9  Skins      Riga, Reval, Ladoga, Novgorod
    [7, 11, 12, 13, 15],              # 10 Oil        Ripen, Bergen, Oslo, Aalborg, Stockholm
    [1, 4, 12, 13, 15, 19, 23],       # 11 Timber     Scarborough, Groningen, Oslo, Aalborg, Stockholm, Torun, Novgorod
    [0, 1, 6, 9, 11, 15, 21],         # 12 Iron Goods Edinburgh, Scarborough, Bremen, Luebeck, Bergen, Stockholm, Reval
    [2, 11, 13, 14, 18, 19, 23],      # 13 Leather    London, Bergen, Aalborg, Malmo, Gdansk, Torun, Novgorod
    [1, 2, 3, 14, 16, 19],            # 14 Wool       Scarborough, London, Burges, Malmo, Visby, Torun
    [9, 11, 12, 18, 20, 23],          # 15 Pitch      Luebeck, Bergen, Oslo, Gdansk, Riga, Novgorod
    [2, 7, 12, 13, 15, 22],           # 16 Pig Iron   London, Ripen, Oslo, Aalborg, Stockholm, Ladoga
    [3, 4, 8, 10, 17, 18, 22],        # 17 Hemp       Burges, Groningen, Hamburg, Rostock, Stettin, Gdansk, Ladoga
    [3, 5, 7, 10, 16, 19],            # 18 Pottery    Burges, Cologne, Ripen, Rostock, Visby, Torun
    [4, 6, 7, 9, 12],                 # 19 Bricks     Groningen, Bremen, Ripen, Luebeck, Oslo
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
