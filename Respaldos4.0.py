#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Respaldos Avanzado - VERSIÓN TERMINAL PORTABLE
- Todas las funciones: respaldo general, extensiones, XAMPP, disco externo, red, etc.
- Optimizado con paralelismo, scandir, hashes.
- Rutas dinámicas: se adapta a la carpeta del ejecutable.
"""

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
from typing import List, Dict, Set, Optional, Tuple, Generator
from dataclasses import dataclass, asdict
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================================
# DETECCIÓN DE RUTA BASE (PARA EJECUTABLE PORTABLE)
# ============================================================================
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

# Crear carpetas necesarias
os.makedirs(RUTA_RESPALDOS, exist_ok=True)
os.makedirs(RUTA_CONFIG_DIR, exist_ok=True)

# ============================================================================
# CONSTANTES DE RENDIMIENTO
# ============================================================================
MAX_WORKERS = min(32, (os.cpu_count() or 2) * 2)
BUFFER_SIZE = 256 * 1024
HASH_CHUNK_SIZE = 8192
NETWORK_PORT = 56789

# ============================================================================
# UTILIDADES
# ============================================================================
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

# ============================================================================
# FILTRO DE RUTAS (LISTAS BLANCA/NEGRA)
# ============================================================================
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

# ============================================================================
# BARRA DE PROGRESO Y COPIADO PARALELO
# ============================================================================
class ProgresoConsola:
    def __init__(self, total, descripcion="Progreso", ancho=50):
        self.total = total
        self.descripcion = descripcion
        self.ancho = ancho
        self.completado = 0
        self.inicio = time.time()
        self.last_update = 0
        self.update_step = max(1, total // 200) if total > 0 else 1
    
    def actualizar(self, n=1):
        self.completado += n
        if self.completado - self.last_update >= self.update_step or self.completado == self.total:
            self.last_update = self.completado
            self._mostrar()
    
    def _mostrar(self):
        porcentaje = self.completado / self.total if self.total else 0
        elapsed = time.time() - self.inicio
        eta = (elapsed / porcentaje) - elapsed if porcentaje > 0 else 0
        eta_str = f"{eta/60:.1f}min" if eta > 60 else f"{eta:.0f}s"
        filled = int(self.ancho * porcentaje)
        barra = '█' * filled + '░' * (self.ancho - filled)
        sys.stdout.write(f"\r{self.descripcion}: |{barra}| {porcentaje:.1%} ({self.completado}/{self.total}) ETA: {eta_str}")
        sys.stdout.flush()
    
    def completar(self):
        self._mostrar()
        print(f"\n✅ Completado en {time.time()-self.inicio:.1f}s")

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

def copia_paralela(archivos, destino_base, sobrescribir=False, max_workers=MAX_WORKERS, progreso=None):
    hash_cache = {}
    tasks = [(origen, os.path.join(destino_base, rel), sobrescribir, hash_cache) for origen, rel, _ in archivos]
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
                print(f"\n⚠️ Error: {os.path.basename(futures[future][0])} - {msg}")
            if progreso:
                progreso.actualizar()
    return copiados, duplicados, errores, tam_total

# ============================================================================
# CLASES DE CONFIGURACIÓN Y ESTADO (con rutas portables)
# ============================================================================
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
    
    @classmethod
    def cargar(cls, ruta=RUTA_CONFIG):
        default = cls()
        if os.path.exists(ruta):
            try:
                with open(ruta, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                    return cls(**datos)
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

# ============================================================================
# FUNCIONES DE RESPALDO (con rutas portables)
# ============================================================================
def registrar_respaldo(ruta, tipo, detalles, config):
    if config.registrar_rutas:
        with open(RUTA_REGISTRO, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}|{ruta}|{tipo}|{detalles}\n")

def crear_carpeta_respaldo(base):
    fecha = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    carpeta = os.path.join(base, f"Respaldo_{fecha}")
    os.makedirs(carpeta, exist_ok=True)
    return carpeta

def comprimir_respaldo(carpeta, nivel=6):
    zip_path = carpeta + ".zip"
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=nivel) as zf:
            for root, _, files in os.walk(carpeta):
                for f in files:
                    full = os.path.join(root, f)
                    zf.write(full, os.path.relpath(full, carpeta))
        shutil.rmtree(carpeta)
        print(f"✅ Comprimido: {zip_path}")
        return zip_path
    except Exception as e:
        print(f"❌ Error comprimiendo: {e}")
        return None

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
    archivos = []
    for c in seleccionadas:
        print(f"🔍 Escaneando {c}...")
        for ruta, nombre, size in walk_fast(c):
            rel = os.path.relpath(ruta, c)
            archivos.append((ruta, os.path.join(os.path.basename(c), rel), size))
    total = len(archivos)
    if total == 0:
        print("No hay archivos para respaldar.")
        return
    progreso = ProgresoConsola(total, "Copiando") if config.mostrar_progreso else None
    estado = gestor.crear_estado(" + ".join(seleccionadas), carpeta_destino, "general", total) if config.guardar_estado_respaldos else None
    copiados, dup, err, tam = copia_paralela(archivos, carpeta_destino, max_workers=config.max_archivos_paralelos, progreso=progreso)
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    registrar_respaldo(carpeta_destino, "general", f"{len(seleccionadas)} carpetas, {copiados} archivos", config)
    print(f"\n✅ Respaldo completado. Copiados: {copiados}, Duplicados: {dup}, Errores: {err}")
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
    progreso = ProgresoConsola(total, "Copiando") if config.mostrar_progreso else None
    estado = gestor.crear_estado(home, carpeta_destino, "extensiones", total) if config.guardar_estado_respaldos else None
    copiados, dup, err, tam = copia_paralela(archivos_a_copiar, carpeta_destino, max_workers=config.max_archivos_paralelos, progreso=progreso)
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    registrar_respaldo(carpeta_destino, "extensiones", f"{len(archivos_por_ext)} extensiones, {copiados} archivos", config)
    print(f"\n✅ Copiados: {copiados}, Duplicados: {dup}, Errores: {err}")
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
    progreso = ProgresoConsola(total, "Recuperando") if config.mostrar_progreso else None
    estado = gestor.crear_estado(origen, carpeta_destino, "disco_externo", total) if config.guardar_estado_respaldos else None
    copiados, dup, err, tam = copia_paralela(archivos, carpeta_destino, max_workers=config.max_archivos_paralelos, progreso=progreso)
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    registrar_respaldo(carpeta_destino, "disco_externo", f"{copiados} archivos", config)
    print(f"\n✅ Recuperados: {copiados}, Duplicados: {dup}, Errores: {err}")
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
    progreso = ProgresoConsola(total, "Respaldando") if config.mostrar_progreso else None
    estado = gestor.crear_estado(" + ".join([n for n,_ in selec]), carpeta_destino, "xampp", total) if config.guardar_estado_respaldos else None
    copiados, dup, err, tam = copia_paralela(archivos, carpeta_destino, max_workers=config.max_archivos_paralelos, progreso=progreso)
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    registrar_respaldo(carpeta_destino, "xampp", f"{len(selec)} instalaciones, {copiados} archivos", config)
    print(f"\n✅ Copiados: {copiados}, Errores: {err}")
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
    progreso = ProgresoConsola(total, "Reanudando") if config.mostrar_progreso else None
    gestor.reanudar_respaldo(estado.id)
    copiados, dup, err, tam = copia_paralela(archivos_pendientes, estado.destino, max_workers=config.max_archivos_paralelos, progreso=progreso)
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
        progreso = ProgresoConsola(total, "Descargando") if config.mostrar_progreso else None
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
            if progreso:
                progreso.actualizar()
        if progreso:
            progreso.completar()
        sock.close()
        registrar_respaldo(carpeta_destino, "red_general", f"{total} archivos", config)
        print(f"✅ Respaldo remoto completado en {carpeta_destino}")
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
    patron = re.compile(r'^Respaldo_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(\.zip)?$')
    base = config.ruta_base_respaldos
    if not os.path.exists(base):
        print(f"La carpeta {base} no existe.")
        input("Presiona ENTER...")
        return
    respaldos = []
    for item in os.listdir(base):
        if patron.match(item):
            full = os.path.join(base, item)
            if os.path.isdir(full):
                size = sum(os.path.getsize(os.path.join(root,f)) for root,_,fs in os.walk(full) for f in fs)
            else:
                size = os.path.getsize(full)
            respaldos.append((item, full, size))
    if not respaldos:
        print("No hay respaldos generados por el programa.")
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
        print(f"1. Compresión automática: {'✅' if config.comprimir_automatico else '❌'}")
        print(f"2. Registrar rutas en .txt: {'✅' if config.registrar_rutas else '❌'}")
        print(f"3. Barra de progreso: {'✅' if config.mostrar_progreso else '❌'}")
        print(f"4. Nivel compresión (0-9): {config.nivel_compresion}")
        print(f"5. Hilos paralelos: {config.max_archivos_paralelos}")
        print(f"6. Ruta base respaldos: {config.ruta_base_respaldos}")
        print("7. Guardar y volver")
        op = input("Opción: ").strip()
        if op == "1":
            config.comprimir_automatico = not config.comprimir_automatico
        elif op == "2":
            config.registrar_rutas = not config.registrar_rutas
        elif op == "3":
            config.mostrar_progreso = not config.mostrar_progreso
        elif op == "4":
            print("\n📦 NIVEL DE COMPRESIÓN:")
            print("   0 = Sin compresión (más rápido, archivos más grandes)")
            print("   6 = Equilibrio por defecto (recomendado)")
            print("   9 = Máxima compresión (más lento, archivos más pequeños)")
            try:
                n = int(input("Nuevo nivel (0-9): "))
                if 0 <= n <= 9:
                    config.nivel_compresion = n
            except: pass
        elif op == "5":
            print("\n🧵 HILOS PARALELOS:")
            print("   Controla cuántos archivos se copian simultáneamente.")
            print(f"   Recomendado: entre 4 y {MAX_WORKERS} (tu CPU tiene {os.cpu_count()} núcleos).")
            try:
                n = int(input(f"Nuevo número de hilos (1-64): "))
                config.max_archivos_paralelos = max(1, min(64, n))
            except: pass
        elif op == "6":
            nueva = input("Nueva ruta base: ").strip()
            if nueva:
                config.ruta_base_respaldos = expandir_ruta(nueva)
        elif op == "7":
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
        pausados = len(gestor.obtener_pausados())
        if pausados:
            print(f"⏸️ Respaldos interrumpidos: {pausados}")
        print("\n📋 MENÚ:")
        print(" 1) 📂 Respaldo general (carpetas usuario)")
        print(" 2) 🔤 Respaldo por extensiones")
        print(" 3) 💾 Recuperar disco externo")
        print(" 4) 🗄️ Respaldo XAMPP/MySQL")
        print(" 5) 🔄 Reanudar respaldo interrumpido")
        print(" 6) 🌐 Modo red interna")
        print(" 7) 🗑️ Eliminar respaldo seguro")
        print(" 8) 📜 Ver registros")
        print(" 9) ⚙️ Configuración")
        print("10) 🚪 Salir")
        op = input("Opción: ").strip()
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
            modo_red(config)
        elif op == "7":
            eliminar_respaldo(config)
        elif op == "8":
            mostrar_registros()
        elif op == "9":
            menu_configuracion(config)
        elif op == "10":
            print("👋 Hasta pronto")
            config.guardar()
            gestor._guardar()
            break
        else:
            print("Opción no válida")
            time.sleep(1)

if __name__ == "__main__":
    menu_principal()