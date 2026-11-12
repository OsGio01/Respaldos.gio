# -*- coding: utf-8 -*-
"""Bateria de pruebas de Respaldos.Gio v6.0.

Uso:
    python Pruebas\\run_all_tests.py            # nucleo y frentes
    python Pruebas\\run_all_tests.py --exe      # ademas los ejecutables

Cada prueba es un script suelto en esta misma carpeta. Devuelve codigo de
salida 1 si alguna falla.
"""
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)

ARCHIVOS = [
    "main.py", "Respaldos.py", "RespaldosTkinter.py", "RespaldosMovil.py",
    "core/constantes.py", "core/utilidades.py", "core/persistencia.py",
    "core/configuracion.py", "core/estados.py", "core/seguridad.py",
    "core/escaneo.py", "core/progreso.py", "core/motor.py", "core/fuentes.py",
    "core/red.py", "core/__init__.py",
    "fronts/terminal.py", "fronts/tema.py", "fronts/acciones.py",
    "fronts/hud_paneles.py", "fronts/hud.py", "fronts/movil.py", "fronts/__init__.py",
]

# (nombre, script)
PRUEBAS = [
    ("SMOKE CORE", "smoke_core.py"),
    ("E2E CORE", "e2e_core.py"),
    ("SMOKE HUD 1", "smoke_hud.py"),
    ("SMOKE HUD 2", "smoke_hud2.py"),
    ("SMOKE MOVIL", "smoke_movil.py"),
    ("TERMINAL FRONT", "test_terminal_front.py"),
    ("FACHADAS", "smoke_fachada.py"),
    ("ESCRITORIO", "test_escritorio.py"),
    ("FASE 2 CONFIG", "test_fase2.py"),
    ("FASE 3 MOVIL", "test_fase3.py"),
    ("VENTANA", "test_ventana.py"),
    ("SEGURIDAD", "tests_seguridad_rendimiento.py"),
    ("SCRIPTS MINIMOS", "test_scripts_minimos.py"),
]

PRUEBAS_EXE = [
    ("ICONOS EXE", "verif_iconos_exe.py"),
    ("EXE TERMINAL", "test_exe_terminal.py"),
    ("EXE GUI", "test_exe_gui.py"),
    ("EXE CELULAR", "test_exe_celular.py"),
]


def correr(nombre, script, timeout=180):
    ruta = os.path.join(AQUI, script)
    if not os.path.exists(ruta):
        print(f"FAIL {nombre}  (no existe {script})")
        return False
    r = subprocess.run([sys.executable, ruta], capture_output=True, text=True,
                       timeout=timeout, cwd=RAIZ,
                       env={**os.environ, "PYTHONPATH": RAIZ})
    salida = (r.stdout or "") + (r.stderr or "")
    bien = r.returncode == 0 and "Traceback" not in salida
    print(f"{'OK  ' if bien else 'FAIL'} {nombre}")
    if not bien:
        print("OUT:", salida[-1500:])
    return bien


def main():
    con_exe = "--exe" in sys.argv

    print("== Compilacion ==")
    r = subprocess.run([sys.executable, "-m", "py_compile"]
                       + [os.path.join(RAIZ, a) for a in ARCHIVOS],
                       capture_output=True, text=True)
    print("PY_COMPILE:", "OK" if r.returncode == 0 else "FALLO")
    if r.returncode != 0:
        print(r.stdout or "", r.stderr or "")
        return 1

    print("\n== Nucleo y frentes ==")
    fallos = 0
    for nombre, script in PRUEBAS:
        if not correr(nombre, script):
            fallos += 1

    if con_exe:
        print("\n== Ejecutables ==")
        for nombre, script in PRUEBAS_EXE:
            if not correr(nombre, script, timeout=240):
                fallos += 1

    print("\nRESULTADO FINAL:", "TODOS OK" if not fallos else f"{fallos} FALLAS")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
