# Prueba de Respaldos.Gio v6.0 (ver Pruebas/README.md)

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import subprocess, sys, os, time

exe = os.path.join(RAIZ, "Ejecutables", "Respaldosterminal6.0", "Respaldos.gio-Terminal6.0.exe")
cwd = os.path.dirname(exe)

proc = subprocess.Popen([exe], cwd=cwd, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    out, err = proc.communicate(input=b"11\n\n", timeout=60)
except subprocess.TimeoutExpired:
    proc.kill()
    out, err = proc.communicate()
    print("FAIL se colgo (timeout)")
    sys.exit(1)

texto = out.decode("utf-8", "replace")
fallos = []


def comprobar(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        fallos.append(msg)


comprobar("6.0" in texto, "muestra la version 6.0")
comprobar("RESPALDO" in texto.upper(), "muestra el menu de respaldos")
comprobar("Salir" in texto or "SALIR" in texto, "ofrece salir")
comprobar(proc.returncode == 0, f"salida limpia (codigo {proc.returncode})")
comprobar(not err.decode("utf-8", "replace").strip(), "sin stderr")

print()
print("SALIDA (primeras 40 lineas):")
for linea in texto.splitlines()[:40]:
    print("   |", linea)

print()
print("FALLOS:", len(fallos))
print("RESULTADO:", "TODOS OK" if not fallos else "HAY FALLOS")
sys.exit(0 if not fallos else 1)
