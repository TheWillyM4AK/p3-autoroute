"""Integration tests for the server, the API, and the generators.

Run:  python tests/test_server.py
"""
import json
import os
import sys
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from p3autoroute import generators, goods, production, rou, server, towns  # noqa: E402
from p3autoroute.api import Api  # noqa: E402
from p3autoroute.models import Route  # noqa: E402


def _good_data(enabled_ids):
    return [{"good": g, "enabled": g in enabled_ids,
             "quantity": 5, "buying_price": 100, "selling_price": 120}
            for g in range(goods.COUNT)]


def test_generators_shapes_and_serialize():
    data = _good_data({0, 3, 8})
    routes = {
        "day_trader": generators.day_trader(9, data),
        "seller": generators.seller(9, data),
        "supplier": generators.supplier(9, data),
        "sucker": generators.sucker(9, 3, data),
    }
    for kind, stops in routes.items():
        assert len(stops) == generators.MAX_STOPS, kind
        for s in stops:
            assert len(s.rules) == 24, kind
        # Must serialize and parse back without breaking.
        r = Route(kind, stops)
        back = rou.parse_route(rou.serialize_route(r), kind)
        assert len(back.trade_stops) == generators.MAX_STOPS, kind

    s2w = generators.sucker_to_warehouse(9, 14, data, _good_data({1, 2}))
    assert len(s2w) == 7
    back = rou.parse_route(rou.serialize_route(Route("s2w", s2w)), "s2w")
    assert len(back.trade_stops) == 7


def test_route_repo_roundtrip():
    d = tempfile.mkdtemp()
    repo = rou.RouteRepository(d)
    stops = generators.day_trader(2, _good_data({0, 1, 2, 7}))
    repo.create(Route("Initial", stops))
    assert "Initial" in repo.list_names()
    loaded = repo.read("Initial")
    assert len(loaded.trade_stops) == generators.MAX_STOPS
    assert os.path.exists(os.path.join(d, "Initial.rou"))


def test_api_settings_remembers_last_folder():
    folder = tempfile.mkdtemp()
    api = Api()
    res = api.folder_open({"path": folder})
    assert res["ok"]
    # A new Api/store instance should read the persisted last_folder.
    assert Api().settings({}).get("last_folder") == folder


def _http_get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def _http_post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())


def test_http_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        status, body = _http_get(base + "/")
        assert status == 200 and b"<title" in body

        status, meta = _http_post(base + "/api/folder/open", {"path": tempfile.mkdtemp()})
        assert meta["ok"] and meta["names"] == []

        status, gen = _http_post(base + "/api/generate", {
            "kind": "supplier", "town": 5, "goods": _good_data({4, 5, 6})})
        assert gen["ok"] and len(gen["stops"]) == generators.MAX_STOPS

        status, m = _http_get(base + "/api/meta")
        meta = json.loads(m)
        assert meta["goods"]["count"] == 24 and len(meta["towns"]["names"]) == 24
        assert len(meta["goods"]["icons"]) == 24
        assert len(meta["production"]["producers"]) == 24
        assert len(meta["production"]["consumable"]) == 24

        # The icon files must actually be served (and as PNG).
        first_icon = next(p for p in meta["goods"]["icons"] if p)
        status, body = _http_get(base + "/" + first_icon)
        assert status == 200 and body[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        httpd.shutdown()


def test_production_data_integrity():
    # One producer list per good, all town ids valid; the 4 weapons have none.
    assert len(production.PRODUCERS) == goods.COUNT
    assert len(production.CONSUMABLE) == goods.COUNT
    for gid, prod in enumerate(production.PRODUCERS):
        assert len(set(prod)) == len(prod), f"duplicate town in good {gid}"
        for t in prod:
            assert 0 <= t < towns.COUNT, f"bad town id {t} in good {gid}"
        if gid in (20, 21, 22, 23):  # weapons
            assert prod == [] and not production.CONSUMABLE[gid]
        else:
            assert prod, f"good {goods.NAMES[gid]} has no producers"
            assert production.CONSUMABLE[gid]


def test_production_buy_sell_model():
    # A producing town is a BUY candidate and never also a SELL candidate;
    # a consumable good not produced locally is a SELL candidate.
    grain = int(goods.Good.GRAIN)
    for gid in range(goods.COUNT):
        for t in range(towns.COUNT):
            if production.produces(t, gid):
                assert not production.demands(t, gid)
            elif production.CONSUMABLE[gid]:
                assert production.demands(t, gid)
            else:
                assert not production.demands(t, gid)
    # Spot check: Grain is produced in Hamburg (8) and demanded in Cologne (5).
    assert production.produces(8, grain) and production.demands(5, grain)


def test_good_icons_exist_on_disk():
    from p3autoroute.paths import web_dir
    web = web_dir()
    # One icon per non-weapon good (the 4 weapons have no trade-good symbol).
    assert len(goods.ICONS) == goods.COUNT
    for gid, rel in enumerate(goods.ICONS):
        if goods.VISIBILITY[gid]:
            assert rel, f"visible good {goods.NAMES[gid]} has no icon"
            full = os.path.join(web, rel.replace("/", os.sep))
            with open(full, "rb") as fh:
                assert fh.read(8) == b"\x89PNG\r\n\x1a\n", rel
        else:
            assert rel == "", f"weapon {goods.NAMES[gid]} should have no icon"


def _run():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests OK")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
