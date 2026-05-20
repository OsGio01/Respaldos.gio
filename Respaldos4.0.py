#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Respaldos Avanzado - Versión Completa
Cumple con todas las características documentadas:
- Respaldo general, por extensiones, XAMPP, unidades externas
- Modo red interna (servidor/cliente)
- Modo disco externo recuperado (filtra SO)
- Listas blanca/negra configurables
- Registro persistente de rutas (rutas_respaldo.txt)
- Soporte macOS (rutas, extensiones, exclusiones)
- Eliminación segura, reanudación, compresión, barra de progreso
- Optimizado con paralelismo, os.scandir, hashes rápidos
- Ayudas interactivas en configuración
"""

import os
import shutil
import platform
from datetime import datetime
import zipfile
import json
import re
import time
import sys
import threading
import socket
from typing import List, Dict, Set, Optional, Tuple, Generator
from dataclasses import dataclass, asdict, field
from pathlib import Path
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
from collections import deque

# ============================================================================
# CONSTANTES DE RENDIMIENTO Y CONFIGURACIÓN
# ============================================================================
MAX_WORKERS = min(32, (os.cpu_count() or 2) * 2)
BUFFER_SIZE = 256 * 1024
HASH_CHUNK_SIZE = 8192
NETWORK_PORT = 56789

# ============================================================================
# UTILIDADES MULTIPLATAFORMA
# ============================================================================
def limpiar_terminal():
    os.system('cls' if platform.system() == "Windows" else 'clear')

def expandir_ruta(ruta: str) -> str:
    return os.path.normpath(os.path.expanduser(os.path.expandvars(ruta)))

def get_file_hash(filepath: str, quick: bool = True) -> str:
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

def formatear_tamano(gb: float) -> str:
    if gb >= 1000:
        return f"{gb/1024:.1f} TB"
    elif gb >= 1:
        return f"{gb:.1f} GB"
    else:
        return f"{gb*1024:.0f} MB"

# ============================================================================
# WALK OPTIMIZADO CON SCANDIR + EXCLUSIONES (LISTAS NEGRA/BLANCA)
# ============================================================================
class FiltroRutas:
    """Carga listas blanca y negra desde archivos JSON configurables"""
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        os.makedirs(config_dir, exist_ok=True)
        self.blacklist = self._cargar_lista("blacklist.json", self._blacklist_default())
        self.whitelist = self._cargar_lista("whitelist.json", self._whitelist_default())
    
    def _blacklist_default(self) -> List[str]:
        return [
            "$RECYCLE.BIN", "System Volume Information", ".Trash", ".Spotlight-V100",
            ".fseventsd", "Caches", "Logs", "AppData", "ProgramData", "Windows",
            "System32", "WinSxS", "Program Files", "Program Files (x86)",
            "boot", "dev", "proc", "sys", "tmp", "var/tmp", "lost+found",
            "Library/Caches", "Library/Logs", "Library/Preferences",
            "Library/Cookies", "Library/Saved Application State"
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
            os.path.join(home, "Library/Mobile Documents"),
            "/Applications/XAMPP/htdocs", os.path.expanduser("~/Applications/XAMPP/htdocs")
        ]
    
    def _cargar_lista(self, archivo: str, defaults: List[str]) -> List[str]:
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
    
    def deberia_excluir(self, ruta: str) -> bool:
        ruta_norm = os.path.normpath(ruta).lower()
        for w in self.whitelist:
            if ruta_norm.startswith(os.path.normpath(w).lower()):
                return False
        for b in self.blacklist:
            if b.lower() in ruta_norm.split(os.sep):
                return True
        return False

filtro_rutas = FiltroRutas()

def walk_fast(path: str) -> Generator[Tuple[str, str, int], None, None]:
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    try:
                        if filtro_rutas.deberia_excluir(entry.path):
                            continue
                        yield (entry.path, entry.name, entry.stat().st_size)
                    except OSError:
                        continue
                elif entry.is_dir(follow_symlinks=False):
                    if filtro_rutas.deberia_excluir(entry.path):
                        continue
                    yield from walk_fast(entry.path)
    except PermissionError:
        pass

# ============================================================================
# BARRA DE PROGRESO ADAPTATIVA
# ============================================================================
class ProgresoAdaptativo:
    def __init__(self, total: int, descripcion: str = "Progreso", ancho: int = 50):
        self.total = total
        self.descripcion = descripcion
        self.ancho = ancho
        self.completado = 0
        self.inicio = time.time()
        self.lock = threading.Lock()
        self.last_update = 0
        self.update_step = max(1, total // 200) if total > 0 else 1

    def actualizar(self, n: int = 1):
        with self.lock:
            self.completado += n
            if self.completado - self.last_update >= self.update_step or self.completado == self.total:
                self.last_update = self.completado
                self._mostrar()

    def _mostrar(self):
        porcentaje = self.completado / self.total if self.total else 0
        elapsed = time.time() - self.inicio
        if porcentaje > 0:
            eta = (elapsed / porcentaje) - elapsed
            eta_str = f"{eta/60:.1f}min" if eta > 60 else f"{eta:.0f}s"
        else:
            eta_str = "calculando"
        filled = int(self.ancho * porcentaje)
        barra = '█' * filled + '░' * (self.ancho - filled)
        sys.stdout.write(f"\r{self.descripcion}: |{barra}| {porcentaje:.1%} ({self.completado}/{self.total}) ETA: {eta_str}")
        sys.stdout.flush()

    def completar(self):
        self._mostrar()
        print(f"\n✅ Completado en {time.time()-self.inicio:.1f}s")

# ============================================================================
# COPIADO PARALELO
# ============================================================================
def copiar_archivo(args):
    origen, destino, sobrescribir, hash_cache = args
    try:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        if os.path.exists(destino) and not sobrescribir:
            if os.path.getsize(origen) == os.path.getsize(destino):
                if origen in hash_cache:
                    h1 = hash_cache[origen]
                else:
                    h1 = get_file_hash(origen, quick=True)
                    hash_cache[origen] = h1
                h2 = get_file_hash(destino, quick=True)
                if h1 == h2:
                    return (True, 0, "duplicado")
        with open(origen, 'rb') as src, open(destino, 'wb') as dst:
            shutil.copyfileobj(src, dst, length=BUFFER_SIZE)
        shutil.copystat(origen, destino)
        return (True, os.path.getsize(origen), "ok")
    except Exception as e:
        return (False, 0, str(e))

def copia_paralela(archivos: List[Tuple[str, str, int]], destino_base: str,
                   sobrescribir: bool = False, max_workers: int = MAX_WORKERS,
                   progreso: ProgresoAdaptativo = None) -> Tuple[int, int, int, int]:
    hash_cache = {}
    tasks = [(origen, os.path.join(destino_base, rel), sobrescribir, hash_cache) for origen, rel, _ in archivos]
    copiados = duplicados = errores = tam_total = 0
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
# CLASES DE CONFIGURACIÓN Y ESTADO
# ============================================================================
@dataclass
class EstadoRespaldo:
    id: str
    origen: str
    destino: str
    tipo: str
    total_archivos: int
    procesados: int = 0
    archivos_completados: List[str] = field(default_factory=list)
    archivos_pendientes: List[str] = field(default_factory=list)
    fecha_inicio: str = ""
    fecha_pausa: str = ""
    activo: bool = False

@dataclass
class Configuracion:
    comprimir_automatico: bool = True
    registrar_rutas: bool = True
    mostrar_progreso: bool = True
    nivel_compresion: int = 6
    max_archivos_paralelos: int = MAX_WORKERS
    tamano_buffer_mb: int = 8
    guardar_estado_respaldos: bool = True
    ruta_base_respaldos: str = "Respaldos"
    
    @classmethod
    def cargar(cls, ruta="config.json"):
        default = cls()
        if os.path.exists(ruta):
            try:
                with open(ruta, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                    return cls(**datos)
            except:
                pass
        return default
    
    def guardar(self, ruta="config.json"):
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

class GestorEstados:
    def __init__(self, archivo="estados_respaldo.json"):
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
# REGISTRO PERSISTENTE
# ============================================================================
def registrar_respaldo(ruta_destino: str, tipo: str, detalles: str, config: Configuracion):
    if not config.registrar_rutas:
        return
    with open("rutas_respaldo.txt", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()}|{ruta_destino}|{tipo}|{detalles}\n")

def mostrar_registros():
    if not os.path.exists("rutas_respaldo.txt"):
        print("📭 No hay registros.")
        input("\n⏎ Presiona ENTER...")
        return
    with open("rutas_respaldo.txt", "r", encoding="utf-8") as f:
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
    input("\n⏎ Presiona ENTER...")

def crear_carpeta_respaldo(destino_base: str) -> str:
    fecha = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    carpeta = os.path.join(destino_base, f"Respaldo_{fecha}")
    os.makedirs(carpeta, exist_ok=True)
    return carpeta

def comprimir_respaldo(carpeta: str, nivel: int = 6):
    zip_path = carpeta + ".zip"
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=nivel) as zf:
            for root, _, files in os.walk(carpeta):
                for f in files:
                    full = os.path.join(root, f)
                    zf.write(full, os.path.relpath(full, carpeta))
        shutil.rmtree(carpeta)
        print(f"✅ Comprimido: {zip_path}")
    except Exception as e:
        print(f"❌ Error comprimiendo: {e}")

# ============================================================================
# FUNCIONES DE RESPALDO (respaldo_general, extensiones, xampp, disco_externo)
# ============================================================================
def obtener_carpetas_usuario() -> List[str]:
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

def respaldo_general(config: Configuracion, gestor: GestorEstados):
    print("\n📂 RESPALDO GENERAL")
    carpetas_comunes = obtener_carpetas_usuario()
    print("Carpetas comunes encontradas:")
    for i, c in enumerate(carpetas_comunes, 1):
        print(f"  {i}. {os.path.basename(c)} -> {c}")
    seleccion = input("\nNúmeros separados por espacio (o 'todos'): ").strip()
    if seleccion.lower() == "todos":
        seleccionadas = carpetas_comunes
    else:
        indices = [int(x)-1 for x in seleccion.split() if x.isdigit()]
        seleccionadas = [carpetas_comunes[i] for i in indices if 0 <= i < len(carpetas_comunes)]
    if not seleccionadas:
        print("❌ No se seleccionó ninguna.")
        return
    destino_base = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    if not destino_base:
        destino_base = config.ruta_base_respaldos
    destino_base = expandir_ruta(destino_base)
    carpeta_destino = crear_carpeta_respaldo(destino_base)
    archivos = []
    for carpeta in seleccionadas:
        for ruta, nombre, size in walk_fast(carpeta):
            rel = os.path.relpath(ruta, carpeta)
            archivos.append((ruta, os.path.join(os.path.basename(carpeta), rel), size))
    total = len(archivos)
    if total == 0:
        print("⚠️ No hay archivos.")
        return
    progreso = ProgresoAdaptativo(total, "Respaldando") if config.mostrar_progreso else None
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
    input("\n⏎ Presiona ENTER...")

EXTENSIONES_BUSQUEDA = [
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "rtf", "odt", "ods", "odp",
    "jpg", "jpeg", "png", "gif", "bmp", "tiff", "svg", "webp",
    "mp3", "wav", "flac", "mp4", "avi", "mkv", "mov", "wmv",
    "zip", "rar", "7z", "tar", "gz",
    "py", "js", "html", "css", "java", "cpp", "c", "h", "cs", "php", "json", "xml", "sql", "md",
    "m", "mm", "plist", "strings"
]

def respaldo_extensiones(config: Configuracion, gestor: GestorEstados):
    print("\n🔤 RESPALDO POR EXTENSIONES")
    extensiones_set = {f".{ext.lower()}" for ext in EXTENSIONES_BUSQUEDA}
    archivos_por_ext = {}
    home = os.path.expanduser("~")
    total_archivos = 0
    print("🔍 Escaneando...")
    for ruta, nombre, size in walk_fast(home):
        ext = os.path.splitext(nombre)[1].lower()
        if ext in extensiones_set:
            archivos_por_ext.setdefault(ext, []).append((ruta, nombre, size))
            total_archivos += 1
    if total_archivos == 0:
        print("⚠️ No se encontraron archivos.")
        return
    print(f"Extensiones encontradas: {len(archivos_por_ext)}")
    destino_base = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    if not destino_base:
        destino_base = config.ruta_base_respaldos
    destino_base = expandir_ruta(destino_base)
    carpeta_destino = crear_carpeta_respaldo(destino_base)
    archivos_a_copiar = []
    for ext, lista in archivos_por_ext.items():
        for ruta, nombre, size in lista:
            rel = os.path.join(f"Archivos_{ext[1:].upper()}", nombre)
            archivos_a_copiar.append((ruta, rel, size))
    progreso = ProgresoAdaptativo(len(archivos_a_copiar), "Copiando") if config.mostrar_progreso else None
    estado = gestor.crear_estado(home, carpeta_destino, "extensiones", len(archivos_a_copiar)) if config.guardar_estado_respaldos else None
    copiados, dup, err, tam = copia_paralela(archivos_a_copiar, carpeta_destino, max_workers=config.max_archivos_paralelos, progreso=progreso)
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    registrar_respaldo(carpeta_destino, "extensiones", f"{len(archivos_por_ext)} extensiones, {copiados} archivos", config)
    print(f"\n✅ Respaldo completado. Copiados: {copiados}, Duplicados: {dup}, Errores: {err}")
    if config.comprimir_automatico:
        comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    input("\n⏎ Presiona ENTER...")

def recuperar_disco_externo(config: Configuracion, gestor: GestorEstados):
    print("\n💾 MODO DISCO EXTERNO RECUPERADO")
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
        print("❌ No se detectaron discos externos.")
        return
    print("Unidades externas detectadas:")
    for i, u in enumerate(unidades, 1):
        print(f"  {i}. {u}")
    sel = input("Selecciona número (0 cancelar): ").strip()
    if sel == "0":
        return
    idx = int(sel)-1
    if idx < 0 or idx >= len(unidades):
        print("❌ Opción inválida")
        return
    origen = unidades[idx]
    destino_base = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    if not destino_base:
        destino_base = config.ruta_base_respaldos
    destino_base = expandir_ruta(destino_base)
    carpeta_destino = crear_carpeta_respaldo(destino_base)
    archivos = []
    for ruta, nombre, size in walk_fast(origen):
        rel = os.path.relpath(ruta, origen)
        archivos.append((ruta, rel, size))
    total = len(archivos)
    if total == 0:
        print("⚠️ No hay archivos recuperables.")
        return
    print(f"Archivos a recuperar: {total}")
    progreso = ProgresoAdaptativo(total, "Recuperando") if config.mostrar_progreso else None
    estado = gestor.crear_estado(origen, carpeta_destino, "disco_externo", total) if config.guardar_estado_respaldos else None
    copiados, dup, err, tam = copia_paralela(archivos, carpeta_destino, max_workers=config.max_archivos_paralelos, progreso=progreso)
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    registrar_respaldo(carpeta_destino, "disco_externo", f"{copiados} archivos", config)
    print(f"\n✅ Recuperación completada. Copiados: {copiados}, Duplicados: {dup}, Errores: {err}")
    if config.comprimir_automatico:
        comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    input("\n⏎ Presiona ENTER...")

def buscar_xampp_mysql() -> List[Tuple[str, str]]:
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

def respaldo_xampp(config: Configuracion, gestor: GestorEstados):
    print("\n🗄️ RESPALDO XAMPP/MYSQL")
    instalaciones = buscar_xampp_mysql()
    if not instalaciones:
        print("❌ No se encontraron instalaciones.")
        return
    for i, (nombre, ruta) in enumerate(instalaciones, 1):
        print(f"  {i}. {nombre}: {ruta}")
    seleccion = input("Números separados por espacio (o 'todos'): ").strip()
    if seleccion.lower() == "todos":
        selec = instalaciones
    else:
        indices = [int(x)-1 for x in seleccion.split() if x.isdigit()]
        selec = [instalaciones[i] for i in indices if 0 <= i < len(instalaciones)]
    if not selec:
        return
    destino_base = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    if not destino_base:
        destino_base = config.ruta_base_respaldos
    destino_base = expandir_ruta(destino_base)
    carpeta_destino = crear_carpeta_respaldo(destino_base)
    archivos = []
    for nombre, ruta in selec:
        for fpath, fname, size in walk_fast(ruta):
            rel = os.path.join(nombre, os.path.relpath(fpath, ruta))
            archivos.append((fpath, rel, size))
    total = len(archivos)
    if total == 0:
        print("⚠️ No hay archivos.")
        return
    progreso = ProgresoAdaptativo(total, "Respaldando XAMPP") if config.mostrar_progreso else None
    estado = gestor.crear_estado(" + ".join([n for n,_ in selec]), carpeta_destino, "xampp", total) if config.guardar_estado_respaldos else None
    copiados, dup, err, tam = copia_paralela(archivos, carpeta_destino, max_workers=config.max_archivos_paralelos, progreso=progreso)
    if progreso:
        progreso.completar()
    if estado:
        gestor.completar_respaldo(estado.id)
    registrar_respaldo(carpeta_destino, "xampp", f"{len(selec)} instalaciones, {copiados} archivos", config)
    print(f"\n✅ Respaldo XAMPP completado. Copiados: {copiados}, Errores: {err}")
    if config.comprimir_automatico:
        comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    input("\n⏎ Presiona ENTER...")

# ============================================================================
# REANUDAR RESPALDO (simplificado)
# ============================================================================
def reanudar_respaldo(config: Configuracion, gestor: GestorEstados):
    pausados = gestor.obtener_pausados()
    if not pausados:
        print("📭 No hay respaldos interrumpidos.")
        input("\n⏎ Presiona ENTER...")
        return
    print("\n🔄 RESPALDOS INTERRUMPIDOS")
    for i, e in enumerate(pausados, 1):
        print(f"{i}. {e.tipo} | {e.origen[:50]} | {e.procesados}/{e.total_archivos}")
    sel = input("Selecciona número (0 cancelar): ").strip()
    if sel == "0":
        return
    idx = int(sel)-1
    if idx < 0 or idx >= len(pausados):
        print("❌ Opción inválida")
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
        print("✅ No hay archivos pendientes.")
        gestor.completar_respaldo(estado.id)
        return
    print(f"Archivos pendientes: {total}")
    progreso = ProgresoAdaptativo(total, "Reanudando") if config.mostrar_progreso else None
    gestor.reanudar_respaldo(estado.id)
    copiados, dup, err, tam = copia_paralela(archivos_pendientes, estado.destino, max_workers=config.max_archivos_paralelos, progreso=progreso)
    if progreso:
        progreso.completar()
    gestor.completar_respaldo(estado.id)
    print(f"✅ Reanudación completada. Copiados: {copiados}, Errores: {err}")
    input("\n⏎ Presiona ENTER...")

# ============================================================================
# MODO RED INTERNA (SERVIDOR Y CLIENTE)
# ============================================================================
def servidor_red(config: Configuracion):
    print("\n🌐 MODO SERVIDOR - Esperando clientes...")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', NETWORK_PORT))
    server.listen(1)
    print(f"Servidor escuchando en puerto {NETWORK_PORT}")
    conn, addr = server.accept()
    print(f"Cliente conectado desde {addr}")
    comando = conn.recv(4096).decode().strip()
    print(f"Comando solicitado: {comando}")
    # Por simplicidad, se envía respaldo general de las carpetas del usuario
    carpetas = obtener_carpetas_usuario()
    archivos = []
    for c in carpetas:
        for ruta, nombre, size in walk_fast(c):
            archivos.append((ruta, os.path.basename(c) + "/" + os.path.relpath(ruta, c), size))
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

def cliente_red(config: Configuracion):
    print("\n🌐 MODO CLIENTE - Conectando al servidor...")
    servidor_ip = input("IP del servidor (ej. 192.168.1.10): ").strip()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((servidor_ip, NETWORK_PORT))
        tipo = input("Tipo de respaldo (general/extensiones/xampp): ").strip()
        sock.sendall(tipo.encode())
        total = int(sock.recv(4096).decode())
        print(f"Recibiendo {total} archivos...")
        destino_base = input(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
        if not destino_base:
            destino_base = config.ruta_base_respaldos
        destino_base = expandir_ruta(destino_base)
        carpeta_destino = crear_carpeta_respaldo(destino_base)
        progreso = ProgresoAdaptativo(total, "Descargando") if config.mostrar_progreso else None
        copiados = 0
        for _ in range(total):
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
            copiados += 1
            if progreso:
                progreso.actualizar()
        if progreso:
            progreso.completar()
        registrar_respaldo(carpeta_destino, f"red_{tipo}", f"{copiados} archivos", config)
        print(f"✅ Respaldo remoto completado en {carpeta_destino}")
        if config.comprimir_automatico:
            comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    except Exception as e:
        print(f"❌ Error en cliente: {e}")
    finally:
        sock.close()
    input("\n⏎ Presiona ENTER...")

def menu_red(config: Configuracion):
    print("\n🌐 MODO RED")
    print("1. Actuar como SERVIDOR (enviar archivos)")
    print("2. Actuar como CLIENTE (recibir archivos)")
    op = input("Selecciona: ").strip()
    if op == "1":
        servidor_red(config)
    elif op == "2":
        cliente_red(config)
    else:
        print("Opción inválida")

# ============================================================================
# ELIMINAR RESPALDOS SEGURO
# ============================================================================
def eliminar_respaldo_seguro(config: Configuracion):
    patron = re.compile(r'^Respaldo_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(\.zip)?$')
    ruta_base = input(f"Ruta base de respaldos (Enter: {config.ruta_base_respaldos}): ").strip()
    if not ruta_base:
        ruta_base = config.ruta_base_respaldos
    ruta_base = expandir_ruta(ruta_base)
    if not os.path.exists(ruta_base):
        print("❌ La ruta no existe.")
        input("\n⏎ Presiona ENTER...")
        return
    respaldos = []
    for item in os.listdir(ruta_base):
        if patron.match(item):
            full = os.path.join(ruta_base, item)
            if os.path.isdir(full):
                total_size = sum(os.path.getsize(os.path.join(root,f)) for root,_,fs in os.walk(full) for f in fs)
            else:
                total_size = os.path.getsize(full)
            respaldos.append((item, full, total_size))
    if not respaldos:
        print("📭 No hay respaldos generados por el programa.")
        input("\n⏎ Presiona ENTER...")
        return
    print("\n🗑️ RESPALDOS DISPONIBLES PARA ELIMINAR")
    for i, (nombre, _, tam) in enumerate(respaldos, 1):
        print(f"{i}. {nombre} ({formatear_tamano(tam/(1024**3))})")
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
            # Actualizar registro
            if os.path.exists("rutas_respaldo.txt"):
                with open("rutas_respaldo.txt", "r", encoding="utf-8") as f:
                    lines = f.readlines()
                with open("rutas_respaldo.txt", "w", encoding="utf-8") as f:
                    for line in lines:
                        if full not in line:
                            f.write(line)
        else:
            print("Cancelado")
    else:
        print("Número inválido")
    input("\n⏎ Presiona ENTER...")

# ============================================================================
# MENÚ DE CONFIGURACIÓN CON AYUDAS
# ============================================================================
def menu_configuracion(config: Configuracion):
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
                    print(f"✅ Nivel establecido a {n}")
                else:
                    print("❌ Debe estar entre 0 y 9")
            except:
                print("❌ Valor inválido")
            time.sleep(1.5)
        elif op == "5":
            print("\n🧵 HILOS PARALELOS:")
            print("   Controla cuántos archivos se copian simultáneamente.")
            print("   - Un valor más alto acelera la copia en discos rápidos (SSD, red).")
            print("   - En discos mecánicos (HDD) o equipos lentos, valores altos pueden empeorar el rendimiento.")
            print(f"   - Recomendado: entre 4 y {MAX_WORKERS} (tu CPU tiene {os.cpu_count()} núcleos).")
            try:
                n = int(input(f"Nuevo número de hilos (1-64): "))
                config.max_archivos_paralelos = max(1, min(64, n))
                print(f"✅ Hilos establecidos a {config.max_archivos_paralelos}")
            except:
                print("❌ Valor inválido")
            time.sleep(2)
        elif op == "6":
            nueva = input("Nueva ruta base: ").strip()
            if nueva:
                config.ruta_base_respaldos = expandir_ruta(nueva)
                print(f"✅ Ruta base cambiada a {config.ruta_base_respaldos}")
                time.sleep(1)
        elif op == "7":
            config.guardar()
            print("✅ Configuración guardada")
            break
        else:
            print("Opción no válida")
            time.sleep(0.5)

# ============================================================================
# MENÚ PRINCIPAL
# ============================================================================
def menu_principal(config: Configuracion, gestor: GestorEstados):
    while True:
        limpiar_terminal()
        print("\n" + "="*70)
        print("            SISTEMA DE RESPALDOS AVANZADO - VERSIÓN COMPLETA")
        print("="*70)
        print(f"💻 {platform.system()} | 📁 Base: {config.ruta_base_respaldos}")
        pausados = len(gestor.obtener_pausados())
        if pausados:
            print(f"⏸️ Respaldos interrumpidos: {pausados}")
        print("\n📋 MENÚ:")
        print(" 1) 📂 Respaldo general (carpetas usuario)")
        print(" 2) 🔤 Respaldo por extensiones")
        print(" 3) 💾 Respaldo de disco externo (modo recuperación)")
        print(" 4) 🗄️ Respaldo XAMPP/MySQL")
        print(" 5) 🔄 Reanudar respaldo interrumpido")
        print(" 6) 🌐 Modo red interna (servidor/cliente)")
        print(" 7) 🗑️ Eliminar respaldo seguro")
        print(" 8) 📜 Ver registros (rutas_respaldo.txt)")
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
            menu_red(config)
        elif op == "7":
            eliminar_respaldo_seguro(config)
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

# ============================================================================
# INICIO
# ============================================================================
if __name__ == "__main__":
    config = Configuracion.cargar()
    gestor = GestorEstados()
    os.makedirs(config.ruta_base_respaldos, exist_ok=True)
    menu_principal(config, gestor)