#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Estados de respaldo y bitacora de hechos (nucleo v6.2)."""
import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, Iterator, List, Optional

from core import constantes, persistencia


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
    """Bitacora de archivos copiados. Formato por linea: [rel, sha256_hex]."""

    def __init__(self, ruta: str):
        self._f = open(ruta, "a", encoding="utf-8")
        self._lock = threading.Lock()
        self._n = 0

    def marcar(self, rel: str, sha256: Optional[str] = None) -> None:
        with self._lock:
            if sha256:
                self._f.write(json.dumps([rel, sha256]) + "\n")
            else:
                self._f.write(json.dumps(rel) + "\n")
            self._n += 1
            if self._n % 200 == 0:
                self._f.flush()
                try:
                    os.fsync(self._f.fileno())
                except OSError:
                    pass

    def cerrar(self) -> None:
        with self._lock:
            try:
                self._f.flush()
                self._f.close()
            except OSError:
                pass


class GestorEstados:
    def __init__(self, archivo: str = constantes.RUTA_ESTADOS):
        self.archivo = archivo
        self.estados = self._cargar()

    def _cargar(self) -> Dict[str, EstadoRespaldo]:
        data = persistencia.cargar_json(self.archivo, {})
        try:
            return {k: EstadoRespaldo(**v) for k, v in data.items()}
        except TypeError:
            return {}

    def guardar(self) -> None:
        persistencia.guardar_json(self.archivo, {k: asdict(v) for k, v in self.estados.items()})

    def ruta_manifiesto(self, id_res: str) -> str:
        return os.path.join(constantes.RUTA_ESTADOS_DIR, id_res + ".manifest.jsonl")

    def ruta_hechos(self, id_res: str) -> str:
        return os.path.join(constantes.RUTA_ESTADOS_DIR, id_res + ".hechos.jsonl")

    def escribir_manifiesto(self, id_res: str, items) -> None:
        with open(self.ruta_manifiesto(id_res), "w", encoding="utf-8") as f:
            for origen, rel, size in items:
                f.write(json.dumps([origen, rel, size]) + "\n")

    def leer_manifiesto(self, id_res: str):
        with open(self.ruta_manifiesto(id_res), "r", encoding="utf-8") as f:
            for linea in f:
                try:
                    o, r, s = json.loads(linea)
                    yield (o, r, s)
                except ValueError:
                    continue

    def leer_hechos(self, id_res: str) -> Dict[str, Optional[str]]:
        hechos: Dict[str, Optional[str]] = {}
        try:
            with open(self.ruta_hechos(id_res), "r", encoding="utf-8") as f:
                for linea in f:
                    try:
                        dato = json.loads(linea)
                    except ValueError:
                        continue
                    if isinstance(dato, list) and dato:
                        sha = dato[1] if len(dato) > 1 and isinstance(dato[1], str) else None
                        hechos[dato[0]] = sha
                    elif isinstance(dato, str):
                        hechos[dato] = None
        except OSError:
            pass
        return hechos

    def crear_estado(self, origen, destino, tipo, total_archivos, total_bytes) -> EstadoRespaldo:
        id_res = f"{tipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hashlib.sha256(origen.encode('utf-8', 'replace')).hexdigest()[:8]}"
        estado = EstadoRespaldo(id=id_res, origen=origen, destino=destino, tipo=tipo,
                                total_archivos=total_archivos, total_bytes=total_bytes,
                                fecha_inicio=datetime.now().isoformat(), activo=True)
        self.estados[id_res] = estado
        self.guardar()
        return estado

    def completar(self, id_res: str) -> None:
        self.estados.pop(id_res, None)
        self.guardar()
        for ruta in (self.ruta_manifiesto(id_res), self.ruta_hechos(id_res)):
            try:
                os.remove(ruta)
            except OSError:
                pass

    def pausar(self, id_res: str) -> None:
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
