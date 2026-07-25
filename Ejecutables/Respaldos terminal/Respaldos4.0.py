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
    hasher = hashlib.md5()
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
        id_res = f"{tipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(origen.encode()).hexdigest()[:8]}"
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

def crear_carpeta_respaldo(base):
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
    return carpeta

def comprimir_respaldo(carpeta, nivel=6):
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

def servidor_red(config):
    print("\n🌐 MODO SERVIDOR - Esperando clientes...")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', NETWORK_PORT))
    server.listen(1)
    print(f"Escuchando en puerto {NETWORK_PORT}")
    conn, addr = server.accept()
    print(f"Cliente conectado desde {addr}")
    comando = conn.recv(4096).decode().strip()
    print(f"Solicitud: {comando}")
    carpetas = obtener_carpetas_usuario()
    archivos = []
    for c in carpetas:
        for ruta, nombre, size in walk_fast(c):
            rel = os.path.basename(c) + "/" + os.path.relpath(ruta, c)
            archivos.append((ruta, rel, size))
    conn.sendall(str(len(archivos)).encode())
    time.sleep(0.1)
    for origen, rel, size in archivos:
        conn.sendall(rel.encode() + b'\n')
        conn.sendall(str(size).encode() + b'\n')
        with open(origen, 'rb') as f:
            while chunk := f.read(BUFFER_SIZE):
                conn.sendall(chunk)
        time.sleep(0.01)
    conn.close()
    server.close()
    print("✅ Transferencia completada.")
    input("Presiona ENTER...")

def cliente_red(config):
    servidor_ip = input("IP del servidor: ").strip()
    if not servidor_ip:
        return
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((servidor_ip, NETWORK_PORT))
        sock.sendall(b"general")
        total = int(sock.recv(4096).decode())
        print(f"Recibiendo {total} archivos...")
        destino = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
        if not destino:
            destino = config.ruta_base_respaldos
        destino = expandir_ruta(destino)
        carpeta_destino = crear_carpeta_respaldo(destino)
        progreso = ProgresoConsola(total, 0, "Descargando") if config.mostrar_progreso else None
        tam_total = 0
        inicio = time.time()
        for i in range(total):
            rel = sock.recv(4096).decode().strip()
            size = int(sock.recv(4096).decode().strip())
            destino_archivo = os.path.join(carpeta_destino, rel)
            os.makedirs(os.path.dirname(destino_archivo), exist_ok=True)
            with open(destino_archivo, 'wb') as f:
                recibido = 0
                while recibido < size:
                    chunk = sock.recv(min(BUFFER_SIZE, size - recibido))
                    if not chunk:
                        break
                    f.write(chunk)
                    recibido += len(chunk)
            tam_total += recibido
            if progreso:
                progreso.actualizar(1, recibido)
        if progreso:
            progreso.completar()
        sock.close()
        duracion = time.time() - inicio
        metadatos = generar_metadatos_respaldo(servidor_ip, carpeta_destino, "red_general", total, tam_total, duracion, "completado" if total > 0 else "sin_archivos", config)
        guardar_metadatos_respaldo(carpeta_destino, metadatos)
        registrar_respaldo(carpeta_destino, "red_general", f"{total} archivos", config)
        guardar_ultima_ruta(carpeta_destino, "red_general")
        print(f"{icono('✅','OK')} Respaldo remoto completado en {carpeta_destino}")
        if config.comprimir_automatico:
            comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    except Exception as e:
        print(f"❌ Error en cliente: {e}")
    input("Presiona ENTER...")

def modo_red(config):
    print("\n🌐 MODO RED")
    print("1. Actuar como SERVIDOR")
    print("2. Actuar como CLIENTE")
    op = input("Selecciona: ").strip()
    if op == "1":
        servidor_red(config)
    elif op == "2":
        cliente_red(config)
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