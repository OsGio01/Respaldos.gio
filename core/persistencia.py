#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistencia local del programa (JSON, registro de nombres y ultima ruta)."""
import json
import os
from datetime import datetime
from typing import Set, Optional

from core.constantes import RUTA_NOMBRES_GENERADOS, RUTA_ULTIMO_RESPALDO


def cargar_json(ruta: str, valor_default):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return valor_default


def guardar_json(ruta: str, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)
    os.replace(tmp, ruta)


class RegistroNombres:
    """Registro de nombres base (sin .zip) de los respaldos creados por el programa."""

    def __init__(self, ruta: str = RUTA_NOMBRES_GENERADOS):
        self.ruta = ruta

    def todos(self) -> Set[str]:
        return set(cargar_json(self.ruta, []))

    def agregar(self, nombre: str) -> None:
        nombres = cargar_json(self.ruta, [])
        if nombre not in nombres:
            nombres.append(nombre)
            self._guardar(nombres)

    def quitar(self, nombre: str) -> None:
        nombres = cargar_json(self.ruta, [])
        if nombre in nombres:
            nombres.remove(nombre)
            self._guardar(nombres)

    def _guardar(self, nombres) -> None:
        try:
            guardar_json(self.ruta, nombres)
        except OSError:
            pass


registro_nombres = RegistroNombres()


def guardar_ultima_ruta(carpeta_destino: str, tipo: str) -> None:
    try:
        with open(RUTA_ULTIMO_RESPALDO, "w", encoding="utf-8") as f:
            f.write(f"Ultima respaldo: {carpeta_destino}\n")
            f.write(f"Tipo: {tipo}\n")
            f.write(f"Fecha: {datetime.now().isoformat()}\n")
    except OSError:
        pass


def leer_ultima_ruta() -> Optional[str]:
    try:
        with open(RUTA_ULTIMO_RESPALDO, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None
