#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Respaldos Avanzado - Versión Final para Ejecutable
- Modo claro/oscuro, interfaz moderna, todas las funciones.
- Gestión de rutas para que funcione correctamente como .exe.
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
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog, simpledialog
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass, asdict
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================================
# DETECCIÓN DE RUTA BASE PARA EJECUTABLE (¡CRÍTICO!)
# ============================================================================
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

# Asegurar que existan las carpetas necesarias
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
# CLASES DEL NÚCLEO (con rutas ajustadas)
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
    tema_oscuro: bool = False
    
    @classmethod
    def cargar(cls, ruta=None):
        if ruta is None:
            ruta = RUTA_CONFIG
        default = cls()
        if os.path.exists(ruta):
            try:
                with open(ruta, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                    return cls(**datos)
            except:
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

def copia_paralela(archivos, destino_base, sobrescribir=False, max_workers=MAX_WORKERS, progreso_callback=None):
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
            if progreso_callback:
                progreso_callback(copiados + duplicados + errores, total)
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

# ============================================================================
# INTERFAZ MODERNA CON TEMA CLARO/OSCURO
# ============================================================================

class Tema:
    claro = {
        "bg": "#f5f5f5",
        "fg": "#2c3e50",
        "frame_bg": "#ffffff",
        "frame_fg": "#2c3e50",
        "button_bg": "#3498db",
        "button_fg": "#ffffff",
        "button_active_bg": "#2980b9",
        "progress_bg": "#ecf0f1",
        "progress_color": "#2ecc71",
        "log_bg": "#ffffff",
        "log_fg": "#2c3e50",
        "select_bg": "#ffffff",
        "select_fg": "#2c3e50",
        "title_fg": "#2c3e50",
        "border": "#dcdde1"
    }
    oscuro = {
        "bg": "#1e1e1e",
        "fg": "#e0e0e0",
        "frame_bg": "#2d2d2d",
        "frame_fg": "#e0e0e0",
        "button_bg": "#0f6bff",
        "button_fg": "#ffffff",
        "button_active_bg": "#0a5ad9",
        "progress_bg": "#3c3c3c",
        "progress_color": "#0f6bff",
        "log_bg": "#252526",
        "log_fg": "#d4d4d4",
        "select_bg": "#2d2d2d",
        "select_fg": "#e0e0e0",
        "title_fg": "#ffffff",
        "border": "#3c3c3c"
    }
    
    @classmethod
    def aplicar(cls, root, config):
        tema = cls.oscuro if config.tema_oscuro else cls.claro
        root.configure(bg=tema["bg"])
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background=tema["bg"])
        style.configure("TLabel", background=tema["bg"], foreground=tema["fg"])
        style.configure("TLabelframe", background=tema["bg"], foreground=tema["fg"], bordercolor=tema["border"])
        style.configure("TLabelframe.Label", background=tema["bg"], foreground=tema["fg"])
        style.configure("TButton", background=tema["button_bg"], foreground=tema["button_fg"], borderwidth=0, focusthickness=0)
        style.map("TButton", background=[("active", tema["button_active_bg"])])
        style.configure("TProgressbar", background=tema["progress_color"], troughcolor=tema["progress_bg"])
        style.configure("TEntry", fieldbackground=tema["select_bg"], foreground=tema["select_fg"])
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
        
        self.tema = Tema.aplicar(root, self.config)
        self._build_ui()
        self.actualizar_estado()
    
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
        self.progress_bar['value'] = 0
        self.label_progreso.config(text="⏳ Procesando...")
        self.log("Iniciando tarea...")
        thread = threading.Thread(target=self._ejecutar_con_progreso, args=(target, args))
        thread.daemon = True
        thread.start()
    
    def _ejecutar_con_progreso(self, target, args):
        try:
            target(*args)
        except Exception as e:
            self.log(f"❌ Error: {str(e)}", "ERROR")
            messagebox.showerror("Error", str(e))
        finally:
            self.label_progreso.config(text="✅ Listo")
            self.progress_bar['value'] = 0
            self.actualizar_estado()
    
    def actualizar_progreso(self, actual, total):
        if total > 0:
            valor = (actual / total) * 100
            self.progress_bar['value'] = valor
            self.label_progreso.config(text=f"📊 Progreso: {actual}/{total} ({valor:.1f}%)")
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
        self.log(f"📦 Iniciando copia de {total} archivos...")
        copiados, dup, err, tam = copia_paralela(archivos, carpeta_destino, max_workers=self.config.max_archivos_paralelos, progreso_callback=self.actualizar_progreso)
        if estado:
            self.gestor.completar_respaldo(estado.id)
        registrar_respaldo(carpeta_destino, "general", f"{len(carpetas)} carpetas, {copiados} archivos", self.config)
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
        self.log(f"📦 Copiando {total_archivos} archivos...")
        copiados, dup, err, tam = copia_paralela(archivos_a_copiar, carpeta_destino, max_workers=self.config.max_archivos_paralelos, progreso_callback=self.actualizar_progreso)
        registrar_respaldo(carpeta_destino, "extensiones", f"{len(archivos_por_ext)} extensiones, {copiados} archivos", self.config)
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
        self.log(f"📦 Recuperando {total} archivos...")
        copiados, dup, err, tam = copia_paralela(archivos, carpeta_destino, max_workers=self.config.max_archivos_paralelos, progreso_callback=self.actualizar_progreso)
        registrar_respaldo(carpeta_destino, "disco_externo", f"{copiados} archivos", self.config)
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
        self.log(f"📦 Respaldando {total} archivos...")
        copiados, dup, err, tam = copia_paralela(archivos, carpeta_destino, max_workers=self.config.max_archivos_paralelos, progreso_callback=self.actualizar_progreso)
        registrar_respaldo(carpeta_destino, "xampp", f"{len(instalaciones)} instalaciones, {copiados} archivos", self.config)
        self.log(f"✅ Copiados: {copiados}, Errores: {err}")
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
        self.log(f"🔄 Reanudando: {total} archivos pendientes...")
        copiados, dup, err, tam = copia_paralela(archivos_pendientes, estado.destino, max_workers=self.config.max_archivos_paralelos, progreso_callback=self.actualizar_progreso)
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
            self.log(f"✅ Respaldo remoto completado en {carpeta_destino}")
            if self.config.comprimir_automatico:
                zip_path = comprimir_respaldo(carpeta_destino, self.config.nivel_compresion)
                self.log(f"✅ Comprimido: {zip_path}")
        except Exception as e:
            self.log(f"❌ Error en cliente: {e}")
    
    def eliminar_respaldo(self):
        patron = re.compile(r'^Respaldo_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(\.zip)?$')
        base = self.config.ruta_base_respaldos
        if not os.path.exists(base):
            messagebox.showwarning("No existe", f"La carpeta {base} no existe.")
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
            messagebox.showinfo("Sin respaldos", "No hay respaldos generados por el programa.")
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
        fecha = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        carpeta = os.path.join(base, f"Respaldo_{fecha}")
        os.makedirs(carpeta, exist_ok=True)
        return carpeta

# ============================================================================
# INICIO
# ============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = AppRespaldo(root)
    root.mainloop()