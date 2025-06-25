# -*- mode: python ; coding: utf-8 -*-

# based on https://github.com/DasAmpharos/EonTimer/blob/main/EonTimer.spec

import os


datas = [
]


a = Analysis(
    ['SpotiDownloader.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SpotiDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    codesign_identity=None,
    entitlements_file=None,
    #icon='eon_timer/resources/icon-512.png'
)
app = BUNDLE(
    exe,
    name='SpotiDownloader.app',
    #icon='eon_timer/resources/icon-512.png',
    bundle_identifier=None,
)
