#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import errno
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import zipfile
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable, Dict, Iterator, List, NamedTuple, Optional, Set, Tuple

try:
    import psutil
except ImportError:
    psutil = None

# ======================================================================
# RUTAS Y CONSTANTES
# ======================================================================
VERSION_PROGRAMA = "5.0"


def obtener_ruta_base() -> str:
    """Carpeta del ejecutable (si está congelado) o del script."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


RUTA_APP = obtener_ruta_base()
RUTA_RESPALDOS = os.path.join(RUTA_APP, "Respaldos")
RUTA_CONFIG = os.path.join(RUTA_APP, "config.json")
RUTA_ESTADOS = os.path.join(RUTA_APP, "estados_respaldo.json")
RUTA_ESTADOS_DIR = os.path.join(RUTA_APP, "estados")
RUTA_REGISTRO = os.path.join(RUTA_APP, "rutas_respaldo.txt")
RUTA_CONFIG_DIR = os.path.join(RUTA_APP, "config")
RUTA_NOMBRES_GENERADOS = os.path.join(RUTA_APP, "respaldos_generados.json")
RUTA_ULTIMO_RESPALDO = os.path.join(RUTA_APP, "ultimo_respaldo.txt")

for _d in (RUTA_RESPALDOS, RUTA_CONFIG_DIR, RUTA_ESTADOS_DIR):
    os.makedirs(_d, exist_ok=True)

MAX_WORKERS = min(32, (os.cpu_count() or 2) * 2)
BUFFER_SIZE = 1024 * 1024
NETWORK_PORT = 56789
MAGIA_RED = b"RGIO1"

EXTENSIONES_RESPALDO = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf",
    ".jpg", ".jpeg", ".png", ".gif", ".mp3", ".mp4", ".py", ".js", ".html", ".css",
    ".java", ".cpp", ".c", ".m", ".mm", ".plist", ".strings",
}
EXT_YA_COMPRIMIDAS = {
    ".zip", ".rar", ".7z", ".gz", ".bz2", ".xz", ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".pdf", ".jar", ".apk",
}

# ======================================================================
# UTILIDADES
# ======================================================================
UNICODE_SUPPORT = False
try:
    if "--ascii" not in sys.argv and sys.stdout.encoding and "UTF" in sys.stdout.encoding.upper():
        UNICODE_SUPPORT = True
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def icono(texto_emoji: str, texto_fallback: str) -> str:
    return texto_emoji if UNICODE_SUPPORT else texto_fallback


def limpiar_terminal():
    try:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    except Exception:
        os.system("cls" if platform.system() == "Windows" else "clear")


def pausa():
    input("Presiona ENTER para continuar...")


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


def motivo_corto(e: BaseException) -> str:
    if isinstance(e, PermissionError):
        return "sin permisos"
    if isinstance(e, FileNotFoundError):
        return "ya no existe"
    if _es_disco_lleno(e):
        return "disco de destino lleno"
    return str(e)[:80]


def _es_disco_lleno(e: BaseException) -> bool:
    return isinstance(e, OSError) and (e.errno == errno.ENOSPC or getattr(e, "winerror", None) == 112)


def mensaje_error_amigable(e: Exception) -> str:
    if isinstance(e, PermissionError):
        return ("No se pudo completar la operación porque no hay permisos suficientes para acceder a algunos "
                "archivos o carpetas. Intenta ejecutar el programa como administrador o revisa los permisos.")
    if isinstance(e, FileNotFoundError):
        return ("No se pudo completar la operación porque una de las rutas ya no existe. Verifica que el disco, "
                "USB o carpeta siga conectado y disponible.")
    if _es_disco_lleno(e):
        return "No hay suficiente espacio en el disco de destino. Libera espacio o elige otra ubicación."
    if isinstance(e, (ConnectionError, socket.timeout, socket.gaierror)):
        return "Se perdió la conexión de red durante la transferencia. Verifica que ambos equipos sigan en la misma red."
    return f"Ocurrió un problema inesperado ({e}). Si había un respaldo en curso quedó pausado y puede reanudarse desde el menú."


def obtener_info_sistema() -> Dict:
    usuario, equipo = obtener_usuario_equipo()
    memoria_total = memoria_disponible = cpu_uso = cpu_fisico = None
    cpu_logico = os.cpu_count() or 1
    if psutil:
        try:
            mem = psutil.virtual_memory()
            memoria_total, memoria_disponible = mem.total, mem.available
            cpu_uso = psutil.cpu_percent(interval=0.2)
            cpu_logico = psutil.cpu_count(logical=True) or cpu_logico
            cpu_fisico = psutil.cpu_count(logical=False) or cpu_logico
        except Exception:
            pass
    return {
        "usuario": usuario, "equipo": equipo,
        "sistema": f"{platform.system()} {platform.release()}",
        "arquitectura": platform.architecture()[0],
        "cpu_logico": cpu_logico, "cpu_fisico": cpu_fisico, "cpu_uso": cpu_uso,
        "memoria_total": memoria_total, "memoria_disponible": memoria_disponible,
    }


def obtener_info_disco(ruta: str) -> Dict:
    datos = {"ruta": ruta, "total_bytes": None, "free_bytes": None, "percent": None}
    try:
        uso = shutil.disk_usage(ruta)
        datos.update({"total_bytes": uso.total, "free_bytes": uso.free,
                      "percent": round(uso.used * 100 / uso.total, 1) if uso.total else None})
    except Exception:
        pass
    return datos


def calcular_hilos_optimos(config) -> int:
    max_threads = min(64, config.max_archivos_paralelos or MAX_WORKERS)
    if not config.auto_ajustar_hilos or not psutil:
        return max_threads
    try:
        cpu_pct = psutil.cpu_percent(interval=None)
        mem_pct = psutil.virtual_memory().percent
        nucleos = psutil.cpu_count(logical=True) or (os.cpu_count() or 1)
        base = max(1, int(nucleos * 0.8))
        valor = base // 2 if (cpu_pct > 70 or mem_pct > 80) else base
        return max(1, min(max_threads, valor))
    except Exception:
        return max_threads


def ajustar_prioridad_proceso(reducir: bool):
    if not psutil:
        return
    try:
        proceso = psutil.Process(os.getpid())
        if platform.system() == "Windows":
            clase = "BELOW_NORMAL_PRIORITY_CLASS" if reducir else "NORMAL_PRIORITY_CLASS"
            if hasattr(psutil, clase):
                proceso.nice(getattr(psutil, clase))
        else:
            proceso.nice(10 if reducir else 0)
    except Exception:
        pass


# ======================================================================
# PERSISTENCIA
# ======================================================================
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
    def __init__(self, ruta: str = RUTA_NOMBRES_GENERADOS):
        self.ruta = ruta

    def todos(self) -> Set[str]:
        return set(cargar_json(self.ruta, []))

    def agregar(self, nombre: str):
        nombres = cargar_json(self.ruta, [])
        if nombre not in nombres:
            nombres.append(nombre)
            self._guardar(nombres)

    def quitar(self, nombre: str):
        nombres = cargar_json(self.ruta, [])
        if nombre in nombres:
            nombres.remove(nombre)
            self._guardar(nombres)

    def _guardar(self, nombres):
        try:
            guardar_json(self.ruta, nombres)
        except OSError:
            pass


registro_nombres = RegistroNombres()


def guardar_ultima_ruta(carpeta_destino: str, tipo: str):
    try:
        with open(RUTA_ULTIMO_RESPALDO, "w", encoding="utf-8") as f:
            f.write(f"Último respaldo: {carpeta_destino}\nTipo: {tipo}\nFecha: {datetime.now().isoformat()}\n")
    except OSError:
        pass


def leer_ultima_ruta() -> Optional[str]:
    try:
        with open(RUTA_ULTIMO_RESPALDO, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _validar_campo(nombre: str, valor, default):
    """Corrige un valor de config si está fuera de rango o tiene tipo incorrecto."""
    try:
        if nombre in ("comprimir_automatico", "registrar_rutas", "mostrar_progreso",
                        "guardar_estado_respaldos", "auto_ajustar_hilos", "tema_oscuro",
                        "red_usar_tls"):
            return bool(valor)
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
        if nombre in ("red_clave", "red_bind_ip", "adb_path"):
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
    max_archivos_paralelos: int = MAX_WORKERS
    tamano_buffer_mb: int = 8
    guardar_estado_respaldos: bool = True
    auto_ajustar_hilos: bool = True
    ruta_base_respaldos: str = RUTA_RESPALDOS
    tema_oscuro: bool = False
    # --- Nuevos campos de seguridad ---
    red_clave: str = ""
    red_bind_ip: str = ""
    red_usar_tls: bool = True
    adb_path: str = "adb"

    @classmethod
    def cargar(cls, ruta: str = RUTA_CONFIG) -> "Configuracion":
        datos = cargar_json(ruta, None)
        inst = cls()
        if not isinstance(datos, dict):
            return inst
        for k, v in datos.items():
            if k in cls.__annotations__:
                try:
                    setattr(inst, k, _validar_campo(k, v, getattr(inst, k)))
                except Exception:
                    pass
        return inst

    def guardar(self, ruta: str = RUTA_CONFIG):
        guardar_json(ruta, asdict(self))


@dataclass
class EstadoRespaldo:
    id: str
    origen: str
    destino: str
    tipo: str
    total_archivos: int
    procesados: int = 0
    archivos_completados: List[str] = None
    archivos_pendientes: List[str] = None
    fecha_inicio: str = ""
    fecha_pausa: str = ""
    activo: bool = False
    total_bytes: int = 0

    def __post_init__(self):
        self.archivos_completados = self.archivos_completados or []
        self.archivos_pendientes = self.archivos_pendientes or []


class RegistroHechos:
    def __init__(self, ruta: str):
        self._f = open(ruta, "a", encoding="utf-8")
        self._lock = threading.Lock()
        self._n = 0

    def marcar(self, rel: str):
        with self._lock:
            self._f.write(json.dumps(rel) + "\n")
            self._n += 1
            if self._n % 200 == 0:
                self._f.flush()
                try:
                    os.fsync(self._f.fileno())
                except OSError:
                    pass

    def cerrar(self):
        with self._lock:
            try:
                self._f.flush()
                self._f.close()
            except OSError:
                pass


class GestorEstados:
    def __init__(self, archivo: str = RUTA_ESTADOS):
        self.archivo = archivo
        self.estados = self._cargar()

    def _cargar(self) -> Dict[str, EstadoRespaldo]:
        data = cargar_json(self.archivo, {})
        try:
            return {k: EstadoRespaldo(**v) for k, v in data.items()}
        except TypeError:
            return {}

    def guardar(self):
        guardar_json(self.archivo, {k: asdict(v) for k, v in self.estados.items()})

    def ruta_manifiesto(self, id_res: str) -> str:
        return os.path.join(RUTA_ESTADOS_DIR, id_res + ".manifest.jsonl")

    def ruta_hechos(self, id_res: str) -> str:
        return os.path.join(RUTA_ESTADOS_DIR, id_res + ".hechos.jsonl")

    def escribir_manifiesto(self, id_res: str, items):
        with open(self.ruta_manifiesto(id_res), "w", encoding="utf-8") as f:
            for origen, rel, size in items:
                f.write(json.dumps([origen, rel, size]) + "\n")

    def leer_manifiesto(self, id_res: str) -> Iterator[Tuple[str, str, int]]:
        with open(self.ruta_manifiesto(id_res), "r", encoding="utf-8") as f:
            for linea in f:
                try:
                    o, r, s = json.loads(linea)
                    yield (o, r, s)
                except ValueError:
                    continue

    def leer_hechos(self, id_res: str) -> Set[str]:
        hechos = set()
        try:
            with open(self.ruta_hechos(id_res), "r", encoding="utf-8") as f:
                for linea in f:
                    try:
                        hechos.add(json.loads(linea))
                    except ValueError:
                        continue
        except OSError:
            pass
        return hechos

    def crear_estado(self, origen, destino, tipo, total_archivos, total_bytes) -> EstadoRespaldo:
        id_res = f"{tipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hashlib.sha1(origen.encode('utf-8', 'replace')).hexdigest()[:8]}"
        estado = EstadoRespaldo(id=id_res, origen=origen, destino=destino, tipo=tipo,
                                total_archivos=total_archivos, total_bytes=total_bytes,
                                fecha_inicio=datetime.now().isoformat(), activo=True)
        self.estados[id_res] = estado
        self.guardar()
        return estado

    def completar(self, id_res: str):
        self.estados.pop(id_res, None)
        self.guardar()
        for ruta in (self.ruta_manifiesto(id_res), self.ruta_hechos(id_res)):
            try:
                os.remove(ruta)
            except OSError:
                pass

    def pausar(self, id_res: str):
        e = self.estados.get(id_res)
        if e:
            e.activo = False
            e.fecha_pausa = datetime.now().isoformat()
            self.guardar()

    def reanudar(self, id_res: str) -> Optional[EstadoRespaldo]:
        e = self.estados.get(id_res)
        if e:
            e.activo = True
            e.fecha_pausa = ""
            self.guardar()
        return e

    def pausados(self) -> List[EstadoRespaldo]:
        return [e for e in self.estados.values() if not e.activo]


# ======================================================================
# FILTRO DE RUTAS Y ESCANEO
# ======================================================================
class FiltroRutas:
    def __init__(self, config_dir: str = RUTA_CONFIG_DIR):
        self.config_dir = config_dir
        self.blacklist = self._cargar_lista("blacklist.json", self._blacklist_default())
        self.whitelist = self._cargar_lista("whitelist.json", self._whitelist_default())
        self._compilar()

    @staticmethod
    def _blacklist_default() -> List[str]:
        return [
            "$RECYCLE.BIN", "System Volume Information", ".Trash", ".Spotlight-V100",
            ".fseventsd", "Caches", "Logs", "AppData", "ProgramData", "Windows",
            "System32", "WinSxS", "Program Files", "Program Files (x86)",
            "boot", "dev", "proc", "sys", "lost+found",
            "Library/Caches", "Library/Logs", "Library/Preferences",
            "var/tmp",
        ]

    @staticmethod
    def _whitelist_default() -> List[str]:
        home = os.path.expanduser("~")
        nombres = ["Documents", "Documentos", "Desktop", "Escritorio", "Downloads", "Descargas",
                    "Music", "Música", "Pictures", "Imágenes", "Videos", "Vídeos", "Development", "Projects"]
        return [os.path.join(home, n) for n in nombres] + [
            "/Applications/XAMPP/htdocs", os.path.expanduser("~/Applications/XAMPP/htdocs")]

    def _cargar_lista(self, archivo: str, defaults: List[str]) -> List[str]:
        ruta = os.path.join(self.config_dir, archivo)
        data = cargar_json(ruta, None)
        if isinstance(data, list):
            return data
        try:
            guardar_json(ruta, defaults)
        except OSError:
            pass
        return defaults

    def _compilar(self):
        self._wl = [os.path.normpath(w).lower() for w in self.whitelist]
        self._bl_nombres: Set[str] = set()
        self._bl_rutas: List[str] = []
        for b in self.blacklist:
            partes = [p for p in re.split(r"[\\/]", b.lower()) if p]
            if len(partes) == 1:
                self._bl_nombres.add(partes[0])
            elif partes:
                self._bl_rutas.append("/" + "/".join(partes))

    def en_whitelist(self, ruta: str) -> bool:
        r = os.path.normpath(ruta).lower()
        for w in self._wl:
            if r == w or r.startswith(w + os.sep):
                return True
        return False

    def excluir_dir(self, nombre: str, ruta: str) -> bool:
        if nombre.lower() in self._bl_nombres:
            return True
        if self._bl_rutas:
            r = "/" + ruta.lower().replace("\\", "/").strip("/")
            for p in self._bl_rutas:
                if r.endswith(p):
                    return True
        return False

    def excluir_archivo(self, nombre: str) -> bool:
        return nombre.lower() in self._bl_nombres


filtro = FiltroRutas()


class Escaner:
    def __init__(self, filtro_rutas: Optional[FiltroRutas] = None):
        self.filtro = filtro_rutas or filtro
        self.omitidas: List[Tuple[str, str]] = []

    def recorrer(self, raiz: str, extensiones: Optional[Set[str]] = None) -> Iterator[Tuple[str, str, int]]:
        f = self.filtro
        pila = [(raiz, "", f.en_whitelist(raiz))]
        while pila:
            ruta, rel_dir, protegida = pila.pop()
            try:
                with os.scandir(ruta) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if protegida:
                                    pila.append((e.path, rel_dir + e.name + os.sep, True))
                                elif not f.excluir_dir(e.name, e.path):
                                    pila.append((e.path, rel_dir + e.name + os.sep, f.en_whitelist(e.path)))
                            elif e.is_file(follow_symlinks=False):
                                if not protegida and f.excluir_archivo(e.name):
                                    continue
                                if extensiones is not None and os.path.splitext(e.name)[1].lower() not in extensiones:
                                    continue
                                yield (e.path, rel_dir + e.name, e.stat(follow_symlinks=False).st_size)
                        except OSError:
                            continue
            except OSError as exc:
                self.omitidas.append((ruta, motivo_corto(exc)))


# ======================================================================
# PROGRESO Y MONITOR DE RECURSOS
# ======================================================================
class Progreso:
    def __init__(self, total_archivos: int, total_bytes: int = 0, descripcion: str = "Progreso", silencioso: bool = False):
        self.total_archivos = total_archivos
        self.total_bytes = total_bytes
        self.descripcion = descripcion
        self.silencioso = silencioso
        self.archivos = 0
        self.bytes_copiados = 0
        self.bytes_saltados = 0
        self._lock = threading.Lock()
        self.inicio = time.monotonic()
        self._ultimo = 0.0
        self._largo = 0

    def sumar_bytes(self, n: int):
        with self._lock:
            self.bytes_copiados += n

    def archivo_listo(self, bytes_saltados: int = 0):
        self.archivos += 1
        self.bytes_saltados += bytes_saltados

    def _fraccion(self) -> float:
        if self.total_bytes > 0:
            return min(1.0, (self.bytes_copiados + self.bytes_saltados) / self.total_bytes)
        if self.total_archivos > 0:
            return min(1.0, self.archivos / self.total_archivos)
        return 1.0

    def mostrar(self, forzar: bool = False):
        if self.silencioso:
            return
        ahora = time.monotonic()
        if not forzar and ahora - self._ultimo < 0.25:
            return
        self._ultimo = ahora
        frac = self._fraccion()
        transcurrido = max(ahora - self.inicio, 0.001)
        velocidad = self.bytes_copiados / transcurrido
        if self.total_bytes > 0 and velocidad > 0:
            eta = (self.total_bytes - self.bytes_copiados - self.bytes_saltados) / velocidad
        elif frac > 0:
            eta = transcurrido * (1 - frac) / frac
        else:
            eta = None
        ancho = 24
        llenos = int(ancho * frac)
        barra = ("█" * llenos + "░" * (ancho - llenos)) if UNICODE_SUPPORT else ("#" * llenos + "-" * (ancho - llenos))
        linea = (f"{self.descripcion}: [{barra}] {frac:5.1%} {self.archivos}/{self.total_archivos} "
                    f"{formatear_bytes(velocidad)}/s ETA {formatear_tiempo(max(eta, 0) if eta is not None else None)}")
        columnas = shutil.get_terminal_size((80, 20)).columns - 1
        linea = linea[:columnas]
        sys.stdout.write("\r" + linea.ljust(self._largo))
        sys.stdout.flush()
        self._largo = len(linea)

    def cerrar(self):
        self.mostrar(forzar=True)
        if not self.silencioso:
            print()
        print(f"{icono('✅', 'OK')} Completado en {time.monotonic() - self.inicio:.1f}s")


class MonitorRecursos(threading.Thread):
    """Si el equipo va justo de CPU/RAM/disco, frena un poco la copia para no estorbar al usuario."""
    INTERVALO = 2.0

    def __init__(self, bytes_propios: Callable[[], int]):
        super().__init__(daemon=True)
        self._bytes_propios = bytes_propios
        self._detener = threading.Event()
        self.delay = 0.0
        self.prioridad_reducida = False
        self.carga_alta = False

    @staticmethod
    def _io_disco() -> Optional[int]:
        try:
            c = psutil.disk_io_counters()
            return (c.read_bytes + c.write_bytes) if c else None
        except Exception:
            return None

    def run(self):
        try:
            yo = psutil.Process(os.getpid())
            yo.cpu_percent(None)
            psutil.cpu_percent(None)
        except Exception:
            yo = None
        nucleos = psutil.cpu_count(logical=True) or 1
        t_prev = time.monotonic()
        io_prev = self._io_disco()
        propios_prev = self._bytes_propios()
        while not self._detener.wait(self.INTERVALO):
            try:
                ahora = time.monotonic()
                dt = max(ahora - t_prev, 0.001)
                cpu_total = psutil.cpu_percent(None)
                cpu_propio = (yo.cpu_percent(None) / nucleos) if yo else 0.0
                cpu = max(0.0, cpu_total - cpu_propio)
                mem = psutil.virtual_memory().percent
                io = self._io_disco()
                propios = self._bytes_propios()
                io_ajeno = 0.0
                if io is not None and io_prev is not None:
                    io_ajeno = max(0.0, (io - io_prev) / dt - 2 * (propios - propios_prev) / dt)
                t_prev, io_prev, propios_prev = ahora, io, propios
                if self._detener.is_set():
                    break
                if cpu > 70 or mem > 80 or io_ajeno > 50 * 1024 * 1024:
                    self.delay = min(2.0, max(0.2, (cpu - 50) / 30))
                    if not self.prioridad_reducida:
                        ajustar_prioridad_proceso(reducir=True)
                        self.prioridad_reducida = True
                    self.carga_alta = True
                else:
                    self.delay = 0.0
                    if self.prioridad_reducida:
                        ajustar_prioridad_proceso(reducir=False)
                        self.prioridad_reducida = False
                    self.carga_alta = False
            except Exception:
                pass

    def stop(self):
        self._detener.set()
        try:
            self.join(timeout=3)
        except Exception:
            pass
        if self.prioridad_reducida:
            ajustar_prioridad_proceso(reducir=False)
            self.prioridad_reducida = False


# ======================================================================
# COPIA PARALELA
# ======================================================================
class _Cancelado(Exception):
    pass


@dataclass
class ResultadoCopia:
    copiados: int = 0
    duplicados: int = 0
    bytes_copiados: int = 0
    errores: List[Tuple[str, str]] = field(default_factory=list)


class CopiadorParalelo:
    def __init__(self, base: str, progreso: Progreso, monitor: Optional[MonitorRecursos] = None,
                    hechos: Optional[RegistroHechos] = None):
        self.base = base
        self.progreso = progreso
        self.monitor = monitor
        self.hechos = hechos
        self._cancelar = threading.Event()
        self._tls = threading.local()
        self._fatal: Optional[BaseException] = None

    def _buffer(self) -> bytearray:
        buf = getattr(self._tls, "buf", None)
        if buf is None:
            buf = self._tls.buf = bytearray(BUFFER_SIZE)
        return buf

    @staticmethod
    def _borrar(ruta: str):
        try:
            os.remove(ruta)
        except OSError:
            pass

    def _copiar_uno(self, item):
        origen, rel, size = item
        if self._cancelar.is_set():
            return (rel, "cancelado", 0, None)
        mon = self.monitor
        if mon is not None and mon.delay > 0 and self._cancelar.wait(mon.delay):
            return (rel, "cancelado", 0, None)
        destino = os.path.join(self.base, rel)
        tmp = destino + ".part"
        try:
            try:
                st = os.stat(destino)
                origen_mtime = os.path.getmtime(origen)
                if st.st_size == size:
                    diff = abs(st.st_mtime - origen_mtime)
                    reciente = (time.time() - origen_mtime) < 60
                    if diff < 0.001 or (not reciente and diff < 2):
                        return (rel, "duplicado", size, None)
            except FileNotFoundError:
                pass
            buf = self._buffer()
            vista = memoryview(buf)
            copiado = 0
            with open(origen, "rb", buffering=0) as src, open(tmp, "wb") as dst:
                while True:
                    if self._cancelar.is_set():
                        raise _Cancelado()
                    n = src.readinto(buf)
                    if not n:
                        break
                    dst.write(vista[:n])
                    copiado += n
                    self.progreso.sumar_bytes(n)
            try:
                shutil.copystat(origen, tmp)
            except OSError:
                pass
            os.replace(tmp, destino)
            return (rel, "ok", copiado, None)
        except _Cancelado:
            self._borrar(tmp)
            return (rel, "cancelado", 0, None)
        except Exception as e:
            self._borrar(tmp)
            return (rel, "error", 0, e)

    def _procesar(self, resultado, res: ResultadoCopia):
        rel, estado, tam, extra = resultado
        if estado == "ok":
            res.copiados += 1
            res.bytes_copiados += tam
            self.progreso.archivo_listo()
            if self.hechos:
                self.hechos.marcar(rel)
        elif estado == "duplicado":
            res.duplicados += 1
            self.progreso.archivo_listo(bytes_saltados=tam)
            if self.hechos:
                self.hechos.marcar(rel)
        elif estado == "error":
            res.errores.append((rel, motivo_corto(extra)))
            self.progreso.archivo_listo()
            if _es_disco_lleno(extra):
                self._fatal = extra
                self._cancelar.set()

    def copiar(self, items: List[Tuple[str, str, int]], hilos: int) -> ResultadoCopia:
        res = ResultadoCopia()
        for d in {os.path.dirname(os.path.join(self.base, rel)) for _, rel, _ in items}:
            os.makedirs(d, exist_ok=True)
        it = iter(items)
        en_vuelo = set()
        limite = max(2, hilos * 4)
        ex = ThreadPoolExecutor(max_workers=hilos)
        try:
            while self._fatal is None:
                while len(en_vuelo) < limite:
                    item = next(it, None)
                    if item is None:
                        break
                    en_vuelo.add(ex.submit(self._copiar_uno, item))
                if not en_vuelo:
                    break
                listos, en_vuelo = wait(en_vuelo, timeout=0.5, return_when=FIRST_COMPLETED)
                for fut in listos:
                    self._procesar(fut.result(), res)
                self.progreso.mostrar()
        except BaseException:
            self._cancelar.set()
            raise
        finally:
            ex.shutdown(wait=True)
        if self._fatal is not None:
            raise self._fatal
        return res


def comprimir_respaldo(carpeta: str, nivel: int = 6) -> Optional[str]:
    zip_path = carpeta + ".zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=nivel) as zf:
            for raiz, _, archivos in os.walk(carpeta):
                for nombre in archivos:
                    completa = os.path.join(raiz, nombre)
                    ya_comprimido = os.path.splitext(nombre)[1].lower() in EXT_YA_COMPRIMIDAS
                    tipo = zipfile.ZIP_STORED if (ya_comprimido or nivel == 0) else zipfile.ZIP_DEFLATED
                    zf.write(completa, os.path.relpath(completa, carpeta), compress_type=tipo)
        shutil.rmtree(carpeta)
        print(f"{icono('✅', 'OK')} Comprimido: {zip_path}")
        return zip_path
    except Exception as e:
        print(f"{icono('❌', 'ERROR')} Error comprimiendo: {e}")
        try:
            os.remove(zip_path)
        except OSError:
            pass
        return None


# ======================================================================
# REGISTRO, METADATOS Y RESUMEN
# ======================================================================
def registrar_respaldo(ruta: str, tipo: str, detalles: str, config: Configuracion):
    if config.registrar_rutas:
        with open(RUTA_REGISTRO, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}|{ruta}|{tipo}|{detalles}\n")


def crear_carpeta_respaldo(base: str) -> str:
    usuario, equipo = obtener_usuario_equipo()
    nombre = sanitizar_nombre(f"{usuario}_{equipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    carpeta = os.path.join(base, nombre)
    contador = 1
    while os.path.exists(carpeta) or os.path.exists(carpeta + ".zip"):
        carpeta = os.path.join(base, f"{nombre}_{contador}")
        contador += 1
    os.makedirs(carpeta, exist_ok=True)
    registro_nombres.agregar(os.path.basename(carpeta))
    return carpeta


def generar_metadatos_respaldo(origen, destino, tipo, total_archivos, tam_total, duracion, estado, config,
                                info: Dict, extra: Optional[Dict] = None) -> Dict:
    primer_origen = origen.split(" + ")[0] if isinstance(origen, str) else str(origen)
    meta = {
        "fecha_ejecucion": datetime.now().isoformat(),
        "usuario": info["usuario"], "equipo": info["equipo"],
        "sistema_operativo": info["sistema"], "arquitectura": info["arquitectura"],
        "cpu_logico": info["cpu_logico"], "cpu_fisico": info["cpu_fisico"],
        "cpu_uso_inicial": info["cpu_uso"],
        "memoria_total_bytes": info["memoria_total"],
        "memoria_disponible_inicial_bytes": info["memoria_disponible"],
        "origen": origen, "destino": destino,
        "disco_origen": obtener_info_disco(primer_origen),
        "disco_destino": obtener_info_disco(destino),
        "tipo_respaldo": tipo,
        "total_archivos": total_archivos,
        "tamano_total_bytes": tam_total,
        "tamano_total_human": formatear_bytes(tam_total),
        "duracion_segundos": round(duracion, 2),
        "estado_final": estado,
        "version_programa": VERSION_PROGRAMA,
        "configuracion": {
            "comprimir_automatico": config.comprimir_automatico,
            "nivel_compresion": config.nivel_compresion,
            "max_archivos_paralelos": config.max_archivos_paralelos,
            "auto_ajustar_hilos": config.auto_ajustar_hilos,
            "ruta_base_respaldos": config.ruta_base_respaldos,
        },
    }
    if extra:
        meta.update(extra)
    return meta


def guardar_metadatos_respaldo(destino: str, metadatos: Dict):
    try:
        with open(os.path.join(destino, "backup_info.json"), "w", encoding="utf-8") as f:
            json.dump(metadatos, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(icono("⚠️ ", "[AVISO] ") + "Error guardando metadata:", e)


def imprimir_resumen_sistema(info: Dict, origen: Optional[str] = None, destino: Optional[str] = None):
    print("\n" + "=" * 70)
    print(f"{icono('💻', '[SYS]')} Equipo: {info['equipo']} | Usuario: {info['usuario']}")
    print(f"Sistema operativo: {info['sistema']} | Arquitectura: {info['arquitectura']}")
    if info["cpu_fisico"]:
        print(f"CPU: {info['cpu_fisico']} físicos / {info['cpu_logico']} lógicos | Uso inicial: {info['cpu_uso'] or 0:.1f}%")
    else:
        print(f"CPU: {info['cpu_logico']} hilos | Uso inicial: {info['cpu_uso'] or 0:.1f}%")
    print(f"RAM instalada: {formatear_bytes(info['memoria_total'])} | Disponible: {formatear_bytes(info['memoria_disponible'])}")
    for etiqueta, ruta in (("Origen", origen), ("Destino", destino)):
        if ruta:
            d = obtener_info_disco(ruta)
            usado = f"{d['percent']:.0f}% usado" if d["percent"] is not None else "N/A"
            print(f"{etiqueta}: {ruta}\n  Disco libre: {formatear_bytes(d['free_bytes'])} ({usado})")
    print(f"Versión Respaldos.Gio: {VERSION_PROGRAMA}")
    print("=" * 70)


def contar_directorio(carpeta: str) -> Tuple[int, int]:
    n = tam = 0
    for raiz, _, archivos in os.walk(carpeta):
        for a in archivos:
            try:
                tam += os.path.getsize(os.path.join(raiz, a))
                n += 1
            except OSError:
                pass
    return n, tam


# ======================================================================
# MOTOR DE RESPALDO
# ======================================================================
@dataclass
class Plan:
    tipo: str
    origen_txt: str
    archivos: List[Tuple[str, str, int]]
    detalle: str = ""
    omitidas: List[Tuple[str, str]] = field(default_factory=list)


class MotorRespaldo:
    def __init__(self, config: Configuracion, gestor: GestorEstados):
        self.config = config
        self.gestor = gestor

    def ejecutar(self, plan: Plan, base_destino: str) -> Optional[ResultadoCopia]:
        carpeta = crear_carpeta_respaldo(base_destino)
        estado = None
        if self.config.guardar_estado_respaldos:
            total_bytes = sum(s for _, _, s in plan.archivos)
            estado = self.gestor.crear_estado(plan.origen_txt, carpeta, plan.tipo, len(plan.archivos), total_bytes)
            self.gestor.escribir_manifiesto(estado.id, plan.archivos)
        return self._correr(plan.archivos, carpeta, plan.tipo, plan.origen_txt, estado, "Copiando",
                            plan.detalle, plan.omitidas)

    def reanudar(self, estado: EstadoRespaldo) -> Optional[ResultadoCopia]:
        if not os.path.exists(self.gestor.ruta_manifiesto(estado.id)):
            print("Este respaldo viene de una versión anterior y no tiene la lista de archivos necesaria "
                    "para reanudarlo con exactitud. Se descarta el aviso (lo ya copiado sigue en su carpeta).")
            self.gestor.completar(estado.id)
            return None
        if not os.path.isdir(estado.destino):
            print("La carpeta de ese respaldo ya no existe (¿se movió, se comprimió o se borró?). Se descarta el aviso.")
            self.gestor.completar(estado.id)
            return None
        hechos = self.gestor.leer_hechos(estado.id)
        pendientes = [it for it in self.gestor.leer_manifiesto(estado.id) if it[1] not in hechos]
        if not pendientes:
            print("No hay archivos pendientes. El respaldo ya estaba completo.")
            self.gestor.completar(estado.id)
            return None
        print(f"Archivos pendientes: {len(pendientes)}")
        self.gestor.reanudar(estado.id)
        return self._correr(pendientes, estado.destino, estado.tipo, estado.origen, estado, "Reanudando",
                            total_archivos=estado.total_archivos)

    def _correr(self, items, carpeta, tipo, origen_txt, estado, descripcion, detalle="", omitidas=(),
                total_archivos=None) -> Optional[ResultadoCopia]:
        cfg = self.config
        total_bytes = sum(s for _, _, s in items)
        info = obtener_info_sistema()
        imprimir_resumen_sistema(info, origen_txt if os.path.exists(origen_txt) else None, carpeta)
        try:
            libre = shutil.disk_usage(carpeta).free
            if libre < total_bytes:
                print(f"{icono('⚠️ ', '[AVISO] ')}Espacio libre en el destino ({formatear_bytes(libre)}) menor a lo que se "
                        f"va a copiar ({formatear_bytes(total_bytes)}).")
        except OSError:
            pass
        hilos = calcular_hilos_optimos(cfg)
        print(f"{icono('⚙️ ', '[CPU] ')}Usando {hilos} hilos")
        progreso = Progreso(len(items), total_bytes, descripcion, silencioso=not cfg.mostrar_progreso)
        monitor = MonitorRecursos(lambda: progreso.bytes_copiados) if psutil else None
        hechos = RegistroHechos(self.gestor.ruta_hechos(estado.id)) if estado else None
        copiador = CopiadorParalelo(carpeta, progreso, monitor, hechos)
        if monitor:
            monitor.start()
        inicio = time.time()
        try:
            res = copiador.copiar(items, hilos)
        except KeyboardInterrupt:
            print()
            if estado:
                self.gestor.pausar(estado.id)
                print(f"{icono('⏸️ ', '[PAUSA] ')}Respaldo interrumpido. Podrás reanudarlo con la opción 5 del menú.")
            else:
                print("Respaldo interrumpido (no se guardó el estado, así que no se puede reanudar).")
            return None
        except Exception:
            print()
            if estado:
                self.gestor.pausar(estado.id)
            raise
        finally:
            if monitor:
                monitor.stop()
            if hechos:
                hechos.cerrar()
        duracion = time.time() - inicio
        progreso.cerrar()
        if estado:
            self.gestor.completar(estado.id)
        print(f"{icono('✅', 'OK')} Copiados: {res.copiados} | Duplicados: {res.duplicados} | Errores: {len(res.errores)}")
        if res.errores:
            print(f"{icono('⚠️ ', '[ERR] ')}No se pudieron copiar {len(res.errores)} archivo(s):")
            for rel, motivo in res.errores[:10]:
                print(f"   - {rel}: {motivo}")
            if len(res.errores) > 10:
                print(f"   ... y {len(res.errores) - 10} más (detalle en backup_info.json)")
        if omitidas:
            print(f"{icono('⚠️ ', '[AVISO] ')}{len(omitidas)} carpeta(s) no se pudieron leer (permisos u otro motivo); "
                    f"el detalle está en backup_info.json")
        resumen = (detalle + ", " if detalle else "") + f"{res.copiados} archivos"
        self.finalizar(carpeta, tipo, origen_txt, total_archivos if total_archivos is not None else len(items),
                        res.bytes_copiados, duracion, res.errores, resumen, omitidas, info)
        return res

    def finalizar(self, carpeta, tipo, origen_txt, total_archivos, tam, duracion, errores, detalle,
                    omitidas=(), info=None):
        cfg = self.config
        info = info or obtener_info_sistema()
        extra = {"errores": [{"archivo": r, "motivo": m} for r, m in errores[:200]],
                    "carpetas_omitidas": [{"ruta": r, "motivo": m} for r, m in list(omitidas)[:200]]}
        meta = generar_metadatos_respaldo(origen_txt, carpeta, tipo, total_archivos, tam, duracion,
                                            "completado" if not errores else "con_errores", cfg, info, extra)
        guardar_metadatos_respaldo(carpeta, meta)
        registrar_respaldo(carpeta, tipo, detalle, cfg)
        guardar_ultima_ruta(carpeta, tipo)
        if cfg.comprimir_automatico:
            comprimir_respaldo(carpeta, cfg.nivel_compresion)


# ======================================================================
# FUENTES DE RESPALDO
# ======================================================================
class Opcion(NamedTuple):
    texto: str
    ruta: str
    clave: str = ""


def pedir_seleccion(opciones: List[Opcion], multiple: bool) -> List[Opcion]:
    for i, o in enumerate(opciones, 1):
        print(f"  {i}. {o.texto}")
    if multiple:
        s = input("Números separados por espacio (o 'todos', 0 cancelar): ").strip().lower()
    else:
        s = input("Selecciona número (0 cancelar): ").strip().lower()
    if s in ("", "0"):
        return []
    if multiple and s == "todos":
        return list(opciones)
    indices = list(dict.fromkeys(int(x) - 1 for x in s.split() if x.isascii() and x.isdigit()))
    elegidas = [opciones[i] for i in indices if 0 <= i < len(opciones)]
    return elegidas if multiple else elegidas[:1]


def pedir_destino(config: Configuracion) -> str:
    destino = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    return expandir_ruta(destino) if destino else config.ruta_base_respaldos


class Fuente:
    tipo = ""
    titulo = ""
    emoji = ("", "")
    multiple = False
    requiere_seleccion = True
    sin_opciones = "No se encontraron opciones."
    sin_archivos = "No hay archivos para respaldar."

    def detectar(self) -> List[Opcion]:
        return []

    def construir_plan(self, seleccion: List[Opcion], escaner: Escaner) -> Plan:
        raise NotImplementedError

    def ejecutar(self, seleccion: List[Opcion], destino: str, motor: MotorRespaldo):
        plan = self.construir_plan(seleccion, Escaner())
        if not plan.archivos:
            print(self.sin_archivos)
            return
        motor.ejecutar(plan, destino)


def obtener_carpetas_usuario() -> List[str]:
    sistema = platform.system()
    home = os.path.expanduser("~")
    if sistema == "Windows":
        carpetas = ["Documents", "Music", "Pictures", "Videos", "Downloads", "Desktop", "Favorites", "Contacts"]
    elif sistema == "Darwin":
        carpetas = ["Documents", "Music", "Pictures", "Movies", "Downloads", "Desktop", "Library", "Development"]
    else:
        carpetas = ["Documentos", "Música", "Imágenes", "Vídeos", "Descargas", "Escritorio", "Public", "Plantillas",
                    "Documents", "Music", "Pictures", "Videos", "Downloads", "Desktop"]
    return [os.path.join(home, c) for c in carpetas if os.path.exists(os.path.join(home, c))]


class FuenteCarpetasUsuario(Fuente):
    tipo = "general"
    titulo = "RESPALDO GENERAL"
    emoji = ("📂", "[GEN]")
    multiple = True
    sin_opciones = "No se encontraron carpetas de usuario."

    def detectar(self):
        return [Opcion(os.path.basename(c), c) for c in obtener_carpetas_usuario()]

    def construir_plan(self, seleccion, escaner):
        archivos = []
        for o in seleccion:
            print(f"{icono('🔍', '[SCAN]')} Escaneando {o.ruta}...")
            base = os.path.basename(o.ruta)
            for ruta, rel, size in escaner.recorrer(o.ruta):
                archivos.append((ruta, os.path.join(base, rel), size))
        return Plan(self.tipo, " + ".join(o.ruta for o in seleccion), archivos,
                    f"{len(seleccion)} carpetas", escaner.omitidas)


class FuenteExtensiones(Fuente):
    tipo = "extensiones"
    titulo = "RESPALDO POR EXTENSIONES"
    emoji = ("🔤", "[EXT]")
    requiere_seleccion = False
    sin_archivos = "No se encontraron archivos con esas extensiones."

    def construir_plan(self, seleccion, escaner):
        home = os.path.expanduser("~")
        print(f"{icono('🔍', '[SCAN]')} Escaneando archivos...")
        archivos = []
        usados: Set[Tuple[str, str]] = set()
        contador: Dict[Tuple[str, str], int] = defaultdict(int)
        extensiones_vistas: Set[str] = set()
        for ruta, _, size in escaner.recorrer(home, EXTENSIONES_RESPALDO):
            nombre = os.path.basename(ruta)
            base, ext = os.path.splitext(nombre)
            ext = ext.lower()
            carpeta = f"Archivos_{ext[1:].upper()}"
            final = nombre
            clave = (carpeta, nombre.lower())
            while (carpeta, final.lower()) in usados:
                contador[clave] += 1
                final = f"{base}_{contador[clave]}{ext}"
            usados.add((carpeta, final.lower()))
            extensiones_vistas.add(ext)
            archivos.append((ruta, os.path.join(carpeta, final), size))
        print(f"Extensiones encontradas: {len(extensiones_vistas)}")
        return Plan(self.tipo, home, archivos, f"{len(extensiones_vistas)} extensiones", escaner.omitidas)


def detectar_unidades_externas() -> List[str]:
    unidades = []
    if platform.system() == "Windows":
        import ctypes
        import string
        mascara = ctypes.windll.kernel32.GetLogicalDrives()
        for letra in string.ascii_uppercase:
            if mascara & 1:
                d = letra + ":\\"
                try:
                    tipo = ctypes.windll.kernel32.GetDriveTypeW(d)
                except Exception:
                    tipo = 0
                if tipo == 2:  # DRIVE_REMOVABLE
                    unidades.append(d)
            mascara >>= 1
    else:
        usuario = os.environ.get("USER", "")
        for m in ("/Volumes", "/media", f"/media/{usuario}", f"/run/media/{usuario}", "/mnt"):
            if os.path.isdir(m):
                try:
                    for item in os.listdir(m):
                        path = os.path.join(m, item)
                        if os.path.ismount(path) and path not in unidades:
                            unidades.append(path)
                except OSError:
                    pass
    return unidades


class FuenteDiscoExterno(Fuente):
    tipo = "disco_externo"
    titulo = "RECUPERAR DISCO EXTERNO"
    emoji = ("💾", "[DISCO]")
    sin_opciones = "No se detectaron unidades externas."
    sin_archivos = "No hay archivos recuperables."

    def detectar(self):
        return [Opcion(u, u) for u in detectar_unidades_externas()]

    def construir_plan(self, seleccion, escaner):
        origen = seleccion[0].ruta
        print(f"{icono('🔍', '[SCAN]')} Escaneando {origen}...")
        archivos = [(ruta, rel, size) for ruta, rel, size in escaner.recorrer(origen)]
        return Plan(self.tipo, origen, archivos, "", escaner.omitidas)


def buscar_xampp() -> List[Tuple[str, str]]:
    sistema = platform.system()
    if sistema == "Windows":
        candidatos = ["C:\\xampp", "D:\\xampp", "C:\\Program Files\\MySQL", "C:\\Program Files (x86)\\MySQL"]
    elif sistema == "Darwin":
        candidatos = ["/Applications/XAMPP", "/Applications/xampp", "/usr/local/mysql", "/Applications/MAMP"]
    else:
        candidatos = ["/opt/lampp", "/var/lib/mysql", "/usr/local/mysql"]
    rutas = []
    for c in candidatos:
        if os.path.exists(c):
            bajo = c.lower()
            nombre = "XAMPP" if ("xampp" in bajo or "lampp" in bajo) else ("MAMP" if "mamp" in bajo else "MySQL")
            rutas.append((nombre, c))
    return rutas


class FuenteXampp(Fuente):
    tipo = "xampp"
    titulo = "RESPALDO XAMPP/MYSQL"
    emoji = ("🗄️ ", "[XAMPP]")
    multiple = True
    sin_opciones = "No se encontraron instalaciones."

    def detectar(self):
        return [Opcion(f"{nombre}: {ruta}", ruta, nombre) for nombre, ruta in buscar_xampp()]

    def construir_plan(self, seleccion, escaner):
        archivos = []
        for o in seleccion:
            print(f"{icono('🔍', '[SCAN]')} Escaneando {o.clave}...")
            for ruta, rel, size in escaner.recorrer(o.ruta):
                archivos.append((ruta, os.path.join(o.clave, rel), size))
        return Plan(self.tipo, " + ".join(o.clave for o in seleccion), archivos,
                    f"{len(seleccion)} instalaciones", escaner.omitidas)


def _adb_disponible(config: Optional[Configuracion] = None) -> Optional[str]:
    """Devuelve la ruta absoluta verificada de adb, o None."""
    ruta = (config.adb_path if config and config.adb_path else "adb") or "adb"
    if os.path.isabs(ruta) and os.path.exists(ruta):
        return ruta
    return shutil.which(ruta)


def detectar_dispositivos_moviles() -> List[Opcion]:
    dispositivos = []
    sistema = platform.system()

    # 1) ADB (Android por USB con depuración activa)
    adb = _adb_disponible()
    if adb:
        try:
            r = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                lineas = [l.strip() for l in r.stdout.splitlines() if l.strip()]
                if [l for l in lineas[1:] if "device" in l and not l.startswith("*")]:
                    dispositivos.append(Opcion(f"Android ADB ({adb}) -> adb:/sdcard", "adb:/sdcard", "ADB"))
        except Exception:
            pass

    # 2) Montajes de medios (macOS / Linux)
    if sistema != "Windows":
        posibles = ["/Volumes"]
        if sistema == "Linux":
            posibles.append(os.path.join("/media", os.environ.get("USER", "")))
            posibles.append(f"/run/user/{os.getuid()}/gvfs")
        for base in posibles:
            if os.path.exists(base):
                try:
                    for item in os.listdir(base):
                        ruta = os.path.join(base, item)
                        if os.path.ismount(ruta) or os.path.isdir(ruta):
                            etiqueta = item
                            if "iphone" in item.lower() or "ipad" in item.lower():
                                etiqueta = f"Apple {item}"
                            elif "android" in item.lower() or "mtp" in item.lower():
                                etiqueta = f"Android {item}"
                            dispositivos.append(Opcion(f"{etiqueta} ({sistema}) -> {ruta}", ruta, sistema))
                except OSError:
                    pass

    # 3) Windows: unidades removibles (2)
    if sistema == "Windows":
        try:
            import ctypes
            import string
            for letra in string.ascii_uppercase:
                ruta = f"{letra}:\\"
                try:
                    if ctypes.windll.kernel32.GetDriveTypeW(ruta) == 2:
                        dispositivos.append(Opcion(f"Removable {letra} (Windows) -> {ruta}", ruta, "Windows"))
                except Exception:
                    pass
        except Exception:
            pass

    return dispositivos


class FuenteMovil(Fuente):
    tipo = "movil"
    titulo = "RESPALDO MÓVIL - Android / iOS"
    emoji = ("📱", "[MOVIL]")
    sin_opciones = "No se detectaron dispositivos móviles conectados."

    def detectar(self):
        return detectar_dispositivos_moviles()

    def construir_plan(self, seleccion, escaner):
        ruta = seleccion[0].ruta
        if not os.path.exists(ruta):
            return Plan(self.tipo, ruta, [])
        print(f"{icono('🔍', '[SCAN]')} Escaneando {ruta}...")
        archivos = [(r, rel, s) for r, rel, s in escaner.recorrer(ruta)]
        return Plan(self.tipo, ruta, archivos, "", escaner.omitidas)

    def ejecutar(self, seleccion, destino, motor):
        o = seleccion[0]
        if o.clave != "ADB":
            return super().ejecutar(seleccion, destino, motor)
        adb = _adb_disponible()
        if not adb:
            print(f"{icono('❌', 'ERROR')} No se encontró 'adb' en el sistema. Configúralo en config.json (adb_path).")
            return
        carpeta = crear_carpeta_respaldo(destino)
        inicio = time.time()
        try:
            subprocess.run([adb, "pull", o.ruta.split(":", 1)[1], carpeta], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"{icono('❌', 'ERROR')} Error al usar adb: {e}")
            return
        n, tam = contar_directorio(carpeta)
        motor.finalizar(carpeta, "movil_android", "Android ADB", n, tam, time.time() - inicio, [], "Android ADB backup")
        print(f"{icono('✅', 'OK')} Respaldo ADB completado en {carpeta}")


def flujo_respaldo(fuente: Fuente, config: Configuracion, motor: MotorRespaldo):
    print(f"\n{icono(*fuente.emoji)} {fuente.titulo}")
    seleccion: List[Opcion] = []
    if fuente.requiere_seleccion:
        opciones = fuente.detectar()
        if not opciones:
            print(fuente.sin_opciones)
            pausa()
            return
        print("Disponibles:")
        seleccion = pedir_seleccion(opciones, fuente.multiple)
        if not seleccion:
            return
    destino = pedir_destino(config)
    fuente.ejecutar(seleccion, destino, motor)
    pausa()


def menu_reanudar(gestor: GestorEstados, motor: MotorRespaldo):
    pausados = gestor.pausados()
    if not pausados:
        print("No hay respaldos interrumpidos.")
        pausa()
        return
    print(f"\n{icono('🔄', '[REANUDAR]')} RESPALDOS INTERRUMPIDOS")
    for i, e in enumerate(pausados, 1):
        print(f"{i}. {e.tipo} - {e.origen[:50]} - {len(gestor.leer_hechos(e.id))}/{e.total_archivos}")
    sel = input("Selecciona número (0 cancelar): ").strip()
    if not sel.isdigit() or not 1 <= int(sel) <= len(pausados):
        return
    motor.reanudar(pausados[int(sel) - 1])
    pausa()


# ======================================================================
# MODO RED
# ======================================================================
_ENC_ARCHIVO = struct.Struct("!HQ")
_ENC_TOTAL = struct.Struct("!Q")
NETWORK_TIMEOUT_AUTH = 10
MAX_INTENTOS_AUTH = 3


def _recibir_exacto(sock: socket.socket, n: int) -> bytes:
    datos = bytearray()
    while len(datos) < n:
        trozo = sock.recv(n - len(datos))
        if not trozo:
            raise ConnectionError("el otro equipo cerró la conexión")
        datos += trozo
    return bytes(datos)


def _ruta_segura(carpeta: str, rel: str) -> Optional[str]:
    base = os.path.abspath(carpeta)
    destino = os.path.abspath(os.path.join(base, rel.replace("/", os.sep)))
    return destino if destino.startswith(base + os.sep) else None


def _detectar_ip_local() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _clave_red_bytes(config: Configuracion) -> bytes:
    if not config.red_clave:
        config.red_clave = secrets.token_hex(32)
        try:
            config.guardar()
        except OSError:
            pass
    return hashlib.sha256(config.red_clave.encode("utf-8")).digest()


def _handshake_servidor(conn: socket.socket, clave: bytes):
    for _ in range(MAX_INTENTOS_AUTH):
        nonce = secrets.token_bytes(32)
        try:
            conn.sendall(nonce)
            resp = _recibir_exacto(conn, 32)
        except (ConnectionError, OSError):
            raise ConnectionError("conexión cerrada durante autenticación")
        esperado = hmac.new(clave, nonce, hashlib.sha256).digest()
        if hmac.compare_digest(resp, esperado):
            conn.sendall(b"OK")
            return
        try:
            conn.sendall(b"NO")
        except OSError:
            pass
    raise ConnectionError("demasiados intentos fallidos")


def _handshake_cliente(sock: socket.socket, clave: bytes):
    nonce = _recibir_exacto(sock, 32)
    resp = hmac.new(clave, nonce, hashlib.sha256).digest()
    sock.sendall(resp)
    r = _recibir_exacto(sock, 2)
    if r != b"OK":
        raise ConnectionError("el servidor rechazó la autenticación (clave incorrecta)")


def _intentar_tls_servidor() -> Optional[ssl.SSLContext]:
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime as _dt
    except ImportError:
        return None
    cert_path = os.path.join(RUTA_APP, "servidor_red.crt")
    key_path = os.path.join(RUTA_APP, "servidor_red.key")
    if not (os.path.exists(cert_path) and os.path.exists(key_path)):
        try:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"Respaldos.Gio")])
            cert = (x509.CertificateBuilder()
                    .subject_name(subject).issuer_name(issuer)
                    .public_key(key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(_dt.datetime.utcnow())
                    .not_valid_after(_dt.datetime.utcnow() + _dt.timedelta(days=3650))
                    .sign(key, hashes.SHA256()))
            with open(key_path, "wb") as f:
                f.write(key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()))
            with open(cert_path, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
        except Exception:
            return None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        return ctx
    except Exception:
        return None


def servidor_red(config: Configuracion):
    print(f"\n{icono('🌐', '[RED]')} MODO SERVIDOR")
    escaner = Escaner()
    archivos = []
    for c in obtener_carpetas_usuario():
        print(f"{icono('🔍', '[SCAN]')} Escaneando {c}...")
        base = os.path.basename(c)
        for ruta, rel, size in escaner.recorrer(c):
            archivos.append((ruta, base + "/" + rel.replace(os.sep, "/"), size))
    print(f"{len(archivos)} archivos listos para enviar.")

    clave = _clave_red_bytes(config)
    print(f"Clave de red (compártela con el cliente): {config.red_clave}")

    bind_ip = config.red_bind_ip or ""
    if not bind_ip:
        ip_local = _detectar_ip_local()
        sugerida = ip_local or "0.0.0.0"
        entrada = input(f"IP a exponer [Enter = {sugerida}]: ").strip()
        bind_ip = entrada or sugerida
    if bind_ip == "0.0.0.0":
        resp = input("Vas a exponer el servidor en TODAS las interfaces. ¿Continuar? (s/N): ").strip().lower()
        if resp not in ("s", "si", "sí", "y", "yes"):
            ip_local = _detectar_ip_local()
            if ip_local:
                print(f"Usando IP local: {ip_local}")
                bind_ip = ip_local
            else:
                print("Cancelado.")
                return

    tls_ctx = _intentar_tls_servidor() if config.red_usar_tls else None
    if config.red_usar_tls and tls_ctx is None:
        print("Aviso: TLS no disponible (falta 'cryptography' o fallo al generar cert).")
        print("El HMAC evita accesos no autorizados, pero el tráfico viaja en claro.")
        if input("¿Continuar sin TLS? (s/N): ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
            return

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((bind_ip, NETWORK_PORT))
        srv.listen(1)
        print(f"Esperando cliente en {bind_ip}:{NETWORK_PORT}...")
        conn, addr = srv.accept()
        with conn:
            if tls_ctx is not None:
                try:
                    conn = tls_ctx.wrap_socket(conn, server_side=True)
                except ssl.SSLError as e:
                    print(f"Error TLS: {e}")
                    return
            print(f"Cliente conectado desde {addr[0]}")
            if _recibir_exacto(conn, len(MAGIA_RED)) != MAGIA_RED:
                print("El cliente no usa la misma versión del protocolo. Actualiza ambos equipos.")
                return
            try:
                _handshake_servidor(conn, clave)
            except ConnectionError as e:
                print(f"Autenticación fallida: {e}")
                return
            print("Cliente autenticado.")
            conn.sendall(_ENC_TOTAL.pack(len(archivos)))
            progreso = Progreso(len(archivos), sum(s for _, _, s in archivos), "Enviando",
                                silencioso=not config.mostrar_progreso)
            for ruta, rel, _ in archivos:
                try:
                    f = open(ruta, "rb")
                except OSError:
                    progreso.archivo_listo()
                    continue
                with f:
                    real = os.fstat(f.fileno()).st_size
                    nombre = rel.encode("utf-8")
                    conn.sendall(_ENC_ARCHIVO.pack(len(nombre), real) + nombre)
                    if real:
                        if conn.sendfile(f, count=real) != real:
                            raise ConnectionError(f"el archivo cambió mientras se enviaba: {rel}")
                    progreso.sumar_bytes(real)
                progreso.archivo_listo()
                progreso.mostrar()
            conn.sendall(_ENC_ARCHIVO.pack(0, 0))
            progreso.cerrar()
    finally:
        srv.close()
    print(f"{icono('✅', 'OK')} Transferencia completada.")


def cliente_red(config: Configuracion, motor: MotorRespaldo):
    ip = input("IP del servidor: ").strip()
    if not ip:
        return
    clave_txt = input(f"Clave de red (Enter = usar la guardada: {config.red_clave or 'ninguna'}): ").strip()
    if not clave_txt:
        clave_txt = config.red_clave
    if not clave_txt:
        print("Se requiere la clave de red para autenticarse.")
        return
    clave = hashlib.sha256(clave_txt.encode("utf-8")).digest()

    destino = pedir_destino(config)
    sock = socket.create_connection((ip, NETWORK_PORT), timeout=NETWORK_TIMEOUT_AUTH)

    if config.red_usar_tls:
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=ip)
        except ssl.SSLError:
            print("Aviso: el servidor no tiene TLS habilitado. Continuando sin cifrado (HMAC activo).")

    carpeta = None
    try:
        sock.settimeout(120)
        sock.sendall(MAGIA_RED)
        _handshake_cliente(sock, clave)
        total = _ENC_TOTAL.unpack(_recibir_exacto(sock, _ENC_TOTAL.size))[0]
        print(f"Recibiendo {total} archivos...")
        carpeta = crear_carpeta_respaldo(destino)
        progreso = Progreso(total, 0, "Descargando", silencioso=not config.mostrar_progreso)
        buf = bytearray(BUFFER_SIZE)
        vista = memoryview(buf)
        carpetas_ok: Set[str] = set()
        recibidos = tam_total = 0
        inicio = time.time()
        while True:
            largo, size = _ENC_ARCHIVO.unpack(_recibir_exacto(sock, _ENC_ARCHIVO.size))
            if largo == 0:
                break
            rel = _recibir_exacto(sock, largo).decode("utf-8", "replace")
            destino_archivo = _ruta_segura(carpeta, rel)
            f = None
            if destino_archivo:
                d = os.path.dirname(destino_archivo)
                if d not in carpetas_ok:
                    os.makedirs(d, exist_ok=True)
                    carpetas_ok.add(d)
                f = open(destino_archivo, "wb")
            try:
                restante = size
                while restante:
                    n = sock.recv_into(vista[:min(BUFFER_SIZE, restante)])
                    if not n:
                        raise ConnectionError("el otro equipo cerró la conexión")
                    if f:
                        f.write(vista[:n])
                    restante -= n
                    progreso.sumar_bytes(n)
            finally:
                if f:
                    f.close()
            if f:
                recibidos += 1
                tam_total += size
            progreso.archivo_listo()
            progreso.mostrar()
        progreso.cerrar()
        motor.finalizar(carpeta, "red_general", ip, recibidos, tam_total, time.time() - inicio,
                        [], f"{recibidos} archivos")
        print(f"{icono('✅', 'OK')} Respaldo remoto completado en {carpeta}")
    finally:
        sock.close()


def modo_red(config: Configuracion, motor: MotorRespaldo):
    print(f"\n{icono('🌐', '[RED]')} MODO RED")
    print("1. Actuar como SERVIDOR")
    print("2. Actuar como CLIENTE")
    print("3. Cancelar")
    op = input("Selecciona: ").strip()
    if op == "1":
        servidor_red(config)
    elif op == "2":
        cliente_red(config, motor)
    elif op == "3":
        return
    else:
        print("Opción inválida")
    pausa()


# ======================================================================
# ELIMINAR, REGISTROS Y CONFIGURACIÓN
# ======================================================================
def _quitar_zip(nombre: str) -> str:
    return nombre[:-4] if nombre.lower().endswith(".zip") else nombre


def eliminar_respaldo(config: Configuracion):
    generados = registro_nombres.todos()
    base = config.ruta_base_respaldos
    if not os.path.exists(base):
        print(f"La carpeta {base} no existe.")
        pausa()
        return
    respaldos = []
    for item in os.listdir(base):
        if _quitar_zip(item) in generados:
            full = os.path.join(base, item)
            tam = contar_directorio(full)[1] if os.path.isdir(full) else os.path.getsize(full)
            respaldos.append((item, full, tam))
    if not respaldos:
        print("No hay respaldos generados por el programa en esta ruta "
                "(solo se pueden eliminar los que el propio sistema creó).")
        pausa()
        return
    print(f"\n{icono('🗑️ ', '[ELIMINAR] ')}RESPALDOS DISPONIBLES")
    for i, (nombre, _, tam) in enumerate(respaldos, 1):
        print(f"{i}. {nombre} ({formatear_bytes(tam)})")
    sel = input("Número a eliminar (0 cancelar): ").strip()
    if not sel.isdigit() or not 1 <= int(sel) <= len(respaldos):
        if sel not in ("", "0"):
            print("Número inválido")
            pausa()
        return
    nombre, full, _ = respaldos[int(sel) - 1]
    if input(f"¿Eliminar {nombre}? (sí/NO): ").strip().lower() not in ("si", "sí", "yes", "y", "s"):
        print("Cancelado")
        pausa()
        return
    if os.path.isdir(full):
        shutil.rmtree(full)
    else:
        os.remove(full)
    registro_nombres.quitar(_quitar_zip(nombre))
    print(f"{icono('✅', 'OK')} Eliminado: {nombre}")
    if os.path.exists(RUTA_REGISTRO):
        sin_zip = _quitar_zip(full)
        with open(RUTA_REGISTRO, "r", encoding="utf-8") as f:
            lineas = f.readlines()
        with open(RUTA_REGISTRO, "w", encoding="utf-8") as f:
            f.writelines(l for l in lineas if sin_zip not in l)
    pausa()


def mostrar_registros():
    if not os.path.exists(RUTA_REGISTRO):
        print("No hay registros de respaldos.")
        pausa()
        return
    with open(RUTA_REGISTRO, "r", encoding="utf-8") as f:
        lineas = f.readlines()
    print("\n" + "=" * 70)
    print(f"                     {icono('📜', '')}REGISTROS DE RESPALDOS")
    print("=" * 70)
    print(f"Total: {len(lineas)}")
    for i, linea in enumerate(reversed(lineas[-10:]), 1):
        partes = linea.strip().split("|")
        if len(partes) >= 2:
            tipo = partes[2] if len(partes) > 2 else ""
            print(f"{i}. {partes[0][:19]} | {tipo.upper()} | {partes[1]}")
    print("=" * 70)
    pausa()


def _onoff(valor: bool) -> str:
    return f"{icono('✅', '[X]')} Activado" if valor else f"{icono('❌', '[ ]')} Desactivado"


def menu_configuracion(config: Configuracion):
    while True:
        limpiar_terminal()
        print(f"\n{icono('⚙️ ', '')}CONFIGURACIÓN")
        print(f" 1. Compresión automática: {_onoff(config.comprimir_automatico)}")
        print(f" 2. Registrar rutas en .txt: {_onoff(config.registrar_rutas)}")
        print(f" 3. Barra de progreso: {_onoff(config.mostrar_progreso)}")
        print(f" 4. Guardar estado de respaldos: {_onoff(config.guardar_estado_respaldos)}")
        print(f" 5. Ajuste automático de hilos: {_onoff(config.auto_ajustar_hilos)}")
        print(f" 6. Hilos paralelos: {config.max_archivos_paralelos} ({'Auto' if config.auto_ajustar_hilos else 'Manual'})")
        print(f" 7. Nivel compresión (0-9): {config.nivel_compresion}")
        print(f" 8. Ruta base respaldos: {config.ruta_base_respaldos}")
        print(f" 9. Clave de red (HMAC): {'(configurada)' if config.red_clave else '(sin configurar)'}")
        print(f"10. Bind del servidor red: {config.red_bind_ip or '(preguntar)'}")
        print(f"11. TLS en modo red: {_onoff(config.red_usar_tls)}")
        print(f"12. Ruta de adb: {config.adb_path}")
        print("13. Guardar y volver")
        op = input("Opción: ").strip()

        if op in ("1", "2", "3", "4", "5"):
            campo = ("comprimir_automatico", "registrar_rutas", "mostrar_progreso",
                        "guardar_estado_respaldos", "auto_ajustar_hilos")[int(op) - 1]
            setattr(config, campo, not getattr(config, campo))
        elif op == "6":
            print("\nHILOS PARALELOS: cuántos archivos se copian a la vez.")
            print(f"   Recomendado: entre 4 y {MAX_WORKERS} (tu CPU tiene {os.cpu_count()} núcleos).")
            entrada = input("Número de hilos (1-64) o 'auto': ").strip().lower()
            if entrada == "auto":
                config.auto_ajustar_hilos = True
                config.max_archivos_paralelos = min(64, MAX_WORKERS)
            elif entrada.isdigit():
                config.max_archivos_paralelos = max(1, min(64, int(entrada)))
                config.auto_ajustar_hilos = False
        elif op == "7":
            print("\nNIVEL DE COMPRESIÓN: 0 = sin compresión (rápido) | 6 = equilibrio | 9 = máxima (lento)")
            entrada = input("Nuevo nivel (0-9): ").strip()
            if entrada.isdigit() and 0 <= int(entrada) <= 9:
                config.nivel_compresion = int(entrada)
        elif op == "8":
            nueva = input("Nueva ruta base: ").strip()
            if nueva:
                config.ruta_base_respaldos = expandir_ruta(nueva)
        elif op == "9":
            nueva = input("Nueva clave de red (Enter para conservar): ").strip()
            if nueva:
                config.red_clave = nueva
        elif op == "10":
            nueva = input("IP de bind (vacío = preguntar): ").strip()
            config.red_bind_ip = nueva
        elif op == "11":
            config.red_usar_tls = not config.red_usar_tls
        elif op == "12":
            nueva = input("Ruta a adb (ej. /usr/bin/adb o C:\\platform-tools\\adb.exe): ").strip()
            if nueva:
                config.adb_path = nueva
        elif op == "13":
            config.guardar()
            print("Configuración guardada")
            break
        else:
            print("Opción no válida")
            time.sleep(1)
            continue
        config.guardar()


# ======================================================================
# MENÚ PRINCIPAL
# ======================================================================
def menu_principal():
    config = Configuracion.cargar()
    if not os.path.isabs(config.ruta_base_respaldos) or config.ruta_base_respaldos == "Respaldos":
        config.ruta_base_respaldos = RUTA_RESPALDOS
        config.guardar()
    gestor = GestorEstados()
    motor = MotorRespaldo(config, gestor)
    fuentes = {"1": FuenteCarpetasUsuario(), "2": FuenteExtensiones(), "3": FuenteDiscoExterno(),
                "4": FuenteXampp(), "6": FuenteMovil()}
    entradas = [("1", "📂", "Respaldo general (carpetas usuario)"), ("2", "🔤", "Respaldo por extensiones"),
                ("3", "💾", "Recuperar disco externo"), ("4", "🗄️ ", "Respaldo XAMPP/MySQL"),
                ("5", "🔄", "Reanudar respaldo interrumpido"), ("6", "📱", "Respaldo móvil (Android/iOS)"),
                ("7", "🌐", "Modo red interna"), ("8", "🗑️ ", "Eliminar respaldo seguro"),
                ("9", "📜", "Ver registros"), ("10", "⚙️ ", "Configuración"), ("11", "🚪", "Salir")]
    while True:
        limpiar_terminal()
        print("\n" + "=" * 70)
        print("       SISTEMA DE RESPALDOS AVANZADO - TERMINAL PORTABLE")
        print("=" * 70)
        print(f"{platform.system()} | Base: {config.ruta_base_respaldos}")
        ultima = leer_ultima_ruta()
        if ultima:
            print(ultima.splitlines()[0])
        n_pausados = len(gestor.pausados())
        if n_pausados:
            print(f"{icono('⏸️ ', '[PAUSA] ')}Respaldos interrumpidos: {n_pausados}")
        print("\nMENÚ:")
        for num, emoji, texto in entradas:
            print(f"{num:>2}) {emoji + ' ' if UNICODE_SUPPORT else ''}{texto}")
        op = input("Opción: ").strip()
        try:
            if op in fuentes:
                flujo_respaldo(fuentes[op], config, motor)
            elif op == "5":
                menu_reanudar(gestor, motor)
            elif op == "7":
                modo_red(config, motor)
            elif op == "8":
                eliminar_respaldo(config)
            elif op == "9":
                mostrar_registros()
            elif op == "10":
                menu_configuracion(config)
            elif op == "11":
                print("Hasta pronto")
                config.guardar()
                break
            else:
                print("Opción no válida")
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nOperación cancelada.")
            time.sleep(1)
        except Exception as e:
            print(f"\n{icono('⚠️ ', '[ERROR] ')}{mensaje_error_amigable(e)}")
            pausa()


if __name__ == "__main__":
    menu_principal()