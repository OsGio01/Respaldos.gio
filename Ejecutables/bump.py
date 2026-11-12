#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sube la version del programa y renombra lo que depende de ella.

Uso:  python Ejecutables\\bump.py 6.1

Que hace:
  1. Actualiza VERSION_PROGRAMA en core/constantes.py (fuente de la verdad).
  2. Renombra las carpetas de Ejecutables/ y los tres .exe con la nueva version.
  3. Sustituye la version vieja por la nueva en el codigo y la documentacion.

Los specs, el script de construccion y las pruebas ya leen la version del
nucleo, asi que no hay que editarlos a mano.
"""
import os
import re
import subprocess
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
EJEC = os.path.join(RAIZ, "Ejecutables")
CONSTANTES = os.path.join(RAIZ, "core", "constantes.py")

CARPETAS = ["RespaldosInterface", "Respaldosterminal", "Respaldoscelular"]
EXES = ["Respaldos.Gio", "Respaldos.gio-Terminal", "RespaldosCelular"]

# Frases que cuentan historia y no deben cambiar.
HISTORICO = [
    ("La versión 6.0 reescribió todo el programa", "@@HISTORICO1@@"),
    ("portada del motor v5 al core OOP v6.0", "@@HISTORICO2@@"),
    ("las defensas de seguridad de la v6.0", "@@HISTORICO3@@"),
    ("las defensas de la v6.0", "@@HISTORICO4@@"),
]


def version_actual():
    with open(CONSTANTES, encoding="utf-8") as f:
        texto = f.read()
    m = re.search(r'VERSION_PROGRAMA\s*=\s*"([^"]+)"', texto)
    return m.group(1) if m else ""


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=RAIZ, capture_output=True, text=True)


def actualizar_constantes(vieja, nueva):
    with open(CONSTANTES, encoding="utf-8") as f:
        texto = f.read()
    texto = re.sub(r'VERSION_PROGRAMA\s*=\s*"%s"' % re.escape(vieja),
                   'VERSION_PROGRAMA = "%s"' % nueva, texto)
    with open(CONSTANTES, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    print(f"  core/constantes.py: {vieja} -> {nueva}")


def renombrar(vieja, nueva):
    """Renombra los ejecutables y despues las carpetas que los contienen."""
    for base in EXES:
        for carpeta in CARPETAS:
            viejo = os.path.join(EJEC, f"{carpeta}{vieja}", f"{base}{vieja}.exe")
            nuevo = os.path.join(EJEC, f"{carpeta}{vieja}", f"{base}{nueva}.exe")
            if os.path.exists(viejo):
                git("mv", os.path.relpath(viejo, RAIZ).replace("\\", "/"),
                    os.path.relpath(nuevo, RAIZ).replace("\\", "/"))
                print(f"  exe: {os.path.basename(viejo)} -> {os.path.basename(nuevo)}")
    for base in CARPETAS:
        viejo = os.path.join(EJEC, f"{base}{vieja}")
        nuevo = os.path.join(EJEC, f"{base}{nueva}")
        if os.path.isdir(viejo):
            git("mv", os.path.relpath(viejo, RAIZ).replace("\\", "/"),
                os.path.relpath(nuevo, RAIZ).replace("\\", "/"))
            print(f"  carpeta: {os.path.basename(viejo)} -> {os.path.basename(nuevo)}")


def sustituir_texto(vieja, nueva):
    """Cambia la version en codigo y documentacion."""
    objetivos = []
    for carpeta in ("core", "fronts"):
        for f in sorted(os.listdir(os.path.join(RAIZ, carpeta))):
            if f.endswith(".py"):
                objetivos.append(os.path.join(RAIZ, carpeta, f))
    for f in ("Respaldos.py", "RespaldosTkinter.py", "RespaldosMovil.py", "main.py",
              "README.md"):
        objetivos.append(os.path.join(RAIZ, f))
    pruebas = os.path.join(RAIZ, "Pruebas")
    if os.path.isdir(pruebas):
        for f in sorted(os.listdir(pruebas)):
            if f.endswith(".py") or f == "README.md":
                objetivos.append(os.path.join(pruebas, f))
    # los config de los ejecutables guardan la ruta de respaldos con la version
    if os.path.isdir(EJEC):
        for carpeta in sorted(os.listdir(EJEC)):
            config = os.path.join(EJEC, carpeta, "config.json")
            if os.path.exists(config):
                objetivos.append(config)
    ignorados = os.path.join(RAIZ, "ignorados")
    if os.path.isdir(ignorados):
        for f in ("AGENTS.md",):
            p = os.path.join(ignorados, f)
            if os.path.exists(p):
                objetivos.append(p)

    cambios = 0
    for ruta in objetivos:
        if not os.path.exists(ruta):
            continue
        with open(ruta, encoding="utf-8") as f:
            original = f.read()
        if vieja not in original:
            continue
        texto = original
        for frase, marca in HISTORICO:
            texto = texto.replace(frase, marca)
        texto = texto.replace(vieja, nueva)
        for frase, marca in HISTORICO:
            texto = texto.replace(marca, frase)
        if texto != original:
            with open(ruta, "w", encoding="utf-8", newline="\n") as f:
                f.write(texto)
            cambios += 1
            print(f"  actualizado: {os.path.relpath(ruta, RAIZ)}")
    print(f"  {cambios} archivo(s) con la version nueva")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    nueva = sys.argv[1].strip()
    if not re.match(r"^\d+\.\d+(\.\d+)?$", nueva):
        print("Version invalida (usa 6.1, 6.2, ...):", nueva)
        return 1
    vieja = version_actual()
    if not vieja:
        print("No se encontro VERSION_PROGRAMA en core/constantes.py")
        return 1
    if vieja == nueva:
        print(f"La version ya es {nueva}.")
        return 0

    print(f"Subiendo version: {vieja} -> {nueva}")
    actualizar_constantes(vieja, nueva)
    renombrar(vieja, nueva)
    sustituir_texto(vieja, nueva)
    print("\nAhora reconstruye los ejecutables:")
    print("   python Ejecutables\\construir.py")
    print("y corre la bateria:  python Pruebas\\run_all_tests.py --exe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
