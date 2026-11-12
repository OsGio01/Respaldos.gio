#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fuentes de respaldo y flujo de seleccion (nucleo v6.2)."""
import os
from typing import List, NamedTuple

from core import escaneo, motor, utilidades


class Opcion(NamedTuple):
    texto: str
    ruta: str
    clave: str = ""


def pedir_seleccion(opciones: List[Opcion], multiple: bool) -> List[Opcion]:
    for i, o in enumerate(opciones, 1):
        print(f"  {i}. {o.texto}")
    if multiple:
        s = utilidades.pedir("Numeros separados por espacio (o 'todos', 0 cancelar): ").strip().lower()
    else:
        s = utilidades.pedir("Selecciona numero (0 cancelar): ").strip().lower()
    if s in ("", "0"):
        return []
    if multiple and s == "todos":
        return list(opciones)
    indices = list(dict.fromkeys(int(x) - 1 for x in s.split() if x.isascii() and x.isdigit()))
    elegidas = [opciones[i] for i in indices if 0 <= i < len(opciones)]
    return elegidas if multiple else elegidas[:1]


def pedir_destino(config) -> str:
    destino = utilidades.pedir(f"Ruta destino (Enter: {config.ruta_base_respaldos}): ").strip()
    return utilidades.expandir_ruta(destino) if destino else config.ruta_base_respaldos


class Plan:
    def __init__(self, tipo: str, origen_txt: str, archivos: List[tuple], detalle: str = "", omitidas=None):
        self.tipo = tipo
        self.origen_txt = origen_txt
        self.archivos = archivos
        self.detalle = detalle
        self.omitidas = omitidas or []


class Fuente:
    tipo = ""
    titulo = ""
    emoji = ("", "")
    multiple = False
    requiere_seleccion = True
    sin_opciones = "No se encontraron opciones."
    sin_archivos = "No hay archivos para respaldos."

    def detectar(self) -> List[Opcion]:
        return []

    def construir_plan(self, seleccion: List[Opcion], escaner) -> Plan:
        raise NotImplementedError

    def ejecutar(self, seleccion: List[Opcion], destino: str, motor_obj, progreso_obj=None, cancelar=None) -> None:
        plan = self.construir_plan(seleccion, escaneo.Escaner())
        if not plan.archivos:
            print(self.sin_archivos)
            return None
        return motor_obj.ejecutar(plan, destino, progreso_obj=progreso_obj, cancelar=cancelar)


class FuenteCarpetasUsuario(Fuente):
    tipo = "general"
    titulo = "RESPALDO GENERAL"
    emoji = ("📂", "[GEN]")
    multiple = True
    sin_opciones = "No se encontraron carpetas de usuario."

    def detectar(self) -> List[Opcion]:
        return [Opcion(os.path.basename(c), c) for c in escaneo.obtener_carpetas_usuario()]

    def construir_plan(self, seleccion, escaner) -> Plan:
        archivos = []
        for o in seleccion:
            print(f"{utilidades.icono('🔍', '[SCAN]')} Escaneando {o.ruta}...")
            base = os.path.basename(o.ruta)
            for ruta, rel, size in escaner.recorrer(o.ruta):
                archivos.append((ruta, os.path.join(base, rel), size))
        return Plan(self.tipo, " + ".join(o.ruta for o in seleccion), archivos, f"{len(seleccion)} carpetas", escaner.omitidas)


class FuenteExtensiones(Fuente):
    tipo = "extensiones"
    titulo = "RESPALDO POR EXTENSIONES"
    emoji = ("🔤", "[EXT]")
    requiere_seleccion = False
    sin_archivos = "No se encontraron archivos con esas extensiones."

    def construir_plan(self, seleccion, escaner) -> Plan:
        home = os.path.expanduser("~")
        print(f"{utilidades.icono('🔍', '[SCAN]')} Escaneando archivos...")
        archivos = []
        usados = set()
        contador = {}
        extensiones_vistas = set()
        for ruta, _, size in escaner.recorrer(home, escaneo.EXTENSIONES_RESPALDO):
            nombre = os.path.basename(ruta)
            base, ext = os.path.splitext(nombre)
            ext = ext.lower()
            carpeta = f"Archivos_{ext[1:].upper()}"
            final = nombre
            clave = (carpeta, nombre.lower())
            while (carpeta, final.lower()) in usados:
                contador[clave] = contador.get(clave, 0) + 1
                final = f"{base}_{contador[clave]}{ext}"
            usados.add((carpeta, final.lower()))
            extensiones_vistas.add(ext)
            archivos.append((ruta, os.path.join(carpeta, final), size))
        print(f"Extensiones encontradas: {len(extensiones_vistas)}")
        return Plan(self.tipo, home, archivos, f"{len(extensiones_vistas)} extensiones", escaner.omitidas)


