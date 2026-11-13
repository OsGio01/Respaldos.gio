# -*- mode: python ; coding: utf-8 -*-
"""Spec del ejecutable celular de Respaldos.Gio - PLANTILLA, no se construye.

Este front ya NO se distribuye como producto: es la base desde la que se
planea la app nativa de Android e iOS (ver docs/MOVIL.md).

Motivo: un .exe de Windows con forma de telefono no es una app movil. En
Android no hay tkinter y el almacenamiento del usuario vive en /sdcard con
permisos propios; en iOS no hay Python con tkinter ni acceso al sistema de
archivos. Por eso elEjecutable de celular quedo como plantilla.

Se conserva el spec porque:
  1) sirve de referencia de como empaquetar el front movil si alguna vez se
     necesita un binario de escritorio con esa ventana,
  2) el front sigue siendo util para PROBAR el diseno en Windows.

Para construirlo a mano:
  python -m PyInstaller Ejecutables\\Respaldoscelular6.2\\RespaldosCelular.spec
"""
import os
import re
import sys

# Raiz del proyecto: este spec vive en <raiz>/Ejecutables/
RAIZ = os.path.abspath(os.path.join(SPECPATH, os.pardir))
IMG = os.path.join(RAIZ, "IMG")


def _version():
    """Lee la version del nucleo (fuente unica de verdad)."""
    with open(os.path.join(RAIZ, "core", "constantes.py"), encoding="utf-8") as f:
        m = re.search(r'VERSION_PROGRAMA\s*=\s*"([^"]+)"', f.read())
    return m.group(1) if m else "0.0"


VERSION = _version()


def _icono():
    if sys.platform == "darwin":
        icns = os.path.join(IMG, "icono.icns")
        if not os.path.exists(icns):
            try:
                from PIL import Image
                Image.open(os.path.join(IMG, "icono.png")).save(
                    icns, format="ICNS",
                    sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256)])
            except Exception:
                return None
        return icns
    if sys.platform == "win32":
        return os.path.join(IMG, "icono.ico")
    return os.path.join(IMG, "icono.png")


ICONO = _icono()

DATAS = [(os.path.join(IMG, n), "IMG") for n in os.listdir(IMG)
         if n.endswith((".png", ".ico"))]

a = Analysis(
    [os.path.join(RAIZ, 'RespaldosMovil.py')],
    pathex=[RAIZ],
    binaries=[],
    datas=DATAS,
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
    name=f'RespaldosCelular{VERSION}',
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
    icon=[ICONO] if ICONO else [],
)
