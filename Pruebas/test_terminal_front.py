# Prueba de Respaldos.Gio v6.2 (ver Pruebas/README.md)

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import subprocess, sys, os

proyectos = RAIZ

def run_menu(inputs, timeout=60, script=None):
    inp = "".join(inputs)
    cmd = [sys.executable, "-c", script] if script else [sys.executable, "main.py"]
    return subprocess.run(cmd, input=inp, capture_output=True, text=True, timeout=timeout,
                           cwd=proyectos, env={**os.environ, "PYTHONPATH": proyectos})

r = run_menu(["11\n"], timeout=30, script="from fronts.terminal import menu_principal; menu_principal()")
buen = r.returncode == 0 and "Hasta pronto" in (r.stdout or "") and "Traceback" not in (r.stderr or "")
print("OK   TERMINAL MENU (via module) " if buen else "FAIL TERMINAL MENU ")
if not buen:
    print(r.stdout[-1500:], r.stderr[-800:])

r = run_menu(["10\n", "15\n"], timeout=30, script="from fronts.terminal import menu_principal; menu_principal()")
buen2 = r.returncode == 0 and "Configuración guardada" in (r.stdout or "")
print("OK   TERMINAL CONFIG " if buen2 else "FAIL TERMINAL CONFIG ")
if not buen2:
    print(r.stdout[-1500:], r.stderr[-800:])

r = run_menu(["9\n"], timeout=30, script="from fronts.terminal import menu_principal; menu_principal()")
buen3 = r.returncode == 0 and "No hay registros" in (r.stdout or "")
print("OK   TERMINAL REGISTROS " if buen3 else "FAIL TERMINAL REGISTROS ")
if not buen3:
    print(r.stdout[-1500:], r.stderr[-800:])

r = run_menu(["5\n"], timeout=30, script="from fronts.terminal import menu_principal; menu_principal()")
buen4 = r.returncode == 0 and "No hay respaldos interrumpidos" in (r.stdout or "")
print("OK   TERMINAL REANUDAR " if buen4 else "FAIL TERMINAL REANUDAR ")
if not buen4:
    print(r.stdout[-1500:], r.stderr[-800:])
