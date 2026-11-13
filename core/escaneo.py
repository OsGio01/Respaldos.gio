#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Escaneo de fuentes de respaldo (filtro de rutas y escaneo de archivos)."""
import json
import os
import platform
import re
from typing import List, Optional, Set, Tuple

from core import constantes
from core.plataforma import es_android, rutas_android


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


class FiltroRutas:
    def __init__(self, config_dir: str = constantes.RUTA_CONFIG_DIR):
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
            "var/tmp", "tmp",
        ]

    @staticmethod
    def _whitelist_default() -> List[str]:
        home = os.path.expanduser("~")
        # Nombres de carpeta en espanol y en ingles, con y sin tilde.
        # En un Linux en espanol las carpetas son "Musica", "Imagenes" y "Videos"
        # CON tilde: sin esta lista el programa no detecta nada que respaldar.
        # Los acentos van como escapes \uXXXX para que el fuente sea ASCII puro.
        nombres = [
            "Documents", "Documentos",
            "Desktop", "Escritorio",
            "Downloads", "Descargas",
            "Music", "Musica", "M\u00fAsica",
            "Pictures", "Imagenes", "Im\u00e1genes",
            "Videos", "V\u00eddeos", "Videos",
            "Movies", "Pel\u00edculas",
            "Development", "Desarrollo", "Projects", "Proyectos",
        ]
        return [os.path.join(home, n) for n in nombres] + [
            "/Applications/XAMPP/htdocs", os.path.expanduser("~/Applications/XAMPP/htdocs")]

    def _cargar_lista(self, archivo: str, defaults: List[str]) -> List[str]:
        ruta = os.path.join(self.config_dir, archivo)
        data = self._cargar_json_local(ruta, None)
        if isinstance(data, list):
            return data
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(defaults, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
        return defaults

    @staticmethod
    def _cargar_json_local(ruta: str, valor_default):
        if os.path.exists(ruta):
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return valor_default

    def _compilar(self) -> None:
        self._wl = [os.path.normpath(w).lower() for w in self.whitelist]
        self._bl_nombres: Set[str] = set()
        self._bl_rutas: List[str] = []
        for b in self.blacklist:
            partes = [p for p in str(b).lower().replace("\\", "/").split("/") if p]
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
            r = "/" + str(ruta).lower().replace("\\", "/").strip("/")
            for p in self._bl_rutas:
                if r.endswith(p):
                    return True
        return False

    def excluir_archivo(self, nombre: str) -> bool:
        return nombre.lower() in self._bl_nombres


class Escaner:
    def __init__(self, filtro_rutas=None):
        self.filtro = filtro_rutas or FiltroRutas()
        self.omitidas: List[tuple] = []

    def recorrer(self, raiz: str, extensiones: Optional[Set[str]] = None):
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
                self.omitidas.append((ruta, str(exc)[:80]))


def obtener_carpetas_usuario() -> List[str]:
    """Carpetas personales del usuario en este sistema.

    La lista es bilingue (espanol e ingles) y trae los nombres CON tilde:
    en un Linux en espanol las carpetas son "Musica", "Imagenes" y "Videos"
    con tilde, y sin ellas el programa no encuentra nada que respaldar.
    """
    sistema = platform.system()
    home = os.path.expanduser("~")

    if sistema == "Windows":
        carpetas = ["Documents", "Music", "Pictures", "Videos", "Downloads",
                    "Desktop", "Favorites", "Contacts"]
    elif sistema == "Darwin":
        # macOS usa "Movies" (no "Videos") y "Library" como carpeta de usuario.
        carpetas = ["Documents", "Music", "Pictures", "Movies", "Downloads",
                    "Desktop", "Library", "Development"]
    elif es_android():
        # Android (Termux): el almacenamiento compartido vive en /sdcard y sus
        # carpetas tienen nombres propios (DCIM, Download, ...).
        carpetas = []
        for base in rutas_android():
            carpetas += ["DCIM", "Download", "Documents", "Movies", "Music", "Pictures"]
            break
    else:
        carpetas = [
            # espanol (con y sin tilde)
            "Documentos", "Musica", "M\u00fAsica", "Imagenes", "Im\u00e1genes",
            "Videos", "V\u00eddeos", "Descargas", "Escritorio", "Public",
            "Plantillas", "Pel\u00edculas", "Desarrollo", "Proyectos",
            # ingles
            "Documents", "Music", "Pictures", "Videos", "Downloads", "Desktop",
            "Public", "Templates", "Movies", "Development", "Projects",
        ]

    rutas = []
    for c in carpetas:
        # En Android las carpetas cuelgan de /sdcard, no del home.
        base = rutas_android()[0] if es_android() and rutas_android() else home
        ruta = os.path.join(base, c)
        if os.path.exists(ruta):
            rutas.append(ruta)
    return rutas


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
