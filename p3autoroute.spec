# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec to build the desktop .exe.
#   pip install pyinstaller
#   pyinstaller p3autoroute.spec
# The executable ends up at dist/p3-autoroute/p3-autoroute.exe
from PyInstaller.utils.hooks import collect_all

datas = [("p3autoroute/web", "p3autoroute/web")]
binaries = []
hiddenimports = ["clr"]

# PyWebView (WebView2) and its .NET bridge pull in submodules/binaries that must
# be collected explicitly.
for pkg in ("webview", "clr_loader", "proxy_tools", "bottle"):
    d, b, hi = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += hi

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="p3-autoroute",
    debug=False,
    strip=False,
    upx=True,
    console=False,  # GUI app: no console window
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="p3-autoroute",
)
