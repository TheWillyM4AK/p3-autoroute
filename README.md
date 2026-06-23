# p3-autoroute (Python port)

A trade route (`.rou`) editor for **Patrician III**: open, create, edit, reorder
and save routes through a local desktop UI. It lets you **reorder stops and goods
by dragging**, apply sorting and pricing presets, and generate full routes from
templates (Day Trader, Seller, Supplier, Sucker, Sucker → Warehouse).

> **Attribution.** This project is a *port* of **Marco Zanella's** original
> **Godot/GDScript** editor (<https://github.com/marco-zanella/p3-autoroute>),
> rewritten in **Python + HTML/CSS/JS**. The `.rou` (de)compression algorithm
> comes from that project; the original decompression credit goes to
> [Benedikt Radtke](https://github.com/Trolldemorted)
> ([p3-lib](https://github.com/P3Modding/p3-lib/blob/master/p3-rou/src/lib.rs)).
> Distributed under **GPLv3** (see [LICENSE](LICENSE)), like the original.

## Architecture

- **Desktop app** (primary mode): a native window with
  [**PyWebView**](https://pywebview.flowrl.com/) (WebView2 on Windows). The Python
  backend is exposed as the **single `js_api` bridge** (no server, no ports). The
  frontend is **vanilla HTML/CSS/JS** with no bundler; theming uses CSS variables.
- **Fallback web mode** (for debugging in a browser): a small `http.server`. The
  frontend detects whether the bridge exists and, if not, falls back to `fetch`.
- Packageable into a single **`.exe`** with PyInstaller.

## Requirements

- **Python 3.9+** (tested with 3.14).
- `pip install -r requirements.txt` → installs **pywebview**. (The fallback web
  mode and the `.rou` format core need no dependencies.)
- On Windows, **WebView2** (preinstalled on Windows 11).

## How to run

```bash
pip install -r requirements.txt
python -m p3autoroute            # native desktop window
python -m p3autoroute --web      # browser fallback (http://127.0.0.1:8765)
```

In the app:

1. Click **Browse…** (native folder picker) or paste the path to your save's
   **`Save\AutoRoute`** folder and click **Open**. You'll see your routes (for
   example `Initial`). The app **remembers the last folder** and reopens it on the
   next launch. The 🌙/☀️ button in the header toggles between light (default)
   and dark theme.
2. Select a route to edit it: drag the **stops** to reorder them, edit each stop
   (town, mode, and per good: mode/price/quantity), drag the **rules** to reorder
   them, apply presets, etc.
3. Click **Save**. The `.rou` file is written in a format the game can read.

Presets (sortings and pricings) and settings are stored as JSON under
`~/.p3autoroute/` (override with the `P3AUTOROUTE_DATA` environment variable).

## Build the `.exe`

```bash
pip install pyinstaller
pyinstaller p3autoroute.spec
# result: dist/p3-autoroute/p3-autoroute.exe
```

> When running an unsigned `.exe`, Windows may show *"Windows protected your
> PC"*: click **More info → Run anyway** (same as with the original editor).

## Tests

```bash
python tests/test_roundtrip.py   # compressor + .rou serialization (round-trip)
python tests/test_server.py      # API + generators + settings
# or, if you have pytest:  pytest
```

## Structure

```
p3autoroute/
├─ goods.py        # 24 goods (names, visibility, sizes)
├─ towns.py        # 24 towns
├─ models.py       # Rule / TradeStop / Route (+ mode enums)
├─ bitstream.py    # BitArray / BitReader (LSB-first reading)
├─ compressor.py   # LZ77 (de)compressor for the .rou format
├─ rou.py          # .rou serialization/reading + RouteRepository
├─ presets.py      # sorting and pricing presets (JSON) + apply
├─ generators.py   # 5 route generators (templates)
├─ settings.py     # persisted settings (e.g. last opened folder)
├─ api.py          # Api class: ALL the logic (js_api bridge and server)
├─ app.py          # native PyWebView window (primary mode)
├─ server.py       # fallback HTTP server (--web mode)
├─ paths.py        # resource/data paths (PyInstaller compatible)
├─ __main__.py     # python -m p3autoroute [--web]
└─ web/            # frontend (index.html, style.css, app.js)
run_app.py         # PyInstaller entry point
p3autoroute.spec   # packaging recipe
tests/             # core and API tests
```

## Port status

**All** of the original editor's functionality is ported: open/close folder,
route CRUD, reorder stops and rules (by dragging), edit town/mode/price/quantity,
bulk actions, sorting and pricing presets (with a "default"), and the **5 route
generators**. Plus a couple of additions: the app **remembers the last folder**
and has a **light/dark theme**. The only intentional difference is that context
menus (right-click) are replaced by always-visible buttons with the same actions
(edit/rename/duplicate/delete).

## `.rou` file format

A route can have up to **20 stops**, each **220 bytes**. The game saves `.rou`
files compressed, but reads both compressed and uncompressed; this editor exports
in the uncompressed format the game accepts.

| Offset | Size | Description |
| -----: | ---: | ----------- |
| 0x00 | 2 | Padding, usually `0` |
| 0x02 | 1 | Town id (see table) |
| 0x03 | 1 | Dock (`0x00`), repair (`0x01`) or skip (`0x09`) |
| 0x04 | 0x18 | **Order** array for the 24 goods (1 byte per good id) |
| 0x1c | 0x60 | **Price** array (24 × int32; >0 sell, <0 buy) |
| 0x7c | 0x60 | **Quantity** array (24 × int32; with price `0`: >0 withdraw, <0 deposit) |

### Town identifiers

| ID | Town | ID | Town |
| ---: | --- | ---: | --- |
| 0x00 | Edinburgh | 0x0c | Oslo |
| 0x01 | Scarborough | 0x0d | Aalborg |
| 0x02 | London | 0x0e | Malmo |
| 0x03 | Burges | 0x0f | Stockholm |
| 0x04 | Groningen | 0x10 | Visby |
| 0x05 | Cologne | 0x11 | Stettin |
| 0x06 | Bremen | 0x12 | Gdansk |
| 0x07 | Ripen | 0x13 | Torun |
| 0x08 | Hamburg | 0x14 | Riga |
| 0x09 | Luebeck | 0x15 | Reval |
| 0x0a | Rostock | 0x16 | Ladoga |
| 0x0b | Bergen | 0x17 | Novgorod |

### Good identifiers and sizes

| ID | Good | Type | Size | ID | Good | Type | Size |
| ---: | --- | --- | ---: | ---: | --- | --- | ---: |
| 0x00 | Grain | bundle | 2000 | 0x0c | Iron Goods | barrel | 200 |
| 0x01 | Meat | bundle | 2000 | 0x0d | Leather | barrel | 200 |
| 0x02 | Fish | bundle | 2000 | 0x0e | Wool | bundle | 2000 |
| 0x03 | Beer | barrel | 200 | 0x0f | Pitch | barrel | 200 |
| 0x04 | Salt | barrel | 200 | 0x10 | Pig Iron | bundle | 2000 |
| 0x05 | Honey | barrel | 200 | 0x11 | Hemp | bundle | 2000 |
| 0x06 | Spices | barrel | 200 | 0x12 | Pottery | barrel | 200 |
| 0x07 | Wine | barrel | 200 | 0x13 | Bricks | bundle | 2000 |
| 0x08 | Cloth | barrel | 200 | 0x14 | Sword | weapon | 10 |
| 0x09 | Skins | barrel | 200 | 0x15 | Bow | weapon | 10 |
| 0x0a | Oil | barrel | 200 | 0x16 | Crossbow | weapon | 10 |
| 0x0b | Timber | bundle | 2000 | 0x17 | Carbine | weapon | 10 |
