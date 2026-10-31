# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the single-file desktop build.
# Build (after `npm run build` in frontend/):
#   pip install -r requirements.txt pyinstaller
#   pyinstaller datacenter-twin.spec
# Output: dist/RenewableDataCenter.exe (Windows)
#         dist/RenewableDataCenter.app (macOS)

import sys

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
icon_path = "assets/logo.icns" if sys.platform == "darwin" else "assets/logo.ico"

datas = [
    ("frontend/dist", "frontend/dist"),
    ("config", "config"),
    ("data", "data"),
]
# Bundle certifi's CA bundle so requests' HTTPS calls (Open-Meteo, Nominatim)
# work in the frozen exe on a clean machine.
datas += collect_data_files("certifi")

hiddenimports = [
    "requests",
    "certifi",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "backend.twin.location_scorer",
]

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="RenewableDataCenter",
    icon=icon_path,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,   # UPX compression is a common antivirus/SmartScreen false-positive trigger
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # console doubles as the status/stop window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="RenewableDataCenter.app",
        icon=icon_path,
        bundle_identifier="group.seibert.renewable-datacenter",
        info_plist={
            "CFBundleName": "Renewable Data Center",
            "CFBundleDisplayName": "Renewable Data Center",
            "CFBundleShortVersionString": "2.0.0",
            "CFBundleVersion": "2.0.0",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
        },
    )
