#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Front minimalista / HUD del programa Respaldos.Gio (v6.0).

Ventana de una sola pantalla: logo, status dot, anillo de progreso circular,
boton contextual de accion y log estilo consola. Tema oscuro con acento
indigo -> cyan. Toda la logica de respaldo vive en el core (MotorRespaldo).
"""
import os
import threading
import tkinter as tk

from core import constantes, escaneo, fuentes, motor, progreso, seguridad

RUTA_IMAGEN_LOGO = os.path.join(constantes.RUTA_APP, "IMG", "interface.png")
RUTA_ICONO_VENTANA = os.path.join(constantes.RUTA_APP, "IMG", "interface.ico")

COLOR_FONDO = "#0a0e1a"
COLOR_PANEL = "#111830"
COLOR_BORDE = "#1e2a52"
COLOR_TEXTO = "#e2e8f0"
COLOR_LOG_INFO = "#94a3b8"
COLOR_LOG_OK = "#22c55e"
COLOR_LOG_WARN = "#f59e0b"
COLOR_LOG_ERROR = "#ef4444"
COLOR_LOG_ACCION = "#818cf8"
COLOR_ACCENTO = "#6366f1"
COLOR_ACCENTO_FIN = "#22d3ee"
COLOR_ESTADO_IDLE = "#64748b"
COLOR_ESTADO_OK = "#22c55e"
COLOR_ESTADO_WARN = "#f59e0b"
COLOR_ESTADO_ERROR = "#ef4444"
COLOR_ESTADO_RUNNING = "#818cf8"

ANCHO_ARCO = 220
MARGEN_ARCO = 16
COLOR_ARCO = "#6366f1"
COLOR_ARCO_OK = "#22c55e"


class FronteHUD:
    """Ventana HUD minimalista. Estado via hilo worker + `after` en el hilo UI."""

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
        self._build_ui()
        self._refrescar()

    # ------------------------------------------------------------------ log
    def log(self, mensaje: str, nivel: str = "info") -> None:
        with self._lock:
            self._lineas.append((mensaje, nivel))
            if len(self._lineas) > 200:
                self._lineas = self._lineas[-200:]
        # No se refresca aqui (puede llamarse desde hilo); el bucle via `after` se encarga.

    def _actualizar_log(self) -> None:
        try:
            self.lista_log.delete(0, tk.END)
            for m, lvl in self._lineas:
                self.lista_log.insert(tk.END, m)
            self.lista_log.see(tk.END)
        except Exception:
            pass

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title("Respaldos.Gio")
        self.root.configure(bg=COLOR_FONDO)
        try:
            self.root.iconbitmap(RUTA_ICONO_VENTANA)
        except Exception:
            pass

        self.logo_label = None
        try:
            foto = tk.PhotoImage(file=RUTA_IMAGEN_LOGO)
            self.logo_label = tk.Label(self.root, image=foto, bg=COLOR_FONDO)
            self.logo_label.image = foto
        except Exception:
            self.logo_label = None

        self.frame_header = tk.Frame(self.root, bg=COLOR_FONDO)
        self.frame_header.pack(fill="x", padx=14, pady=10)
        self.visor = tk.Canvas(self.frame_header, bg=COLOR_FONDO, width=14, height=14, highlightthickness=0)
        self.visor.place(x=0, y=2)
        self.punto_estado = self.visor.create_oval(2, 2, 12, 12, fill=COLOR_ESTADO_IDLE, outline="")
        self.columna_titulo = tk.Frame(self.frame_header, bg=COLOR_FONDO)
        self.columna_titulo.pack(side="left", fill="x")
        self.frase_titulo = tk.Label(self.columna_titulo, text="RESPALDOS.GIO", bg=COLOR_FONDO, fg=COLOR_TEXTO, font=("Segoe UI", 16, "bold"))
        self.frase_titulo.pack(anchor="w")
        self.subtitulo = tk.Label(self.columna_titulo, text="Sistema de respaldos", bg=COLOR_FONDO, fg=COLOR_LOG_INFO, font=("Segoe UI", 9))
        self.subtitulo.pack(anchor="w")

        self.frame_progreso = tk.Frame(self.root, bg=COLOR_FONDO)
        self.frame_progreso.pack(fill="both", expand=True)
        self.arco = tk.Canvas(self.frame_progreso, bg=COLOR_FONDO, width=ANCHO_ARCO, height=ANCHO_ARCO, highlightthickness=0)
        self.arco.pack(expand=True)
        self.arco.create_oval(MARGEN_ARCO, MARGEN_ARCO, ANCHO_ARCO - MARGEN_ARCO, ANCHO_ARCO - MARGEN_ARCO, outline=COLOR_BORDE, width=2, tags="anillo")
        self.arco.create_text(ANCHO_ARCO / 2, ANCHO_ARCO / 2, text="0%", fill=COLOR_TEXTO, font=("Segoe UI", 26, "bold"), tags="texto")

        self.frame_botones = tk.Frame(self.root, bg=COLOR_FONDO)
        self.frame_botones.pack(fill="x", pady=6)
        self.boton = tk.Button(self.frame_botones, text="INICIAR RESPALDO", bg=COLOR_ACCENTO, fg="#ffffff", activebackground=COLOR_ACCENTO_FIN, relief="flat", cursor="hand2", font=("Segoe UI", 11, "bold"), command=self._al_pulsar_boton)
        self.boton.pack()

        self.frame_log = tk.Frame(self.root, bg=COLOR_FONDO, padx=14, pady=6)
        self.frame_log.pack(fill="x", pady=(0, 8))
        self.titulo_log = tk.Label(self.frame_log, text="REGISTRO", bg=COLOR_FONDO, fg=COLOR_LOG_INFO, font=("Segoe UI", 9, "bold"))
        self.titulo_log.pack(anchor="w")
        self.config_log = tk.Frame(self.frame_log, bg=COLOR_FONDO)
        self.config_log.pack(fill="x")
        self.lista_log = tk.Listbox(self.config_log, bg=COLOR_PANEL, fg=COLOR_LOG_INFO, highlightthickness=0, height=7, font=("Consolas", 9))
        self.scroll = tk.Scrollbar(self.config_log, orient="vertical", command=self.lista_log.yview)
        self.lista_log.configure(yscrollcommand=self.scroll.set)
        self.lista_log.pack(side="left", fill="y", expand=True)
        self.scroll.pack(side="right", fill="y")

    def _dibujar_arco(self, frac: float) -> None:
        c = self.arco
        c.delete("all")
        x0, y0 = MARGEN_ARCO, MARGEN_ARCO
        x1, y1 = ANCHO_ARCO - MARGEN_ARCO, ANCHO_ARCO - MARGEN_ARCO
        c.create_oval(x0, y0, x1, y1, outline=COLOR_BORDE, width=2, tags="anillo")
        f = max(0.0, min(1.0, frac))
        color = COLOR_ARCO_OK if f >= 1 else COLOR_ARCO
        c.create_arc(x0, y0, x1, y1, start=270, extent=f * 360, style="arc", outline=color, width=10, tags="arco")
        c.create_text(x1 - 24, y1 - 30, text=f"{int(f * 100)}%", fill=COLOR_TEXTO, font=("Segoe UI", 26, "bold"), tags="texto")

    # ------------------------------------------------------------------ refresh
    def _refrescar(self) -> None:
        with self._lock:
            est = self._estado.get("estado", "idle")
            detalle = self._estado.get("detalle", "")
            lineas = list(self._lineas)
            pro = self._progreso
            hilo_vivo = self._hilo is not None and self._hilo.is_alive()
        try:
            self._actualizar_log()
            colores = {
                "idle": COLOR_ESTADO_IDLE, "ejecutando": COLOR_ESTADO_RUNNING, "ok": COLOR_ESTADO_OK,
                "error": COLOR_ESTADO_ERROR, "warn": COLOR_ESTADO_WARN, "cancelado": COLOR_ESTADO_WARN, "pausado": COLOR_ESTADO_WARN,
            }
            self.punto_estado.delete("all")
            self.punto_estado.create_oval(2, 2, 12, 12, fill=colores.get(est, COLOR_ESTADO_IDLE), outline="")
            self.subtitulo.config(text=detalle if detalle else "")
            frac = 0.0
            if est == "ejecutando":
                frac = pro.fraccion() if pro is not None else 0.0
            elif est == "ok":
                frac = 1.0
            elif est == "pausado":
                frac = pro.fraccion() if pro is not None else 0.0
            self._dibujar_arco(frac)
            en_curso = est == "ejecutando" or hilo_vivo
            if en_curso:
                self.boton.config(text="RESPALDO EN CURSO...", state=tk.DISABLED, command=lambda: None)
            else:
                self.boton.config(text=self._texto_boton(est), state=tk.NORMAL, command=self._al_pulsar_boton)
        except Exception:
            pass
        self.root.after(100, self._refrescar)

    def _texto_boton(self, est: str) -> str:
        if est == "en_curso":
            return "RESPALDO EN CURSO..."
        if est == "pausado":
            return "REANUDAR"
        if est == "ok":
            return "NUEVO RESPALDO"
        if est in ("error", "warn"):
            return "REINTENTAR"
        return "INICIAR RESPALDO"

    # ------------------------------------------------------------------ acciones
    def _al_pulsar_boton(self) -> None:
        with self._lock:
            est = self._estado.get("estado", "idle")
        if est == "ejecutando" or (self._hilo is not None and self._hilo.is_alive()):
            return
        if est == "pausado":
            pausados = self.gestor.pausados()
            if not pausados:
                return
            sel = pausados[0]
            self._worker_reanudar(sel)
        else:
            self._iniciar_respaldo()

    def _iniciar_respaldo(self) -> None:
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._evento_cancel.clear()
        self._progreso = None
        self._resultado = None
        self._set_estado("ejecutando", "Iniciando escaneo...")
        self.log("Solicitud de respaldo iniciada.", "accion")
        self._hilo = threading.Thread(target=self._worker_backup, daemon=True)
        self._hilo.start()

    def _worker_backup(self) -> None:
        try:
            fuente = fuentes.FuenteCarpetasUsuario()
            opciones = fuente.detectar()
            if not opciones:
                self._set_estado("error", "No se encontraron carpetas de usuario.")
                self.log("No se encontraron carpetas de usuario para respaldar.", "error")
                return
            plan = fuente.construir_plan(opciones, escaneo.Escaner())
            if not plan.archivos:
                self._set_estado("warn", "No hay archivos para respaldar.")
                self.log("No hay archivos para respaldar.", "warn")
                return
            destino = self.config.ruta_base_respaldos
            self._set_estado("ejecutando", f"Respaldo de {len(opciones)} carpeta(s) / {len(plan.archivos)} archivos.")
            self.log(f"Iniciando respaldo general: {plan.detalle}", "accion")
            pro = progreso.Progreso(len(plan.archivos), sum(s for _, _, s in plan.archivos), "Respaldo", silencioso=False)
            self._progreso = pro
            res = self.motor_obj.ejecutar(plan, destino, progreso_obj=pro, cancelar=self._evento_cancel)
            self._resultado = res
            if self._evento_cancel.is_set():
                self._set_estado("cancelado", "Respaldo cancelado.")
                self.log("Respaldo cancelado por el usuario.", "warn")
                return
            self._set_estado("ok", f"Respaldo completado: {res.copiados} copiados, {res.duplicados} duplicados, {len(res.errores)} errores.")
            self.log(f"Respaldo completado: {res.copiados} copiados, {res.duplicados} duplicados.", "ok")
        except BaseException as e:
            self._set_estado("error", seguridad.mensaje_error_amigable(e))
            self.log(f"Error: {seguridad.mensaje_error_amigable(e)}", "error")

    def _worker_reanudar(self, estado) -> None:
        try:
            pro = progreso.Progreso(0, 0, "Reanudando", silencioso=False)
            res = self.motor_obj.reanudar(estado, progreso_obj=pro, cancelar=self._evento_cancel)
            if res is None:
                self._set_estado("idle", "Nada que reanudar.")
                return
            self._set_estado("ejecutando", "Reanudando respaldo...")
            self.log("Reanudando respaldo interrumpido.", "accion")
        except BaseException as e:
            self._set_estado("error", seguridad.mensaje_error_amigable(e))
            self.log(f"Error al reanudar: {seguridad.mensaje_error_amigable(e)}", "error")

    # ------------------------------------------------------------------ estados
    def _set_estado(self, estado: str, detalle: str = None) -> None:
        with self._lock:
            self._estado["estado"] = estado
            if detalle is not None:
                self._estado["detalle"] = detalle

    # ------------------------------------------------------------------ ciclo
    def ejecutar(self) -> None:
        self.root.mainloop()

    def cerrar(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass


def iniciar_hud() -> None:
    """Arranca el front minimalista/HUD (entry grafico de v6.0)."""
    import os
    from core import constantes, configuracion, estados, motor
    config = configuracion.Configuracion.cargar()
    if not os.path.isabs(config.ruta_base_respaldos) or config.ruta_base_respaldos == "Respaldos":
        config.ruta_base_respaldos = constantes.RUTA_RESPALDOS
        config.guardar()
    gestor = estados.GestorEstados()
    motor_obj = motor.MotorRespaldo(config, gestor)
    FronteHUD(config, gestor, motor_obj).ejecutar()
