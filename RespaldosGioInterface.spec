# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\\\Proyectos\\\\Respaldos. gio\\\\Respaldos.gio-1\\\\Ejecutables\\\\RespaldosInterface6.0\\\\RespaldosTkinter.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['core', 'core.constantes', 'core.utilidades', 'core.persistencia', 'core.configuracion', 'core.estados', 'core.seguridad', 'core.escaneo', 'core.progreso', 'core.motor', 'core.fuentes', 'core.red', 'fronts', 'fronts.terminal', 'fronts.hud', 'fronts.movil'],
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
    [],
    exclude_binaries=True,
    name='RespaldosGioInterface',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RespaldosGioInterface',
)
