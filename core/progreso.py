#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Progreso, monitor de recursos y copiador paralelo (nucleo v6.1)."""
import os
import shutil
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from core import constantes, seguridad, utilidades


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

    def sumar_bytes(self, n: int) -> None:
        with self._lock:
            self.bytes_copiados += n

    def archivo_listo(self, bytes_saltados: int = 0) -> None:
        self.archivos += 1
        self.bytes_saltados += bytes_saltados

    def _fraccion(self) -> float:
        if self.total_bytes > 0:
            return min(1.0, (self.bytes_copiados + self.bytes_saltados) / self.total_bytes)
        if self.total_archivos > 0:
            return min(1.0, self.archivos / self.total_archivos)
        return 1.0

    def mostrar(self, forzar: bool = False) -> None:
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
        barra = ("█" * llenos + "░" * (ancho - llenos)) if utilidades.UNICODE_SUPPORT else ("#" * llenos + "-" * (ancho - llenos))
        linea = (f"{self.descripcion}: [{barra}] {frac:5.1%} {self.archivos}/{self.total_archivos} "
                 f"{utilidades.formatear_bytes(velocidad)}/s ETA {utilidades.formatear_tiempo(max(eta, 0) if eta is not None else None)}")
        columnas = shutil.get_terminal_size((80, 20)).columns - 1
        linea = linea[:columnas]
        sys.stdout.write("\r" + linea.ljust(self._largo))
        sys.stdout.flush()
        self._largo = len(linea)

    def fraccion(self) -> float:
        return self._fraccion()

    def cerrar(self) -> None:
        self.mostrar(forzar=True)
        if not self.silencioso:
            print()
        print(f"{utilidades.icono('✅', 'OK')} Completado en {time.monotonic() - self.inicio:.1f}s")


class MonitorRecursos(threading.Thread):
    INTERVALO = 2.0

    def __init__(self, bytes_propios: Callable[[], int]):
        super().__init__(daemon=True)
        self._bytes_propios = bytes_propios
        self._detener = threading.Event()
        self.delay = 0.0
        self.prioridad_reducida = False

    @staticmethod
    def _io_disco():
        try:
            import psutil
            c = psutil.disk_io_counters()
            return (c.read_bytes + c.write_bytes) if c else None
        except Exception:
            return None

    def run(self) -> None:
        import psutil
        yo = None
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
                        self._bajar_prioridad()
                        self.prioridad_reducida = True
                else:
                    self.delay = 0.0
                    if self.prioridad_reducida:
                        self._subir_prioridad()
                        self.prioridad_reducida = False
            except Exception:
                pass

    def _bajar_prioridad(self) -> None:
        try:
            from core import seguridad
            seguridad.ajustar_prioridad_proceso(True)
        except Exception:
            pass

    def _subir_prioridad(self) -> None:
        try:
            from core import seguridad
            seguridad.ajustar_prioridad_proceso(False)
        except Exception:
            pass

    def stop(self) -> None:
        self._detener.set()
        try:
            self.join(timeout=3)
        except Exception:
            pass
        if self.prioridad_reducida:
            self._subir_prioridad()
            self.prioridad_reducida = False


@dataclass
class ResultadoCopia:
    copiados: int = 0
    duplicados: int = 0
    bytes_copiados: int = 0
    errores: List[Tuple[str, str]] = field(default_factory=list)


class _Cancelado(Exception):
    pass


