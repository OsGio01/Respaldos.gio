#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Respaldos.Gio - fachada principal del front de terminal (v6.0).

Delega en el front terminal del nucleo OOP. Toda la logica vive en `core`.
"""
from fronts.terminal import menu_principal


if __name__ == "__main__":
    menu_principal()
