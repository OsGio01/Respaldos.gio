#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconstruye los tres ejecutables de Respaldos.Gio v6.0.

Uso:  python Ejecutables\\construir_6.0.py

Cada ejecutable se arma desde su .spec (que apunta al entry de la raiz del
proyecto y al icono de su propia carpeta). PyInstaller deja dist/ y build/ en
el directorio de trabajo actual, asi que aqui se pasan de forma explicita y
al final se limpian.

Opcional:  python Ejecutables\\construir_6.0.py --solo celular
"""
import os
import shutil
import subprocess
import sys
import time

RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))

# (carpeta, spec, nombre del exe, modo)
OBJETIVOS = [
    ("RespaldosInterface6.0", "Respaldos.Gio.spec", "Respaldos.Gio6.0", "windowed"),
    ("Respaldosterminal6.0", "Respaldos.Gio-Terminal.spec", "Respaldos.gio-Terminal6.0", "console"),
    ("Respaldoscelular6.0", "RespaldosCelular.spec", "RespaldosCelular6.0", "windowed"),
]

# modulos que DEBEN quedar empaquetados (para no volver a confusingnos con
# un exe viejo que se parece en el nombre)
DEBE_TENER = {
    "RespaldosInterface6.0": ["fronts.hud", "fronts.hud_paneles", "core.motor"],
    "Respaldosterminal6.0": ["fronts.terminal", "core.motor"],
    "Respaldoscelular6.0": ["fronts.movil", "core.motor"],
}


def solo(nombre):
    """Filtra los objetivos por coincidencua parcial de la carpeta."""
    if not nombre:
        return OBJETIVOS
    return [o for o in OBJETIVOS if nombre.lower() in o[0].lower()]


def modulos_empaquetados(exe):
    """Nombres de modulo que quedaron dentro del PYZ del exe."""
    from PyInstaller.archive.readers import CArchiveReader
    from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader

    ar = CArchiveReader(exe)
    tmp = os.path.join(os.environ.get("TEMP", "."), "pyz_construir.pyz")
    with open(tmp, "wb") as f:
        f.write(ar.extract("PYZ.pyz"))
    pyz = ZlibArchiveReader(tmp)
    return set(pyz.toc)


def construir(carpeta, spec, nombre, modo):
    base = os.path.join(RAIZ, "Ejecutables", carpeta)
    ruta_spec = os.path.join(base, spec)
    dist = os.path.join(base, "dist")
    build = os.path.join(base, "build")

    if not os.path.exists(ruta_spec):
        print(f"  FALLO: no existe {ruta_spec}")
        return False

    # Con un .spec no se pueden pasar --onefile/--console/--windowed:
    # esas opciones ya viven dentro del spec.
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", dist,
        "--workpath", build,
        ruta_spec,
    ]
    print(f"\n=== {nombre} ({modo}) ===")
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=RAIZ)
    dt = time.time() - t0

    origen = os.path.join(dist, f"{nombre}.exe")
    if r.returncode != 0 or not os.path.exists(origen):
        print("  FALLO al compilar")
        print((r.stdout or "")[-1500:])
        print((r.stderr or "")[-1500:])
        return False

    destino = os.path.join(base, f"{nombre}.exe")
    shutil.copy2(origen, destino)

    # verificar el codigo empaquetado (no confiar en el nombre del archivo)
    faltan = []
    try:
        mods = modulos_empaquetados(destino)
        faltan = [m for m in DEBE_TENER[carpeta] if m not in mods]
    except Exception as e:  # pragma: no cover
        print(f"  AVISO: no se pudo inspeccionar el PYZ ({e})")

    if faltan:
        print(f"  FALLO: el exe no trae {faltan}")
        return False

    tam = os.path.getsize(destino)
    print(f"  OK {nombre}: {tam:,} bytes, {dt:.0f}s -> {os.path.relpath(destino, RAIZ)}")

    # limpiar temporales
    for d in (build, dist):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    objetivos = solo(args[0] if args else None)
    if not objetivos:
        print("No hay objetivos para ese filtro.")
        return 1

    print(f"Reconstruyendo {len(objetivos)} ejecutable(s) de Respaldos.Gio v6.0")
    fallos = []
    for carpeta, spec, nombre, modo in objetivos:
        if not construir(carpeta, spec, nombre, modo):
            fallos.append(nombre)

    print("\n--- RESULTADO ---")
    if fallos:
        print("FALLARON:", ", ".join(fallos))
        return 1
    print("Todos los ejecutables quedaron listos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
