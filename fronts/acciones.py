#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Operaciones compartidas entre fronts (sin impresion).

Devuelven datos crudos para que cada front los presente a su manera
(terminal con prints, escritorio con widgets). La logica de negocio sigue
viviendo en `core`; aqui solo se orquesta sin duplicar codigo.
"""
import os
import shutil
from typing import List, Optional, Tuple

from core import constantes, motor, persistencia


def listar_respaldos(config) -> Tuple[List[Tuple[str, str, int]], Optional[str]]:
    """Respaldos generados por el programa en la ruta base.

    Devuelve (lista, error). Cada elemento es (nombre, ruta_completa, bytes).
    """
    generados = persistencia.registro_nombres.todos()
    base = config.ruta_base_respaldos
    if not os.path.exists(base):
        return [], f"La carpeta {base} no existe."
    respaldos = []
    for item in sorted(os.listdir(base)):
        if motor._quitar_zip(item) not in generados:
            continue
        full = os.path.join(base, item)
        try:
            tam = motor.contar_directorio(full)[1] if os.path.isdir(full) else os.path.getsize(full)
        except OSError:
            continue
        respaldos.append((item, full, tam))
    if not respaldos:
        return [], ("No hay respaldos generados por el programa en esta ruta "
                    "(solo se pueden eliminar los que el propio sistema creo).")
    return respaldos, None


def eliminar_respaldo(nombre: str, ruta: str) -> None:
    """Borra un respaldo generado por el programa y limpia sus registros."""
    if os.path.isdir(ruta):
        shutil.rmtree(ruta)
    else:
        os.remove(ruta)
    persistencia.registro_nombres.quitar(motor._quitar_zip(nombre))
    _limpiar_registro(ruta)


def _limpiar_registro(ruta: str) -> None:
    if not os.path.exists(constantes.RUTA_REGISTRO):
        return
    sin_zip = motor._quitar_zip(ruta)
    try:
        with open(constantes.RUTA_REGISTRO, "r", encoding="utf-8") as f:
            lineas = f.readlines()
        with open(constantes.RUTA_REGISTRO, "w", encoding="utf-8") as f:
            f.writelines(l for l in lineas if sin_zip not in l)
    except OSError:
        pass


def leer_registros() -> Tuple[int, List[str]]:
    """Total de lineas y todas las lineas del registro de respaldos."""
    if not os.path.exists(constantes.RUTA_REGISTRO):
        return 0, []
    try:
        with open(constantes.RUTA_REGISTRO, "r", encoding="utf-8") as f:
            lineas = [l.rstrip("\n") for l in f.readlines()]
    except OSError:
        return 0, []
    return len(lineas), lineas


def resumen_registro(linea: str) -> str:
    """'fecha | TIPO | destino' de una linea del registro (formato terminal)."""
    partes = linea.strip().split("|")
    if len(partes) >= 2:
        tipo = partes[2] if len(partes) > 2 else ""
        return f"{partes[0][:19]} | {tipo.upper()} | {partes[1]}"
    return linea.strip()


def listar_pausados(gestor) -> List[dict]:
    """Respaldos interrumpidos listos para reanudar."""
    salida = []
    for e in gestor.pausados():
        try:
            hechos = len(gestor.leer_hechos(e.id))
        except Exception:
            hechos = 0
        salida.append({
            "estado": e,
            "id": e.id,
            "tipo": e.tipo,
            "origen": e.origen,
            "destino": e.destino,
            "hechos": hechos,
            "total": e.total_archivos,
        })
    return salida


def detalle_pausado(item: dict) -> str:
    origen = item["origen"]
    if len(origen) > 58:
        origen = "..." + origen[-55:]
    return f"{item['tipo']}  -  {origen}  ({item['hechos']}/{item['total']})"
