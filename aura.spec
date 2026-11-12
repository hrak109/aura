# -*- mode: python ; coding: utf-8 -*-
# Aura Home Security Matrix — PyInstaller Spec
# Produces a single standalone Windows .exe with all dependencies bundled.

import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

# ── Collect everything needed for wyze_sdk, fastapi, uvicorn, jinja2 ──────────
datas = [
    ('templates', 'templates'),
    ('aura.ico', '.')
]
binaries = []
hiddenimports = []

# wyze_sdk — has internal JSON/YAML data files that must be bundled
wdatas, wbins, wimports = collect_all('wyze_sdk')
datas    += wdatas
binaries += wbins
hiddenimports += wimports

# fastapi & starlette
hiddenimports += collect_submodules('fastapi')
hiddenimports += collect_submodules('starlette')

# uvicorn (including its lifespan & workers)
hiddenimports += collect_submodules('uvicorn')

# jinja2
hiddenimports += collect_submodules('jinja2')
datas += collect_data_files('jinja2')

# tkinter (required for the GUI control panel)
hiddenimports += [
    'tkinter',
    'tkinter.messagebox',
    'tkinter.ttk',
    'tkinter.scrolledtext',
    '_tkinter',
]

# cryptography (used by wyze_sdk internally)
hiddenimports += collect_submodules('cryptography')

# httpx (used by wyze_sdk)
hiddenimports += collect_submodules('httpx')

# Additional hidden imports that PyInstaller commonly misses
hiddenimports += [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'uvicorn.supervisors',
    'asyncio',
    'email.mime.multipart',
    'email.mime.text',
    'multipart',
    'python_multipart',
    'urllib3',
    'requests',
    'ssl',
    'zipfile',
    'io',
    'socket',
    'threading',
    'signal',
    'webbrowser',
]

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'PIL',
        'cv2',
        'test',
        'unittest',
    ],
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
    name='Aura',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # Disabled to prevent aggressive Antivirus quarantines
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,         # No CMD window — GUI launcher takes over
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='aura.ico',
)
