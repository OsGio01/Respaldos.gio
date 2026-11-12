#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Front movil del programa Respaldos.Gio (v6.2).

`AplicacionMovil` es la ventana celular: reutiliza TODO el nucleo del front
de escritorio (`fronts.hud.Aplicacion`: workers, pedidos, registro, refresco)
y solo cambia la presentacion: ventana estrecha y menu hamburguesa que se
desliza sobre el contenido con las mismas 11 opciones.

`FronteMovil` conserva la logica de estado/progresso sin ventana, por
compatibilidad con el entry movil anterior.
"""
import os
import threading
import tkinter as tk

from core import constantes, configuracion, estados, motor, seguridad
from fronts import tema as _tema
from fronts.hud import Aplicacion, NAVEGACION
from fronts.hud_paneles import MarcoScroll
from fronts.tema import (
    ANCHO_ARCO, COLOR_ARCO, COLOR_ARCO_OK, COLOR_BORDE, COLOR_ESTADO_ERROR,
    COLOR_ESTADO_IDLE, COLOR_ESTADO_OK, COLOR_ESTADO_RUNNING, COLOR_ESTADO_WARN,
    COLOR_FONDO, COLOR_LOG_ACCION, COLOR_LOG_ERROR, COLOR_LOG_INFO, COLOR_LOG_OK,
    COLOR_LOG_WARN, COLOR_PANEL, COLOR_SIDEBAR, COLOR_SIDEBAR_ACTIVO,
    COLOR_SIDEBAR_HOVER, COLOR_SUBTEXTO, COLOR_TEXTO,
)

RUTA_ICONO_MOVIL = os.path.join(constantes.RUTA_APP, "IMG", "icono.ico")


class _TextoCorto:
    """Etiqueta que recorta lo que exceda el ancho celular.

    Por defecto conserva el FINAL (ideal para rutas: se ve el nombre del
    archivo); con `conservar_inicio` conserva el principio (ideal para
    estados: se ve "Listo para res...").
    """

    def __init__(self, etiqueta, maximo, conservar_inicio=False):
        self._etiqueta = etiqueta
        self._maximo = maximo
        self._conservar_inicio = conservar_inicio

    def config(self, **kw):
        if kw.get("text"):
            texto = str(kw["text"])
            if len(texto) > self._maximo:
                if self._conservar_inicio:
                    kw["text"] = texto[:self._maximo - 1] + "…"
                else:
                    kw["text"] = "…" + texto[-(self._maximo - 1):]
        self._etiqueta.config(**kw)

    configure = config

    def __getattr__(self, nombre):
        return getattr(self._etiqueta, nombre)


class AplicacionMovil(Aplicacion):
    """Ventana celular con menu hamburguesa (mismo nucleo que el escritorio)."""

    ANCHO = 420
    ALTO = 760
    ANCHO_MIN = 380
    ALTO_MIN = 600

    # ------------------------------------------------------------------ UI
    def _construir_ui(self):
        # los paneles se construyen estrechos (se hace antes de crearlos)
        _tema.ES_ANCHO = False
        _tema.ANCHO_TEXTO = 330
        _tema.LARGO_ESCALA = 230

        self.root = tk.Tk()
        self.root.title("Respaldos.Gio")
        self.root.configure(bg=COLOR_FONDO)
        self.root.minsize(self.ANCHO_MIN, self.ALTO_MIN)
        self.root.geometry(f"{self.ANCHO}x{self.ALTO}")
        try:
            self.root.iconbitmap(RUTA_ICONO_MOVIL)
        except Exception:
            pass
        self.root.protocol("WM_DELETE_WINDOW", self._al_cerrar)

        self._barra_superior()
        self._barra_progreso()
        self._cuerpo()
        self._barra_registro()

    def _barra_superior(self):
        top = tk.Frame(self.root, bg=COLOR_FONDO)
        top.pack(fill="x", padx=12, pady=(10, 6))

        # --- boton hamburguesa
        self.btn_menu = tk.Label(top, text="\u2630", bg=COLOR_PANEL, fg=COLOR_TEXTO,
                                 font=("Segoe UI", 15), width=2, padx=2, pady=1,
                                 cursor="hand2", relief="flat",
                                 highlightbackground=COLOR_BORDE, highlightthickness=1)
        self.btn_menu.pack(side="left")
        self.btn_menu.bind("<Button-1>", lambda e: self.alternar_menu())

        col = tk.Frame(top, bg=COLOR_FONDO)
        col.pack(side="left")
        tk.Label(col, text="RESPALDOS.GIO", bg=COLOR_FONDO, fg=COLOR_TEXTO,
                 font=("Segoe UI", 12, "bold"), anchor="w").pack(anchor="w")
        self.lbl_ruta = _TextoCorto(
            tk.Label(col, text="", bg=COLOR_FONDO, fg=COLOR_SUBTEXTO,
                     font=("Segoe UI", 8), anchor="w"), 30)

        der = tk.Frame(top, bg=COLOR_FONDO)
        der.pack(side="right")
        self.visor = tk.Canvas(der, width=14, height=14, bg=COLOR_FONDO,
                               highlightthickness=0)
        self.visor.pack(side="left", padx=(0, 5))
        self.lbl_estado = _TextoCorto(
            tk.Label(der, text="Listo", bg=COLOR_FONDO, fg=COLOR_TEXTO,
                     font=("Segoe UI", 8, "bold"), anchor="e"), 16,
            conservar_inicio=True)
        self.lbl_estado.pack(side="left")

    def _barra_progreso(self):
        marco = tk.Frame(self.root, bg=COLOR_FONDO)
        marco.pack(fill="x", padx=12, pady=(0, 8))
        from tkinter import ttk
        estilo = ttk.Style(self.root)
        try:
            estilo.theme_use("clam")
        except Exception:
            pass
        estilo.configure("MOVIL.Horizontal.TProgressbar",
                         background=_tema.COLOR_ACCENTO, troughcolor=COLOR_PANEL,
                         bordercolor=COLOR_PANEL, lightcolor=_tema.COLOR_ACCENTO,
                         darkcolor=_tema.COLOR_ACCENTO)
        self.progreso_barra = ttk.Progressbar(marco, style="MOVIL.Horizontal.TProgressbar",
                                              length=150, mode="determinate")
        self.progreso_barra.pack(side="left", fill="x", expand=True)
        self.btn_cancelar = tk.Button(marco, text="CANCELAR", command=self.cancelar_respaldo,
                                      bg=COLOR_PANEL, fg="#fca5a5", relief="flat",
                                      cursor="hand2", font=("Segoe UI", 8, "bold"),
                                      padx=10, pady=4, state=tk.DISABLED)
        self.btn_cancelar.pack(side="right", padx=(10, 0))

    def _cuerpo(self):
        cuerpo = tk.Frame(self.root, bg=COLOR_FONDO)
        cuerpo.pack(fill="both", expand=True, padx=12)

        # --- area de contenido a ancho completo
        self.contenido = tk.Frame(cuerpo, bg=COLOR_FONDO)
        self.contenido.pack(side="left", fill="both", expand=True)

        # --- menu hamburguesa (se desliza sobre el contenido)
        self._menu_abierto = False
        self.drawer = tk.Frame(cuerpo, bg=COLOR_SIDEBAR, width=252,
                               highlightbackground=COLOR_BORDE, highlightthickness=1)
        self.drawer.pack_propagate(False)

        cab = tk.Frame(self.drawer, bg=COLOR_SIDEBAR)
        cab.pack(fill="x", padx=14, pady=(14, 6))
        tk.Label(cab, text="MENU", bg=COLOR_SIDEBAR, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left")
        cerrar = tk.Label(cab, text="\u2715", bg=COLOR_SIDEBAR, fg=COLOR_TEXTO,
                          font=("Segoe UI", 12), cursor="hand2")
        cerrar.pack(side="right")
        cerrar.bind("<Button-1>", lambda e: self.cerrar_menu())

        scroll = MarcoScroll(self.drawer, bg=COLOR_SIDEBAR)
        scroll.pack(fill="both", expand=True, padx=(2, 0))
        for clave, texto in NAVEGACION:
            if clave == "_grupo":
                tk.Label(scroll.interior, text=texto, bg=COLOR_SIDEBAR,
                         fg=COLOR_SUBTEXTO, font=("Segoe UI", 8, "bold"),
                         anchor="w").pack(fill="x", padx=16, pady=(12, 2))
                continue
            lbl = tk.Label(scroll.interior, text=texto, bg=COLOR_SIDEBAR,
                           fg=COLOR_TEXTO if clave != "_salir" else "#f87171",
                           font=("Segoe UI", 10), anchor="w", padx=16, pady=7,
                           cursor="hand2")
            lbl.pack(fill="x")
            if clave == "_salir":
                lbl.bind("<Button-1>", lambda e: self._al_cerrar())
                continue
            lbl.bind("<Button-1>", lambda e, c=clave: self.navegar(c))
            lbl.bind("<Enter>", lambda e, l=lbl: l.config(bg=COLOR_SIDEBAR_HOVER))
            lbl.bind("<Leave>", lambda e, l=lbl: l.config(
                bg=COLOR_SIDEBAR_ACTIVO if l.cget("text") == self._texto_panel_activo()
                else COLOR_SIDEBAR))
            self._botones_sidebar[clave] = lbl

        tk.Label(self.drawer, text=f"v{constantes.VERSION_PROGRAMA}",
                 bg=COLOR_SIDEBAR, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 8)).pack(side="bottom", pady=10)
        self.drawer.place_forget()

    def _barra_registro(self):
        marco = tk.Frame(self.root, bg=COLOR_FONDO)
        marco.pack(fill="x", padx=12, pady=(8, 12))
        tk.Label(marco, text="REGISTRO", bg=COLOR_FONDO, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(anchor="w")
        caja = tk.Frame(marco, bg=COLOR_PANEL,
                        highlightbackground=COLOR_BORDE, highlightthickness=1)
        caja.pack(fill="x")
        self.lista_log = tk.Listbox(caja, bg=COLOR_PANEL, fg=COLOR_LOG_INFO,
                                    relief="flat", highlightthickness=0,
                                    height=4, font=("Consolas", 8),
                                    selectbackground=COLOR_SIDEBAR_ACTIVO,
                                    selectforeground=COLOR_TEXTO)
        scroll = tk.Scrollbar(caja, orient="vertical", command=self.lista_log.yview)
        self.lista_log.configure(yscrollcommand=scroll.set)
        self.lista_log.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        scroll.pack(side="right", fill="y", pady=6)

    # ---------------------------------------------------------- hamburguesa
    def abrir_menu(self):
        if self._menu_abierto:
            return
        self._menu_abierto = True
        self.drawer.place(x=0, y=0, relheight=1)
        self.drawer.lift()
        self.root.bind("<Button-1>", self._al_tocar_ventana)

    def cerrar_menu(self):
        if not self._menu_abierto:
            return
        self._menu_abierto = False
        self.drawer.place_forget()
        try:
            self.root.unbind("<Button-1>")
        except Exception:
            pass

    def alternar_menu(self):
        self.cerrar_menu() if self._menu_abierto else self.abrir_menu()

    def _al_tocar_ventana(self, evento):
        """Cierra el menu si el toque cae fuera de el (y del boton ☰)."""
        if not self._menu_abierto:
            return
        if str(evento.widget) == str(self.btn_menu):
            return
        x, y = evento.x_root, evento.y_root
        dx, dy = self.drawer.winfo_rootx(), self.drawer.winfo_rooty()
        if dx <= x <= dx + self.drawer.winfo_width() and \
                dy <= y <= dy + self.drawer.winfo_height():
            return
        self.cerrar_menu()

    # ------------------------------------------------------------- navegar
    def navegar(self, clave):
        super().navegar(clave)
        self.cerrar_menu()


# ------------------------------------------------------------------
#  Logica de estado sin ventana (compatibilidad con el entry movil)
# ------------------------------------------------------------------
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

    # ---------------------------------------------------------------- estado
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

    # -------------------------------------------------------------- acciones
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

    # ---------------------------------------------------------------- extras
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
            self.log("Reanudando respaldo...", "accion")
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


def iniciar_movil() -> None:
    """Arranca el front celular (entry movil de v6.2)."""
    config = configuracion.Configuracion.cargar()
    if not os.path.isabs(config.ruta_base_respaldos) or config.ruta_base_respaldos == "Respaldos":
        config.ruta_base_respaldos = constantes.RUTA_RESPALDOS
        config.guardar()
    gestor = estados.GestorEstados()
    motor_obj = motor.MotorRespaldo(config, gestor)
    AplicacionMovil(config, gestor, motor_obj).ejecutar()


if __name__ == "__main__":
    iniciar_movil()
