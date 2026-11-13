#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deteccion de plataforma (nucleo v6.2).

Centraliza las diferencias entre Windows, Linux, macOS y Android para que el
resto del nucleo no tenga que preguntar el SO a mano. Aqui viven:
  - que sistema es (incluido Android/Termux),
  - la familia de fuente que existe en ese SO (Tk no trae Segoe UI fuera de Windows),
  - las carpetas del usuario en cada SO (con nombres en espanol e ingles),
  - la carpeta donde se guardan los datos escribibles del programa.
"""
import os
import platform
import sys
from typing import List, Optional

# Carpeta de datos del programa (config, estados, respaldos, registros).
# Vive en el perfil del usuario porque un .pyz o un ejecutable pueden estar
# en una carpeta de solo lectura (/usr/share, C:\Program Files).
NOMBRE_APP = "Respaldos.Gio"


def es_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def es_macos() -> bool:
    return sys.platform == "darwin"


def es_linux() -> bool:
    return sys.platform.startswith("linux")


def es_android() -> bool:
    """True si corre en Android (Termux, Pydroid 3, ...).

    Android reporta plataforma Linux, asi que hay que buscar señales propias:
    Termux define PREFIX/ANDROID_ROOT y el home cuelga de /data/data.
    """
    if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
        return True
    prefijo = os.environ.get("PREFIX", "")
    if prefijo and "com.termux" in prefijo:
        return True
    home = os.path.expanduser("~")
    return home.startswith("/data/data/")


def sistema_nombre() -> str:
    """Nombre del sistema para mostrarlo en pantalla."""
    if es_android():
        return "Android"
    return platform.system() or "Desconocido"


# ---------------------------------------------------------------- fuentes
# Tk no trae "Segoe UI" fuera de Windows: si se pide una fuente inexistente
# Tk la sustituye por la default, asi que el texto se ve distinto (y mas
# grande) en Linux y macOS. Se pide la primera que exista en el SO.
_FUENTES_UI = {
    "Windows": ["Segoe UI", "Tahoma", "Arial"],
    "Darwin": ["Helvetica Neue", "Helvetica", "Arial"],
    "Linux": ["Ubuntu", "DejaVu Sans", "Noto Sans", "Cantarell"],
}
_FUENTES_MONO = {
    "Windows": ["Consolas", "Cascadia Mono", "Courier New"],
    "Darwin": ["Menlo", "Monaco", "Courier New"],
    "Linux": ["Ubuntu Mono", "DejaVu Sans Mono", "Noto Sans Mono", "Liberation Mono"],
}


def _fuentes_disponibles() -> set:
    """Familias de fuente que Tk puede usar en esta maquina."""
    try:
        import tkinter.font as tkfont
        return set(tkfont.families())
    except Exception:
        return set()


def _elegir_fuente(candidatas: List[str]) -> str:
    disponibles = _fuentes_disponibles()
    if disponibles:
        for f in candidatas:
            if f in disponibles:
                return f
    # Si Tk no esta disponible (terminal), se devuelve la primera: da igual,
    # porque el front grafico no se va a dibujar.
    return candidatas[0]


def familia_ui() -> str:
    """Familia de fuente para la interfaz."""
    if es_windows():
        clave = "Windows"
    elif es_macos():
        clave = "Darwin"
    else:
        clave = "Linux"
    return _elegir_fuente(_FUENTES_UI[clave])


def familia_mono() -> str:
    """Familia de fuente monoespaciada (registros y logs)."""
    if es_windows():
        clave = "Windows"
    elif es_macos():
        clave = "Darwin"
    else:
        clave = "Linux"
    return _elegir_fuente(_FUENTES_MONO[clave])


# ---------------------------------------------------------------- carpetas
def rutas_android() -> List[str]:
    """Rutas del almacenamiento compartido en Android.

    Requiere 'termux-setup-storage' (o el permiso equivalente): sin eso,
    /sdcard no existe y no hay nada que respaldar.
    """
    candidatas = ["/sdcard", "/storage/emulated/0", "/storage/self/primary"]
    return [c for c in candidatas if os.path.isdir(c)]


def carpeta_datos() -> str:
    """Carpeta escribible donde el programa guarda sus datos.

    Si esta definida la variable de entorno RESPALDOS_GIO_DATA, esa manda
    (util para meter todo en un USB: RESPALDOS_GIO_DATA=/mnt/USB/Respaldos).

    Windows: %APPDATA%\\Respaldos.Gio
    macOS:   ~/Library/Application Support/Respaldos.Gio
    Linux:   $XDG_CONFIG_HOME/respaldos.gio (o ~/.config/respaldos.gio)
    """
    personalizada = os.environ.get("RESPALDOS_GIO_DATA", "").strip()
    if personalizada:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(personalizada)))
    if es_windows():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, NOMBRE_APP)
    if es_macos():
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", NOMBRE_APP)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "respaldos.gio")


def asegurar_carpeta(ruta: str) -> bool:
    """Crea la carpeta si hace falta. Devuelve False si no se pudo."""
    try:
        os.makedirs(ruta, exist_ok=True)
        return True
    except OSError:
        return False


def carpeta_legible() -> Optional[str]:
    """Primera carpeta de datos que se puede escribir.

    Se prueban en orden: la del SO y, como respaldo, la carpeta del programa
    (util cuando alguien copia todo a un USB y lo usa desde ahi).
    """
    candidatas = [carpeta_datos()]
    try:
        candidatas.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except Exception:
        pass
    for c in candidatas:
        if asegurar_carpeta(c) and os.access(c, os.W_OK):
            return c
    return None
