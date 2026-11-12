#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rutas y constantes del programa Respaldos.Gio (nucleo v6.0)."""
import os
import struct
import sys

VERSION_PROGRAMA = "6.0"
RED_CLAVE_MIN = 12  # SEG-03: longitud minima de la clave de red
MAX_WORKERS = min(32, (os.cpu_count() or 2) * 2)
BUFFER_SIZE = 1024 * 1024
NETWORK_PORT = 56789
MAGIA_RED = b"RGIO1"
ENC_ARCHIVO = struct.Struct("!HQ")
ENC_TOTAL = struct.Struct("!Q")
NETWORK_TIMEOUT_AUTH = 10
NETWORK_TIMEOUT_SERVIDOR_AUTH = 2   # SEG-01: cada intento de auth es corto para no bloquear el accept
NETWORK_ESPERA_SERVIDOR = 600       # SEG-02: el servidor espera clientes hasta 10 min en total
MAX_INTENTOS_AUTH = 3
MAX_FALLOS_POR_IP = 5               # F-04: bloqueo temporal tras N intentos fallidos desde la misma IP
BINDING_TLS_SIN_SOPORTE = False    # F-06: aviso unico si el SO/Python no soporta tls-server-end-point

RUTA_APP = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
RUTA_RESPALDOS = os.path.join(RUTA_APP, "Respaldos")
RUTA_CONFIG = os.path.join(RUTA_APP, "config.json")
RUTA_ESTADOS = os.path.join(RUTA_APP, "estados_respaldo.json")
RUTA_REGISTRO = os.path.join(RUTA_APP, "rutas_respaldo.txt")
RUTA_CONFIG_DIR = os.path.join(RUTA_APP, "config")
RUTA_CLAVE_RED = os.path.join(RUTA_CONFIG_DIR, "clave_red.key")  # clave de red, fuera del config versionado
RUTA_ESTADOS_DIR = os.path.join(RUTA_APP, "estados")
RUTA_NOMBRES_GENERADOS = os.path.join(RUTA_APP, "respaldos_generados.json")
RUTA_ULTIMO_RESPALDO = os.path.join(RUTA_APP, "ultimo_respaldo.txt")
RUTA_PINNING = os.path.join(RUTA_APP, "servidores_conocidos.json")


def _asegurar_directorios() -> None:
    for d in (RUTA_RESPALDOS, RUTA_CONFIG_DIR, RUTA_ESTADOS_DIR):
        os.makedirs(d, exist_ok=True)


_asegurar_directorios()
