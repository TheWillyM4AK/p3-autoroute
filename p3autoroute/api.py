"""Single editor API — used by the js_api bridge (PyWebView) and by the
fallback web server. Each method receives a `params` dict (possibly empty) and
returns a JSON-serializable object.

Method names map 1:1 to the frontend routes:
    /api/route/load  ->  route_load
    /api/pricings    ->  pricings
"""
from __future__ import annotations

import os

from . import generators, goods, production, settings, towns
from .models import Route, RuleMode, StopMode, TradeStop, default_rules
from .presets import (
    DEFAULT_BUYING, DEFAULT_SELLING,
    Pricing, PricingStore, Sorting, SortingStore, apply_pricing, apply_sorting,
)
from .rou import RouteRepository


class Api:
    def __init__(self, window=None):
        # `window` is set in desktop mode (PyWebView) for the native folder
        # picker; in web mode it stays None. The name MUST start with an
        # underscore: PyWebView's js_api bridge recursively introspects every
        # *public* attribute of this instance to expose it to the frontend, and
        # the native Window object graph is cyclic (its .NET WinForms `Bounds`
        # value-types return a fresh object on each access, defeating pywebview's
        # id()-based cycle guard), which crashes the bridge with "maximum
        # recursion depth exceeded". A leading underscore makes pywebview skip it.
        self._window = window

    # --------------------------------------------------------------- meta
    def meta(self, params=None) -> dict:
        return {
            "goods": {"names": goods.NAMES, "visibility": goods.VISIBILITY,
                      "sizes": goods.SIZES, "icons": goods.ICONS,
                      "count": goods.COUNT},
            "defaultPricing": {"buying": list(DEFAULT_BUYING),
                               "selling": list(DEFAULT_SELLING)},
            "towns": {"names": towns.NAMES, "count": towns.COUNT},
            "production": {"producers": production.PRODUCERS,
                           "consumable": production.CONSUMABLE},
            "ruleModes": [m.name for m in RuleMode],
            "stopModes": [m.name for m in StopMode],
            "maxStops": generators.MAX_STOPS,
        }

    def settings(self, params=None) -> dict:
        """Persisted app settings (e.g. last opened folder)."""
        return settings.load()

    # --------------------------------------------------------------- captains
    def captains_locate(self, params=None) -> dict:
        """Which towns currently have a hireable captain (reads live game RAM)."""
        from . import captains
        return captains.locate()

    # --------------------------------------------------------------- folder
    def pick_folder(self, params=None) -> dict:
        """Open the native folder picker (desktop mode only)."""
        if self._window is None:
            return {"ok": False, "error": "The native picker is only available in the desktop app"}
        import webview
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return {"ok": False, "error": "cancelled"}
        path = result[0] if isinstance(result, (list, tuple)) else result
        settings.set("last_folder", path)
        return {"ok": True, "path": path, "names": RouteRepository(path).list_names()}

    def folder_open(self, params: dict) -> dict:
        path = params["path"]
        if not os.path.isdir(path):
            return {"ok": False, "error": f"Not a folder: {path}"}
        settings.set("last_folder", path)
        return {"ok": True, "names": RouteRepository(path).list_names()}

    # --------------------------------------------------------------- routes
    def route_load(self, params: dict) -> dict:
        route = RouteRepository(params["path"]).read(params["name"])
        return {"ok": True, "route": route.to_dict()}

    def route_save(self, params: dict) -> dict:
        RouteRepository(params["path"]).create(Route.from_dict(params["route"]))
        return {"ok": True}

    def route_create(self, params: dict) -> dict:
        route = Route(name=params["name"], trade_stops=[])
        RouteRepository(params["path"]).create(route)
        return {"ok": True, "route": route.to_dict()}

    def route_delete(self, params: dict) -> dict:
        RouteRepository(params["path"]).delete(params["name"])
        return {"ok": True}

    def route_rename(self, params: dict) -> dict:
        repo = RouteRepository(params["path"])
        route = repo.read(params["old"])
        repo.delete(params["old"])
        route.name = params["new"]
        repo.create(route)
        return {"ok": True}

    def route_duplicate(self, params: dict) -> dict:
        repo = RouteRepository(params["path"])
        route = repo.read(params["name"])
        route.name = params["new"]
        repo.create(route)
        return {"ok": True, "route": route.to_dict()}

    # --------------------------------------------------------------- stops
    def stop_new(self, params: dict) -> dict:
        sorting = SortingStore().get_default()
        rules = default_rules()
        if sorting is not None:
            order = sorting.goods
            rules.sort(key=lambda r: order.index(int(r.good)))
        stop = TradeStop(town=params.get("town", 0), mode=StopMode.DOCK, rules=rules)
        return {"ok": True, "stop": stop.to_dict()}

    def stop_apply_pricing(self, params: dict) -> dict:
        stop = TradeStop.from_dict(params["stop"])
        apply_pricing(stop, Pricing.from_dict(params["pricing"]))
        return {"ok": True, "stop": stop.to_dict()}

    def stop_apply_sorting(self, params: dict) -> dict:
        stop = TradeStop.from_dict(params["stop"])
        apply_sorting(stop, list(params["order"]))
        return {"ok": True, "stop": stop.to_dict()}

    # --------------------------------------------------------------- generate
    def generate(self, params: dict) -> dict:
        kind = params["kind"]
        if kind == "sucker_to_warehouse":
            stops = generators.sucker_to_warehouse(
                params["first_town"], params["second_town"],
                params["first_goods"], params["second_goods"])
        elif kind == "sucker":
            stops = generators.sucker(params["town"], params["maximum_goods"], params["goods"])
        else:
            stops = generators.GENERATORS[kind](params["town"], params["goods"])
        return {"ok": True, "stops": [s.to_dict() for s in stops]}

    # --------------------------------------------------------------- pricings
    def pricings(self, params=None) -> list:
        return [p.to_dict() for p in PricingStore().items]

    def pricings_save(self, params: dict) -> dict:
        PricingStore().upsert(Pricing.from_dict(params["pricing"]))
        return {"ok": True}

    def pricings_delete(self, params: dict) -> dict:
        PricingStore().delete(params["id"])
        return {"ok": True}

    def pricings_setdefault(self, params: dict) -> dict:
        PricingStore().set_default(params["id"])
        return {"ok": True}

    def pricings_rename(self, params: dict) -> dict:
        PricingStore().rename(params["old"], params["new"])
        return {"ok": True}

    # --------------------------------------------------------------- sortings
    def sortings(self, params=None) -> list:
        return [s.to_dict() for s in SortingStore().items]

    def sortings_save(self, params: dict) -> dict:
        SortingStore().upsert(Sorting.from_dict(params["sorting"]))
        return {"ok": True}

    def sortings_delete(self, params: dict) -> dict:
        SortingStore().delete(params["id"])
        return {"ok": True}

    def sortings_setdefault(self, params: dict) -> dict:
        SortingStore().set_default(params["id"])
        return {"ok": True}

    def sortings_rename(self, params: dict) -> dict:
        SortingStore().rename(params["old"], params["new"])
        return {"ok": True}


# Methods exposed by name (for the web server dispatch).
PUBLIC_METHODS = [
    "meta", "settings", "captains_locate", "pick_folder", "folder_open",
    "route_load", "route_save", "route_create", "route_delete",
    "route_rename", "route_duplicate",
    "stop_new", "stop_apply_pricing", "stop_apply_sorting", "generate",
    "pricings", "pricings_save", "pricings_delete", "pricings_setdefault", "pricings_rename",
    "sortings", "sortings_save", "sortings_delete", "sortings_setdefault", "sortings_rename",
]
