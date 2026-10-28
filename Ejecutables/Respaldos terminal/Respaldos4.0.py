import os
import sys
import shutil
import platform
from datetime import datetime
import zipfile
import json
import re
import time
import threading
import socket
import subprocess
from typing import List, Dict, Set, Optional, Tuple, Generator
from dataclasses import dataclass, asdict
import hashlib
import hmac
import struct
import ssl
import secrets
import errno
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import psutil
except ImportError:
    psutil = None

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# DETECCIÓN DE RUTA BASE (PARA EJECUTABLE PORTABLE)
def obtener_ruta_base():
    """Devuelve la carpeta donde está el ejecutable o el script."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

RUTA_APP = obtener_ruta_base()
RUTA_RESPALDOS = os.path.join(RUTA_APP, "Respaldos")
RUTA_CONFIG = os.path.join(RUTA_APP, "config.json")
RUTA_ESTADOS = os.path.join(RUTA_APP, "estados_respaldo.json")
RUTA_REGISTRO = os.path.join(RUTA_APP, "rutas_respaldo.txt")
RUTA_CONFIG_DIR = os.path.join(RUTA_APP, "config")  # listas blanca/negra
RUTA_NOMBRES_GENERADOS = os.path.join(RUTA_APP, "respaldos_generados.json")  # registro de respaldos creados por el programa
RUTA_ULTIMO_RESPALDO = os.path.join(RUTA_APP, "ultimo_respaldo.txt")  # ruta persistente del último respaldo
RUTA_PINNING = os.path.join(RUTA_APP, "servidores_conocidos.json")  # PIN de servidores red (TOFU)

# Crear carpetas necesarias
os.makedirs(RUTA_RESPALDOS, exist_ok=True)
os.makedirs(RUTA_CONFIG_DIR, exist_ok=True)

# Referencia global al estado del respaldo en curso, para poder marcarlo
# como "pausado" automáticamente si el proceso se interrumpe o falla.
_estado_en_curso = None

# CONSTANTES DE RENDIMIENTO
MAX_WORKERS = min(32, (os.cpu_count() or 2) * 2)
BUFFER_SIZE = 256 * 1024
HASH_CHUNK_SIZE = 8192
NETWORK_PORT = 56789

# UTILIDADES
def limpiar_terminal():
    os.system('cls' if platform.system() == "Windows" else 'clear')

def expandir_ruta(ruta: str) -> str:
    return os.path.normpath(os.path.expanduser(os.path.expandvars(ruta)))

def formatear_tamano(gb: float) -> str:
    if gb >= 1000:
        return f"{gb/1024:.1f} TB"
    elif gb >= 1:
        return f"{gb:.1f} GB"
    else:
        return f"{gb*1024:.0f} MB"

def formatear_bytes(bytes_val: Optional[int]) -> str:
    if bytes_val is None:
        return "N/A"
    valor = float(bytes_val)
    for unidad in ["B", "KB", "MB", "GB", "TB"]:
        if valor < 1024 or unidad == "TB":
            return f"{valor:.1f} {unidad}"
        valor /= 1024
    return f"{valor:.1f} TB"

VERSION_PROGRAMA = "4.0"
UNICODE_SUPPORT = False
try:
    if sys.stdout.encoding and "UTF" in sys.stdout.encoding.upper():
        UNICODE_SUPPORT = True
except Exception:
    UNICODE_SUPPORT = False

def icono(texto_emoji: str, texto_fallback: str) -> str:
    return texto_emoji if UNICODE_SUPPORT else texto_fallback

def sanitizar_nombre(texto: str) -> str:
    limpio = re.sub(r"[^A-Za-z0-9_-]", "_", texto.strip())
    return limpio[:64] if limpio else "backup"

def obtener_usuario_equipo() -> Tuple[str, str]:
    usuario = os.environ.get("USERNAME") or os.environ.get("USER") or "usuario"
    equipo = platform.node() or "equipo"
    return sanitizar_nombre(usuario), sanitizar_nombre(equipo)

def obtener_info_sistema() -> Dict[str, Optional[str]]:
    usuario, equipo = obtener_usuario_equipo()
    sistema = platform.system()
    memoria_total = memoria_disponible = None
    cpu_uso = None
    cpu_logico = os.cpu_count() or 1
    cpu_fisico = None
    if psutil:
        try:
            memoria = psutil.virtual_memory()
            memoria_total = memoria.total
            memoria_disponible = memoria.available
            cpu_uso = psutil.cpu_percent(interval=0.2)
            cpu_logico = psutil.cpu_count(logical=True) or cpu_logico
            cpu_fisico = psutil.cpu_count(logical=False) or cpu_logico
        except Exception:
            pass
    return {
        "usuario": usuario,
        "equipo": equipo,
        "sistema": f"{sistema} {platform.release()}",
        "arquitectura": platform.architecture()[0],
        "cpu_logico": cpu_logico,
        "cpu_fisico": cpu_fisico,
        "cpu_uso": cpu_uso,
        "memoria_total": memoria_total,
        "memoria_disponible": memoria_disponible,
    }

def calcular_hilos_optimos(config) -> int:
    max_threads = min(64, config.max_archivos_paralelos or MAX_WORKERS)
    if not getattr(config, 'auto_ajustar_hilos', True):
        return max_threads
    if psutil:
        try:
            cpu_pct = psutil.cpu_percent(interval=0.2)
            memoria = psutil.virtual_memory()
            nucleos = psutil.cpu_count(logical=True) or (os.cpu_count() or 1)
            base = max(1, int(nucleos * 0.8))
            if cpu_pct > 70 or memoria.percent > 80:
                valor = max(1, base // 2)
            elif cpu_pct < 30 and memoria.percent < 70:
                valor = max(1, min(base, max_threads))
            else:
                valor = max(1, min(base, max_threads))
            return min(max_threads, valor)
        except Exception:
            return max_threads
    return max_threads

def ajustar_prioridad_proceso(reducir=False):
    if not psutil:
        return
    try:
        proceso = psutil.Process(os.getpid())
        if platform.system() == "Windows":
            if reducir and hasattr(psutil, 'BELOW_NORMAL_PRIORITY_CLASS'):
                proceso.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            elif not reducir and hasattr(psutil, 'NORMAL_PRIORITY_CLASS'):
                proceso.nice(psutil.NORMAL_PRIORITY_CLASS)
        else:
            if reducir:
                proceso.nice(10)
            else:
                proceso.nice(0)
    except Exception:
        pass

class MonitorRecursos(threading.Thread):
    def __init__(self, config, origen, destino):
        super().__init__(daemon=True)
        self.config = config
        self.origen = origen
        self.destino = destino
        self._stop = threading.Event()
        self.delay = 0.0
        self.prioridad_reducida = False
        self.carga_alta = False
        self.last_disk = self._leer_io_disco()

    def _leer_io_disco(self):
        if not psutil:
            return None
        try:
            return psutil.disk_io_counters()
        except Exception:
            return None

    def _calcular_actividad_disco(self, anterior, actual, intervalo):
        if not anterior or not actual or intervalo <= 0:
            return 0.0
        bytes_totales = (actual.read_bytes + actual.write_bytes) - (anterior.read_bytes + anterior.write_bytes)
        return bytes_totales / intervalo

    def run(self):
        while not self._stop.is_set():
            try:
                cpu_pct = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()
                actual_disk = self._leer_io_disco()
                disco_act = self._calcular_actividad_disco(self.last_disk, actual_disk, 1.0)
                self.last_disk = actual_disk
                uso_alto = cpu_pct > 70 or mem.percent > 80 or disco_act > 50 * 1024 * 1024
                if uso_alto:
                    self.delay = min(2.0, max(0.2, (cpu_pct - 50) / 30))
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
            self._stop.wait(2)

    def stop(self):
        self._stop.set()
        if self.prioridad_reducida:
            ajustar_prioridad_proceso(reducir=False)


def guardar_metadatos_respaldo(destino: str, metadatos: Dict):
    try:
        ruta_meta = os.path.join(destino, "backup_info.json")
        with open(ruta_meta, "w", encoding="utf-8") as f:
            json.dump(metadatos, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(icono("⚠️ Error guardando metadata", "Error guardando metadata"), e)


def mensaje_error_amigable(e: Exception) -> str:
    """Traduce excepciones técnicas a mensajes comprensibles para un usuario sin conocimientos técnicos."""
    texto = str(e)
    if isinstance(e, PermissionError) or "Permission denied" in texto or "Acceso denegado" in texto:
        return ("No se pudo completar la operación porque no hay permisos suficientes para acceder a algunos "
                "archivos o carpetas. Intenta ejecutar el programa como administrador o revisa los permisos.")
    if isinstance(e, FileNotFoundError):
        return ("No se pudo completar la operación porque una de las rutas ya no existe. Verifica que el disco, "
                "USB o carpeta siga conectado y disponible.")
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28 or "No space left" in texto or "espacio" in texto.lower():
        return "No hay suficiente espacio en el disco de destino. Libera espacio o elige otra ubicación."
    if isinstance(e, (ConnectionError, socket.error)):
        return "Se perdió la conexión de red durante la transferencia. Verifica que ambos equipos sigan en la misma red."
    if isinstance(e, KeyboardInterrupt):
        return "El respaldo fue interrumpido manualmente."
    return f"Ocurrió un problema inesperado ({texto}). El respaldo quedó pausado y puede reanudarse desde el menú."


def _cargar_json_seguro(ruta, valor_default):
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return valor_default


def registrar_nombre_respaldo(nombre: str):
    """Registra el nombre base (sin .zip) de un respaldo creado por el programa.
    Esto permite que 'eliminar respaldo' identifique con certeza qué carpetas/zips
    fueron generados por el sistema, sin depender de un patrón de nombre rígido."""
    nombres = _cargar_json_seguro(RUTA_NOMBRES_GENERADOS, [])
    if nombre not in nombres:
        nombres.append(nombre)
        try:
            with open(RUTA_NOMBRES_GENERADOS, "w", encoding="utf-8") as f:
                json.dump(nombres, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


def quitar_nombre_respaldo(nombre: str):
    nombres = _cargar_json_seguro(RUTA_NOMBRES_GENERADOS, [])
    if nombre in nombres:
        nombres.remove(nombre)
        try:
            with open(RUTA_NOMBRES_GENERADOS, "w", encoding="utf-8") as f:
                json.dump(nombres, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


def obtener_nombres_respaldo_generados() -> Set[str]:
    return set(_cargar_json_seguro(RUTA_NOMBRES_GENERADOS, []))


def guardar_ultima_ruta(carpeta_destino: str, tipo: str):
    """Guarda en un .txt simple la ruta del último respaldo realizado, para poder
    consultarla aunque después se cambie la ruta base configurada."""
    try:
        with open(RUTA_ULTIMO_RESPALDO, "w", encoding="utf-8") as f:
            f.write(f"Último respaldo: {carpeta_destino}\n")
            f.write(f"Tipo: {tipo}\n")
            f.write(f"Fecha: {datetime.now().isoformat()}\n")
    except Exception:
        pass


def leer_ultima_ruta() -> Optional[str]:
    if os.path.exists(RUTA_ULTIMO_RESPALDO):
        try:
            with open(RUTA_ULTIMO_RESPALDO, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return None
    return None

# FILTRO DE RUTAS (LISTAS BLANCA/NEGRA)
class FiltroRutas:
    def __init__(self, config_dir=RUTA_CONFIG_DIR):
        self.config_dir = config_dir
        self.blacklist = self._cargar_lista("blacklist.json", self._blacklist_default())
        self.whitelist = self._cargar_lista("whitelist.json", self._whitelist_default())
    
    def _blacklist_default(self) -> List[str]:
        return [
            "$RECYCLE.BIN", "System Volume Information", ".Trash", ".Spotlight-V100",
            ".fseventsd", "Caches", "Logs", "AppData", "ProgramData", "Windows",
            "System32", "WinSxS", "Program Files", "Program Files (x86)",
            "boot", "dev", "proc", "sys", "tmp", "var/tmp", "lost+found",
            "Library/Caches", "Library/Logs", "Library/Preferences"
        ]
    
    def _whitelist_default(self) -> List[str]:
        home = os.path.expanduser("~")
        return [
            os.path.join(home, "Documents"), os.path.join(home, "Documentos"),
            os.path.join(home, "Desktop"), os.path.join(home, "Escritorio"),
            os.path.join(home, "Downloads"), os.path.join(home, "Descargas"),
            os.path.join(home, "Music"), os.path.join(home, "Música"),
            os.path.join(home, "Pictures"), os.path.join(home, "Imágenes"),
            os.path.join(home, "Videos"), os.path.join(home, "Vídeos"),
            os.path.join(home, "Development"), os.path.join(home, "Projects"),
            "/Applications/XAMPP/htdocs", os.path.expanduser("~/Applications/XAMPP/htdocs")
        ]
    
    def _cargar_lista(self, archivo, defaults):
        ruta = os.path.join(self.config_dir, archivo)
        if os.path.exists(ruta):
            try:
                with open(ruta, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except:
                pass
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(defaults, f, indent=2, ensure_ascii=False)
        return defaults
    
    def deberia_excluir(self, ruta):
        ruta_norm = os.path.normpath(ruta).lower()
        for w in self.whitelist:
            if ruta_norm.startswith(os.path.normpath(w).lower()):
                return False
        for b in self.blacklist:
            if b.lower() in ruta_norm.split(os.sep):
                return True
        return False

filtro = FiltroRutas()

def walk_fast(path):
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    if filtro.deberia_excluir(entry.path):
                        continue
                    yield (entry.path, entry.name, entry.stat().st_size)
                elif entry.is_dir(follow_symlinks=False):
                    if filtro.deberia_excluir(entry.path):
                        continue
                    yield from walk_fast(entry.path)
    except PermissionError:
        pass

def get_file_hash(filepath, quick=True):
    hasher = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            if quick:
                hasher.update(f.read(HASH_CHUNK_SIZE))
            else:
                while chunk := f.read(BUFFER_SIZE):
                    hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return ""

# BARRA DE PROGRESO Y COPIADO PARALELO
class ProgresoConsola:
    def __init__(self, total_files, total_bytes=0, descripcion="Progreso", ancho=50):
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.descripcion = descripcion
        self.ancho = ancho
        self.completado = 0
        self.completado_bytes = 0
        self.inicio = time.time()
        self.last_update = 0
        self.update_step = max(1, total_files // 200) if total_files > 0 else 1
        self._tqdm = None
        if tqdm:
            try:
                self._tqdm = tqdm(total=total_files, desc=descripcion, unit="arch", ncols=80, leave=False)
            except Exception:
                self._tqdm = None

    def actualizar(self, archivos=1, bytes_copied=0):
        self.completado += archivos
        self.completado_bytes += bytes_copied
        if self._tqdm:
            self._tqdm.update(archivos)
        if self.completado - self.last_update >= self.update_step or self.completado == self.total_files:
            self.last_update = self.completado
            self._mostrar()

    def _mostrar(self):
        porcentaje = self.completado / self.total_files if self.total_files else 0
        elapsed = max(time.time() - self.inicio, 0.001)
        eta = (elapsed / porcentaje) - elapsed if porcentaje > 0 else 0
        velocidad = self.completado_bytes / elapsed
        velocidad_str = formatear_bytes(velocidad) + "/s"
        eta_str = f"{int(eta//60)}m {int(eta%60)}s" if eta > 60 else f"{int(eta)}s"
        filled = int(self.ancho * porcentaje)
        barra = '█' * filled + '░' * (self.ancho - filled)
        sys.stdout.write(
            f"\r{self.descripcion}: |{barra}| {porcentaje:.1%} "
            f"({self.completado}/{self.total_files}) {velocidad_str} ETA: {eta_str}"
        )
        sys.stdout.flush()

    def completar(self):
        if self._tqdm:
            self._tqdm.close()
        self._mostrar()
        print(f"\n{icono('✅', 'OK')} Completado en {time.time()-self.inicio:.1f}s")

    def cerrar(self):
        if self._tqdm:
            self._tqdm.close()


def copiar_archivo(args):
    origen, destino, sobrescribir, hash_cache, monitor = args
    try:
        if monitor and monitor.delay > 0:
            time.sleep(monitor.delay)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        if os.path.exists(destino) and not sobrescribir:
            if os.path.getsize(origen) == os.path.getsize(destino):
                h1 = hash_cache.get(origen) or get_file_hash(origen, True)
                hash_cache[origen] = h1
                h2 = get_file_hash(destino, True)
                if h1 == h2:
                    return (True, 0, "duplicado")
        with open(origen, 'rb') as src, open(destino, 'wb') as dst:
            shutil.copyfileobj(src, dst, length=BUFFER_SIZE)
        shutil.copystat(origen, destino)
        return (True, os.path.getsize(origen), "ok")
    except Exception as e:
        return (False, 0, str(e))

def copia_paralela(archivos, destino_base, sobrescribir=False, max_workers=MAX_WORKERS, progreso=None, monitor=None):
    hash_cache = {}
    tasks = [(origen, os.path.join(destino_base, rel), sobrescribir, hash_cache, monitor) for origen, rel, _ in archivos]
    copiados = duplicados = errores = tam_total = 0
    total = len(tasks)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(copiar_archivo, t): t for t in tasks}
        for future in as_completed(futures):
            ok, tam, msg = future.result()
            if ok:
                if msg == "duplicado":
                    duplicados += 1
                else:
                    copiados += 1
                    tam_total += tam
            else:
                errores += 1
                print(f"\n{icono('⚠️','[ERR]')} No se pudo copiar '{os.path.basename(futures[future][0])}': {msg}")
            if progreso:
                progreso.actualizar(1, tam if ok and msg != "duplicado" else 0)
    return copiados, duplicados, errores, tam_total


def ejecutar_copia_con_monitor(archivos, carpeta_destino, hilos, progreso, config):
    monitor = None
    if psutil:
        origen = archivos[0][0] if archivos else None
        monitor = MonitorRecursos(config, origen, carpeta_destino)
        monitor.start()
    try:
        return copia_paralela(archivos, carpeta_destino, max_workers=hilos, progreso=progreso, monitor=monitor)
    finally:
        if monitor:
            monitor.stop()
            monitor.join(timeout=2)

# CLASES DE CONFIGURACIÓN Y ESTADO (con rutas portables)
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
    
    def __post_init__(self):
        if self.archivos_completados is None:
            self.archivos_completados = []
        if self.archivos_pendientes is None:
            self.archivos_pendientes = []

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
    tema_oscuro: bool = False  # solo lo usa la versión GUI, se conserva aquí para que ambas compartan config.json sin perder ajustes
    red_clave: str = ""
    red_bind_ip: str = ""
    red_usar_tls: bool = True
    proteger_respaldos: bool = True
    
    @classmethod
    def cargar(cls, ruta=RUTA_CONFIG):
        default = cls()
        if os.path.exists(ruta):
            try:
                with open(ruta, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                    filtros = {k: v for k, v in datos.items() if k in cls.__annotations__}
                    return cls(**filtros)
            except:
                pass
        return default
    
    def guardar(self, ruta=RUTA_CONFIG):
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

class GestorEstados:
    def __init__(self, archivo=RUTA_ESTADOS):
        self.archivo = archivo
        self.estados = self._cargar()
    
    def _cargar(self) -> Dict[str, EstadoRespaldo]:
        if os.path.exists(self.archivo):
            try:
                with open(self.archivo, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return {k: EstadoRespaldo(**v) for k, v in data.items()}
            except:
                pass
        return {}
    
    def _guardar(self):
        with open(self.archivo, 'w', encoding='utf-8') as f:
            json.dump({k: asdict(v) for k, v in self.estados.items()}, f, indent=2)
    
    def crear_estado(self, origen, destino, tipo, total_archivos) -> EstadoRespaldo:
        global _estado_en_curso
        id_res = f"{tipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hashlib.sha256(origen.encode()).hexdigest()[:8]}"
        estado = EstadoRespaldo(id=id_res, origen=origen, destino=destino, tipo=tipo,
                                total_archivos=total_archivos, fecha_inicio=datetime.now().isoformat(), activo=True)
        self.estados[id_res] = estado
        self._guardar()
        _estado_en_curso = estado
        return estado
    
    def completar_respaldo(self, id_res):
        global _estado_en_curso
        if id_res in self.estados:
            del self.estados[id_res]
            self._guardar()
        if _estado_en_curso and _estado_en_curso.id == id_res:
            _estado_en_curso = None
    
    def obtener_pausados(self) -> List[EstadoRespaldo]:
        return [e for e in self.estados.values() if not e.activo]
    
    def pausar_respaldo(self, id_res, completados, pendientes):
        if id_res in self.estados:
            e = self.estados[id_res]
            e.activo = False
            e.fecha_pausa = datetime.now().isoformat()
            e.archivos_completados = completados
            e.archivos_pendientes = pendientes
            e.procesados = len(completados)
            self._guardar()
    
    def reanudar_respaldo(self, id_res):
        if id_res in self.estados:
            e = self.estados[id_res]
            e.activo = True
            e.fecha_pausa = ""
            self._guardar()
            return e
        return None

# FUNCIONES DE RESPALDO (con rutas portables)
def registrar_respaldo(ruta, tipo, detalles, config):
    if config.registrar_rutas:
        with open(RUTA_REGISTRO, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}|{ruta}|{tipo}|{detalles}\n")

def crear_carpeta_respaldo(base, proteger=False):
    usuario, equipo = obtener_usuario_equipo()
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"{usuario}_{equipo}_{fecha}"
    nombre = sanitizar_nombre(nombre)
    carpeta = os.path.join(base, nombre)
    contador = 1
    while os.path.exists(carpeta):
        carpeta = os.path.join(base, f"{nombre}_{contador}")
        contador += 1
    os.makedirs(carpeta, exist_ok=True)
    registrar_nombre_respaldo(os.path.basename(carpeta))
    if proteger:
        _restringir_permisos(carpeta, es_carpeta=True)
    return carpeta

def comprimir_respaldo(carpeta, nivel=6, proteger=False):
    zip_path = carpeta + ".zip"
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=nivel) as zf:
            for root, _, files in os.walk(carpeta):
                for f in files:
                    full = os.path.join(root, f)
                    zf.write(full, os.path.relpath(full, carpeta))
            meta_path = os.path.join(carpeta, "backup_info.json")
            if os.path.exists(meta_path):
                zf.write(meta_path, "backup_info.json")
        shutil.rmtree(carpeta)
        print(f"{icono('✅', 'OK')} Comprimido: {zip_path}")
        if proteger:
            _restringir_permisos(zip_path)
        return zip_path
    except Exception as e:
        print(f"{icono('❌', 'ERROR')} Error comprimiendo: {e}")
        return None

def obtener_info_disco(ruta: str) -> Dict[str, Optional[str]]:
    datos = {
        "ruta": ruta,
        "total_bytes": None,
        "free_bytes": None,
        "percent": None,
    }
    if not ruta or not psutil:
        return datos
    try:
        uso = psutil.disk_usage(ruta)
        datos.update({
            "total_bytes": uso.total,
            "free_bytes": uso.free,
            "percent": uso.percent,
        })
    except Exception:
        pass
    return datos


def detectar_dispositivos_moviles():
    dispositivos = []
    sistema = platform.system()
    if sistema == "Windows":
        try:
            import string, ctypes
            for letra in string.ascii_uppercase:
                ruta = f"{letra}:\\"
                try:
                    tipo = ctypes.windll.kernel32.GetDriveTypeW(ruta)
                    if tipo == 2:
                        dispositivos.append((f"Removable {letra}", ruta, "Windows"))
                except Exception:
                    pass
        except Exception:
            pass
    else:
        posibles = ["/Volumes"]
        if sistema == "Linux":
            posibles.append(os.path.join('/media', os.environ.get('USER', '')))
            posibles.append(f"/run/user/{os.getuid()}/gvfs")
        for base in posibles:
            if os.path.exists(base):
                for item in os.listdir(base):
                    ruta = os.path.join(base, item)
                    if os.path.ismount(ruta) or os.path.isdir(ruta):
                        etiqueta = item
                        if "iphone" in item.lower() or "ipad" in item.lower():
                            etiqueta = f"Apple {item}"
                        elif "android" in item.lower() or "mtp" in item.lower():
                            etiqueta = f"Android {item}"
                        dispositivos.append((etiqueta, ruta, sistema))
    try:
        resultado = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=5)
        if resultado.returncode == 0:
            lineas = [l.strip() for l in resultado.stdout.splitlines() if l.strip()]
            dispositivos_adb = [l for l in lineas[1:] if 'device' in l and not l.startswith('*')]
            if dispositivos_adb:
                dispositivos.append(("Android ADB", "adb:/sdcard", "ADB"))
    except Exception:
        pass
    return dispositivos


def respaldar_moviles(config, gestor):
    print("\n📱 RESPALDO MÓVIL - Android / iOS")
    dispositivos = detectar_dispositivos_moviles()
    if not dispositivos:
        print("No se detectaron dispositivos móviles conectados.")
        input("Presiona ENTER para continuar...")
        return
    print("Dispositivos disponibles:")
    for i, (nombre, ruta, tipo) in enumerate(dispositivos, 1):
        print(f"  {i}. {nombre} ({tipo}) -> {ruta}")
    sel = input("Selecciona número (0 cancelar): ").strip()
    if sel == "0":
        return
    try:
        idx = int(sel) - 1
    except ValueError:
        print("Selección inválida")
        return
    if idx < 0 or idx >= len(dispositivos):
        print("Opción inválida")
        return
    nombre, ruta, tipo = dispositivos[idx]
    destino = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    if not destino:
        destino = config.ruta_base_respaldos
    destino = expandir_ruta(destino)
    carpeta_destino = crear_carpeta_respaldo(destino)
    if tipo == "ADB" and ruta.startswith("adb:"):
        device_path = ruta.split(':', 1)[1]
        inicio = time.time()
        try:
            subprocess.run(['adb', 'pull', device_path, carpeta_destino], check=True)
            tam = sum(os.path.getsize(os.path.join(root, f)) for root, _, files in os.walk(carpeta_destino) for f in files)
            duracion = time.time() - inicio
            metadatos = generar_metadatos_respaldo("Android ADB", carpeta_destino, "movil_android", 0, tam, duracion, "completado", config)
            guardar_metadatos_respaldo(carpeta_destino, metadatos)
            registrar_respaldo(carpeta_destino, "movil_android", "Android ADB backup", config)
            guardar_ultima_ruta(carpeta_destino, "movil_android")
            print(f"{icono('✅','OK')} Respaldo ADB completado en {carpeta_destino}")
        except subprocess.CalledProcessError as e:
            print(f"{icono('❌','ERROR')} Error al usar adb: {e}")
        input("Presiona ENTER para continuar...")
        return
    if not os.path.exists(ruta):
        print("La ruta del dispositivo no está disponible.")
        input("Presiona ENTER para continuar...")
        return
    archivos = []
    print(f"🔍 Escaneando {ruta}...")
    for ruta_archivo, nombre_archivo, size in walk_fast(ruta):
        rel = os.path.relpath(ruta_archivo, ruta)
        archivos.append((ruta_archivo, rel, size))
    total = len(archivos)
    if total == 0:
        print("No se encontraron archivos para respaldar.")
        input("Presiona ENTER para continuar...")
        return
    imprimir_resumen_sistema(ruta, destino)
    ajustar_prioridad_proceso()
    hilos = calcular_hilos_optimos(config)
    print(f"{icono('⚙️','[CPU]')} Usando {hilos} hilos optimizados")
    progreso = ProgresoConsola(total, sum(size for _, _, size in archivos), "Respaldando móvil") if config.mostrar_progreso else None
    estado = gestor.crear_estado(ruta, carpeta_destino, "movil", total) if config.guardar_estado_respaldos else None
    inicio = time.time()
    copiados, dup, err, tam = ejecutar_copia_con_monitor(archivos, carpeta_destino, hilos, progreso, config)
    duracion = time.time() - inicio
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    metadatos = generar_metadatos_respaldo(ruta, carpeta_destino, "movil", total, tam, duracion, "completado" if err == 0 else "con_errores", config)
    guardar_metadatos_respaldo(carpeta_destino, metadatos)
    registrar_respaldo(carpeta_destino, "movil", f"{copiados} archivos", config)
    guardar_ultima_ruta(carpeta_destino, "movil")
    print(f"\n{icono('✅','OK')} Copiados: {copiados}, Duplicados: {dup}, Errores: {err}")
    if config.comprimir_automatico:
        comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    input("Presiona ENTER para continuar...")


def imprimir_resumen_sistema(origen=None, destino=None):
    info = obtener_info_sistema()
    print("\n" + "="*70)
    print(f"{icono('💻','[SYS]')} Equipo: {info['equipo']} | Usuario: {info['usuario']}")
    print(f"Sistema operativo: {info['sistema']} | Arquitectura: {info['arquitectura']}")
    if info['cpu_fisico']:
        print(f"CPU: {info['cpu_fisico']} físicos / {info['cpu_logico']} lógicos | Uso inicial: {info['cpu_uso'] or 0:.1f}%")
    else:
        print(f"CPU: {info['cpu_logico']} hilos | Uso inicial: {info['cpu_uso'] or 0:.1f}%")
    print(f"RAM instalada: {formatear_bytes(info['memoria_total'])} | Disponible: {formatear_bytes(info['memoria_disponible'])}")
    if origen:
        disco_origen = obtener_info_disco(origen)
        print(f"Origen: {origen}")
        print(f"  Disco origen libre: {formatear_bytes(disco_origen['free_bytes'])} ({disco_origen['percent'] or 'N/A'}%)")
    if destino:
        disco_destino = obtener_info_disco(destino)
        print(f"Destino: {destino}")
        print(f"  Disco destino libre: {formatear_bytes(disco_destino['free_bytes'])} ({disco_destino['percent'] or 'N/A'}%)")
    print(f"Versión Respaldos.Gio: {VERSION_PROGRAMA}")
    print("="*70)


def generar_metadatos_respaldo(origen, destino, tipo, total_archivos, tam_total, duracion, estado, config):
    info = obtener_info_sistema()
    disco_origen = obtener_info_disco(origen if isinstance(origen, str) else origen.split(' + ')[0])
    disco_destino = obtener_info_disco(destino)
    return {
        "fecha_ejecucion": datetime.now().isoformat(),
        "usuario": info['usuario'],
        "equipo": info['equipo'],
        "sistema_operativo": info['sistema'],
        "arquitectura": info['arquitectura'],
        "cpu_logico": info['cpu_logico'],
        "cpu_fisico": info['cpu_fisico'],
        "cpu_uso_inicial": info['cpu_uso'],
        "memoria_total_bytes": info['memoria_total'],
        "memoria_disponible_inicial_bytes": info['memoria_disponible'],
        "origen": origen,
        "destino": destino,
        "disco_origen": disco_origen,
        "disco_destino": disco_destino,
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
            "auto_ajustar_hilos": getattr(config, 'auto_ajustar_hilos', True),
            "ruta_base_respaldos": config.ruta_base_respaldos
        }
    }


def obtener_carpetas_usuario():
    sistema = platform.system()
    home = os.path.expanduser("~")
    carpetas = []
    if sistema == "Windows":
        carpetas = ["Documents", "Music", "Pictures", "Videos", "Downloads", "Desktop", "Favorites", "Contacts"]
    elif sistema == "Darwin":
        carpetas = ["Documents", "Music", "Pictures", "Movies", "Downloads", "Desktop", "Library", "Development"]
    else:
        carpetas = ["Documentos", "Música", "Imágenes", "Vídeos", "Descargas", "Escritorio", "Public", "Plantillas",
                    "Documents", "Music", "Pictures", "Videos", "Downloads", "Desktop"]
    return [os.path.join(home, c) for c in carpetas if os.path.exists(os.path.join(home, c))]

def respaldo_general(config, gestor):
    print("\n📂 RESPALDO GENERAL")
    carpetas = obtener_carpetas_usuario()
    if not carpetas:
        print("No se encontraron carpetas de usuario.")
        input("Presiona ENTER...")
        return
    print("Carpetas disponibles:")
    for i, c in enumerate(carpetas, 1):
        print(f"  {i}. {os.path.basename(c)}")
    sel = input("Números separados por espacio (o 'todos'): ").strip()
    if sel.lower() == "todos":
        seleccionadas = carpetas
    else:
        indices = [int(x)-1 for x in sel.split() if x.isdigit()]
        seleccionadas = [carpetas[i] for i in indices if 0 <= i < len(carpetas)]
    if not seleccionadas:
        print("No se seleccionó ninguna.")
        return
    destino = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    if not destino:
        destino = config.ruta_base_respaldos
    destino = expandir_ruta(destino)
    carpeta_destino = crear_carpeta_respaldo(destino)
    imprimir_resumen_sistema()
    ajustar_prioridad_proceso()
    archivos = []
    for c in seleccionadas:
        print(f"{icono('🔍','[SCAN]')} Escaneando {c}...")
        for ruta, nombre, size in walk_fast(c):
            rel = os.path.relpath(ruta, c)
            archivos.append((ruta, os.path.join(os.path.basename(c), rel), size))
    total = len(archivos)
    if total == 0:
        print("No hay archivos para respaldar.")
        return
    hilos = calcular_hilos_optimos(config)
    print(f"{icono('⚙️','[CPU]')} Usando {hilos} hilos optimizados")
    progreso = ProgresoConsola(total, sum(size for _,_,size in archivos), "Copiando") if config.mostrar_progreso else None
    estado = gestor.crear_estado(" + ".join(seleccionadas), carpeta_destino, "general", total) if config.guardar_estado_respaldos else None
    inicio = time.time()
    copiados, dup, err, tam = ejecutar_copia_con_monitor(archivos, carpeta_destino, hilos, progreso, config)
    duracion = time.time() - inicio
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    metadatos = generar_metadatos_respaldo(" + ".join(seleccionadas), carpeta_destino, "general", total, tam, duracion, "completado" if err == 0 else "con_errores", config)
    guardar_metadatos_respaldo(carpeta_destino, metadatos)
    registrar_respaldo(carpeta_destino, "general", f"{len(seleccionadas)} carpetas, {copiados} archivos", config)
    guardar_ultima_ruta(carpeta_destino, "general")
    print(f"\n{icono('✅','OK')} Respaldo completado. Copiados: {copiados}, Duplicados: {dup}, Errores: {err}")
    if config.comprimir_automatico:
        comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    input("Presiona ENTER para continuar...")

def respaldo_extensiones(config, gestor):
    print("\n🔤 RESPALDO POR EXTENSIONES")
    extensiones_set = {".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".txt",".rtf",
                        ".jpg",".jpeg",".png",".gif",".mp3",".mp4",".py",".js",".html",".css",
                        ".java",".cpp",".c",".m",".mm",".plist",".strings"}
    archivos_por_ext = {}
    home = os.path.expanduser("~")
    print("🔍 Escaneando archivos...")
    for ruta, nombre, size in walk_fast(home):
        ext = os.path.splitext(nombre)[1].lower()
        if ext in extensiones_set:
            archivos_por_ext.setdefault(ext, []).append((ruta, nombre, size))
    if not archivos_por_ext:
        print("No se encontraron archivos con esas extensiones.")
        input("Presiona ENTER...")
        return
    print(f"Extensiones encontradas: {len(archivos_por_ext)}")
    destino = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    if not destino:
        destino = config.ruta_base_respaldos
    destino = expandir_ruta(destino)
    carpeta_destino = crear_carpeta_respaldo(destino)
    archivos_a_copiar = []
    for ext, lista in archivos_por_ext.items():
        for ruta, nombre, size in lista:
            rel = os.path.join(f"Archivos_{ext[1:].upper()}", nombre)
            archivos_a_copiar.append((ruta, rel, size))
    total = len(archivos_a_copiar)
    if total == 0:
        print("No hay archivos para respaldar.")
        return
    imprimir_resumen_sistema()
    ajustar_prioridad_proceso()
    hilos = calcular_hilos_optimos(config)
    print(f"{icono('⚙️','[CPU]')} Usando {hilos} hilos optimizados")
    progreso = ProgresoConsola(total, sum(size for _,_,size in archivos_a_copiar), "Copiando") if config.mostrar_progreso else None
    estado = gestor.crear_estado(home, carpeta_destino, "extensiones", total) if config.guardar_estado_respaldos else None
    inicio = time.time()
    copiados, dup, err, tam = ejecutar_copia_con_monitor(archivos_a_copiar, carpeta_destino, hilos, progreso, config)
    duracion = time.time() - inicio
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    metadatos = generar_metadatos_respaldo(home, carpeta_destino, "extensiones", total, tam, duracion, "completado" if err == 0 else "con_errores", config)
    guardar_metadatos_respaldo(carpeta_destino, metadatos)
    registrar_respaldo(carpeta_destino, "extensiones", f"{len(archivos_por_ext)} extensiones, {copiados} archivos", config)
    guardar_ultima_ruta(carpeta_destino, "extensiones")
    print(f"\n{icono('✅','OK')} Copiados: {copiados}, Duplicados: {dup}, Errores: {err}")
    if config.comprimir_automatico:
        comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    input("Presiona ENTER...")

def recuperar_disco_externo(config, gestor):
    print("\n💾 RECUPERAR DISCO EXTERNO")
    sistema = platform.system()
    unidades = []
    if sistema == "Windows":
        import string, ctypes
        drives = []
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if mask & 1:
                drives.append(letter + ":\\")
            mask >>= 1
        for d in drives:
            if d != "C:\\" and ctypes.windll.kernel32.GetDriveTypeW(d) in (2,3):
                unidades.append(d)
    else:
        for m in ['/Volumes', '/media', '/mnt']:
            if os.path.exists(m):
                for item in os.listdir(m):
                    path = os.path.join(m, item)
                    if os.path.ismount(path):
                        unidades.append(path)
    if not unidades:
        print("No se detectaron unidades externas.")
        input("Presiona ENTER...")
        return
    print("Unidades detectadas:")
    for i, u in enumerate(unidades, 1):
        print(f"  {i}. {u}")
    sel = input("Selecciona número (0 cancelar): ").strip()
    if sel == "0":
        return
    idx = int(sel)-1
    if idx < 0 or idx >= len(unidades):
        print("Opción inválida")
        return
    origen = unidades[idx]
    destino = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    if not destino:
        destino = config.ruta_base_respaldos
    destino = expandir_ruta(destino)
    carpeta_destino = crear_carpeta_respaldo(destino)
    archivos = []
    print(f"🔍 Escaneando {origen}...")
    for ruta, nombre, size in walk_fast(origen):
        rel = os.path.relpath(ruta, origen)
        archivos.append((ruta, rel, size))
    total = len(archivos)
    if total == 0:
        print("No hay archivos recuperables.")
        return
    imprimir_resumen_sistema()
    ajustar_prioridad_proceso()
    hilos = calcular_hilos_optimos(config)
    print(f"{icono('⚙️','[CPU]')} Usando {hilos} hilos optimizados")
    progreso = ProgresoConsola(total, sum(size for _,_,size in archivos), "Recuperando") if config.mostrar_progreso else None
    estado = gestor.crear_estado(origen, carpeta_destino, "disco_externo", total) if config.guardar_estado_respaldos else None
    inicio = time.time()
    copiados, dup, err, tam = ejecutar_copia_con_monitor(archivos, carpeta_destino, hilos, progreso, config)
    duracion = time.time() - inicio
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    metadatos = generar_metadatos_respaldo(origen, carpeta_destino, "disco_externo", total, tam, duracion, "completado" if err == 0 else "con_errores", config)
    guardar_metadatos_respaldo(carpeta_destino, metadatos)
    registrar_respaldo(carpeta_destino, "disco_externo", f"{copiados} archivos", config)
    guardar_ultima_ruta(carpeta_destino, "disco_externo")
    print(f"\n{icono('✅','OK')} Recuperados: {copiados}, Duplicados: {dup}, Errores: {err}")
    if config.comprimir_automatico:
        comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    input("Presiona ENTER...")

def buscar_xampp():
    sistema = platform.system()
    rutas = []
    if sistema == "Windows":
        candidatos = ["C:\\xampp", "D:\\xampp", "C:\\Program Files\\MySQL", "C:\\Program Files (x86)\\MySQL"]
        for c in candidatos:
            if os.path.exists(c):
                rutas.append(("XAMPP" if "xampp" in c.lower() else "MySQL", c))
    elif sistema == "Darwin":
        candidatos = ["/Applications/XAMPP", "/Applications/xampp", "/usr/local/mysql", "/Applications/MAMP"]
        for c in candidatos:
            if os.path.exists(c):
                rutas.append(("XAMPP" if "xampp" in c.lower() else "MAMP" if "mamp" in c.lower() else "MySQL", c))
    else:
        candidatos = ["/opt/lampp", "/var/lib/mysql", "/usr/local/mysql"]
        for c in candidatos:
            if os.path.exists(c):
                rutas.append(("XAMPP" if "lampp" in c else "MySQL", c))
    return rutas

def respaldo_xampp(config, gestor):
    print("\n🗄️ RESPALDO XAMPP/MYSQL")
    instalaciones = buscar_xampp()
    if not instalaciones:
        print("No se encontraron instalaciones.")
        input("Presiona ENTER...")
        return
    print("Instalaciones encontradas:")
    for i, (nombre, ruta) in enumerate(instalaciones, 1):
        print(f"  {i}. {nombre}: {ruta}")
    sel = input("Números separados por espacio (o 'todos'): ").strip()
    if sel.lower() == "todos":
        selec = instalaciones
    else:
        indices = [int(x)-1 for x in sel.split() if x.isdigit()]
        selec = [instalaciones[i] for i in indices if 0 <= i < len(instalaciones)]
    if not selec:
        return
    destino = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    if not destino:
        destino = config.ruta_base_respaldos
    destino = expandir_ruta(destino)
    carpeta_destino = crear_carpeta_respaldo(destino)
    archivos = []
    for nombre, ruta in selec:
        print(f"🔍 Escaneando {nombre}...")
        for fpath, fname, size in walk_fast(ruta):
            rel = os.path.join(nombre, os.path.relpath(fpath, ruta))
            archivos.append((fpath, rel, size))
    total = len(archivos)
    if total == 0:
        print("No hay archivos para respaldar.")
        return
    imprimir_resumen_sistema()
    ajustar_prioridad_proceso()
    hilos = calcular_hilos_optimos(config)
    print(f"{icono('⚙️','[CPU]')} Usando {hilos} hilos optimizados")
    progreso = ProgresoConsola(total, sum(size for _,_,size in archivos), "Respaldando") if config.mostrar_progreso else None
    estado = gestor.crear_estado(" + ".join([n for n,_ in selec]), carpeta_destino, "xampp", total) if config.guardar_estado_respaldos else None
    inicio = time.time()
    copiados, dup, err, tam = ejecutar_copia_con_monitor(archivos, carpeta_destino, hilos, progreso, config)
    duracion = time.time() - inicio
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    metadatos = generar_metadatos_respaldo(" + ".join([n for n,_ in selec]), carpeta_destino, "xampp", total, tam, duracion, "completado" if err == 0 else "con_errores", config)
    guardar_metadatos_respaldo(carpeta_destino, metadatos)
    registrar_respaldo(carpeta_destino, "xampp", f"{len(selec)} instalaciones, {copiados} archivos", config)
    guardar_ultima_ruta(carpeta_destino, "xampp")
    print(f"\n{icono('✅','OK')} Copiados: {copiados}, Errores: {err}")
    if config.comprimir_automatico:
        comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    input("Presiona ENTER...")

def reanudar_respaldo(config, gestor):
    pausados = gestor.obtener_pausados()
    if not pausados:
        print("No hay respaldos interrumpidos.")
        input("Presiona ENTER...")
        return
    print("\n🔄 RESPALDOS INTERRUMPIDOS")
    for i, e in enumerate(pausados, 1):
        print(f"{i}. {e.tipo} - {e.origen[:50]} - {e.procesados}/{e.total_archivos}")
    sel = input("Selecciona número (0 cancelar): ").strip()
    if sel == "0":
        return
    idx = int(sel)-1
    if idx < 0 or idx >= len(pausados):
        print("Opción inválida")
        return
    estado = pausados[idx]
    archivos_pendientes = []
    if estado.tipo == "general":
        origenes = estado.origen.split(" + ")
        for o in origenes:
            for ruta, nombre, size in walk_fast(o):
                rel = os.path.relpath(ruta, o)
                destino_rel = os.path.join(os.path.basename(o), rel)
                if not os.path.exists(os.path.join(estado.destino, destino_rel)):
                    archivos_pendientes.append((ruta, destino_rel, size))
    else:
        for ruta, nombre, size in walk_fast(estado.origen):
            rel = os.path.relpath(ruta, estado.origen)
            if not os.path.exists(os.path.join(estado.destino, rel)):
                archivos_pendientes.append((ruta, rel, size))
    total = len(archivos_pendientes)
    if total == 0:
        print("No hay archivos pendientes. Respaldo ya completado.")
        gestor.completar_respaldo(estado.id)
        return
    print(f"Archivos pendientes: {total}")
    progreso = ProgresoConsola(total, sum(size for _, _, size in archivos_pendientes), "Reanudando") if config.mostrar_progreso else None
    gestor.reanudar_respaldo(estado.id)
    hilos = calcular_hilos_optimos(config)
    copiados, dup, err, tam = ejecutar_copia_con_monitor(archivos_pendientes, estado.destino, hilos, progreso, config)
    if progreso:
        progreso.completar()
    gestor.completar_respaldo(estado.id)
    print(f"✅ Reanudación completada. Copiados: {copiados}, Errores: {err}")
    input("Presiona ENTER...")

# ======================================================================
# SEGURIDAD / MODO RED — motor seguro unificado (adaptado de Respaldos5.0.py)
# ======================================================================

def _recibir_exacto(sock, n):
    datos = bytearray()
    while len(datos) < n:
        trozo = sock.recv(n - len(datos))
        if not trozo:
            raise ConnectionError("el otro equipo cerró la conexión")
        datos += trozo
    return bytes(datos)

def _ruta_segura(carpeta, rel):
    try:
        if "\x00" in rel:
            return None
        base = os.path.realpath(os.path.abspath(carpeta))
        destino = os.path.realpath(os.path.abspath(os.path.join(base, rel.replace("/", os.sep))))
        if destino == base or os.path.commonpath((base, destino)) != base:
            return None
        return destino
    except (ValueError, OSError):
        return None

def _enmascarar(clave):
    return "ninguna" if not clave else P + clave[-4:]

def _detectar_ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def _clave_red_bytes(config):
    if not config.red_clave:
        config.red_clave = secrets.token_hex(32)
        try:
            config.guardar()
        except OSError:
            pass
    return hashlib.pbkdf2_hmac("sha256", config.red_clave.encode("utf-8"), b"Respaldos.Gio", 100_000, dklen=32)

_BINDING_TLS_SIN_SOPORTE = False

def _binding_tls(sock):
    global _BINDING_TLS_SIN_SOPORTE
    try:
        binding = sock.get_channel_binding("tls-server-end-point")
    except (AttributeError, ValueError, OSError):
        return b""
    if not binding and not _BINDING_TLS_SIN_SOPORTE and hasattr(sock, "getpeercert"):
        _BINDING_TLS_SIN_SOPORTE = True
        print("Aviso: este Python/OpenSSL no expone 'tls-server-end-point'.")
    return binding or b""

def _handshake_servidor(conn, clave):
    binding = _binding_tls(conn)
    for _ in range(MAX_INTENTOS_AUTH):
        nonce = secrets.token_bytes(32)
        try:
            conn.sendall(nonce)
            resp = _recibir_exacto(conn, 32)
        except (ConnectionError, OSError):
            raise ConnectionError("conexión cerrada durante autenticación")
        esperado = hmac.new(clave, nonce + binding, hashlib.sha256).digest()
        if hmac.compare_digest(resp, esperado):
            conn.sendall(b"OK")
            return
        try:
            conn.sendall(b"NO")
        except OSError:
            pass
    raise ConnectionError("demasiados intentos fallidos")

def _handshake_cliente(sock, clave):
    nonce = _recibir_exacto(sock, 32)
    binding = _binding_tls(sock)
    resp = hmac.new(clave, nonce + binding, hashlib.sha256).digest()
    sock.sendall(resp)
    r = _recibir_exacto(sock, 2)
    if r != b"OK":
        raise ConnectionError("el servidor rechazó la autenticación (clave incorrecta)")

def _intentar_tls_servidor():
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
        for pth in (cert_path, key_path):
            try:
                os.remove(pth)
            except OSError:
                pass
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
                f.write(key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.TraditionalOpenSSL, encryption_algorithm=serialization.NoEncryption()))
            with open(cert_path, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
            _restringir_permisos(key_path)
        except Exception:
            return None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        return ctx
    except Exception:
        return None

def _huella_cert(sock):
    try:
        der = sock.getpeercert(binary_form=True)
        if not der:
            return None
        return hashlib.sha256(der).hexdigest()
    except Exception:
        return None

def _verificar_pin(ip, huella):
    datos = _cargar_json_seguro(RUTA_PINNING, {})
    if not isinstance(datos, dict):
        datos = {}
    conocida = datos.get(ip)
    if conocida is None:
        print(f"\nServidor nuevo: {ip}")
        print("Huella del certificado (SHA-256):")
        print(f"  {huella}")
        resp = input("¿Confiar en este servidor y recordarlo? (s/N): ").strip().lower()
        if resp not in ("s", "si", "sí", "y", "yes"):
            return False
        datos[ip] = huella
        try:
            with open(RUTA_PINNING, "w", encoding="utf-8") as f:
                json.dump(datos, f, indent=2, ensure_ascii=False)
            _restringir_permisos(RUTA_PINNING)
        except OSError:
            pass
        return True
    if hmac.compare_digest(conocida, huella):
        return True
    print(f"\n¡ALERTA! La huella del certificado de {ip} CAMBIÓ.")
    print(f"  Esperada: {conocida}")
    print(f"  Recibida: {huella}")
    print("Esto puede indicar un MITM, una reinstalación legítima o rotación de certificado.")
    resp = input("¿Actualizar la huella guardada? (s/N): ").strip().lower()
    if resp not in ("s", "si", "sí", "y", "yes"):
        return False
    datos[ip] = huella
    try:
        with open(RUTA_PINNING, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
    return True

def _restringir_permisos(ruta, es_carpeta=False):
    if platform.system() == "Windows":
        try:
            usuario = os.environ.get("USERNAME", "")
            if usuario:
                subprocess.run(["icacls", ruta, "/inheritance:r", "/grant:r", f"{usuario}:F"], capture_output=True, timeout=5)
        except Exception:
            pass
        return
    try:
        os.chmod(ruta, 0o700 if es_carpeta else 0o600)
    except OSError:
        pass

def motivo_corto(e):
    if isinstance(e, PermissionError):
        return "sin permisos"
    if isinstance(e, FileNotFoundError):
        return "ya no existe"
    if isinstance(e, OSError) and (e.errno == errno.ENOSPC or getattr(e, "winerror", None) in (39, 112)):
        return "disco de destino lleno"
    return str(e)[:80]


def servidor_red(config):
    print(f"\n🌐 MODO SERVIDOR")
    archivos = []
    for c in obtener_carpetas_usuario():
        print(f"🔍 Escaneando {c}...")
        base = os.path.basename(c)
        for ruta, nombre, size in walk_fast(c):
            archivos.append((ruta, base + "/" + os.path.relpath(ruta, c).replace(os.sep, "/"), size))
    print(f"{len(archivos)} archivos listos para enviar.")

    clave = _clave_red_bytes(config)
    print(f"Clave de red configurada: {_enmascarar(config.red_clave)}")
    if input("¿Mostrar la clave completa en pantalla para copiarla? (s/N): ").strip().lower() in ("s","si","sí","y","yes"):
        print(f"Clave de red (compártela con el cliente): {config.red_clave}")

    bind_ip = config.red_bind_ip or ""
    if not bind_ip:
        ip_local = _detectar_ip_local()
        sugerida = ip_local or "0.0.0.0"
        entrada = input(f"IP a exponer [Enter = {sugerida}]: ").strip()
        bind_ip = entrada or sugerida
    if bind_ip == "0.0.0.0":
        resp = input("Vas a exponer el servidor en TODAS las interfaces. ¿Continuar? (s/N): ").strip().lower()
        if resp not in ("s","si","sí","y","yes"):
            ip_local = _detectar_ip_local()
            if ip_local:
                print(f"Usando IP local: {ip_local}")
                bind_ip = ip_local
            else:
                print("Cancelado.")
                return

    if not config.red_usar_tls:
        print("AVISO: TLS está desactivado. Los archivos viajarán SIN CIFRAR por la red.")
        if input("¿Continuar sin TLS? (s/N): ").strip().lower() not in ("s","si","sí","y","yes"):
            return

    tls_ctx = _intentar_tls_servidor() if config.red_usar_tls else None
    if config.red_usar_tls and tls_ctx is None:
        print("Aviso: TLS no disponible (falta 'cryptography' o fallo al generar cert).")
        print("El HMAC evita accesos no autorizados, pero el tráfico viaja en claro.")
        if input("¿Continuar sin TLS? (s/N): ").strip().lower() not in ("s","si","sí","y","yes"):
            return

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((bind_ip, NETWORK_PORT))
        srv.listen(8)
        srv.settimeout(5.0)
        print(f"Esperando cliente en {bind_ip}:{NETWORK_PORT}...")
        limite = time.monotonic() + NETWORK_ESPERA_SERVIDOR
        conn = None
        fallos_por_ip = defaultdict(int)
        ips_bloqueadas = set()
        while conn is None:
            if time.monotonic() > limite:
                print("Tiempo de espera agotado sin un cliente autenticado. Servidor cerrado.")
                return
            try:
                crudo, addr = srv.accept()
            except socket.timeout:
                continue
            ip_origen = addr[0]
            if ip_origen in ips_bloqueadas:
                try:
                    crudo.close()
                except OSError:
                    pass
                continue
            try:
                crudo.settimeout(NETWORK_TIMEOUT_SERVIDOR_AUTH)
                candidata = tls_ctx.wrap_socket(crudo, server_side=True) if tls_ctx is not None else crudo
                if _recibir_exacto(candidata, len(MAGIA_RED)) != MAGIA_RED:
                    raise ConnectionError("protocolo o versión distintos")
                _handshake_servidor(candidata, clave)
                conn = candidata
            except (ssl.SSLError, ConnectionError, OSError) as e:
                fallos_por_ip[ip_origen] += 1
                print(f"Conexión de {ip_origen} descartada ({type(e).__name__}); sigo esperando...")
                if fallos_por_ip[ip_origen] >= MAX_FALLOS_POR_IP:
                    ips_bloqueadas.add(ip_origen)
                    print(f"IP {ip_origen} bloqueada tras {MAX_FALLOS_POR_IP} intentos fallidos.")
                try:
                    crudo.close()
                except OSError:
                    pass
        with conn:
            print(f"Cliente autenticado desde {addr[0]}")
            conn.settimeout(120)
            conn.sendall(ENC_TOTAL.pack(len(archivos)))
            tam_total_envio = sum(s for _,_,s in archivos)
            progreso = ProgresoConsola(len(archivos), tam_total_envio, "Enviando") if config.mostrar_progreso else None
            for ruta, rel, _ in archivos:
                try:
                    f = open(ruta, "rb")
                except OSError:
                    if progreso: progreso.actualizar(1, 0)
                    continue
                with f:
                    real = os.fstat(f.fileno()).st_size
                    nombre = rel.encode("utf-8")
                    conn.sendall(ENC_ARCHIVO.pack(len(nombre), real) + nombre)
                    if real:
                        if conn.sendfile(f, count=real) != real:
                            raise ConnectionError(f"el archivo cambió mientras se enviaba: {rel}")
                    if progreso: progreso.actualizar(1, real)
            conn.sendall(ENC_ARCHIVO.pack(0, 0))
            if progreso: progreso.completar()
    finally:
        srv.close()
    print(f"✅ Transferencia completada.")
    input("Presiona ENTER...")


def cliente_red(config):
    ip = input("IP del servidor: ").strip()
    if not ip:
        return
    clave_txt = input(f"Clave de red (Enter = usar la guardada: {_enmascarar(config.red_clave)}): ").strip()
    if not clave_txt:
        clave_txt = config.red_clave
    if not clave_txt:
        print("Se requiere la clave de red para autenticarse.")
        return
    clave = hashlib.sha256(clave_txt.encode("utf-8")).digest()
    if not config.red_usar_tls:
        print("AVISO: TLS está desactivado. Todo lo que recibas viajará SIN CIFRAR por la red.")
        if input("¿Continuar sin TLS? (s/N): ").strip().lower() not in ("s","si","sí","y","yes"):
            return
    destino = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    if not destino:
        destino = config.ruta_base_respaldos
    destino = expandir_ruta(destino)
    sock = socket.create_connection((ip, NETWORK_PORT), timeout=NETWORK_TIMEOUT_AUTH)
    if config.red_usar_tls:
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=ip)
        except ssl.SSLError as e:
            print(f"Error TLS: {e}")
            print("Se aborta la conexión. Desactiva \'red_usar_tls\' en configuración si quieres ir en claro.")
            try:
                sock.close()
            except OSError:
                pass
            return
    if config.red_usar_tls:
        huella = _huella_cert(sock)
        if not huella:
            print("No se pudo obtener el certificado del servidor. Se aborta.")
            try:
                sock.close()
            except OSError:
                pass
            return
        if not _verificar_pin(ip, huella):
            print("Conexión abortada por verificación de identidad del servidor.")
            try:
                sock.close()
            except OSError:
                pass
            return
    carpeta = None
    try:
        sock.settimeout(120)
        sock.sendall(MAGIA_RED)
        _handshake_cliente(sock, clave)
        total = ENC_TOTAL.unpack(_recibir_exacto(sock, ENC_TOTAL.size))[0]
        print(f"Recibiendo {total} archivos...")
        carpeta = crear_carpeta_respaldo(destino, config.proteger_respaldos)
        progreso = ProgresoConsola(total, 0, "Descargando") if config.mostrar_progreso else None
        buf = bytearray(max(256 * 1024, (config.tamano_buffer_mb or 8) * 1024 * 1024))
        vista = memoryview(buf)
        carpetas_ok = set()
        recibidos = tam_total = 0
        errores_red = []
        inicio = time.time()
        while True:
            largo, size = ENC_ARCHIVO.unpack(_recibir_exacto(sock, ENC_ARCHIVO.size))
            if largo == 0:
                break
            rel = _recibir_exacto(sock, largo).decode("utf-8", "replace")
            destino_archivo = _ruta_segura(carpeta, rel)
            guardado_ok = False
            f = None
            if destino_archivo:
                try:
                    d = os.path.dirname(destino_archivo)
                    if d not in carpetas_ok:
                        os.makedirs(d, exist_ok=True)
                        carpetas_ok.add(d)
                    f = open(destino_archivo, "wb")
                    guardado_ok = True
                except OSError as e:
                    errores_red.append((rel, motivo_corto(e)))
                    f = None
                    guardado_ok = False
            else:
                errores_red.append((rel, "ruta no permitida (bloqueada)"))
            try:
                restante = size
                while restante:
                    n = sock.recv_into(vista[:min(len(buf), restante)])
                    if not n:
                        raise ConnectionError("el otro equipo cerró la conexión")
                    if f:
                        try:
                            f.write(vista[:n])
                        except OSError as e:
                            errores_red.append((rel, motivo_corto(e)))
                            try:
                                f.close()
                            except OSError:
                                pass
                            f = None
                            guardado_ok = False
                    restante -= n
                    if progreso: progreso.actualizar(0, n)
            finally:
                if f:
                    try:
                        f.close()
                    except OSError:
                        pass
            if guardado_ok:
                recibidos += 1
                tam_total += size
            if progreso: progreso.actualizar(1, 0)
        if progreso: progreso.completar()
        if errores_red:
            print(f"⚠{len(errores_red)} archivo(s) del servidor NO se guardaron")
        registrar_respaldo(carpeta, "red_general", f"{recibidos} archivos", config)
        guardar_ultima_ruta(carpeta, "red_general")
        print(f"✅ Respaldo remoto completado en {carpeta}")
        if config.comprimir_automatico:
            comprimir_respaldo(carpeta, config.nivel_compresion, proteger=config.proteger_respaldos)
    finally:
        sock.close()
    input("Presiona ENTER...")


def modo_red(config):
    print(f"\n🌐 MODO RED")
    print("1. Actuar como SERVIDOR")
    print("2. Actuar como CLIENTE")
    print("3. Cancelar")
    op = input("Selecciona: ").strip()
    if op == "1":
        servidor_red(config)
    elif op == "2":
        cliente_red(config)
    elif op == "3":
        return
    else:
        print("Opción inválida")
def eliminar_respaldo(config):
    nombres_generados = obtener_nombres_respaldo_generados()
    base = config.ruta_base_respaldos
    if not os.path.exists(base):
        print(f"La carpeta {base} no existe.")
        input("Presiona ENTER...")
        return
    respaldos = []
    for item in os.listdir(base):
        nombre_base = item[:-4] if item.lower().endswith(".zip") else item
        if nombre_base in nombres_generados:
            full = os.path.join(base, item)
            if os.path.isdir(full):
                size = sum(os.path.getsize(os.path.join(root,f)) for root,_,fs in os.walk(full) for f in fs)
            else:
                size = os.path.getsize(full)
            respaldos.append((item, full, size))
    if not respaldos:
        print("No hay respaldos generados por el programa en esta ruta (recuerda que solo se pueden eliminar los que el propio sistema creó).")
        input("Presiona ENTER...")
        return
    print("\n🗑️ RESPALDOS DISPONIBLES")
    for i, (nombre, _, tam) in enumerate(respaldos, 1):
        tam_text = f"{tam/(1024**2):.1f} MB" if tam < 1024**3 else f"{tam/(1024**3):.2f} GB"
        print(f"{i}. {nombre} ({tam_text})")
    sel = input("Número a eliminar (0 cancelar): ").strip()
    if sel == "0":
        return
    idx = int(sel)-1
    if 0 <= idx < len(respaldos):
        nombre, full, _ = respaldos[idx]
        conf = input(f"¿Eliminar {nombre}? (sí/NO): ").strip().lower()
        if conf in ['si','sí','yes','y']:
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
            nombre_base = nombre[:-4] if nombre.lower().endswith(".zip") else nombre
            quitar_nombre_respaldo(nombre_base)
            print(f"✅ Eliminado: {nombre}")
            if os.path.exists(RUTA_REGISTRO):
                with open(RUTA_REGISTRO, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                with open(RUTA_REGISTRO, "w", encoding="utf-8") as f:
                    for line in lines:
                        if full not in line:
                            f.write(line)
        else:
            print("Cancelado")
    else:
        print("Número inválido")
    input("Presiona ENTER...")

def mostrar_registros():
    if not os.path.exists(RUTA_REGISTRO):
        print("No hay registros de respaldos.")
        input("Presiona ENTER...")
        return
    with open(RUTA_REGISTRO, "r", encoding="utf-8") as f:
        lineas = f.readlines()
    print("\n" + "="*70)
    print("                     📜 REGISTROS DE RESPALDOS")
    print("="*70)
    print(f"Total: {len(lineas)}")
    for i, linea in enumerate(reversed(lineas[-10:]), 1):
        partes = linea.strip().split("|")
        if len(partes) >= 2:
            fecha = partes[0]
            ruta = partes[1]
            tipo = partes[2] if len(partes)>2 else ""
            print(f"{i}. {fecha[:19]} | {tipo.upper()} | {ruta}")
    print("="*70)
    input("Presiona ENTER...")

def menu_configuracion(config):
    while True:
        limpiar_terminal()
        print("\n⚙️ CONFIGURACIÓN")
        print(f"1. Compresión automática: {'✅ Activado' if config.comprimir_automatico else '❌ Desactivado'}")
        print(f"2. Registrar rutas en .txt: {'✅ Activado' if config.registrar_rutas else '❌ Desactivado'}")
        print(f"3. Barra de progreso: {'✅ Activado' if config.mostrar_progreso else '❌ Desactivado'}")
        print(f"4. Guardar estado de respaldos: {'✅ Activado' if config.guardar_estado_respaldos else '❌ Desactivado'}")
        print(f"5. Ajuste automático de hilos: {'✅ Activado' if config.auto_ajustar_hilos else '❌ Desactivado'}")
        print(f"6. Hilos paralelos: {config.max_archivos_paralelos} ({'Auto' if config.auto_ajustar_hilos else 'Manual'})")
        print(f"7. Nivel compresión (0-9): {config.nivel_compresion}")
        print(f"8. Ruta base respaldos: {config.ruta_base_respaldos}")
        print("9. Guardar y volver")
        op = input("Opción: ").strip()
        if op == "1":
            config.comprimir_automatico = not config.comprimir_automatico
            config.guardar()
        elif op == "2":
            config.registrar_rutas = not config.registrar_rutas
            config.guardar()
        elif op == "3":
            config.mostrar_progreso = not config.mostrar_progreso
            config.guardar()
        elif op == "4":
            config.guardar_estado_respaldos = not config.guardar_estado_respaldos
            config.guardar()
        elif op == "5":
            config.auto_ajustar_hilos = not config.auto_ajustar_hilos
            config.guardar()
        elif op == "6":
            print("\n🧵 HILOS PARALELOS:")
            print("   Controla cuántos archivos se copian simultáneamente.")
            print(f"   Recomendado: entre 4 y {MAX_WORKERS} (tu CPU tiene {os.cpu_count()} núcleos).")
            entrada = input("Número de hilos (1-64) o 'auto': ").strip().lower()
            if entrada == 'auto':
                config.auto_ajustar_hilos = True
                config.max_archivos_paralelos = min(64, MAX_WORKERS)
            else:
                try:
                    n = int(entrada)
                    config.max_archivos_paralelos = max(1, min(64, n))
                    config.auto_ajustar_hilos = False
                except:
                    pass
            config.guardar()
        elif op == "7":
            print("\n📦 NIVEL DE COMPRESIÓN:")
            print("   0 = Sin compresión (más rápido, archivos más grandes)")
            print("   6 = Equilibrio por defecto (recomendado)")
            print("   9 = Máxima compresión (más lento, archivos más pequeños)")
            try:
                n = int(input("Nuevo nivel (0-9): "))
                if 0 <= n <= 9:
                    config.nivel_compresion = n
                    config.guardar()
            except:
                pass
        elif op == "8":
            nueva = input("Nueva ruta base: ").strip()
            if nueva:
                config.ruta_base_respaldos = expandir_ruta(nueva)
                config.guardar()
        elif op == "9":
            config.guardar()
            print("Configuración guardada")
            break

def menu_principal():
    config = Configuracion.cargar()
    # Asegurar que la ruta base sea absoluta
    if not os.path.isabs(config.ruta_base_respaldos) or config.ruta_base_respaldos == "Respaldos":
        config.ruta_base_respaldos = RUTA_RESPALDOS
        config.guardar()
    gestor = GestorEstados()
    while True:
        limpiar_terminal()
        print("\n" + "="*70)
        print("       SISTEMA DE RESPALDOS AVANZADO - TERMINAL PORTABLE")
        print("="*70)
        print(f"💻 {platform.system()} | 📁 Base: {config.ruta_base_respaldos}")
        ultima = leer_ultima_ruta()
        if ultima:
            print(f"🕘 {ultima.splitlines()[0]}")
        pausados = len(gestor.obtener_pausados())
        if pausados:
            print(f"⏸️ Respaldos interrumpidos: {pausados}")
        print("\n📋 MENÚ:")
        print(" 1) 📂 Respaldo general (carpetas usuario)")
        print(" 2) 🔤 Respaldo por extensiones")
        print(" 3) 💾 Recuperar disco externo")
        print(" 4) 🗄️ Respaldo XAMPP/MySQL")
        print(" 5) 🔄 Reanudar respaldo interrumpido")
        print(" 6) 📱 Respaldo móvil (Android/iOS)")
        print(" 7) 🌐 Modo red interna")
        print(" 8) 🗑️ Eliminar respaldo seguro")
        print(" 9) 📜 Ver registros")
        print("10) ⚙️ Configuración")
        print("11) 🚪 Salir")
        op = input("Opción: ").strip()
        try:
            if op == "1":
                respaldo_general(config, gestor)
            elif op == "2":
                respaldo_extensiones(config, gestor)
            elif op == "3":
                recuperar_disco_externo(config, gestor)
            elif op == "4":
                respaldo_xampp(config, gestor)
            elif op == "5":
                reanudar_respaldo(config, gestor)
            elif op == "6":
                respaldar_moviles(config, gestor)
            elif op == "7":
                modo_red(config)
            elif op == "8":
                eliminar_respaldo(config)
            elif op == "9":
                mostrar_registros()
            elif op == "10":
                menu_configuracion(config)
            elif op == "11":
                print("👋 Hasta pronto")
                config.guardar()
                gestor._guardar()
                break
            else:
                print("Opción no válida")
                time.sleep(1)
        except KeyboardInterrupt:
            global _estado_en_curso
            if _estado_en_curso:
                gestor.pausar_respaldo(_estado_en_curso.id, [], [])
                print(f"\n{icono('⏸️','[PAUSA]')} Respaldo interrumpido. Podrás reanudarlo con la opción 5 (Reanudar respaldo interrumpido).")
                _estado_en_curso = None
            else:
                print("\nOperación cancelada.")
            time.sleep(1)
        except Exception as e:
            if _estado_en_curso:
                gestor.pausar_respaldo(_estado_en_curso.id, [], [])
                _estado_en_curso = None
            print(f"\n{icono('⚠️','[ERROR]')} {mensaje_error_amigable(e)}")
            input("Presiona ENTER para continuar...")

if __name__ == "__main__":
    menu_principal()