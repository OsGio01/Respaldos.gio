#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconstruye los ejecutables de Respaldos.Gio.

Uso:  python Ejecutables\\construir.py
      python Ejecutables\\construir.py --solo escritorio

Cada ejecutable se arma desde su .spec (que apunta al entry de la raiz del
proyecto). La version se lee del nucleo (core/constantes.py), asi que no hay
nada que actualizar a mano al subirla.

PyInstaller NO cruza sistemas operativos: el binario que sale aqui es del SO
donde se compila. El resultado se deja en:

    Ejecutables\\windows\\   (compilado en Windows)
    Ejecutables\\linux\\     (compilado en Linux)
    Ejecutables\\macos\\     (compilado en macOS)

El archivo universal que sirve para los tres sistemas es Respaldos.pyz, que se
genera aparte con:  python Ejecutables\\generar_pyz.py

PyInstaller deja dist/ y build/ en el directorio de trabajo actual, asi que
aqui se pasan de forma explicita y al final se limpian.
"""
import os
import re
import shutil
import subprocess
import sys
import time

RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
EJEC = os.path.join(RAIZ, "Ejecutables")


def version_programa():
    """La version vive en el nucleo: es la fuente unica de la verdad."""
    with open(os.path.join(RAIZ, "core", "constantes.py"), encoding="utf-8") as f:
        m = re.search(r'VERSION_PROGRAMA\s*=\s*"([^"]+)"', f.read())
    if not m:
        raise SystemExit("No se encontro VERSION_PROGRAMA en core/constantes.py")
    return m.group(1)


VERSION = version_programa()


def sistema_actual():
    """Nombre de la carpeta de salida para este sistema operativo."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def extension_ejecutable():
    """Windows usa .exe; Linux y macOS no usan extension."""
    return ".exe" if sys.platform.startswith("win") else ""


# (spec, nombre sin extension, modo)
# El front celular no se construye: queda como plantilla para la app movil
# nativa (ver docs/MOVIL.md).
OBJETIVOS = [
    ("Respaldos.Gio.spec", f"Respaldos.Gio{VERSION}", "windowed"),
    ("Respaldos.Gio-Terminal.spec", f"Respaldos.gio-Terminal{VERSION}", "console"),
]

# modulos que DEBEN quedar empaquetados (para no volver a confusingnos con
# un ejecutable viejo que se parece en el nombre)
DEBE_TENER = {
    f"Respaldos.Gio{VERSION}": ["fronts.hud", "fronts.hud_paneles", "core.motor"],
    f"Respaldos.gio-Terminal{VERSION}": ["fronts.terminal", "core.motor"],
}


def solo(nombre):
    """Filtra los objetivos por coincidencia parcial del nombre."""
    if not nombre:
        return OBJETIVOS
    return [o for o in OBJETIVOS if nombre.lower() in o[1].lower()]


def modulos_empaquetados(exe):
    """Nombres de modulo que quedaron dentro del PYZ del ejecutable."""
    from PyInstaller.archive.readers import CArchiveReader
    from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader

    ar = CArchiveReader(exe)
    tmp = os.path.join(os.environ.get("TEMP", "."), "pyz_construir.pyz")
    with open(tmp, "wb") as f:
        f.write(ar.extract("PYZ.pyz"))
    pyz = ZlibArchiveReader(tmp)
    return set(pyz.toc)


def construir(spec, nombre, modo):
    base = EJEC
    ruta_spec = os.path.join(base, spec)
    dist = os.path.join(base, "dist")
    build = os.path.join(base, "build")
    salida = os.path.join(EJEC, sistema_actual())
    os.makedirs(salida, exist_ok=True)

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

    origen = os.path.join(dist, nombre + extension_ejecutable())
    if r.returncode != 0 or not os.path.exists(origen):
        print("  FALLO al compilar")
        print((r.stdout or "")[-1500:])
        print((r.stderr or "")[-1500:])
        return False

    destino = os.path.join(salida, nombre + extension_ejecutable())
    shutil.copy2(origen, destino)

    # verificar el codigo empaquetado (no confiar en el nombre del archivo)
    faltan = []
    try:
        mods = modulos_empaquetados(destino)
        faltan = [m for m in DEBE_TENER[nombre] if m not in mods]
    except Exception as e:  # pragma: no cover
        print(f"  AVISO: no se pudo inspeccionar el PYZ ({e})")

    if faltan:
        print(f"  FALLO: el ejecutable no trae {faltan}")
        return False

    # verificar que las imagenes van dentro del binario
    try:
        from PyInstaller.archive.readers import CArchiveReader
        ar = CArchiveReader(destino)
        if not any(n.startswith("IMG") for n in ar.toc):
            print("  AVISO: el binario no trae IMG/ (el logo no se mostrara)")
    except Exception:
        pass

    tam = os.path.getsize(destino)
    print(f"  OK {nombre}: {tam:,} bytes, {dt:.0f}s -> "
          f"{os.path.relpath(destino, RAIZ)}")

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

    print(f"Reconstruyendo {len(objetivos)} ejecutable(s) de "
          f"Respaldos.Gio v{VERSION} para {sistema_actual()}")
    fallos = []
    for spec, nombre, modo in objetivos:
        if not construir(spec, nombre, modo):
            fallos.append(nombre)

    if not fallos:
        print(f"\nListo. Estan en Ejecutables\\{sistema_actual()}\\")
        print("El archivo universal para los tres sistemas es Respaldos.pyz "
              "(python Ejecutables\\generar_pyz.py)")

    print("\n--- RESULTADO ---")
    if fallos:
        print("FALLARON:", ", ".join(fallos))
        return 1
    print("Todos los ejecutables quedaron listos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
