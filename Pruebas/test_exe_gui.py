# Prueba de Respaldos.Gio v6.2 (ver Pruebas/README.md)

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import subprocess, time, ctypes, sys, os
import ctypes.wintypes as wt

from core import constantes

V = constantes.VERSION_PROGRAMA
exe = os.path.join(RAIZ, "Ejecutables", f"RespaldosInterface{V}", f"Respaldos.Gio{V}.exe")
cwd = os.path.dirname(exe)
TITULO = "Respaldos.Gio"

user32 = ctypes.windll.user32
EnumWindows = user32.EnumWindows
GetWindowTextLengthW = user32.GetWindowTextLengthW
GetWindowTextW = user32.GetWindowTextW
IsWindowVisible = user32.IsWindowVisible
GetWindowRect = user32.GetWindowRect
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)


def ventanas(titulo):
    """Todas las ventanas visibles con ese titulo."""
    halladas = []

    def cb(hwnd, lParam):
        if not IsWindowVisible(hwnd):
            return True
        n = GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        GetWindowTextW(hwnd, buf, n + 1)
        if buf.value.strip() == titulo:
            halladas.append(hwnd)
        return True

    EnumWindows(CB(cb), 0)
    return halladas


antes = set(ventanas(TITULO))
print("ventanas previas:", len(antes))

proc = subprocess.Popen([exe], cwd=cwd)

hwnd = None
for i in range(60):  # hasta 30 s
    time.sleep(0.5)
    nuevas = [h for h in ventanas(TITULO) if h not in antes]
    if nuevas:
        hwnd = nuevas[0]
        print(f"[{i*0.5:.1f}s] ventana encontrada")
        break
    if proc.poll() is not None and i > 6:
        break

fallos = []


def comprobar(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        fallos.append(msg)


comprobar(bool(hwnd), "la ventana 'Respaldos.Gio' abre")

if hwnd:
    # la ventana tarda en aplicar su geometria final: esperar a que estabilice
    ancho, alto = 0, 0
    for _ in range(20):
        time.sleep(0.5)
        rect = wt.RECT()
        GetWindowRect(hwnd, ctypes.byref(rect))
        ancho, alto = rect.right - rect.left, rect.bottom - rect.top
        if ancho >= 960 and alto >= 620:
            break
    print(f"     TAMANO: {ancho} x {alto}")
    comprobar(ancho >= 960 and alto >= 620, "es de tamano escritorio")
    time.sleep(1.0)  # deja que termine de pintar
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE -> cierre limpio

try:
    proc.wait(timeout=25)
    comprobar(proc.returncode == 0, f"cierra limpio (codigo {proc.returncode})")
except subprocess.TimeoutExpired:
    proc.kill()
    comprobar(False, "cierra limpio (tuvo que matarse)")

# --- icono embebido en el exe -------------------------------------------
try:
    gdi32 = ctypes.windll.gdi32
    shell32 = ctypes.windll.shell32
    shell32.ExtractIconExW.argtypes = [ctypes.c_wchar_p, ctypes.c_int,
                                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    shell32.ExtractIconExW.restype = ctypes.c_uint
    grande = ctypes.c_void_p()
    n = shell32.ExtractIconExW(exe, 0, ctypes.byref(grande), None, 1)
    comprobar(bool(n) and bool(grande.value), f"el exe tiene icono propio ({n})")
    if grande.value:
        class BITMAP(ctypes.Structure):
            _fields_ = [("bmType", wt.LONG), ("bmWidth", wt.LONG),
                        ("bmHeight", wt.LONG), ("bmWidthBytes", wt.LONG),
                        ("bmPlanes", wt.WORD), ("bmBitsPixel", wt.WORD),
                        ("bmBits", ctypes.c_void_p)]
        class ICONINFO(ctypes.Structure):
            _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD),
                        ("yHotspot", wt.DWORD), ("hbmMask", ctypes.c_void_p),
                        ("hbmColor", ctypes.c_void_p)]
        # tipos explicitos: sin ellos ctypes trunca los punteros
        gdi32.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        gdi32.GetObjectW.restype = ctypes.c_int
        user32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.GetIconInfo.restype = wt.BOOL
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        ii = ICONINFO()
        if user32.GetIconInfo(grande.value, ctypes.byref(ii)):
            bmp = ii.hbmColor or ii.hbmMask
            bm = BITMAP()
            gdi32.GetObjectW(bmp, ctypes.sizeof(bm), ctypes.byref(bm))
            print(f"     ICONO: {bm.bmWidth} x {bm.bmHeight}")
            comprobar(bm.bmWidth >= 32, f"resolucion del icono ({bm.bmWidth}px)")
            gdi32.DeleteObject(bmp)
        user32.DestroyIcon(grande.value)
except Exception as e:
    print("     (aviso icono):", e)
    comprobar(False, f"lectura del icono ({e})")

print()
print("FALLOS:", len(fallos))
print("RESULTADO:", "TODOS OK" if not fallos else "HAY FALLOS")
sys.exit(0 if not fallos else 1)