class FuenteDiscoExterno(Fuente):
    tipo = "disco_externo"
    titulo = "RECUPERAR DISCO EXTERNO"
    emoji = ("💾", "[DISCO]")
    sin_opciones = "No se detectaron unidades externas."
    sin_archivos = "No hay archivos recuperables."

    def detectar(self) -> List[Opcion]:
        return [Opcion(u, u) for u in escaneo.detectar_unidades_externas()]

    def construir_plan(self, seleccion, escaner) -> Plan:
        origen = seleccion[0].ruta
        print(f"{utilidades.icono('🔍', '[SCAN]')} Escaneando {origen}...")
        archivos = [(ruta, rel, size) for ruta, rel, size in escaner.recorrer(origen)]
        return Plan(self.tipo, origen, archivos, "", escaner.omitidas)


def buscar_xampp():
    import platform
    if platform.system() == "Windows":
        candidatos = ["C:\\xampp", "D:\\xampp", "C:\\Program Files\\MySQL", "C:\\Program Files (x86)\\MySQL"]
    elif platform.system() == "Darwin":
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
    sin_opciones = "No se encontro ninguna instalacion."

    def detectar(self) -> List[Opcion]:
        return [Opcion(f"{nombre}: {ruta}", ruta, nombre) for nombre, ruta in buscar_xampp()]

    def construir_plan(self, seleccion, escaner) -> Plan:
        archivos = []
        for o in seleccion:
            print(f"{utilidades.icono('🔍', '[SCAN]')} Escaneando {o.clave}...")
            for ruta, rel, size in escaner.recorrer(o.ruta):
                archivos.append((ruta, os.path.join(o.clave, rel), size))
        return Plan(self.tipo, " + ".join(o.clave for o in seleccion), archivos,
                    f"{len(seleccion)} instalaciones", escaner.omitidas)


def detectar_dispositivos_moviles():
    import platform
    dispositivos = []
    sistema = platform.system()
    from core import seguridad
    adb = seguridad._adb_disponible()
    if adb:
        try:
            import subprocess
            r = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                lineas = [l.strip() for l in r.stdout.splitlines() if l.strip()]
                if [l for l in lineas[1:] if "device" in l and not l.startswith("*")]:
                    dispositivos.append(Opcion(f"Android ADB ({adb}) -> adb:/sdcard", "adb:/sdcard", "ADB"))
        except Exception:
            pass
    if sistema != "Windows":
        posibles = ["/Volumes"]
        if sistema == "Linux":
            posibles.append(os.path.join("/media", os.environ.get("USER", "")))
            posibles.append(f"/run/user/{os.getuid()}/gvfs")
        for base in posibles:
            if os.path.isdir(base):
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
    if sistema == "Windows":
        import ctypes
        import string
        try:
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
    titulo = "RESPALDO MOVIL - Android / iOS"
    emoji = ("📱", "[MOVIL]")
    sin_opciones = "No se detectaron dispositivos moviles conectados."

    def detectar(self) -> List[Opcion]:
        return detectar_dispositivos_moviles()

    def ejecutar(self, seleccion, destino, motor_obj, progreso_obj=None, cancelar=None) -> None:
        o = seleccion[0]
        if o.clave != "ADB":
            return super().ejecutar(seleccion, destino, motor_obj,
                                    progreso_obj=progreso_obj, cancelar=cancelar)
        from core import seguridad
        import subprocess
        import time as _time
        adb = seguridad._adb_disponible()
        if not adb:
            print(f"{utilidades.icono('❌', 'ERROR')} No se encontro 'adb' en el sistema. Configuralo en config.json (adb_path).")
            return
        carpeta = motor.crear_carpeta_respaldo(destino, motor_obj.config.proteger_respaldos)
        inicio = _time.time()
        try:
            subprocess.run([adb, "pull", o.ruta.split(":", 1)[1], carpeta], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"{utilidades.icono('❌', 'ERROR')} Error al usar adb: {e}")
            return
        n, tam = motor.contar_directorio(carpeta)
        motor_obj.finalizar(carpeta, "movil_android", "Android ADB", n, tam, _time.time() - inicio, [], "Android ADB backup")
        print(f"{utilidades.icono('✅', 'OK')} Respaldo ADB completado en {carpeta}")


def flujo_respaldo(fuente: Fuente, config, motor_obj) -> None:
    print(f"\n{utilidades.icono(*fuente.emoji)} {fuente.titulo}")
    seleccion = []
    if fuente.requiere_seleccion:
        opciones = fuente.detectar()
        if not opciones:
            print(fuente.sin_opciones)
            utilidades.pausa()
            return
        print("Disponibles:")
        seleccion = pedir_seleccion(opciones, fuente.multiple)
        if not seleccion:
            return
    destino = pedir_destino(config)
    fuente.ejecutar(seleccion, destino, motor_obj)
    utilidades.pausa()
