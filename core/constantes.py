#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rutas y constantes del programa Respaldos.Gio (nucleo v6.2).

Aqui se decide de donde lee el programa y donde escribe:

  - RECURSOS: cosas de solo lectura que vienen con el programa (las imagenes).
    En un .exe o un .pyz se extraen a una carpeta temporal; desde el codigo
    fuente es la raiz del proyecto.
  - DATOS: cosas escribibles (config, estados, respaldos, registros). Van a la
    carpeta de datos del sistema (Windows: %APPDATA%, Linux: ~/.config,
    macOS: ~/Library/Application Support) porque un .pyz o un ejecutable
    pueden estar en una carpeta de solo lectura (/usr/share, Program Files).
"""
import os
import struct
import sys

VERSION_PROGRAMA = "6.2"
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


def _detectar_zipapp(ruta: str):
    """Si el modulo vive dentro de un .pyz, devuelve la ruta del zip.

    Dentro de un zipapp el __file__ es algo como /ruta/Respaldos.pyz/core,
    que no existe en disco. Subiendo niveles se llega al .pyz, que si existe.
    """
    actual = ruta
    for _ in range(8):
        if os.path.isfile(actual):
            return actual
        padre = os.path.dirname(actual)
        if padre == actual:
            break
        actual = padre
    return None


def _extraer_recursos_zipapp(zip_path: str, destino: str) -> bool:
    """Saca la carpeta IMG/ del .pyz a una carpeta temporal.

    Devuelve la ruta de la carpeta TEMP (sin el subdirectorio IMG), porque
    RUTA_IMG_DIR le anade "IMG" al final.
    """
    import shutil
    import tempfile
    import zipfile
    try:
        tmp = tempfile.mkdtemp(prefix="respaldos_gio_img_")
        destino_img = os.path.join(tmp, "IMG")
        os.makedirs(destino_img, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            for nombre in z.namelist():
                if not nombre.startswith("IMG/") or nombre.endswith("/"):
                    continue
                destino_final = os.path.join(destino_img, os.path.basename(nombre))
                with z.open(nombre) as origen, open(destino_final, "wb") as salida:
                    shutil.copyfileobj(origen, salida)
        return tmp
    except Exception:
        return False


# --------------------------------------------------------------------------
#  RUTAS
# --------------------------------------------------------------------------
_RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ZIPAPP = _detectar_zipapp(os.path.dirname(os.path.abspath(__file__)))

# Carpeta de datos del sistema (escribible).
try:
    from core import plataforma as _plataforma
    _DIR_DATOS = _plataforma.carpeta_legible() or _RAIZ_PROYECTO
except Exception:
    _DIR_DATOS = _RAIZ_PROYECTO

# Recursos de solo lectura (imagenes).
if getattr(sys, "frozen", False):
    # PyInstaller onefile: los datos van en sys._MEIPASS.
    _DIR_RECURSOS = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
elif _ZIPAPP:
    _DIR_RECURSOS = _extraer_recursos_zipapp(_ZIPAPP, "") or _RAIZ_PROYECTO
else:
    _DIR_RECURSOS = _RAIZ_PROYECTO

# Carpeta base del programa: donde esta el codigo.
if getattr(sys, "frozen", False):
    RUTA_APP = os.path.dirname(sys.executable)
elif _ZIPAPP:
    RUTA_APP = _DIR_DATOS
else:
    RUTA_APP = _RAIZ_PROYECTO

# Carpeta de datos escribibles.
RUTA_DATOS = _DIR_DATOS

RUTA_RESPALDOS = os.path.join(RUTA_DATOS, "Respaldos")
RUTA_CONFIG = os.path.join(RUTA_DATOS, "config.json")
RUTA_ESTADOS = os.path.join(RUTA_DATOS, "estados_respaldo.json")
RUTA_REGISTRO = os.path.join(RUTA_DATOS, "rutas_respaldo.txt")
RUTA_CONFIG_DIR = os.path.join(RUTA_DATOS, "config")
RUTA_CLAVE_RED = os.path.join(RUTA_CONFIG_DIR, "clave_red.key")  # clave de red, fuera del config versionado
RUTA_ESTADOS_DIR = os.path.join(RUTA_DATOS, "estados")
RUTA_NOMBRES_GENERADOS = os.path.join(RUTA_DATOS, "respaldos_generados.json")
RUTA_ULTIMO_RESPALDO = os.path.join(RUTA_DATOS, "ultimo_respaldo.txt")
RUTA_PINNING = os.path.join(RUTA_DATOS, "servidores_conocidos.json")

# Imagenes (de solo lectura, van con el programa).
RUTA_IMG_DIR = os.path.join(_DIR_RECURSOS, "IMG")


def ruta_imagen(nombre: str) -> str:
    """Ruta de una imagen del programa (interface.png, icono.ico, ...)."""
    return os.path.join(RUTA_IMG_DIR, nombre)


def _migrar_config_previo() -> None:
    """Copia el config.json de la version anterior si todavia no hay uno.

    Antes los datos vivian junto al programa (en la raiz del repo o junto al
    .exe). Ahora viven en la carpeta de datos del sistema. Para no perder los
    ajustes del usuario (nivel de compresion, rutas, etc.) el archivo viejo se
    copia al nuevo si el nuevo todavia no existe.
    """
    import shutil
    if os.path.exists(RUTA_CONFIG):
        return
    # Carpeta de donde vienen los datos en la version anterior.
    candidatos = []
    if getattr(sys, "frozen", False):
        candidatos.append(os.path.dirname(sys.executable))
    else:
        candidatos.append(_RAIZ_PROYECTO)
        candidatos.append(os.path.join(_RAIZ_PROYECTO, "core"))
    for carpeta in candidatos:
        if not carpeta or os.path.abspath(carpeta) == os.path.abspath(RUTA_DATOS):
            continue
        viejo = os.path.join(carpeta, "config.json")
        if not os.path.exists(viejo):
            continue
        try:
            shutil.copy2(viejo, RUTA_CONFIG)
            # La lista blanca/negra tambien se migra.
            config_viejo = os.path.join(carpeta, "config")
            if os.path.isdir(config_viejo):
                os.makedirs(RUTA_CONFIG_DIR, exist_ok=True)
                for nombre in ("whitelist.json", "blacklist.json"):
                    origen = os.path.join(config_viejo, nombre)
                    destino = os.path.join(RUTA_CONFIG_DIR, nombre)
                    if os.path.exists(origen) and not os.path.exists(destino):
                        shutil.copy2(origen, destino)
            break
        except OSError:
            pass


_migrar_config_previo()


def _asegurar_directorios() -> None:
    for d in (RUTA_RESPALDOS, RUTA_CONFIG_DIR, RUTA_ESTADOS_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


_asegurar_directorios()
