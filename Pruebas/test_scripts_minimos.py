# -*- coding: utf-8 -*-
"""Prueba de los scripts minimos de terminal (sin Python).

En Windows prueba el script de PowerShell de punta a punta: respaldo general,
reanudar y eliminar. En cualquier sistema revisa la sintaxis de los scripts de
bash (Linux y macOS) con `bash -n` si hay bash disponible.

Uso:  python Pruebas\\test_scripts_minimos.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

WINDOWS = os.path.join(RAIZ, "windows")
LINUX = os.path.join(RAIZ, "Linux")
MACOS = os.path.join(RAIZ, "macOS")

fallos = []


def comprobar(condicion, mensaje):
    if condicion:
        print(f"OK   {mensaje}")
    else:
        print(f"FAIL {mensaje}")
        fallos.append(mensaje)


def preparar_origen():
    base = tempfile.mkdtemp(prefix="gio_ori_")
    origen = os.path.join(base, "Datos")
    os.makedirs(os.path.join(origen, "sub"))
    with open(os.path.join(origen, "a.txt"), "w", encoding="utf-8") as f:
        f.write("contenido de a")
    with open(os.path.join(origen, "con espacio.txt"), "w", encoding="utf-8") as f:
        f.write("contenido con espacio")
    with open(os.path.join(origen, "sub", "b.txt"), "w", encoding="utf-8") as f:
        f.write("contenido de b")
    return base, origen


def correr_ps1(destino_fuentes, entrada, timeout=120):
    ps = os.path.join(WINDOWS, "Respaldos.gio.ps1")
    env = {**os.environ, "RESPALDOS_GIO_FUENTES": destino_fuentes}
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps],
        input=entrada.encode("utf-8"), capture_output=True, timeout=timeout, env=env)


def respaldos_creados(destino):
    if not os.path.isdir(destino):
        return []
    return [d for d in os.listdir(destino) if d.startswith("Respaldo_")
            and os.path.isdir(os.path.join(destino, d))]


def probar_windows():
    print("== Script de Windows (PowerShell) ==")
    base, origen = preparar_origen()
    destino = os.path.join(base, "Respaldos")
    os.makedirs(destino, exist_ok=True)
    estado = os.path.join(WINDOWS, "respaldos.estado")
    conf = os.path.join(WINDOWS, "respaldos.conf")
    try:
        # --- 1) respaldo general ------------------------------------------
        entrada = f"1\n{destino}\nn\n4\n"
        r = correr_ps1(f"Datos|{origen}", entrada)
        salida = (r.stdout or b"").decode("utf-8", "replace") + \
                 (r.stderr or b"").decode("utf-8", "replace")
        creados = respaldos_creados(destino)
        comprobar(len(creados) == 1, f"se creo un respaldo (creados: {creados})")
        if not creados:
            print(salida[-1200:])
            return
        carpeta = os.path.join(destino, creados[0])
        comprobar(os.path.isfile(os.path.join(carpeta, "Datos", "a.txt")),
                  "copio el archivo de la raiz")
        comprobar(os.path.isfile(os.path.join(carpeta, "Datos", "sub", "b.txt")),
                  "copio el archivo de una subcarpeta")
        comprobar(os.path.isfile(os.path.join(carpeta, "Datos", "con espacio.txt")),
                  "copio el archivo con espacios en el nombre")
        with open(os.path.join(carpeta, "Datos", "a.txt"), encoding="utf-8") as f:
            comprobar(f.read() == "contenido de a", "el contenido quedo integro")
        comprobar(not os.path.exists(estado), "el estado se borro al terminar bien")

        # --- 2) reanudar -------------------------------------------------
        # Se simula una interrupcion: queda el estado con un archivo copiado.
        with open(estado, "w", encoding="utf-8") as f:
            f.write("# Respaldos.Gio - estado de reanudacion\n")
            f.write(f"CARPETA={creados[0]}\n")
            f.write(f"FUENTE=Datos|{origen}\n")
            f.write("COPIA=Datos/a.txt\n")
        os.remove(os.path.join(carpeta, "Datos", "sub", "b.txt"))
        r = correr_ps1(f"Datos|{origen}", "2\nn\n4\n")
        comprobar(os.path.isfile(os.path.join(carpeta, "Datos", "sub", "b.txt")),
                  "reanudar copio lo que faltaba")
        comprobar(not os.path.exists(estado), "reanudar borro el estado al terminar")

        # --- 3) eliminar -------------------------------------------------
        r = correr_ps1(f"Datos|{origen}", "3\n1\nBORRAR\n4\n")
        comprobar(len(respaldos_creados(destino)) == 0, "elimino el respaldo elegido")

        # --- 4) eliminar cancelado ---------------------------------------
        entrada = f"1\n{destino}\nn\n4\n"
        r = correr_ps1(f"Datos|{origen}", entrada)
        creados = respaldos_creados(destino)
        if creados:
            carpeta = os.path.join(destino, creados[0])
            r = correr_ps1(f"Datos|{origen}", "3\n1\nno\n4\n")
            comprobar(os.path.isdir(carpeta), "no elimino si no se escribe BORRAR")
    finally:
        for f in (estado, conf, os.path.join(WINDOWS, "respaldos.fuentes.tmp")):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        shutil.rmtree(base, ignore_errors=True)


def probar_bash():
    print("== Scripts de bash (Linux y macOS) ==")
    bash = shutil.which("bash")
    if not bash:
        git_bash = r"C:\Program Files\Git\bin\bash.exe"
        bash = git_bash if os.path.exists(git_bash) else None
    if not bash:
        print("SKIP no hay bash en esta maquina: no se revisa la sintaxis")
        return
    for carpeta, nombre in ((LINUX, "respaldos.sh"), (MACOS, "respaldos.sh"),
                            (MACOS, "Respaldos.gio.command")):
        ruta = os.path.join(carpeta, nombre)
        if not os.path.exists(ruta):
            comprobar(False, f"existe {nombre}")
            continue
        r = subprocess.run([bash, "-n", ruta], capture_output=True, text=True, timeout=60)
        comprobar(r.returncode == 0,
                  f"sintaxis correcta de {carpeta}/{nombre}"
                  + (f" ({r.stderr.strip()[:200]})" if r.returncode else ""))

    # prueba funcional del script de Linux (con git-bash tambien funciona)
    base, origen = preparar_origen()
    destino = os.path.join(base, "Respaldos")
    os.makedirs(destino, exist_ok=True)
    estado = os.path.join(LINUX, "respaldos.estado")
    conf = os.path.join(LINUX, "respaldos.conf")
    temporales = os.path.join(LINUX, "respaldos.fuentes.tmp")
    try:
        ruta = os.path.join(LINUX, "respaldos.sh").replace("\\", "/")
        env = {**os.environ,
               "RESPALDOS_GIO_FUENTES": f"Datos|{origen.replace(chr(92), '/')}",
               "HOME": base}
        entrada = f"1\n{destino.replace(chr(92), '/')}\nn\n4\n"
        r = subprocess.run([bash, ruta], input=entrada.encode(), capture_output=True,
                           timeout=180, env=env)
        creados = respaldos_creados(destino)
        comprobar(len(creados) == 1, f"bash creo un respaldo (creados: {creados})")
        if creados:
            carpeta = os.path.join(destino, creados[0])
            comprobar(os.path.isfile(os.path.join(carpeta, "Datos", "a.txt")),
                      "bash copio el archivo de la raiz")
            comprobar(os.path.isfile(os.path.join(carpeta, "Datos", "sub", "b.txt")),
                      "bash copio el archivo de una subcarpeta")
            comprobar(not os.path.exists(estado), "bash borro el estado al terminar")
    finally:
        for f in (estado, conf, temporales):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        shutil.rmtree(base, ignore_errors=True)


def main():
    if os.name == "nt":
        probar_windows()
    else:
        print("SKIP la prueba funcional de Windows solo corre en Windows")
    probar_bash()
    print()
    if fallos:
        print(f"FALLOS: {len(fallos)}")
        for f in fallos:
            print("  -", f)
        return 1
    print("RESULTADO: TODOS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
