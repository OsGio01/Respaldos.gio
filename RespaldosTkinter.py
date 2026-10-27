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
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog, simpledialog
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass, asdict
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import psutil
except ImportError:
    psutil = None

# DETECCIÓN DE RUTA BASE PARA EJECUTABLE (¡CRÍTICO!)
def obtener_ruta_base():
    """Devuelve la carpeta donde está el ejecutable o el script."""
    if getattr(sys, 'frozen', False):
        # Si es un .exe, usamos la carpeta donde está el ejecutable
        return os.path.dirname(sys.executable)
    else:
        # Si es un script, usamos la carpeta actual
        return os.path.dirname(os.path.abspath(__file__))

# Carpeta donde se guardarán configuraciones, logs y respaldos
RUTA_APP = obtener_ruta_base()
RUTA_RESPALDOS = os.path.join(RUTA_APP, "Respaldos")
RUTA_CONFIG = os.path.join(RUTA_APP, "config.json")
RUTA_ESTADOS = os.path.join(RUTA_APP, "estados_respaldo.json")
RUTA_REGISTRO = os.path.join(RUTA_APP, "rutas_respaldo.txt")
RUTA_CONFIG_DIR = os.path.join(RUTA_APP, "config")  # Para listas blanca/negra
RUTA_NOMBRES_GENERADOS = os.path.join(RUTA_APP, "respaldos_generados.json")  # registro de respaldos creados por el programa
RUTA_ULTIMO_RESPALDO = os.path.join(RUTA_APP, "ultimo_respaldo.txt")  # ruta persistente del último respaldo

# Asegurar que existan las carpetas necesarias
os.makedirs(RUTA_RESPALDOS, exist_ok=True)
os.makedirs(RUTA_CONFIG_DIR, exist_ok=True)

# CONSTANTES DE RENDIMIENTO
MAX_WORKERS = min(32, (os.cpu_count() or 2) * 2)
BUFFER_SIZE = 256 * 1024
HASH_CHUNK_SIZE = 8192
NETWORK_PORT = 56789

# CLASES DEL NÚCLEO (con rutas ajustadas)
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
    ruta_base_respaldos: str = RUTA_RESPALDOS
    tema_oscuro: bool = False
    auto_ajustar_hilos: bool = True  # compartido con la versión terminal
    
    @classmethod
    def cargar(cls, ruta=None):
        if ruta is None:
            ruta = RUTA_CONFIG
        default = cls()
        if os.path.exists(ruta):
            try:
                with open(ruta, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                    # Filtrar claves desconocidas (p.ej. campos que solo existen en la
                    # versión terminal) para no perder el resto de la configuración
                    # guardada si ambas versiones comparten el mismo config.json.
                    filtros = {k: v for k, v in datos.items() if k in cls.__annotations__}
                    return cls(**filtros)
            except Exception:
                pass
        return default
    
    def guardar(self, ruta=None):
        if ruta is None:
            ruta = RUTA_CONFIG
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

class GestorEstados:
    def __init__(self, archivo=None):
        if archivo is None:
            archivo = RUTA_ESTADOS
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
        id_res = f"{tipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(origen.encode()).hexdigest()[:8]}"
        estado = EstadoRespaldo(id=id_res, origen=origen, destino=destino, tipo=tipo,
                                total_archivos=total_archivos, fecha_inicio=datetime.now().isoformat(), activo=True)
        self.estados[id_res] = estado
        self._guardar()
        return estado
    
    def completar_respaldo(self, id_res):
        if id_res in self.estados:
            del self.estados[id_res]
            self._guardar()
    
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

class FiltroRutas:
    def __init__(self, config_dir=None):
        if config_dir is None:
            config_dir = RUTA_CONFIG_DIR
        self.config_dir = config_dir
        os.makedirs(self.config_dir, exist_ok=True)
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

def copiar_archivo(args):
    origen, destino, sobrescribir, hash_cache = args
    try:
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

def copia_paralela(archivos, destino_base, sobrescribir=False, max_workers=MAX_WORKERS, progreso_callback=None, monitor=None):
    hash_cache = {}
    tasks = [(origen, os.path.join(destino_base, rel), sobrescribir, hash_cache) for origen, rel, _ in archivos]
    copiados = duplicados = errores = tam_total = 0
    total = len(tasks)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(copiar_archivo, t): t for t in tasks}
        for future in as_completed(futures):
            if monitor and monitor.delay > 0:
                time.sleep(monitor.delay)
            ok, tam, msg = future.result()
            bytes_delta = 0
            if ok:
                if msg == "duplicado":
                    duplicados += 1
                else:
                    copiados += 1
                    tam_total += tam
                    bytes_delta = tam
            else:
                errores += 1
            if progreso_callback:
                progreso_callback(copiados + duplicados + errores, total, bytes_delta)
    return copiados, duplicados, errores, tam_total

def comprimir_respaldo(carpeta, nivel=6):
    zip_path = carpeta + ".zip"
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=nivel) as zf:
            for root, _, files in os.walk(carpeta):
                for f in files:
                    full = os.path.join(root, f)
                    zf.write(full, os.path.relpath(full, carpeta))
        shutil.rmtree(carpeta)
        return zip_path
    except Exception as e:
        raise e

def registrar_respaldo(ruta, tipo, detalles, config):
    if config.registrar_rutas:
        with open(RUTA_REGISTRO, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}|{ruta}|{tipo}|{detalles}\n")


def sanitizar_nombre(texto: str) -> str:
    limpio = re.sub(r"[^A-Za-z0-9_-]", "_", texto.strip())
    return limpio[:64] if limpio else "backup"


def obtener_usuario_equipo() -> Tuple[str, str]:
    usuario = os.environ.get("USERNAME") or os.environ.get("USER") or "usuario"
    equipo = platform.node() or "equipo"
    return sanitizar_nombre(usuario), sanitizar_nombre(equipo)


