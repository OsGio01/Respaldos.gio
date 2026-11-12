# Prueba de Respaldos.Gio v6.2 (ver Pruebas/README.md)

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import subprocess, time, ctypes, sys, os

proyecto = RAIZ
proc = subprocess.Popen([sys.executable, "main.py"], cwd=proyecto,
                        env={**os.environ, "PYTHONPATH": proyecto},
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
pid = proc.pid
user32 = ctypes.windll.user32
EnumWindows = user32.EnumWindows
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowTextLengthW = user32.GetWindowTextLengthW
GetWindowTextW = user32.GetWindowTextW
IsWindowVisible = user32.IsWindowVisible
GetWindowRect = user32.GetWindowRect
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

hwnd_hallado = None

def buscar(hwnd, lParam):
    global hwnd_hallado
    wpid = ctypes.c_ulong(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
    if wpid.value != pid or not IsWindowVisible(hwnd):
        return True
    n = GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    GetWindowTextW(hwnd, buf, n + 1)
    if buf.value.strip() == "Respaldos.Gio":
        hwnd_hallado = hwnd
        return False
    return True

cb = CB(buscar)
for i in range(25):
    time.sleep(0.4)
    EnumWindows(cb, 0)
    if hwnd_hallado:
        break

if hwnd_hallado:
    r = ctypes.wintypes_RECT() if hasattr(ctypes, "wintypes") else None
    import ctypes.wintypes as wt
    rect = wt.RECT()
    GetWindowRect(hwnd_hallado, ctypes.byref(rect))
    ancho = rect.right - rect.left
    alto = rect.bottom - rect.top
    print("VENTANA OK: Respaldos.Gio")
    print(f"TAMANO: {ancho} x {alto}")
    print("ES_DE_ESCRITORIO:", ancho >= 960 and alto >= 620)
else:
    print("VENTANA NO ENCONTRADA")

time.sleep(1)
proc.terminate()
try:
    out, err = proc.communicate(timeout=10)
except Exception:
    proc.kill()
    out, err = b"", b""
if err:
    print("STDERR:", err.decode("utf-8", "replace")[-1500:])
print("EXITO:", bool(hwnd_hallado))
