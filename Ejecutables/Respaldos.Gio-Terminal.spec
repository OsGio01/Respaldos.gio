# -*- mode: python ; coding: utf-8 -*-
"""Spec del ejecutable de terminal de Respaldos.Gio.

Se ejecuta con:  python -m PyInstaller Ejecutables\\Respaldosterminal6.2\\Respaldos.Gio-Terminal.spec
(o mejor:  python Ejecutables\\construir.py)

El entry vive en la raiz del proyecto (fuente unica de verdad). El icono y los
recursos se ajustan al sistema donde se compila (Windows: .ico y .exe;
Linux: .png; macOS: .icns), asi que el mismo spec sirve para los tres SO.
"""
import os
import re
import sys

# Raiz del proyecto: este spec vive en <raiz>/Ejecutables/
RAIZ = os.path.abspath(os.path.join(SPECPATH, os.pardir))
IMG = os.path.join(RAIZ, "IMG")


def _version():
    """Lee la version del nucleo (fuente unica de la verdad)."""
    with open(os.path.join(RAIZ, "core", "constantes.py"), encoding="utf-8") as f:
        m = re.search(r'VERSION_PROGRAMA\s*=\s*"([^"]+)"', f.read())
    return m.group(1) if m else "0.0"


VERSION = _version()


def _icono():
    """Icono segun el sistema donde se compila."""
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
    [os.path.join(RAIZ, 'Respaldos.py')],
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
    name=f'Respaldos.gio-Terminal{VERSION}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[ICONO] if ICONO else [],
)