def mensaje_error_amigable(e: Exception) -> str:
    """Traduce excepciones técnicas a mensajes comprensibles para un usuario sin conocimientos técnicos."""
    texto = str(e)
    if isinstance(e, PermissionError) or "Permission denied" in texto or "Acceso denegado" in texto:
        return ("No se pudo completar la operación porque no hay permisos suficientes para acceder a algunos "
                "archivos o carpetas. Intenta ejecutar el programa como administrador o revisa los permisos.")
    if isinstance(e, FileNotFoundError):
        return ("No se pudo completar la operación porque una de las rutas ya no existe. Verifica que el disco, "
                "USB o carpeta siga conectado y disponible.")
    if (isinstance(e, OSError) and getattr(e, "errno", None) == 28) or "No space left" in texto or "espacio" in texto.lower():
        return "No hay suficiente espacio en el disco de destino. Libera espacio o elige otra ubicación."
    if isinstance(e, (ConnectionError, socket.error)):
        return "Se perdió la conexión de red durante la transferencia. Verifica que ambos equipos sigan en la misma red."
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
    """Registra el nombre base (sin .zip) de un respaldo creado por el programa,
    compartiendo el mismo registro que usa la versión de terminal."""
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


def obtener_nombres_respaldo_generados():
    return set(_cargar_json_seguro(RUTA_NOMBRES_GENERADOS, []))


def guardar_ultima_ruta(carpeta_destino: str, tipo: str):
    try:
        with open(RUTA_ULTIMO_RESPALDO, "w", encoding="utf-8") as f:
            f.write(f"Último respaldo: {carpeta_destino}\n")
            f.write(f"Tipo: {tipo}\n")
            f.write(f"Fecha: {datetime.now().isoformat()}\n")
    except Exception:
        pass


