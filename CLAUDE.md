# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A desktop editor for Patrician III trade-route (`.rou`) files. It is a **port of
Marco Zanella's Godot/GDScript editor** to Python + vanilla HTML/CSS/JS. Most
Python modules carry a docstring naming the original `.gd` file they port
(e.g. `compressor.py` ports `scripts/helper/Compressor.gd`). Byte-for-byte
compatibility with the game's `.rou` format is a hard constraint — see the
"Binary format" section before touching the (de)serialization path.

## Commands

```bash
pip install -r requirements.txt   # installs pywebview (only runtime dep)

python -m p3autoroute              # native desktop window (primary mode)
python -m p3autoroute --web        # browser fallback at http://127.0.0.1:8765

python tests/test_roundtrip.py     # core: compressor + .rou round-trip
python tests/test_server.py        # API + generators + HTTP server
pytest                             # both, if pytest is installed

pyinstaller p3autoroute.spec       # build dist/p3-autoroute/p3-autoroute.exe
```

Single test: `pytest tests/test_roundtrip.py::test_empty_route`. The custom
runners in the test files (`python tests/test_*.py`) run the whole file and need
no dependencies — the core is standard-library only; only the desktop window
needs `pywebview`.

## Architecture

### One `Api` class, two transports

[`api.py`](p3autoroute/api.py) holds **all** backend logic in a single `Api`
class. It is served two ways from the same instance shape:

- **Desktop (primary):** [`app.py`](p3autoroute/app.py) creates a PyWebView
  window with `js_api=Api()`. The frontend calls
  `window.pywebview.api.<method>(params)` — no HTTP, no port.
- **Web (fallback, for browser debugging):** [`server.py`](p3autoroute/server.py)
  is a stdlib `http.server` that dispatches `POST /api/<path>` to the same `Api`
  methods.

The frontend ([`web/app.js`](p3autoroute/web/app.js)) detects whether the bridge
exists and otherwise falls back to `fetch`. Both paths translate a route to a
method name by `path.replace("/api/", "").replaceAll("/", "_")`, so
`/api/route/load` → `route_load`.

**Adding an endpoint requires three edits in lockstep:** add the method to
`Api`, add its name to `PUBLIC_METHODS` in `api.py` (the web server's allowlist —
methods missing from it return 404 in web mode but still work over the bridge,
an easy-to-miss asymmetry), and call it from the frontend via `api("/api/...")`.

### Binary format pipeline (`.rou` read/write)

The serialization stack must reproduce the game's bytes exactly:

- [`bitstream.py`](p3autoroute/bitstream.py) — `BitArray`/`BitReader`, **LSB-first**
  bit packing. The ordering is load-bearing for compatibility.
- [`compressor.py`](p3autoroute/compressor.py) — `encode` always emits the
  *uncompressed* framing (each byte preceded by a `0` bit); `decode` handles both
  literals and LZ77 back-references (the game saves compressed, reads either).
  The lookup tables are transcribed verbatim from upstream, **including the typo
  `BITMASK_TABLE_2[13] = 0x1ff`** — do not "fix" it; it preserves byte
  compatibility and never triggers for real route files.
- [`rou.py`](p3autoroute/rou.py) — `serialize_route` / `parse_route` map between
  `Route` objects and `.rou` bytes (each stop is 220 bytes), plus
  `RouteRepository` for CRUD over a folder of `.rou` files. The full byte layout
  and the town/good id tables are documented in [README.md](README.md).

Round-trip correctness is the main thing tests guard; `test_roundtrip.py` is the
canonical regression check after any change here.

### Domain model and ordering semantics

[`models.py`](p3autoroute/models.py): a `Route` has `TradeStop`s; each stop has
**exactly 24 `Rule`s, one per good, and their order within the stop is
significant** — it is written to the `.rou` "order" array, while prices and
quantities are indexed by good id. Key encoding rules (in `rou.py`):

- `Rule.quantity == -1` is the "maximum" sentinel, stored as `MAX_AMOUNT`
  (1e9). Otherwise on-disk quantity is `quantity * goods.SIZES[good]` (each good
  has a load size of 200/2000/10 — see [`goods.py`](p3autoroute/goods.py)).
- A rule's `RuleMode` (BUY/SELL/WITHDRAW/DEPOSIT/NONE) is reconstructed on read
  from the sign of price/quantity, not stored directly.

### Generators and presets

- [`generators.py`](p3autoroute/generators.py) — the 5 route templates
  (`day_trader`, `seller`, `supplier`, `sucker`, `sucker_to_warehouse`),
  registered in the `GENERATORS` dict and dispatched by `Api.generate`. Each
  produces a list of `TradeStop`; the first is always a `SKIP` at `town+1` to
  suppress in-game notifications.
- [`presets.py`](p3autoroute/presets.py) — Sorting (a 24-good permutation) and
  Pricing (buy/sell price per good) presets, persisted as JSON via a shared
  `_Store`. Seeds are written only when the user has none of their own.

### Persistence and paths

User data (presets, `settings.json` with the last-opened folder) lives in
`~/.p3autoroute/`, overridable via the `P3AUTOROUTE_DATA` env var.
[`paths.py`](p3autoroute/paths.py) resolves both the data dir and the bundled
`web/` dir, and is **PyInstaller-frozen aware** (checks `sys.frozen` / `_MEIPASS`);
keep that branch working when changing how resources are located.

## Conventions

- License is **GPLv3** (inherited from the original); keep attribution intact.
- The frontend is intentionally dependency-free vanilla JS with a tiny `h()`
  DOM helper — no build step, no framework. Theming is via CSS variables.

## Git / GitHub

This is a fork: `origin` is `TheWillyM4AK/p3-autoroute` (where PRs go), and
there is an `upstream` remote pointing at the parent `marco-zanella/p3-autoroute`.
Because of `upstream`, `gh` resolves the **parent** repo by default, so PR/issue
commands silently target the wrong repo (the symptom is `gh pr create` failing
with "No commits between main and …"). **Always pass `--repo
TheWillyM4AK/p3-autoroute` to every `gh` command** (`gh pr create`, `gh pr view`,
`gh issue …`, etc.) so it acts on the fork.
