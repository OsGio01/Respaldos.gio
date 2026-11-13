#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostico de Respaldos.Gio: dice por que el programa no arranca.

Uso:
    python Respaldos.py --diagnostico
    python3 Respaldos.pyz --diagnostico

Imprime el sistema, si hay tkinter, el display, las rutas que usa el programa
y si son escribibles. Es lo primero que hay que correr cuando el programa
"no abre" en otra maquina.
"""
import os
import sys


def _linea(etiqueta, valor, detalle=""):
    print(f"  {etiqueta:<22} {valor}" + (f"   {detalle}" if detalle else ""))


def diagnostico():
    print("")
    print("=" * 66)
    print("  RESPALDOS.GIO - DIAGNOSTICO")
    print("=" * 66)

    # --- sistema
    print("\n[ SISTEMA ]")
    from core import plataforma
    _linea("Sistema", plataforma.sistema_nombre(),
           f"({platform_plataforma()})")
    _linea("Python", sys.version.split()[0], sys.executable)
    _linea("Ejecutandose como", os.path.basename(sys.argv[0]))

    # --- interfaz grafica
    print("\n[ INTERFAZ GRAFICA ]")
    try:
        import tkinter
        _linea("tkinter", "instalado", f"version {tkinter.TkVersion}")
        try:
            raiz = tkinter.Tk()
            raiz.withdraw()
            raiz.destroy()
            _linea("Ventana (display)", "funciona")
        except Exception as e:
            _linea("Ventana (display)", "NO ABRE", str(e))
            print("      -> Sin display no hay ventana grafica.")
            print("         El front de Terminal (opcion 1) si funciona.")
    except ImportError:
        _linea("tkinter", "NO INSTALADO")
        print("      -> En Debian/Ubuntu: sudo apt install python3-tk")
        print("         En Fedora:         sudo dnf install python3-tkinter")
        print("         El front de Terminal (opcion 1) si funciona.")

    print(f"      DISPLAY=[{os.environ.get('DISPLAY', '')}]")

    # --- rutas
    print("\n[ RUTAS ]")
    from core import constantes
    _linea("Carpeta de recursos", constantes.RUTA_IMG_DIR)
    for nombre in ("interface.png", "icono.png", "interface.ico", "icono.ico"):
        ruta = constantes.ruta_imagen(nombre)
        _linea(f"  {nombre}", "ok" if os.path.exists(ruta) else "FALTA", ruta)
    print()
    _linea("Carpeta de datos", constantes.RUTA_DATOS)
    _linea("Config", constantes.RUTA_CONFIG,
           "ok" if os.path.exists(constantes.RUTA_CONFIG) else "se creara al guardar")
    _linea("Respaldos", constantes.RUTA_RESPALDOS)
    _linea("Estados", constantes.RUTA_ESTADOS_DIR)

    # --- escritura
    print("\n[ ESCRITURA ]")
    for nombre, ruta in (("Carpeta de datos", constantes.RUTA_DATOS),
                         ("Carpeta de respaldos", constantes.RUTA_RESPALDOS),
                         ("Carpeta de estados", constantes.RUTA_ESTADOS_DIR)):
        existe = os.path.isdir(ruta)
        escribible = os.access(ruta, os.W_OK) if existe else False
        _linea(nombre, "ok" if escribible else ("no existe todavia" if not existe else "NO ESCRIBIBLE"), ruta)

    # --- pendientes
    print("\n[ PENDIENTES ]")
    pendientes = []
    if constantes.RUTA_CONFIG in constantes.RUTA_DATOS:
        pass
    try:
        from core import estados as _estados
        gestor = _estados.GestorEstados()
        n = len(gestor.pausados())
        _linea("Respaldos interrumpidos", n)
    except Exception as e:
        _linea("Respaldos interrumpidos", "no se pudo leer", str(e)[:60])

    print("\n" + "=" * 66)
    print("  Si el problema sigue, pega esta salida junto al traceback.")
    print("=" * 66)
    print("")
    return 0


def platform_plataforma():
    import platform
    return platform.platform()


if __name__ == "__main__":
    if "--diagnostico" in sys.argv or "-d" in sys.argv:
        sys.exit(diagnostico())
    from fronts.terminal import menu_principal
    menu_principal()
