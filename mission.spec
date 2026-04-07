# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['agentforce/cli/cli.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'yaml',
        'agentforce.core.engine',
        'agentforce.core.spec',
        'agentforce.core.state',
        'agentforce.memory.memory',
        'agentforce.telemetry',
    ],
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
    name='mission',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