class CopiadorParalelo:
    def __init__(self, base: str, progreso_obj: Progreso, monitor=None, hechos=None, calcular_hash: bool = True, buffer_size: int = constantes.BUFFER_SIZE, cancelar=None):
        self.calcular_hash = calcular_hash
        self.buffer_size = buffer_size
        self.base = base
        self.progreso = progreso_obj
        self.monitor = monitor
        self.hechos = hechos
        self._cancelar = cancelar or threading.Event()
        self._tls = threading.local()
        self._fatal = None

    @property
    def cancelado(self) -> bool:
        return self._cancelar.is_set()

    def _buffer(self) -> bytearray:
        buf = getattr(self._tls, "buf", None)
        if buf is None:
            buf = self._tls.buf = bytearray(self.buffer_size)
        return buf

    @staticmethod
    def _borrar(ruta: str) -> None:
        import os as _os
        try:
            _os.remove(ruta)
        except OSError:
            pass

    def _copiar_uno(self, item):
        """Copia un archivo y devuelve (rel, estado, bytes, error, sha256_destino_o_None)."""
        from core import seguridad
        origen, rel, size = item
        if self._cancelar.is_set():
            return (rel, "cancelado", 0, None, None)
        mon = self.monitor
        if mon is not None and mon.delay > 0 and self._cancelar.wait(mon.delay):
            return (rel, "cancelado", 0, None, None)
        if not seguridad.rel_es_segura(rel):
            return (rel, "error", 0, ValueError("ruta no permitida (fuera de la carpeta de respaldo)"), None)
        destino = os.path.join(self.base, rel)
        tmp = destino + ".part"
        try:
            try:
                st = os.stat(destino)
                if st.st_size == size:
                    if self.calcular_hash:
                        sha_dest = seguridad._sha256_archivo(destino)
                        if sha_dest == seguridad._sha256_archivo(origen):
                            return (rel, "duplicado", size, None, sha_dest)
                    elif abs(st.st_mtime - os.path.getmtime(origen)) < 2:
                        return (rel, "duplicado", size, None, None)
            except FileNotFoundError:
                pass
            buf = self._buffer()
            vista = memoryview(buf)
            copiado = 0
            import hashlib
            hasher = hashlib.sha256() if self.calcular_hash else None
            with open(origen, "rb", buffering=0) as src, open(tmp, "wb") as dst:
                while True:
                    if self._cancelar.is_set():
                        raise _Cancelado()
                    n = src.readinto(buf)
                    if not n:
                        break
                    bloque = vista[:n]
                    dst.write(bloque)
                    if hasher:
                        hasher.update(bloque)
                    copiado += n
                    self.progreso.sumar_bytes(n)
            try:
                shutil.copystat(origen, tmp)
            except OSError:
                pass
            os.replace(tmp, destino)
            return (rel, "ok", copiado, None, hasher.hexdigest() if hasher else None)
        except _Cancelado:
            self._borrar(tmp)
            return (rel, "cancelado", 0, None, None)
        except Exception as e:
            self._borrar(tmp)
            return (rel, "error", 0, e, None)

    def _procesar(self, resultado, res: ResultadoCopia) -> None:
        rel, estado, tam, extra, sha = resultado
        if estado == "ok":
            res.copiados += 1
            res.bytes_copiados += tam
            self.progreso.archivo_listo()
            if self.hechos:
                self.hechos.marcar(rel, sha)
        elif estado == "duplicado":
            res.duplicados += 1
            self.progreso.archivo_listo(bytes_saltados=tam)
            if self.hechos:
                self.hechos.marcar(rel, sha)
        elif estado == "error":
            res.errores.append((rel, seguridad.motivo_corto(extra)))
            self.progreso.archivo_listo()
            if seguridad._es_disco_lleno(extra):
                self._fatal = extra
                self._cancelar.set()

    def copiar(self, items: List[Tuple[str, str, int]], hilos: int) -> ResultadoCopia:
        items = list(items)
        res = ResultadoCopia()
        for d in {os.path.dirname(os.path.join(self.base, rel)) for _, rel, _ in items}:
            os.makedirs(d, exist_ok=True)
        it = iter(items)
        en_vuelo = set()
        limite = max(2, hilos * 4)
        ex = ThreadPoolExecutor(max_workers=hilos)
        try:
            while self._fatal is None and not self._cancelar.is_set():
                while len(en_vuelo) < limite and not self._cancelar.is_set():
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
