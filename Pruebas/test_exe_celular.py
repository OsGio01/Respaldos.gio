#!/usr/bin/env python3
# Prueba de Respaldos.Gio v6.2 (ver Pruebas/README.md)
"""Prueba el exe celular: abre ventana tipo telefono y cierra limpio."""

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import subprocess
import sys
import time
import ctypes
import ctypes.wintypes as wt

from core import constantes

V = constantes.VERSION_PROGRAMA
exe = os.path.join(RAIZ, "Ejecutables", "windows", f"RespaldosCelular{V}.exe")
cwd = os.path.dirname(exe)

# El front celular quedo como PLANTILLA para la app nativa de Android/iOS:
# ya no se compila ni se distribuye (ver docs/MOVIL.md). Si alguien lo
# construye a mano, la prueba sigue sirviendo.
if not os.path.exists(exe):
    print("SKIP el ejecutable celular no se construye (quedo como plantilla)")
    print("OK   EXE CELULAR (omitido)")
    sys.exit(0)

user32 = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)


def ventanas(titulo):
    halladas = []

    def cb(hwnd, lParam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value.strip() == titulo:
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            halladas.append((hwnd, r.right - r.left, r.bottom - r.top))
        return True

    user32.EnumWindows(CB(cb), 0)
    return halladas


antes = set(h for h, _w, _h in ventanas("Respaldos.Gio"))
print("ventanas previas:", len(antes))

proc = subprocess.Popen([exe], cwd=cwd)

hwnd = None
ancho = alto = 0
for i in range(60):
    time.sleep(0.5)
    nuevas = [v for v in ventanas("Respaldos.Gio") if v[0] not in antes]
    if nuevas:
        hwnd, ancho, alto = nuevas[0]
        print(f"[{i*0.5:.1f}s] ventana encontrada {ancho}x{alto}")
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
    # esperar a que estabilice su geometria celular
    for _ in range(20):
        time.sleep(0.5)
        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        ancho, alto = r.right - r.left, r.bottom - r.top
        if 380 <= ancho <= 520 and 600 <= alto <= 860:
            break
    print(f"     TAMANO: {ancho} x {alto}")
    comprobar(380 <= ancho <= 520, f"ancho celular ({ancho})")
    comprobar(600 <= alto <= 860, f"alto celular ({alto})")
    comprobar(not (ancho >= 900), "no es la ventana de escritorio")
    time.sleep(1.0)
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE

try:
    proc.wait(timeout=25)
    comprobar(proc.returncode == 0, f"cierra limpio (codigo {proc.returncode})")
except subprocess.TimeoutExpired:
    # el onefile puede dejar el proceso hijo: matar todo
    subprocess.run(["taskkill", "/F", "/IM", f"RespaldosCelular{V}.exe"],
                   capture_output=True)
    comprobar(False, "cierra limpio (tuvo que matarse)")

# el hijo huerfano del onefile cierra con el padre o sobrevive: asegurar limpieza
subprocess.run(["taskkill", "/F", "/IM", f"RespaldosCelular{V}.exe"],
               capture_output=True)

print()
print("FALLOS:", len(fallos))
print("RESULTADO:", "TODOS OK" if not fallos else "HAY FALLOS")
sys.exit(1 if fallos else 0)
