# -*- mode: python ; coding: utf-8 -*-
"""Spec del ejecutable celular (menu hamburguesa) de Respaldos.Gio v6.0.

Se ejecuta con:  python -m PyInstaller Ejecutables\Respaldoscelular6.0\RespaldosCelular.spec
(o mejor:  python Ejecutables\construir_6.0.py)

El entry vive en la raiz del proyecto (fuente unica de verdad) y el icono se
toma de esta misma carpeta, como exige el requerimiento del icono propio.
"""
import os

# Raiz del proyecto: la carpeta de este spec esta en <raiz>/Ejecutables/<carpeta>
RAIZ = os.path.abspath(os.path.join(SPECPATH, os.pardir, os.pardir))

a = Analysis(
    [os.path.join(RAIZ, 'RespaldosMovil.py')],
    pathex=[RAIZ],
    binaries=[],
    datas=[],
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
    name='RespaldosCelular6.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(SPECPATH, 'icono.ico')],
)
