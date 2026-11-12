#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utilidades varias del programa (nucleo v6.1)."""
import os
import platform
import re
import sys
from datetime import datetime
from typing import Optional, Tuple

UNICODE_SUPPORT = False
try:
    if "--ascii" not in sys.argv and sys.stdout.encoding and "UTF" in sys.stdout.encoding.upper():
        UNICODE_SUPPORT = True
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def icono(texto_emoji: str, texto_fallback: str) -> str:
    return texto_emoji if UNICODE_SUPPORT else texto_fallback


def limpiar_terminal() -> None:
    # FUN-01: en Windows se usa 'cls' (las consolas antiguas no interpretan secuencias ANSI)
    if platform.system() == "Windows":
        os.system("cls")
        return
    try:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    except Exception:
        os.system("clear")


def pausa() -> None:
    try:
        pedir("Presiona ENTER para continuar...")
    except EOFError:
        return


# --------------------------------------------------------------------------
# Peticion de datos al usuario.
# El front de terminal usa input() (comportamiento clasico); los fronts
# graficos instalan su propio proveedor con `instalar_pedidor` para recoger
# los datos sin bloquear la ventana.
# --------------------------------------------------------------------------
_proveedor_pedir = None


def instalar_pedidor(proveedor) -> None:
    """Instala `proveedor(mensaje, ocultar) -> str`. None vuelve a input()."""
    global _proveedor_pedir
    _proveedor_pedir = proveedor


def pedir(mensaje: str, ocultar: bool = False) -> str:
    """Pide un dato al usuario (siempre devuelve texto, nunca None)."""
    if _proveedor_pedir is not None:
        return _proveedor_pedir(mensaje, ocultar)
    if ocultar:
        try:
            import getpass
            return getpass.getpass(mensaje)
        except Exception:
            pass
    try:
        return input(mensaje)
    except EOFError:
        return ""


def expandir_ruta(ruta: str) -> str:
    return os.path.normpath(os.path.expanduser(os.path.expandvars(ruta)))


def formatear_bytes(valor: Optional[float]) -> str:
    if valor is None:
        return "N/A"
    valor = float(valor)
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if valor < 1024 or unidad == "TB":
            return f"{valor:.1f} {unidad}"
        valor /= 1024
    return f"{valor:.1f} TB"


def formatear_tiempo(segundos: Optional[float]) -> str:
    if segundos is None:
        return "--"
    s = int(segundos)
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


def sanitizar_nombre(texto: str) -> str:
    limpio = re.sub(r"[^A-Za-z0-9_-]", "_", texto.strip())
    return limpio[:64] if limpio else "backup"


def obtener_usuario_equipo() -> Tuple[str, str]:
    usuario = os.environ.get("USERNAME") or os.environ.get("USER") or "usuario"
    equipo = platform.node() or "equipo"
    return sanitizar_nombre(usuario), sanitizar_nombre(equipo)
