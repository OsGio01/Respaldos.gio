#!/usr/bin/env python3
# Prueba de Respaldos.Gio v6.0 (ver Pruebas/README.md)
"""Verifica que los 3 exe lleven el icono HD (pide el tamano 256 al SO)."""

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import ctypes
import ctypes.wintypes as wt

shell32 = ctypes.windll.shell32
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

gdi32.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
gdi32.GetObjectW.restype = ctypes.c_int
user32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.GetIconInfo.restype = wt.BOOL
user32.PrivateExtractIconsW.argtypes = [
    ctypes.c_wchar_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
user32.PrivateExtractIconsW.restype = ctypes.c_uint
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = wt.BOOL


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wt.BOOL),
        ("xHotspot", wt.DWORD),
        ("yHotspot", wt.DWORD),
        ("hbmMask", ctypes.c_void_p),
        ("hbmColor", ctypes.c_void_p),
    ]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wt.LONG),
        ("bmWidth", wt.LONG),
        ("bmHeight", wt.LONG),
        ("bmWidthBytes", wt.LONG),
        ("bmPlanes", wt.WORD),
        ("bmBitsPixel", wt.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


def tamano_real(hicon):
    info = ICONINFO()
    if not user32.GetIconInfo(hicon, ctypes.byref(info)):
        return None
    mejor = 0
    for hb in (info.hbmColor, info.hbmMask):
        if hb:
            bm = BITMAP()
            if gdi32.GetObjectW(hb, ctypes.sizeof(bm), ctypes.byref(bm)):
                mejor = max(mejor, bm.bmWidth, abs(bm.bmHeight))
            gdi32.DeleteObject(hb)
    return mejor


def mejores_tamanos(ruta):
    """Pide varios tamanos al SO y devuelve los que existen de verdad."""
    hallados = set()
    for lado in (256, 128, 64, 48, 32, 24, 16):
        hicon = ctypes.c_void_p()
        nid = ctypes.c_uint()
        n = user32.PrivateExtractIconsW(ruta, 0, lado, lado,
                                         ctypes.byref(hicon), ctypes.byref(nid), 1, 0)
        if n and hicon.value:
            tam = tamano_real(hicon.value)
            if tam:
                hallados.add(tam)
    return sorted(hallados)


from core import constantes

V = constantes.VERSION_PROGRAMA

EXES = [
    os.path.join(RAIZ, "Ejecutables", f"RespaldosInterface{V}", f"Respaldos.Gio{V}.exe"),
    os.path.join(RAIZ, "Ejecutables", f"Respaldosterminal{V}", f"Respaldos.gio-Terminal{V}.exe"),
    os.path.join(RAIZ, "Ejecutables", f"Respaldoscelular{V}", f"RespaldosCelular{V}.exe"),
]

fallos = 0
for ruta in EXES:
    nombre = ruta.split("\\")[-1]
    tams = mejores_tamanos(ruta)
    hd = any(t >= 128 for t in tams)
    print(f"{'OK  ' if hd else 'FAIL'} {nombre}: tamanos reales {tams}")
    if not hd:
        fallos += 1

print("RESULTADO:", "TODOS OK" if not fallos else "HAY FALLOS")
raise SystemExit(1 if fallos else 0)
