#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Front movil del programa Respaldos.Gio (v6.0).

Misma cara que el front minimalista/HUD: tokens de diseno, log, anillo de
progreso, estado y acciones. Para el diseno del dispositivo movil se adaptara
la capa grafica (la logica de estado/progreso/log se reusa del patron HUD).
"""
import os
import threading

from core import seguridad
from fronts.hud import (
    ANCHO_ARCO, COLOR_ARCO, COLOR_ARCO_OK, COLOR_ESTADO_ERROR, COLOR_ESTADO_IDLE,
    COLOR_ESTADO_OK, COLOR_ESTADO_RUNNING, COLOR_ESTADO_WARN, COLOR_FONDO, COLOR_LOG_ACCION,
    COLOR_LOG_ERROR, COLOR_LOG_INFO, COLOR_LOG_OK, COLOR_LOG_WARN, COLOR_PANEL, COLOR_TEXTO,
)


class FronteMovil:
    """Front movil: misma experiencia visual y de estado que el HUD."""

    def __init__(self, config, gestor, motor_obj):
        self.config = config
        self.gestor = gestor
        self.motor_obj = motor_obj
        self._lock = threading.Lock()
        self._evento_cancel = threading.Event()
        self._hilo = None
        self._progreso = None
        self._resultado = None
        self._estado = {"estado": "idle", "detalle": "Listo para respaldar."}
        self._lineas = []

    # ------------------------------------------------------------------ log
    def log(self, mensaje: str, nivel: str = "info") -> None:
        with self._lock:
            self._lineas.append((mensaje, nivel))
            if len(self._lineas) > 200:
                self._lineas = self._lineas[-200:]

    # ------------------------------------------------------------------ estado
    def set_estado(self, estado: str, detalle: str = None) -> None:
        with self._lock:
            self._estado["estado"] = estado
            if detalle is not None:
                self._estado["detalle"] = detalle

    def set_progreso(self, fraccion: float, detalle: str = None) -> None:
        with self._lock:
            self._progreso_fraccion = max(0.0, min(1.0, fraccion))
            if detalle is not None:
                self._estado["detalle"] = detalle

    # ------------------------------------------------------------------ acciones
    def iniciar_respaldo(self) -> None:
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._evento_cancel.clear()
        self._progreso = None
        self._resultado = None
        self.set_estado("ejecutando", "Iniciando escaneo...")
        self.log("Solicitud de respaldo iniciada.", "accion")
        self._hilo = threading.Thread(target=self._worker_backup, daemon=True)
        self._hilo.start()

    def _worker_backup(self) -> None:
        try:
            from core import escaneo, fuentes, progreso, seguridad as _seg
            fuente = fuentes.FuenteCarpetasUsuario()
            opciones = fuente.detectar()
            if not opciones:
                self.set_estado("error", "No se encontraron carpetas de usuario.")
                self.log("No se encontraron carpetas de usuario para respaldar.", "error")
                return
            plan = fuente.construir_plan(opciones, escaneo.Escaner())
            if not plan.archivos:
                self.set_estado("warn", "No hay archivos para respaldar.")
                self.log("No hay archivos para respaldar.", "warn")
                return
            destino = self.config.ruta_base_respaldos
            self.set_estado("ejecutando", f"Respaldo de {len(opciones)} carpeta(s) / {len(plan.archivos)} archivos.")
            self.log(f"Iniciando respaldo general: {plan.detalle}", "accion")
            pro = progreso.Progreso(len(plan.archivos), sum(s for _, _, s in plan.archivos), "Respaldo", silencioso=False)
            self._progreso = pro
            res = self.motor_obj.ejecutar(plan, destino, progreso_obj=pro, cancelar=self._evento_cancel)
            self._resultado = res
            if self._evento_cancel.is_set():
                self.set_estado("cancelado", "Respaldo cancelado.")
                self.log("Respaldo cancelado por el usuario.", "warn")
                return
            self.set_estado("ok", f"Respaldo completado: {res.copiados} copiados, {res.duplicados} duplicados, {len(res.errores)} errores.")
            self.log(f"Respaldo completado: {res.copiados} copiados, {res.duplicados} duplicados.", "ok")
        except BaseException as e:
            self.set_estado("error", _seg.mensaje_error_amigable(e))
            self.log(f"Error: {_seg.mensaje_error_amigable(e)}", "error")

    # ------------------------------------------------------------------ extras
    def reanudar(self, estado) -> None:
        try:
            pro = None
            from core import progreso as _pro
            pro = _pro.Progreso(0, 0, "Reanudando", silencioso=False)
            res = self.motor_obj.reanudar(estado, progreso_obj=pro, cancelar=self._evento_cancel)
            if res is None:
                self.set_estado("idle", "Nada que reanudar.")
                return
            self.set_estado("ejecutando", "Reanudando respaldo...")
            self.log("Reanudando respaldo interrumpido.", "accion")
        except BaseException as e:
            self.set_estado("error", seguridad.mensaje_error_amigable(e))
            self.log(f"Error al reanudar: {seguridad.mensaje_error_amigable(e)}", "error")

    def cancelar(self) -> None:
        self._evento_cancel.set()

    def estado_actual(self):
        with self._lock:
            return dict(self._estado)

    def lineas(self):
        with self._lock:
            return list(self._lineas)
