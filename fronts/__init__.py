#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fronts del programa Respaldos.Gio (v6.2).

Los imports son perezosos: solo se carga un front cuando se usa. Antes, este
paquete importaba `hud` y `movil` siempre, y como esos modulos hacen
`import tkinter`, el front de TERMINAL tambien exigia tkinter instalado: en un
Linux sin python3-tk el programa no arrancaba, aunque la terminal no lo
necesite.

Con __getattr__ (PEP 562) `from fronts.terminal import menu_principal` solo
carga el modulo terminal, y `import fronts` se queda barato.
"""
import importlib

__all__ = ["acciones", "hud", "hud_paneles", "movil", "terminal", "tema"]


def __getattr__(nombre):
    """Carga el front pedido la primera vez que se usa."""
    if nombre in __all__:
        modulo = importlib.import_module(f"fronts.{nombre}")
        globals()[nombre] = modulo
        return modulo
    raise AttributeError(f"module 'fronts' has no attribute '{nombre}'")


def __dir__():
    return sorted(list(globals().keys()) + __all__)