def leer_ultima_ruta():
    if os.path.exists(RUTA_ULTIMO_RESPALDO):
        try:
            with open(RUTA_ULTIMO_RESPALDO, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return None
    return None


def formatear_bytes(bytes_val: Optional[float]) -> str:
    if bytes_val is None:
        return "N/A"
    valor = float(bytes_val)
    for unidad in ["B", "KB", "MB", "GB", "TB"]:
        if valor < 1024 or unidad == "TB":
            return f"{valor:.1f} {unidad}"
        valor /= 1024
    return f"{valor:.1f} TB"


def calcular_hilos_optimos(config) -> int:
    """Ajusta automáticamente el número de hilos según CPU/memoria disponibles
    (paridad con la versión de terminal, antes solo disponible ahí)."""
    max_threads = min(64, config.max_archivos_paralelos or MAX_WORKERS)
    if not getattr(config, 'auto_ajustar_hilos', True) or not psutil:
        return max_threads
    try:
        cpu_pct = psutil.cpu_percent(interval=0.2)
        memoria = psutil.virtual_memory()
        nucleos = psutil.cpu_count(logical=True) or (os.cpu_count() or 1)
        base = max(1, int(nucleos * 0.8))
        if cpu_pct > 70 or memoria.percent > 80:
            valor = max(1, base // 2)
        else:
            valor = max(1, min(base, max_threads))
        return min(max_threads, valor)
    except Exception:
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
            proceso.nice(10 if reducir else 0)
    except Exception:
        pass


class MonitorRecursos(threading.Thread):
    """Supervisa CPU/memoria durante el respaldo y reduce la prioridad del proceso
    si detecta carga alta, igual que en la versión de terminal."""
    def __init__(self, config):
        super().__init__(daemon=True)
        self.config = config
        self._stop = threading.Event()
        self.delay = 0.0
        self.prioridad_reducida = False

    def run(self):
        if not psutil:
            return
        while not self._stop.is_set():
            try:
                cpu_pct = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()
                uso_alto = cpu_pct > 70 or mem.percent > 80
                if uso_alto:
                    self.delay = min(2.0, max(0.2, (cpu_pct - 50) / 30))
                    if not self.prioridad_reducida:
                        ajustar_prioridad_proceso(reducir=True)
                        self.prioridad_reducida = True
                else:
                    self.delay = 0.0
                    if self.prioridad_reducida:
                        ajustar_prioridad_proceso(reducir=False)
                        self.prioridad_reducida = False
            except Exception:
                pass
            self._stop.wait(2)

    def stop(self):
        self._stop.set()
        if self.prioridad_reducida:
            ajustar_prioridad_proceso(reducir=False)


def obtener_info_sistema() -> Dict[str, Optional[object]]:
    usuario, equipo = obtener_usuario_equipo()
    sistema = platform.system()
    memoria_total = memoria_disponible = None
    cpu_uso = None
    cpu_logico = os.cpu_count() or 1
    if psutil:
        try:
            memoria = psutil.virtual_memory()
            memoria_total = memoria.total
            memoria_disponible = memoria.available
            cpu_uso = psutil.cpu_percent(interval=0.2)
            cpu_logico = psutil.cpu_count(logical=True) or cpu_logico
        except Exception:
            pass
    return {
        "usuario": usuario, "equipo": equipo,
        "sistema": f"{sistema} {platform.release()}",
        "cpu_logico": cpu_logico, "cpu_uso": cpu_uso,
        "memoria_total": memoria_total, "memoria_disponible": memoria_disponible,
    }


def detectar_dispositivos_moviles():
    """Detecta dispositivos móviles conectados (Android/iOS), igual que en la versión terminal."""
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

# TIPOGRAFÍA CONSISTENTE
FUENTE_BASE = "Segoe UI"
FUENTE_MONO = "Consolas"
F_TITULO = (FUENTE_BASE, 19, "bold")
F_SUBTITULO = (FUENTE_BASE, 10)
F_SECCION = (FUENTE_BASE, 11, "bold")
F_BOTON_ICONO = (FUENTE_BASE, 20)
F_BOTON_TEXTO = (FUENTE_BASE, 9, "bold")
F_CUERPO = (FUENTE_BASE, 9)
F_LOG = (FUENTE_MONO, 9)

# INTERFAZ MODERNA CON TEMA CLARO/OSCURO
class Tema:
    # Paleta clara: fondo azulado muy suave, acentos con un solo color primario
    # (índigo) + colores semánticos (peligro/advertencia/info/neutral) en vez
    # de un botón de cada color del arcoíris.
    claro = {
        "bg": "#eef1f7",
        "fg": "#1f2937",
        "fg_muted": "#6b7280",
        "frame_bg": "#ffffff",
        "frame_fg": "#1f2937",
        "border": "#e2e6ee",
        "title_fg": "#1f2937",

        "accent_primary": "#4f5fee",
        "accent_primary_hover": "#3f4ed6",
        "accent_neutral": "#f1f3f8",
        "accent_neutral_hover": "#e4e8f2",
        "accent_neutral_fg": "#334155",
        "accent_warning": "#f59e0b",
        "accent_warning_hover": "#d98708",
        "accent_info": "#0ea5a4",
        "accent_info_hover": "#0c8988",
        "accent_danger": "#e5484d",
        "accent_danger_hover": "#cf3b40",
        "accent_fg": "#ffffff",

        "button_bg": "#4f5fee",
        "button_fg": "#ffffff",
        "button_active_bg": "#3f4ed6",
        "progress_bg": "#e2e6ee",
        "progress_color": "#4f5fee",
        "log_bg": "#0f172a",
        "log_fg": "#d7dee8",
        "log_info": "#7dd3fc",
        "log_success": "#4ade80",
        "log_warn": "#fbbf24",
        "log_error": "#f87171",
        "select_bg": "#ffffff",
        "select_fg": "#1f2937",
    }
    oscuro = {
        "bg": "#12141c",
        "fg": "#e6e9f0",
        "fg_muted": "#9aa3b2",
        "frame_bg": "#1b1e29",
        "frame_fg": "#e6e9f0",
        "border": "#2a2e3d",
        "title_fg": "#ffffff",

        "accent_primary": "#6d7bff",
        "accent_primary_hover": "#5b69f0",
        "accent_neutral": "#242837",
        "accent_neutral_hover": "#2e3345",
        "accent_neutral_fg": "#cbd2e1",
        "accent_warning": "#f5a524",
        "accent_warning_hover": "#d98f13",
        "accent_info": "#22b8b0",
        "accent_info_hover": "#1a9a93",
        "accent_danger": "#f0555b",
        "accent_danger_hover": "#d94048",
        "accent_fg": "#ffffff",

        "button_bg": "#6d7bff",
        "button_fg": "#ffffff",
        "button_active_bg": "#5b69f0",
        "progress_bg": "#242837",
        "progress_color": "#6d7bff",
        "log_bg": "#0b0d13",
        "log_fg": "#d7dee8",
        "log_info": "#7dd3fc",
        "log_success": "#4ade80",
        "log_warn": "#fbbf24",
        "log_error": "#f87171",
        "select_bg": "#1b1e29",
        "select_fg": "#e6e9f0",
    }
    
    @classmethod
    def aplicar(cls, root, config):
        tema = cls.oscuro if config.tema_oscuro else cls.claro
        root.configure(bg=tema["bg"])
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background=tema["bg"])
        style.configure("Card.TFrame", background=tema["frame_bg"])
        style.configure("TLabel", background=tema["bg"], foreground=tema["fg"], font=F_CUERPO)
        style.configure("Muted.TLabel", background=tema["bg"], foreground=tema["fg_muted"], font=F_CUERPO)
        style.configure("TLabelframe", background=tema["bg"], foreground=tema["fg"], bordercolor=tema["border"])
        style.configure("TLabelframe.Label", background=tema["bg"], foreground=tema["fg"], font=F_SECCION)
        style.configure("TButton", background=tema["accent_neutral"], foreground=tema["accent_neutral_fg"],
                         borderwidth=0, focusthickness=0, font=F_CUERPO, padding=6)
        style.map("TButton", background=[("active", tema["accent_neutral_hover"])])
        style.configure("Progreso.Horizontal.TProgressbar", background=tema["progress_color"],
                         troughcolor=tema["progress_bg"], borderwidth=0, thickness=16)
        style.configure("TEntry", fieldbackground=tema["select_bg"], foreground=tema["select_fg"])
        style.configure("TCheckbutton", background=tema["bg"], foreground=tema["fg"], font=F_CUERPO)
        style.configure("TScale", background=tema["bg"])
        return tema

class AppRespaldo:
    def __init__(self, root):
        self.root = root
        self.root.title("Sistema de Respaldos Avanzado")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        self.config = Configuracion.cargar()
        # Forzar que la ruta base sea la de la app si no está configurada
        if self.config.ruta_base_respaldos == "Respaldos" or not os.path.isabs(self.config.ruta_base_respaldos):
            self.config.ruta_base_respaldos = RUTA_RESPALDOS
            self.config.guardar()
        self.gestor = GestorEstados()
        self.progreso_actual = 0
        self.progreso_total = 0
        self.cancelar_proceso = False
        self.estado_actual = None  # referencia al EstadoRespaldo en curso, para poder pausarlo si algo falla
        self._inicio_tarea = None
        
        self.tema = Tema.aplicar(root, self.config)
        self._build_ui()
        self.actualizar_estado()
        ultima = leer_ultima_ruta()
        if ultima:
            self.log(f"🕘 {ultima.splitlines()[0]}")
        if not psutil:
            self.log("ℹ️ psutil no está instalado: la gestión inteligente de recursos e info del sistema serán limitadas.", "INFO")
    
    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        header = ttk.Frame(main_frame)
        header.pack(fill=tk.X, pady=(0, 15))
        ttk.Label(header, text="📦 Sistema de Respaldos Avanzado", font=("Segoe UI", 18, "bold")).pack(side=tk.LEFT)
        self.btn_tema = ttk.Button(header, text="🌙 Modo Oscuro" if not self.config.tema_oscuro else "☀️ Modo Claro", command=self.cambiar_tema)
        self.btn_tema.pack(side=tk.RIGHT)
        
        botones_frame = ttk.LabelFrame(main_frame, text="Acciones principales", padding="10")
        botones_frame.pack(fill=tk.X, pady=5)
        
        botones = [
            ("📂 Respaldo General", self.respaldo_general, "#2ecc71"),
            ("🔤 Respaldar por Extensiones", self.respaldo_extensiones, "#3498db"),
            ("💾 Recuperar Disco Externo", self.respaldo_disco_externo, "#e67e22"),
            ("🗄️ Respaldo XAMPP/MySQL", self.respaldo_xampp, "#9b59b6"),
            ("📱 Respaldo Móvil", self.respaldo_movil, "#16a085"),
            ("🔄 Reanudar Respaldo", self.reanudar_respaldo, "#f39c12"),
            ("🌐 Modo Red Interna", self.modo_red, "#1abc9c"),
            ("🗑️ Eliminar Respaldo", self.eliminar_respaldo, "#e74c3c"),
            ("📜 Ver Registros", self.ver_registros, "#95a5a6"),
            ("⚙️ Configuración", self.configuracion, "#7f8c8d")
        ]
        
        for idx, (texto, comando, color) in enumerate(botones):
            btn = tk.Button(botones_frame, text=texto, command=comando, bg=color, fg="white",
                            font=("Segoe UI", 10), padx=10, pady=5, relief=tk.FLAT, cursor="hand2")
            btn.grid(row=idx//3, column=idx%3, padx=8, pady=8, sticky="ew")
            btn._color = color
        
        for i in range(3):
            botones_frame.grid_columnconfigure(i, weight=1)
        
        self.progress_bar = ttk.Progressbar(main_frame, mode='determinate', style="TProgressbar")
        self.progress_bar.pack(fill=tk.X, pady=15)
        self.label_progreso = ttk.Label(main_frame, text="💡 Listo para iniciar", font=("Segoe UI", 9))
        self.label_progreso.pack()
        
        log_frame = ttk.LabelFrame(main_frame, text="Registro de eventos", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, wrap=tk.WORD, state='disabled',
                                                    font=("Consolas", 9), relief=tk.FLAT, borderwidth=0)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        footer = ttk.Frame(main_frame)
        footer.pack(fill=tk.X, pady=(10,0))
        ttk.Label(footer, text=f"💻 {platform.system()} {platform.release()} | 🧵 Hilos máx: {self.config.max_archivos_paralelos}").pack(side=tk.LEFT)
        ttk.Label(footer, text="© Respaldos Avanzado", font=("Segoe UI", 8)).pack(side=tk.RIGHT)
    
    def cambiar_tema(self):
        self.config.tema_oscuro = not self.config.tema_oscuro
        self.config.guardar()
        self.tema = Tema.aplicar(self.root, self.config)
        for child in self.root.winfo_children():
            self._actualizar_colores_widget(child)
        self.btn_tema.config(text="🌙 Modo Oscuro" if not self.config.tema_oscuro else "☀️ Modo Claro")
        self.log("Tema cambiado", "INFO")
    
    def _actualizar_colores_widget(self, widget):
        if isinstance(widget, tk.Button) and hasattr(widget, "_color"):
            widget.config(bg=widget._color, fg="white")
        elif isinstance(widget, tk.Text) or isinstance(widget, scrolledtext.ScrolledText):
            widget.config(bg=self.tema["log_bg"], fg=self.tema["log_fg"])
        elif isinstance(widget, tk.Frame) or isinstance(widget, ttk.Frame):
            widget.config(bg=self.tema["bg"])
        for child in widget.winfo_children():
            self._actualizar_colores_widget(child)
    
    def log(self, mensaje, nivel="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, f"[{timestamp}] {mensaje}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
        self.root.update_idletasks()
    
    def actualizar_estado(self):
        pausados = len(self.gestor.obtener_pausados())
        self.root.title(f"Sistema de Respaldos - {'⚠️ ' + str(pausados) + ' pausados' if pausados else 'Activo'}")
    
    def iniciar_tarea_larga(self, target, args=()):
        self.cancelar_proceso = False
        self.estado_actual = None
        self.progress_bar['value'] = 0
        self._inicio_tarea = time.time()
        self._bytes_copiados_tarea = 0
        self.label_progreso.config(text="⏳ Procesando...")
        self.log("Iniciando tarea...")
        thread = threading.Thread(target=self._ejecutar_con_progreso, args=(target, args))
        thread.daemon = True
        thread.start()
    
    def _ejecutar_con_progreso(self, target, args):
        try:
            target(*args)
        except Exception as e:
            # Si había un respaldo con estado registrado, lo marcamos como pausado
            # para que pueda reanudarse desde el menú, en vez de quedar huérfano.
            if self.estado_actual:
                self.gestor.pausar_respaldo(self.estado_actual.id, [], [])
                self.log("⏸️ El respaldo quedó pausado. Podrás reanudarlo con 'Reanudar Respaldo'.", "WARN")
            mensaje = mensaje_error_amigable(e)
            self.log(f"❌ {mensaje}", "ERROR")
            messagebox.showerror("Error", mensaje)
        finally:
            self.label_progreso.config(text="✅ Listo")
            self.progress_bar['value'] = 0
            self.estado_actual = None
            self.actualizar_estado()
    
    def _log_resumen_sistema(self):
        info = obtener_info_sistema()
        cpu_txt = f"{info['cpu_uso']:.1f}%" if info['cpu_uso'] is not None else "N/A"
        ram_txt = (f"{formatear_bytes(info['memoria_disponible'])} libres de {formatear_bytes(info['memoria_total'])}"
                   if info['memoria_total'] else "N/A")
        self.log(f"💻 {info['equipo']} | {info['usuario']} | {info['sistema']} | CPU: {info['cpu_logico']} hilos ({cpu_txt}) | RAM: {ram_txt}")

    def _copiar_con_recursos(self, archivos, destino):
        """Copia los archivos usando el número de hilos óptimo según la carga actual
        del equipo, y reduce la prioridad del proceso si detecta uso alto de CPU/RAM
        (paridad con la gestión inteligente de recursos de la versión terminal)."""
        hilos = calcular_hilos_optimos(self.config)
        auto_txt = " (ajuste automático)" if self.config.auto_ajustar_hilos else ""
        self.log(f"⚙️ Usando {hilos} hilos{auto_txt}")
        monitor = MonitorRecursos(self.config) if psutil else None
        if monitor:
            monitor.start()
        try:
            return copia_paralela(archivos, destino, max_workers=hilos,
                                   progreso_callback=self.actualizar_progreso, monitor=monitor)
        finally:
            if monitor:
                monitor.stop()
                monitor.join(timeout=2)

    def actualizar_progreso(self, actual, total, bytes_delta=0):
        self._bytes_copiados_tarea = getattr(self, "_bytes_copiados_tarea", 0) + bytes_delta
        if total > 0:
            valor = (actual / total) * 100
            self.progress_bar['value'] = valor
            elapsed = max(time.time() - (self._inicio_tarea or time.time()), 0.001)
            velocidad = self._bytes_copiados_tarea / elapsed
            eta_seg = (elapsed / actual) * (total - actual) if actual > 0 else 0
            eta_str = f"{int(eta_seg//60)}m {int(eta_seg%60)}s" if eta_seg > 60 else f"{int(eta_seg)}s"
            self.label_progreso.config(
                text=f"📊 Progreso: {actual}/{total} ({valor:.1f}%) | {formatear_bytes(velocidad)}/s | ETA: {eta_str}"
            )
            self.root.update_idletasks()
    
    # ========== Funciones de respaldo ==========
    def respaldo_general(self):
        carpetas = obtener_carpetas_usuario()
        if not carpetas:
            messagebox.showwarning("Sin carpetas", "No se encontraron carpetas de usuario.")
            return
        seleccion = []
        ventana = tk.Toplevel(self.root)
        ventana.title("Seleccionar carpetas")
        ventana.geometry("400x400")
        ventana.configure(bg=self.tema["bg"])
        tk.Label(ventana, text="Selecciona carpetas a respaldar:", bg=self.tema["bg"], fg=self.tema["fg"]).pack(pady=5)
        frame_lista = ttk.Frame(ventana)
        frame_lista.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        canvas = tk.Canvas(frame_lista, bg=self.tema["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        var_dict = {}
        for c in carpetas:
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(scrollable_frame, text=os.path.basename(c), variable=var)
            cb.pack(anchor='w', pady=2)
            var_dict[c] = var
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        def aceptar():
            nonlocal seleccion
            seleccion = [c for c, var in var_dict.items() if var.get()]
            ventana.destroy()
        ttk.Button(ventana, text="Aceptar", command=aceptar).pack(pady=10)
        self.root.wait_window(ventana)
        if not seleccion:
            return
        destino = filedialog.askdirectory(title="Carpeta destino", initialdir=self.config.ruta_base_respaldos)
        if not destino:
            return
        self.config.ruta_base_respaldos = destino
        self.config.guardar()
        self.iniciar_tarea_larga(self._ejecutar_respaldo_general, (seleccion, destino))
    
    def _ejecutar_respaldo_general(self, carpetas, destino_base):
        carpeta_destino = self._crear_carpeta_respaldo(destino_base)
        archivos = []
        for carpeta in carpetas:
            self.log(f"🔍 Escaneando {carpeta}...")
            for ruta, nombre, size in walk_fast(carpeta):
                rel = os.path.relpath(ruta, carpeta)
                archivos.append((ruta, os.path.join(os.path.basename(carpeta), rel), size))
        total = len(archivos)
        if total == 0:
            self.log("No hay archivos para respaldar.")
            return
        estado = self.gestor.crear_estado(" + ".join(carpetas), carpeta_destino, "general", total) if self.config.guardar_estado_respaldos else None
        self.estado_actual = estado
        self._log_resumen_sistema()
        self.log(f"📦 Iniciando copia de {total} archivos...")
        copiados, dup, err, tam = self._copiar_con_recursos(archivos, carpeta_destino)
        if estado:
            self.gestor.completar_respaldo(estado.id)
        registrar_respaldo(carpeta_destino, "general", f"{len(carpetas)} carpetas, {copiados} archivos", self.config)
        guardar_ultima_ruta(carpeta_destino, "general")
        self.log(f"✅ Respaldo completado. Copiados: {copiados}, Duplicados: {dup}, Errores: {err}")
        if self.config.comprimir_automatico:
            self.log("🗜️ Comprimiendo...")
            zip_path = comprimir_respaldo(carpeta_destino, self.config.nivel_compresion)
            self.log(f"✅ Comprimido: {zip_path}")
        self.log(f"💾 Respaldo guardado en: {carpeta_destino}")
    
    def respaldo_extensiones(self):
        destino = filedialog.askdirectory(title="Carpeta destino", initialdir=self.config.ruta_base_respaldos)
        if not destino:
            return
        self.iniciar_tarea_larga(self._ejecutar_respaldo_extensiones, (destino,))
    
    def _ejecutar_respaldo_extensiones(self, destino_base):
        extensiones_set = {".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".txt",".rtf",
                            ".jpg",".jpeg",".png",".gif",".mp3",".mp4",".py",".js",".html",".css",
                            ".java",".cpp",".c",".m",".mm",".plist",".strings"}
        archivos_por_ext = {}
        home = os.path.expanduser("~")
        self.log("🔍 Escaneando archivos por extensión...")
        for ruta, nombre, size in walk_fast(home):
            ext = os.path.splitext(nombre)[1].lower()
            if ext in extensiones_set:
                archivos_por_ext.setdefault(ext, []).append((ruta, nombre, size))
        if not archivos_por_ext:
            self.log("No se encontraron archivos con esas extensiones.")
            return
        total_archivos = sum(len(v) for v in archivos_por_ext.values())
        carpeta_destino = self._crear_carpeta_respaldo(destino_base)
        archivos_a_copiar = []
        for ext, lista in archivos_por_ext.items():
            for ruta, nombre, size in lista:
                rel = os.path.join(f"Archivos_{ext[1:].upper()}", nombre)
                archivos_a_copiar.append((ruta, rel, size))
        estado = self.gestor.crear_estado(home, carpeta_destino, "extensiones", total_archivos) if self.config.guardar_estado_respaldos else None
        self.estado_actual = estado
        self._log_resumen_sistema()
        self.log(f"📦 Copiando {total_archivos} archivos...")
        copiados, dup, err, tam = self._copiar_con_recursos(archivos_a_copiar, carpeta_destino)
        if estado:
            self.gestor.completar_respaldo(estado.id)
        registrar_respaldo(carpeta_destino, "extensiones", f"{len(archivos_por_ext)} extensiones, {copiados} archivos", self.config)
        guardar_ultima_ruta(carpeta_destino, "extensiones")
        self.log(f"✅ Copiados: {copiados}, Duplicados: {dup}, Errores: {err}")
        if self.config.comprimir_automatico:
            zip_path = comprimir_respaldo(carpeta_destino, self.config.nivel_compresion)
            self.log(f"✅ Comprimido: {zip_path}")
    
    def respaldo_disco_externo(self):
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
            messagebox.showwarning("Sin unidades", "No se detectaron unidades externas.")
            return
        ventana = tk.Toplevel(self.root)
        ventana.title("Seleccionar unidad externa")
        ventana.geometry("300x200")
        ventana.configure(bg=self.tema["bg"])
        tk.Label(ventana, text="Unidades detectadas:", bg=self.tema["bg"], fg=self.tema["fg"]).pack(pady=5)
        var = tk.StringVar()
        for u in unidades:
            tk.Radiobutton(ventana, text=u, variable=var, value=u, bg=self.tema["bg"], fg=self.tema["fg"], selectcolor=self.tema["bg"]).pack(anchor='w')
        def aceptar():
            ventana.destroy()
        ttk.Button(ventana, text="Aceptar", command=aceptar).pack(pady=10)
        self.root.wait_window(ventana)
        if not var.get():
            return
        origen = var.get()
        destino = filedialog.askdirectory(title="Carpeta destino", initialdir=self.config.ruta_base_respaldos)
        if not destino:
            return
        self.iniciar_tarea_larga(self._ejecutar_recuperar_disco, (origen, destino))
    
    def _ejecutar_recuperar_disco(self, origen, destino_base):
        carpeta_destino = self._crear_carpeta_respaldo(destino_base)
        archivos = []
        self.log(f"🔍 Escaneando {origen}...")
        for ruta, nombre, size in walk_fast(origen):
            rel = os.path.relpath(ruta, origen)
            archivos.append((ruta, rel, size))
        total = len(archivos)
        if total == 0:
            self.log("No hay archivos recuperables en el disco.")
            return
        estado = self.gestor.crear_estado(origen, carpeta_destino, "disco_externo", total) if self.config.guardar_estado_respaldos else None
        self.estado_actual = estado
        self._log_resumen_sistema()
        self.log(f"📦 Recuperando {total} archivos...")
        copiados, dup, err, tam = self._copiar_con_recursos(archivos, carpeta_destino)
        if estado:
            self.gestor.completar_respaldo(estado.id)
        registrar_respaldo(carpeta_destino, "disco_externo", f"{copiados} archivos", self.config)
        guardar_ultima_ruta(carpeta_destino, "disco_externo")
        self.log(f"✅ Recuperados: {copiados}, Duplicados: {dup}, Errores: {err}")
        if self.config.comprimir_automatico:
            zip_path = comprimir_respaldo(carpeta_destino, self.config.nivel_compresion)
            self.log(f"✅ Comprimido: {zip_path}")
    
    def respaldo_xampp(self):
        instalaciones = self._buscar_xampp()
        if not instalaciones:
            messagebox.showinfo("No encontrado", "No se encontró XAMPP/MySQL en el sistema.")
            return
        destino = filedialog.askdirectory(title="Carpeta destino", initialdir=self.config.ruta_base_respaldos)
        if not destino:
            return
        self.iniciar_tarea_larga(self._ejecutar_respaldo_xampp, (instalaciones, destino))
    
    def _buscar_xampp(self):
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
    
    def _ejecutar_respaldo_xampp(self, instalaciones, destino_base):
        carpeta_destino = self._crear_carpeta_respaldo(destino_base)
        archivos = []
        for nombre, ruta in instalaciones:
            self.log(f"🔍 Escaneando {nombre} en {ruta}...")
            for fpath, fname, size in walk_fast(ruta):
                rel = os.path.join(nombre, os.path.relpath(fpath, ruta))
                archivos.append((fpath, rel, size))
        total = len(archivos)
        if total == 0:
            self.log("No hay archivos para respaldar.")
            return
        estado = self.gestor.crear_estado(" + ".join(n for n, _ in instalaciones), carpeta_destino, "xampp", total) if self.config.guardar_estado_respaldos else None
        self.estado_actual = estado
        self._log_resumen_sistema()
        self.log(f"📦 Respaldando {total} archivos...")
        copiados, dup, err, tam = self._copiar_con_recursos(archivos, carpeta_destino)
        if estado:
            self.gestor.completar_respaldo(estado.id)
        registrar_respaldo(carpeta_destino, "xampp", f"{len(instalaciones)} instalaciones, {copiados} archivos", self.config)
        guardar_ultima_ruta(carpeta_destino, "xampp")
        self.log(f"✅ Copiados: {copiados}, Errores: {err}")
        if self.config.comprimir_automatico:
            zip_path = comprimir_respaldo(carpeta_destino, self.config.nivel_compresion)
            self.log(f"✅ Comprimido: {zip_path}")
    
    def respaldo_movil(self):
        dispositivos = detectar_dispositivos_moviles()
        if not dispositivos:
            messagebox.showinfo("Sin dispositivos", "No se detectaron dispositivos móviles conectados.")
            return
        ventana = tk.Toplevel(self.root)
        ventana.title("Seleccionar dispositivo móvil")
        ventana.geometry("400x250")
        ventana.configure(bg=self.tema["bg"])
        tk.Label(ventana, text="Dispositivos disponibles:", bg=self.tema["bg"], fg=self.tema["fg"]).pack(pady=5)
        var = tk.StringVar()
        for nombre, ruta, tipo in dispositivos:
            tk.Radiobutton(ventana, text=f"{nombre} ({tipo})", variable=var, value=ruta,
                           bg=self.tema["bg"], fg=self.tema["fg"], selectcolor=self.tema["bg"]).pack(anchor='w')
        def aceptar():
            ventana.destroy()
        ttk.Button(ventana, text="Aceptar", command=aceptar).pack(pady=10)
        self.root.wait_window(ventana)
        if not var.get():
            return
        origen = var.get()
        destino = filedialog.askdirectory(title="Carpeta destino", initialdir=self.config.ruta_base_respaldos)
        if not destino:
            return
        self.iniciar_tarea_larga(self._ejecutar_respaldo_movil, (origen, destino))

    def _ejecutar_respaldo_movil(self, origen, destino_base):
        carpeta_destino = self._crear_carpeta_respaldo(destino_base)
        if origen.startswith("adb:"):
            device_path = origen.split(':', 1)[1]
            self.log(f"📱 Extrayendo vía ADB desde {device_path}...")
            try:
                subprocess.run(['adb', 'pull', device_path, carpeta_destino], check=True)
            except subprocess.CalledProcessError as e:
                self.log(f"❌ Error al usar adb: {e}", "ERROR")
                return
            registrar_respaldo(carpeta_destino, "movil_android", "Android ADB backup", self.config)
            guardar_ultima_ruta(carpeta_destino, "movil_android")
            self.log(f"✅ Respaldo ADB completado en {carpeta_destino}")
            if self.config.comprimir_automatico:
                zip_path = comprimir_respaldo(carpeta_destino, self.config.nivel_compresion)
                self.log(f"✅ Comprimido: {zip_path}")
            return
        if not os.path.exists(origen):
            self.log("La ruta del dispositivo no está disponible.")
            return
        archivos = []
        self.log(f"🔍 Escaneando {origen}...")
        for ruta, nombre, size in walk_fast(origen):
            rel = os.path.relpath(ruta, origen)
            archivos.append((ruta, rel, size))
        total = len(archivos)
        if total == 0:
            self.log("No se encontraron archivos para respaldar.")
            return
        estado = self.gestor.crear_estado(origen, carpeta_destino, "movil", total) if self.config.guardar_estado_respaldos else None
        self.estado_actual = estado
        self._log_resumen_sistema()
        self.log(f"📦 Copiando {total} archivos...")
        copiados, dup, err, tam = self._copiar_con_recursos(archivos, carpeta_destino)
        if estado:
            self.gestor.completar_respaldo(estado.id)
        registrar_respaldo(carpeta_destino, "movil", f"{copiados} archivos", self.config)
        guardar_ultima_ruta(carpeta_destino, "movil")
        self.log(f"✅ Copiados: {copiados}, Duplicados: {dup}, Errores: {err}")
        if self.config.comprimir_automatico:
            zip_path = comprimir_respaldo(carpeta_destino, self.config.nivel_compresion)
            self.log(f"✅ Comprimido: {zip_path}")

    def reanudar_respaldo(self):
        pausados = self.gestor.obtener_pausados()
        if not pausados:
            messagebox.showinfo("Sin respaldos", "No hay respaldos interrumpidos.")
            return
        ventana = tk.Toplevel(self.root)
        ventana.title("Seleccionar respaldo a reanudar")
        ventana.geometry("500x300")
        ventana.configure(bg=self.tema["bg"])
        tk.Label(ventana, text="Respaldos interrumpidos:", bg=self.tema["bg"], fg=self.tema["fg"]).pack(pady=5)
        var = tk.StringVar()
        for e in pausados:
            tk.Radiobutton(ventana, text=f"{e.tipo} - {e.origen[:50]} - {e.procesados}/{e.total_archivos}", variable=var, value=e.id,
                            bg=self.tema["bg"], fg=self.tema["fg"], selectcolor=self.tema["bg"]).pack(anchor='w')
        def aceptar():
            ventana.destroy()
        ttk.Button(ventana, text="Reanudar", command=aceptar).pack(pady=10)
        self.root.wait_window(ventana)
        if var.get():
            self.iniciar_tarea_larga(self._ejecutar_reanudar, (var.get(),))
    
    def _ejecutar_reanudar(self, estado_id):
        estado = self.gestor.reanudar_respaldo(estado_id)
        if not estado:
            self.log("No se pudo reanudar.")
            return
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
            self.log("No hay archivos pendientes. Respaldo ya completado.")
            self.gestor.completar_respaldo(estado.id)
            return
        self.estado_actual = estado
        self.log(f"🔄 Reanudando: {total} archivos pendientes...")
        copiados, dup, err, tam = self._copiar_con_recursos(archivos_pendientes, estado.destino)
        self.gestor.completar_respaldo(estado.id)
        self.log(f"✅ Reanudación completada. Copiados: {copiados}, Errores: {err}")
    
    def modo_red(self):
        ventana = tk.Toplevel(self.root)
        ventana.title("Modo Red")
        ventana.geometry("300x150")
        ventana.configure(bg=self.tema["bg"])
        tk.Label(ventana, text="Selecciona modo:", bg=self.tema["bg"], fg=self.tema["fg"]).pack(pady=10)
        def servidor():
            ventana.destroy()
            self.iniciar_tarea_larga(self._servidor_red)
        def cliente():
            ventana.destroy()
            self.iniciar_tarea_larga(self._cliente_red)
        ttk.Button(ventana, text="Actuar como SERVIDOR", command=servidor).pack(pady=5)
        ttk.Button(ventana, text="Actuar como CLIENTE", command=cliente).pack(pady=5)
    
    def _servidor_red(self):
        self.log("🌐 Modo servidor iniciado. Esperando conexión...")
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', NETWORK_PORT))
        server.listen(1)
        self.log(f"Escuchando en puerto {NETWORK_PORT}")
        conn, addr = server.accept()
        self.log(f"Cliente conectado desde {addr}")
        comando = conn.recv(4096).decode().strip()
        self.log(f"Solicitud: {comando}")
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
        self.log("✅ Transferencia completada.")
    
    def _cliente_red(self):
        servidor_ip = simpledialog.askstring("Cliente Red", "IP del servidor:", parent=self.root)
        if not servidor_ip:
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((servidor_ip, NETWORK_PORT))
            sock.sendall(b"general")
            total = int(sock.recv(4096).decode())
            self.log(f"Recibiendo {total} archivos...")
            destino_base = filedialog.askdirectory(title="Carpeta destino", initialdir=self.config.ruta_base_respaldos)
            if not destino_base:
                sock.close()
                return
            carpeta_destino = self._crear_carpeta_respaldo(destino_base)
            for i in range(total):
                rel = sock.recv(4096).decode().strip()
                size = int(sock.recv(4096).decode().strip())
                destino = os.path.join(carpeta_destino, rel)
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                with open(destino, 'wb') as f:
                    recibido = 0
                    while recibido < size:
                        chunk = sock.recv(min(BUFFER_SIZE, size - recibido))
                        if not chunk:
                            break
                        f.write(chunk)
                        recibido += len(chunk)
                self.actualizar_progreso(i+1, total)
            sock.close()
            registrar_respaldo(carpeta_destino, "red_general", f"{total} archivos", self.config)
            guardar_ultima_ruta(carpeta_destino, "red_general")
            self.log(f"✅ Respaldo remoto completado en {carpeta_destino}")
            if self.config.comprimir_automatico:
                zip_path = comprimir_respaldo(carpeta_destino, self.config.nivel_compresion)
                self.log(f"✅ Comprimido: {zip_path}")
        except Exception as e:
            self.log(f"❌ Error en cliente: {e}")
    
    def eliminar_respaldo(self):
        nombres_generados = obtener_nombres_respaldo_generados()
        base = self.config.ruta_base_respaldos
        if not os.path.exists(base):
            messagebox.showwarning("No existe", f"La carpeta {base} no existe.")
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
            messagebox.showinfo("Sin respaldos", "No hay respaldos generados por el programa en esta ruta.")
            return
        ventana = tk.Toplevel(self.root)
        ventana.title("Eliminar Respaldo")
        ventana.geometry("400x300")
        ventana.configure(bg=self.tema["bg"])
        tk.Label(ventana, text="Selecciona el respaldo a eliminar:", bg=self.tema["bg"], fg=self.tema["fg"]).pack(pady=5)
        var = tk.StringVar()
        for nombre, _, tam in respaldos:
            tam_text = f"({tam/(1024**3):.2f} GB)" if tam > 1024**3 else f"({tam/(1024**2):.1f} MB)"
            tk.Radiobutton(ventana, text=f"{nombre} {tam_text}", variable=var, value=nombre,
                            bg=self.tema["bg"], fg=self.tema["fg"], selectcolor=self.tema["bg"]).pack(anchor='w')
        def eliminar():
            nombre = var.get()
            if not nombre:
                return
            for n, full, _ in respaldos:
                if n == nombre:
                    if messagebox.askyesno("Confirmar", f"¿Eliminar {nombre} permanentemente?"):
                        if os.path.isdir(full):
                            shutil.rmtree(full)
                        else:
                            os.remove(full)
                        nombre_base = nombre[:-4] if nombre.lower().endswith(".zip") else nombre
                        quitar_nombre_respaldo(nombre_base)
                        self.log(f"✅ Eliminado: {nombre}")
                        with open(RUTA_REGISTRO, "r", encoding="utf-8") as f:
                            lines = f.readlines()
                        with open(RUTA_REGISTRO, "w", encoding="utf-8") as f:
                            for line in lines:
                                if full not in line:
                                    f.write(line)
                    break
            ventana.destroy()
        ttk.Button(ventana, text="Eliminar", command=eliminar).pack(pady=10)
    
    def ver_registros(self):
        if not os.path.exists(RUTA_REGISTRO):
            messagebox.showinfo("Sin registros", "No hay registros de respaldos.")
            return
        with open(RUTA_REGISTRO, "r", encoding="utf-8") as f:
            contenido = f.read()
        ventana = tk.Toplevel(self.root)
        ventana.title("Registros de Respaldos")
        ventana.geometry("700x400")
        ventana.configure(bg=self.tema["bg"])
        text = scrolledtext.ScrolledText(ventana, wrap=tk.WORD, bg=self.tema["log_bg"], fg=self.tema["log_fg"])
        text.pack(fill=tk.BOTH, expand=True)
        text.insert(tk.END, contenido)
        text.config(state='disabled')
    
    def configuracion(self):
        ventana = tk.Toplevel(self.root)
        ventana.title("Configuración")
        ventana.geometry("450x400")
        ventana.configure(bg=self.tema["bg"])
        frame = ttk.Frame(ventana, padding="15")
        frame.pack(fill=tk.BOTH, expand=True)
        
        comp_auto = tk.BooleanVar(value=self.config.comprimir_automatico)
        reg_rutas = tk.BooleanVar(value=self.config.registrar_rutas)
        nivel_comp = tk.IntVar(value=self.config.nivel_compresion)
        hilos = tk.IntVar(value=self.config.max_archivos_paralelos)
        ruta_base = tk.StringVar(value=self.config.ruta_base_respaldos)
        
        ttk.Checkbutton(frame, text="Compresión automática", variable=comp_auto).grid(row=0, column=0, sticky='w', pady=5)
        ttk.Checkbutton(frame, text="Registrar rutas en .txt", variable=reg_rutas).grid(row=1, column=0, sticky='w', pady=5)
        
        ttk.Label(frame, text="Nivel compresión (0-9):").grid(row=2, column=0, sticky='w', pady=5)
        scale = ttk.Scale(frame, from_=0, to=9, variable=nivel_comp, orient='horizontal')
        scale.grid(row=2, column=1, sticky='ew', padx=5)
        ttk.Label(frame, textvariable=nivel_comp).grid(row=2, column=2, padx=5)
        
        ttk.Label(frame, text="Hilos paralelos:").grid(row=3, column=0, sticky='w', pady=5)
        spin = ttk.Spinbox(frame, from_=1, to=64, textvariable=hilos, width=10)
        spin.grid(row=3, column=1, sticky='w', padx=5)
        
        ttk.Label(frame, text="Ruta base respaldos:").grid(row=4, column=0, sticky='w', pady=5)
        entry_ruta = ttk.Entry(frame, textvariable=ruta_base, width=25)
        entry_ruta.grid(row=4, column=1, sticky='ew', padx=5)
        ttk.Button(frame, text="📁", width=3, command=lambda: ruta_base.set(filedialog.askdirectory(initialdir=ruta_base.get()))).grid(row=4, column=2)
        
        def guardar():
            self.config.comprimir_automatico = comp_auto.get()
            self.config.registrar_rutas = reg_rutas.get()
            self.config.nivel_compresion = nivel_comp.get()
            self.config.max_archivos_paralelos = hilos.get()
            self.config.ruta_base_respaldos = ruta_base.get()
            self.config.guardar()
            messagebox.showinfo("Configuración", "Guardada correctamente")
            ventana.destroy()
        
        ttk.Button(frame, text="Guardar", command=guardar).grid(row=5, column=0, columnspan=3, pady=20)
        frame.grid_columnconfigure(1, weight=1)
    
    def _crear_carpeta_respaldo(self, base):
        # Mismo esquema de nombres que la versión terminal (Usuario_Equipo_Fecha),
        # para que ambas versiones identifiquen igual sus propios respaldos.
        usuario, equipo = obtener_usuario_equipo()
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre = sanitizar_nombre(f"{usuario}_{equipo}_{fecha}")
        carpeta = os.path.join(base, nombre)
        contador = 1
        while os.path.exists(carpeta):
            carpeta = os.path.join(base, f"{nombre}_{contador}")
            contador += 1
        os.makedirs(carpeta, exist_ok=True)
        registrar_nombre_respaldo(os.path.basename(carpeta))
        return carpeta

# INICIO
if __name__ == "__main__":
    root = tk.Tk()
    app = AppRespaldo(root)
    root.mainloop()