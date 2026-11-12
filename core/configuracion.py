#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuracion del programa (nucleo v6.0 - Programacion Orientada a Objetos)."""
import json
import os
from dataclasses import asdict, dataclass

from core import constantes, persistencia
from core import seguridad


def _validar_campo(nombre: str, valor, default):
    try:
        if nombre in ("comprimir_automatico", "registrar_rutas", "mostrar_progreso",
                      "guardar_estado_respaldos", "auto_ajustar_hilos", "red_usar_tls",
                      "proteger_respaldos", "verificar_hash_al_reanudar"):
            if isinstance(valor, bool):
                return valor
            if isinstance(valor, (int, float)) and valor in (0, 1):
                return bool(valor)
            if isinstance(valor, str):
                v = valor.strip().lower()
                if v in ("true", "1", "sí", "si", "yes", "on"):
                    return True
                if v in ("false", "0", "no", "n", "off"):
                    return False
            return default
        if nombre == "nivel_compresion":
            return max(0, min(9, int(valor)))
        if nombre == "max_archivos_paralelos":
            return max(1, min(64, int(valor)))
        if nombre == "tamano_buffer_mb":
            return max(1, min(64, int(valor)))
        if nombre == "ruta_base_respaldos":
            s = str(valor).strip()
            if not s:
                return default
            return os.path.normpath(os.path.expanduser(os.path.expandvars(s)))
        if nombre == "red_clave":
            clave = str(valor).strip()
            return clave if len(clave) >= constantes.RED_CLAVE_MIN else default
        if nombre in ("red_bind_ip", "adb_path"):
            return str(valor).strip()
        return valor
    except (TypeError, ValueError):
        return default


@dataclass
class Configuracion:
    comprimir_automatico: bool = True
    registrar_rutas: bool = True
    mostrar_progreso: bool = True
    nivel_compresion: int = 6
    max_archivos_paralelos: int = constantes.MAX_WORKERS
    tamano_buffer_mb: int = 8
    guardar_estado_respaldos: bool = True
    auto_ajustar_hilos: bool = True
    ruta_base_respaldos: str = constantes.RUTA_RESPALDOS
    tema_oscuro: bool = False
    red_clave: str = ""
    red_bind_ip: str = ""
    red_usar_tls: bool = True
    adb_path: str = "adb"
    proteger_respaldos: bool = True  # SEG-07: carpeta 0700 / zip 0600 (solo tu usuario)
    verificar_hash_al_reanudar: bool = False  # False = reanudar solo comparando tamaño (mucho más rápido)

    @classmethod
    def cargar(cls, ruta: str = constantes.RUTA_CONFIG) -> "Configuracion":
        datos = persistencia.cargar_json(ruta, None)
        inst = cls()
        if isinstance(datos, dict):
            for k, v in datos.items():
                if k in cls.__annotations__:
                    try:
                        setattr(inst, k, _validar_campo(k, v, getattr(inst, k)))
                    except Exception:
                        pass
        # La clave de red no viaja en el config (se versiona): vive aparte.
        if not inst.red_clave:
            inst.red_clave = seguridad._leer_clave_red(ruta)
        return inst

    def guardar(self, ruta: str = constantes.RUTA_CONFIG) -> None:
        datos = asdict(self)
        clave = datos.get("red_clave", "")
        datos["red_clave"] = ""  # el config queda sin el secreto
        persistencia.guardar_json(ruta, datos)
        seguridad._restringir_permisos(ruta)
        # La clave se guarda en el archivo protegido con permisos restringidos.
        # Con clave vacia no se toca el archivo: borrarla es accion explicita.
        if clave:
            seguridad._guardar_clave_red(clave, ruta)

    def borrar_clave_red(self, ruta: str = constantes.RUTA_CONFIG) -> None:
        """Borra la clave de red guardada (el usuario la limpio a proposito)."""
        self.red_clave = ""
        seguridad._borrar_clave_red(ruta)


def cargar_config(ruta: str = constantes.RUTA_CONFIG) -> Configuracion:
    return Configuracion.cargar(ruta)
