#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Front de escritorio del programa Respaldos.Gio (v6.0).

Ventana de escritorio con barra lateral de navegacion, panel contextual,
barra de progreso, anillo de estado y registro estilo consola. Tema oscuro
con acento indigo -> cyan.

Toda la logica de respaldo vive en el nucleo (`core`); esta capa solo
presenta widgets, pide datos y lanza trabajos en hilos aparte para no
congelar la ventana.
"""
import contextlib
import os
import queue
import threading
import tkinter as tk
from tkinter import simpledialog, ttk

from core import (constantes, configuracion, escaneo, estados, fuentes, motor,
                  persistencia, progreso, red, seguridad, utilidades)
from fronts import hud_paneles
from fronts.hud_paneles import (PanelConfig, PanelEliminar, PanelFuente, PanelInicio,
                                PanelRed, PanelRegistros, PanelReanudar)
from fronts.tema import (ANCHO_SIDEBAR, ALTO_LOG, ALTO_VENTANA, ANCHO_VENTANA,
                         COLOR_ACCENTO, COLOR_BORDE, COLOR_ESTADO_ERROR,
                         COLOR_ESTADO_IDLE, COLOR_ESTADO_OK, COLOR_ESTADO_RUNNING,
                         COLOR_ESTADO_WARN, COLOR_FONDO, COLOR_LOG_ACCION, COLOR_LOG_ERROR,
                         COLOR_LOG_INFO, COLOR_LOG_OK, COLOR_LOG_WARN, COLOR_PANEL,
                         COLOR_PANEL_2,
                         COLOR_SIDEBAR, COLOR_SIDEBAR_ACTIVO,
                         COLOR_SIDEBAR_HOVER, COLOR_SUBTEXTO, COLOR_TEXTO)

RUTA_IMAGEN_LOGO = os.path.join(constantes.RUTA_APP, "IMG", "interface.png")
RUTA_ICONO_VENTANA = os.path.join(constantes.RUTA_APP, "IMG", "interface.ico")

NIVEL_COLOR = {
    "info": COLOR_LOG_INFO,
    "ok": COLOR_LOG_OK,
    "warn": COLOR_LOG_WARN,
    "error": COLOR_LOG_ERROR,
    "accion": COLOR_LOG_ACCION,
}

ESTADO_COLOR = {
    "idle": COLOR_ESTADO_IDLE,
    "ejecutando": COLOR_ESTADO_RUNNING,
    "ok": COLOR_ESTADO_OK,
    "error": COLOR_ESTADO_ERROR,
    "warn": COLOR_ESTADO_WARN,
    "cancelado": COLOR_ESTADO_WARN,
    "pausado": COLOR_ESTADO_WARN,
}

# (clave o separador, texto)
NAVEGACION = [
    ("inicio", "Inicio"),
    ("_grupo", "RESPALDOS"),
    ("general", "Respaldo general"),
    ("extensiones", "Por extensiones"),
    ("disco_externo", "Disco externo"),
    ("xampp", "XAMPP / MySQL"),
    ("movil", "Respaldo movil"),
    ("_grupo", "SISTEMA"),
    ("reanudar", "Reanudar"),
    ("red", "Modo red"),
    ("eliminar", "Eliminar respaldo"),
    ("registros", "Registros"),
    ("config", "Configuracion"),
    ("_salir", "Salir"),
]

TITULOS_FUENTES = {
    "general": ("Respaldo general", "Copia las carpetas de usuario que detecta el programa."),
    "extensiones": ("Por extensiones", "Copia solo los archivos de las extensiones configuradas."),
    "disco_externo": ("Recuperar disco externo", "Recupera el contenido de una unidad externa."),
    "xampp": ("Respaldos XAMPP / MySQL", "Copia las instalaciones de XAMPP o MySQL detectadas."),
    "movil": ("Respaldo movil", "Descarga el contenido de un dispositivo Android o iOS conectado."),
}


class _SalidaGUI:
    """Redirige lo que el core imprime hacia el registro de la ventana."""

    def __init__(self, app):
        self.app = app
        self._buffer = ""

    def write(self, texto):
        self._buffer += texto
        while "\n" in self._buffer:
            linea, self._buffer = self._buffer.split("\n", 1)
            linea = linea.replace("\r", "").rstrip()
            if linea:
                self.app.log(linea, "info")

    def flush(self):
        if self._buffer.replace("\r", "").strip():
            self.app.log(self._buffer.replace("\r", "").rstrip(), "info")
        self._buffer = ""


class _Peticion:
    """Peticion de dato hecha por un hilo de trabajo hacia la ventana."""

    __slots__ = ("mensaje", "ocultar", "resultado", "evento")

    def __init__(self, mensaje, ocultar):
        self.mensaje = mensaje
        self.ocultar = ocultar
        self.resultado = []
        self.evento = threading.Event()


class Aplicacion:
    """Ventana principal del front de escritorio."""

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
        self._version_log = 0
        self._log_visto = -1

        self._cola_ui = queue.Queue()
        self._cola_pedidos = queue.Queue()

        self.paneles = {}
        self.panel_actual = None
        self._botones_sidebar = {}

        # el core pregunta por ventana en vez de por consola
        utilidades.instalar_pedidor(self._pedir)

        self._construir_ui()
        self.navegar("inicio")
        self.log(f"Respaldos.Gio v{constantes.VERSION_PROGRAMA} listo.", "ok")
        self._refrescar()

    # ==================================================================
    #  construccion de la ventana
    # ==================================================================
    def _construir_ui(self):
        self.root = tk.Tk()
        self.root.title("Respaldos.Gio")
        self.root.configure(bg=COLOR_FONDO)
        self.root.minsize(960, 620)
        self.root.geometry(f"{ANCHO_VENTANA}x{ALTO_VENTANA}")
        try:
            self.root.iconbitmap(RUTA_ICONO_VENTANA)
        except Exception:
            pass
        self.root.protocol("WM_DELETE_WINDOW", self._al_cerrar)

        self._barra_superior()
        self._barra_progreso()
        self._cuerpo()
        self._barra_registro()

    def _barra_superior(self):
        top = tk.Frame(self.root, bg=COLOR_FONDO)
        top.pack(fill="x", padx=18, pady=(14, 6))

        self._logo = None
        try:
            foto = tk.PhotoImage(file=RUTA_IMAGEN_LOGO)
            ancho = foto.width()
            if ancho > 72:
                factor = max(1, round(ancho / 72))
                foto = foto.subsample(factor, factor)
            self._logo = foto
            tk.Label(top, image=foto, bg=COLOR_FONDO).pack(side="left", padx=(0, 12))
        except Exception:
            pass

        col = tk.Frame(top, bg=COLOR_FONDO)
        col.pack(side="left")
        tk.Label(col, text="RESPALDOS.GIO", bg=COLOR_FONDO, fg=COLOR_TEXTO,
                 font=("Segoe UI", 15, "bold"), anchor="w").pack(anchor="w")
        self.lbl_ruta = tk.Label(col, text="", bg=COLOR_FONDO, fg=COLOR_SUBTEXTO,
                                 font=("Segoe UI", 9), anchor="w")
        self.lbl_ruta.pack(anchor="w")

        der = tk.Frame(top, bg=COLOR_FONDO)
        der.pack(side="right")
        self.visor = tk.Canvas(der, width=16, height=16, bg=COLOR_FONDO,
                               highlightthickness=0)
        self.visor.pack(side="left", padx=(0, 8))
        self.punto = self.visor.create_oval(3, 3, 13, 13, fill=COLOR_ESTADO_IDLE, outline="")
        self.lbl_estado = tk.Label(der, text="Listo", bg=COLOR_FONDO, fg=COLOR_TEXTO,
                                   font=("Segoe UI", 10, "bold"), anchor="e")
        self.lbl_estado.pack(side="left")

    def _barra_progreso(self):
        marco = tk.Frame(self.root, bg=COLOR_FONDO)
        marco.pack(fill="x", padx=18, pady=(0, 8))
        estilo = ttk.Style(self.root)
        try:
            estilo.theme_use("clam")
        except Exception:
            pass
        estilo.configure("HUD.Horizontal.TProgressbar",
                         background=COLOR_ACCENTO, troughcolor=COLOR_PANEL_2,
                         bordercolor=COLOR_PANEL_2, lightcolor=COLOR_ACCENTO,
                         darkcolor=COLOR_ACCENTO)
        self.progreso_barra = ttk.Progressbar(marco, style="HUD.Horizontal.TProgressbar",
                                              length=400, mode="determinate")
        self.progreso_barra.pack(side="left", fill="x", expand=True)
        self.btn_cancelar = tk.Button(marco, text="CANCELAR", command=self.cancelar_respaldo,
                                      bg=COLOR_PANEL_2, fg="#fca5a5", relief="flat",
                                      cursor="hand2", font=("Segoe UI", 9, "bold"),
                                      padx=12, pady=4, state=tk.DISABLED)
        self.btn_cancelar.pack(side="right", padx=(12, 0))

    def _cuerpo(self):
        cuerpo = tk.Frame(self.root, bg=COLOR_FONDO)
        cuerpo.pack(fill="both", expand=True, padx=18)

        # --- barra lateral
        self.sidebar = tk.Frame(cuerpo, bg=COLOR_SIDEBAR, width=ANCHO_SIDEBAR,
                                highlightbackground=COLOR_BORDE, highlightthickness=1)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        marca = tk.Frame(self.sidebar, bg=COLOR_SIDEBAR)
        marca.pack(fill="x", padx=14, pady=(16, 12))
        tk.Label(marca, text="MENU", bg=COLOR_SIDEBAR, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(anchor="w")

        for clave, texto in NAVEGACION:
            if clave == "_grupo":
                tk.Label(self.sidebar, text=texto, bg=COLOR_SIDEBAR, fg=COLOR_SUBTEXTO,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(
                    fill="x", padx=18, pady=(12, 2))
                continue
            lbl = tk.Label(self.sidebar, text=texto, bg=COLOR_SIDEBAR,
                           fg=COLOR_TEXTO if clave != "_salir" else "#f87171",
                           font=("Segoe UI", 10), anchor="w", padx=18, pady=7,
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

        pie = tk.Label(self.sidebar, text=f"v{constantes.VERSION_PROGRAMA}",
                       bg=COLOR_SIDEBAR, fg=COLOR_SUBTEXTO, font=("Segoe UI", 8))
        pie.pack(side="bottom", pady=12)

        # --- area de contenido
        self.contenido = tk.Frame(cuerpo, bg=COLOR_FONDO)
        self.contenido.pack(side="left", fill="both", expand=True, padx=(18, 0))

    def _barra_registro(self):
        marco = tk.Frame(self.root, bg=COLOR_FONDO)
        marco.pack(fill="x", padx=18, pady=(8, 14))
        tk.Label(marco, text="REGISTRO", bg=COLOR_FONDO, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(anchor="w")
        caja = tk.Frame(marco, bg=COLOR_PANEL_2,
                        highlightbackground=COLOR_BORDE, highlightthickness=1)
        caja.pack(fill="x")
        self.lista_log = tk.Listbox(caja, bg=COLOR_PANEL_2, fg=COLOR_LOG_INFO,
                                    relief="flat", highlightthickness=0,
                                    height=6, font=("Consolas", 9),
                                    selectbackground=COLOR_PANEL, selectforeground=COLOR_TEXTO)
        scroll = tk.Scrollbar(caja, orient="vertical", command=self.lista_log.yview)
        self.lista_log.configure(yscrollcommand=scroll.set)
        self.lista_log.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        scroll.pack(side="right", fill="y", pady=6)
        self.lista_log.config(height=ALTO_LOG // 18)

    # ==================================================================
    #  navegacion
    # ==================================================================
    def _texto_panel_activo(self):
        for clave, texto in NAVEGACION:
            if clave == self.panel_actual:
                return texto
        return ""

    def _crear_paneles(self):
        if self.paneles:
            return
        cont = self.contenido
        self.paneles["inicio"] = PanelInicio(self, cont)
        for clave in ("general", "extensiones", "disco_externo", "xampp", "movil"):
            titulo, desc = TITULOS_FUENTES[clave]
            self.paneles[clave] = PanelFuente(self, cont, clave, titulo, desc,
                                              self._fabrica_fuentes()[clave])
        self.paneles["reanudar"] = PanelReanudar(self, cont)
        self.paneles["red"] = PanelRed(self, cont)
        self.paneles["eliminar"] = PanelEliminar(self, cont)
        self.paneles["registros"] = PanelRegistros(self, cont)
        self.paneles["config"] = PanelConfig(self, cont)

    def _fabrica_fuentes(self):
        return {
            "general": fuentes.FuenteCarpetasUsuario(),
            "extensiones": fuentes.FuenteExtensiones(),
            "disco_externo": fuentes.FuenteDiscoExterno(),
            "xampp": fuentes.FuenteXampp(),
            "movil": fuentes.FuenteMovil(),
        }

    def navegar(self, clave):
        if clave not in ("inicio", "reanudar", "red", "eliminar", "registros", "config") \
                and clave not in TITULOS_FUENTES:
            return
        self._crear_paneles()
        if self.panel_actual == clave:
            return
        anterior = self.paneles.get(self.panel_actual)
        if anterior:
            anterior.ocultar()
        self.panel_actual = clave
        self.paneles[clave].mostrar()
        self._resaltar_sidebar()

    def _resaltar_sidebar(self):
        texto_activo = self._texto_panel_activo()
        for clave, lbl in self._botones_sidebar.items():
            activo = clave == self.panel_actual
            lbl.config(bg=COLOR_SIDEBAR_ACTIVO if activo else COLOR_SIDEBAR,
                       fg=COLOR_ACCENTO if activo else COLOR_TEXTO,
                       font=("Segoe UI", 10, "bold" if activo else "normal"))

    # ==================================================================
    #  registro y estado
    # ==================================================================
    def log(self, mensaje, nivel="info"):
        with self._lock:
            self._lineas.append((str(mensaje), nivel))
            if len(self._lineas) > 300:
                self._lineas = self._lineas[-300:]
            self._version_log += 1

    def _set_estado(self, estado, detalle=None):
        with self._lock:
            self._estado["estado"] = estado
            if detalle is not None:
                self._estado["detalle"] = detalle

    set_estado = _set_estado

    def estado_actual(self):
        with self._lock:
            return dict(self._estado)

    def lineas(self):
        with self._lock:
            return list(self._lineas)

    def ocupado(self):
        return self._hilo is not None and self._hilo.is_alive()

    def programar(self, funcion):
        """Ejecuta `funcion` en el hilo de la ventana (nunca desde un worker)."""
        self._cola_ui.put(funcion)

    def ejecutar_trabajo(self, nombre, funcion):
        """Lanza un trabajo de fondo (detecciones, lecturas) con su log."""
        hilo = threading.Thread(target=self._envolver, args=(nombre, funcion),
                                daemon=True)
        hilo.start()

    def _envolver(self, nombre, funcion):
        try:
            with contextlib.redirect_stdout(_SalidaGUI(self)):
                funcion()
        except Exception as e:
            self.log(f"{nombre}: {seguridad.mensaje_error_amigable(e)}", "error")

    # ==================================================================
    #  peticiones al usuario (dialogs desde cualquier hilo)
    # ==================================================================
    def _pedir(self, mensaje, ocultar=False):
        if threading.current_thread() is threading.main_thread():
            return self._pedir_dialogo(mensaje, ocultar)
        peticion = _Peticion(mensaje, ocultar)
        self._cola_pedidos.put(peticion)
        peticion.evento.wait()
        return peticion.resultado[0] if peticion.resultado else ""

    def _pedir_dialogo(self, mensaje, ocultar=False):
        try:
            respuesta = simpledialog.askstring("Respaldos.Gio", mensaje,
                                               parent=self.root,
                                               show="*" if ocultar else "")
        except Exception:
            return ""
        return "" if respuesta is None else respuesta

    def _drenar_pedidos(self):
        while True:
            try:
                p = self._cola_pedidos.get_nowait()
            except queue.Empty:
                return
            p.resultado.append(self._pedir_dialogo(p.mensaje, p.ocultar))
            p.evento.set()

    def _drenar_ui(self):
        while True:
            try:
                funcion = self._cola_ui.get_nowait()
            except queue.Empty:
                return
            try:
                funcion()
            except Exception as e:
                self.log(f"Error de interfaz: {e}", "error")

    # ==================================================================
    #  trabajos de respaldo
    # ==================================================================
    def _arrancar(self, objetivo, detalle):
        if self.ocupado():
            self.log("Ya hay un trabajo en curso.", "warn")
            return False
        self._evento_cancel.clear()
        self._progreso = None
        self._resultado = None
        self._set_estado("ejecutando", detalle)
        self._hilo = threading.Thread(target=objetivo, daemon=True)
        self._hilo.start()
        return True

    def iniciar_respaldo_general(self):
        if self.panel_actual != "inicio":
            self.navegar("general")
            return
        self.log("Solicitud de respaldo general.", "accion")
        self._arrancar(lambda: self._worker_fuente(
            fuentes.FuenteCarpetasUsuario(), None, None, TITULOS_FUENTES["general"][0]),
            "Iniciando escaneo...")

    # compatibilidad con la version anterior del front
    _iniciar_respaldo = iniciar_respaldo_general

    def iniciar_fuente(self, fuente, seleccion, destino, origen=""):
        self.log(f"Respaldo {origen or fuente.tipo} iniciado.", "accion")
        self._arrancar(lambda: self._worker_fuente(fuente, seleccion, destino,
                                                   origen or fuente.tipo),
                       f"Iniciando {origen or fuente.tipo}...")

    def iniciar_reanudar(self, estado):
        self.log("Reanudando respaldo interrumpido.", "accion")
        self._arrancar(lambda: self._worker_reanudar(estado), "Reanudando respaldo...")

    def iniciar_red(self, modo):
        texto = "servidor" if modo == "servidor" else "cliente"
        self.log(f"Modo red: {texto}.", "accion")
        self._arrancar(lambda: self._worker_red(modo), f"Modo red ({texto})...")

    def cancelar_respaldo(self):
        if not self.ocupado():
            return
        self._evento_cancel.set()
        self.log("Cancelando el respaldo en curso...", "warn")
        self._set_estado("ejecutando", "Cancelando...")

    # ---------------------------------------------------------- workers
    def _worker_fuente(self, fuente, seleccion, destino, origen):
        try:
            with contextlib.redirect_stdout(_SalidaGUI(self)):
                if seleccion is None:
                    seleccion = fuente.detectar()
                    if not seleccion:
                        self._set_estado("error", "No se encontraron carpetas de usuario.")
                        self.log(fuente.sin_opciones, "error")
                        return
                    seleccion = list(seleccion)
                destino = destino or self.config.ruta_base_respaldos
                if fuente.requiere_seleccion and not seleccion:
                    self._set_estado("warn", "Sin seleccion.")
                    self.log("No se selecciono nada para respaldar.", "warn")
                    return

                if fuente.tipo == "movil" and seleccion and seleccion[0].clave == "ADB":
                    self._set_estado("ejecutando", "Descargando desde el dispositivo...")
                    res = fuente.ejecutar(seleccion, destino, self.motor_obj)
                    self._resultado = res
                    self._set_estado("ok", "Dispositivo descargado.")
                    self.log("Respaldos moviles completados.", "ok")
                    return

                plan = fuente.construir_plan(seleccion, escaneo.Escaner())
                if not plan.archivos:
                    self._set_estado("warn", "No hay archivos para respaldar.")
                    self.log(fuente.sin_archivos, "warn")
                    return

                self._set_estado("ejecutando",
                                 f"{origen}: {len(plan.archivos)} archivo(s).")
                total = sum(s for _, _, s in plan.archivos)
                pro = progreso.Progreso(len(plan.archivos), total, "Respaldo",
                                        silencioso=True)
                self._progreso = pro
                res = self.motor_obj.ejecutar(plan, destino, progreso_obj=pro,
                                              cancelar=self._evento_cancel)
                self._resultado = res

            if self._evento_cancel.is_set():
                self._set_estado("cancelado", "Respaldo cancelado.")
                self.log("Respaldo cancelado por el usuario.", "warn")
                return
            if res is None:
                self._set_estado("warn", "El respaldo no concluyo.")
                return
            detalle = (f"Respaldo completado: {res.copiados} copiados, "
                       f"{res.duplicados} duplicados, {len(res.errores)} errores.")
            self._set_estado("ok", detalle)
            self.log(detalle, "ok" if not res.errores else "warn")
        except BaseException as e:
            self._set_estado("error", seguridad.mensaje_error_amigable(e))
            self.log(f"Error: {seguridad.mensaje_error_amigable(e)}", "error")

    def _worker_reanudar(self, estado):
        try:
            with contextlib.redirect_stdout(_SalidaGUI(self)):
                pro = progreso.Progreso(estado.total_archivos, 0, "Reanudando",
                                        silencioso=True)
                self._progreso = pro
                res = self.motor_obj.reanudar(estado, progreso_obj=pro,
                                              cancelar=self._evento_cancel)
                self._resultado = res
            if self._evento_cancel.is_set():
                self._set_estado("cancelado", "Reanudacion cancelada.")
                self.log("Reanudacion cancelada.", "warn")
                return
            if res is None:
                self._set_estado("idle", "Nada que reanudar.")
                self.log("No hay nada pendiente por reanudar.", "info")
                return
            detalle = f"Reanudado: {res.copiados} copiados, {res.duplicados} duplicados."
            self._set_estado("ok", detalle)
            self.log(detalle, "ok")
        except BaseException as e:
            self._set_estado("error", seguridad.mensaje_error_amigable(e))
            self.log(f"Error al reanudar: {seguridad.mensaje_error_amigable(e)}", "error")

    def _worker_red(self, modo):
        try:
            with contextlib.redirect_stdout(_SalidaGUI(self)):
                if modo == "servidor":
                    red.servidor_red(self.config)
                else:
                    red.cliente_red(self.config, self.motor_obj)
            self._set_estado("ok", "Operacion de red finalizada.")
        except BaseException as e:
            self._set_estado("error", seguridad.mensaje_error_amigable(e))
            self.log(f"Error de red: {seguridad.mensaje_error_amigable(e)}", "error")

    # ==================================================================
    #  refresco periodico (hilo de la ventana)
    # ==================================================================
    def _refrescar(self):
        try:
            self._drenar_ui()
            self._drenar_pedidos()
            self._pintar()
        except Exception:
            pass
        try:
            self.root.after(100, self._refrescar)
        except Exception:
            pass

    def _pintar(self):
        with self._lock:
            estado = self._estado.get("estado", "idle")
            detalle = self._estado.get("detalle", "")
            version = self._version_log
            progreso_obj = self._progreso

        ocupado = self.ocupado()

        # punto de estado y etiqueta
        self.visor.delete("all")
        self.visor.create_oval(3, 3, 13, 13, fill=ESTADO_COLOR.get(estado, COLOR_ESTADO_IDLE),
                               outline="")
        self.lbl_estado.config(text=detalle or estado.capitalize())
        self.lbl_ruta.config(text=self.config.ruta_base_respaldos)

        # barra de progreso
        fraccion = 0.0
        if progreso_obj is not None and estado == "ejecutando":
            try:
                fraccion = progreso_obj.fraccion()
            except Exception:
                fraccion = 0.0
        elif estado == "ok":
            fraccion = 1.0
        self.progreso_barra["value"] = max(0.0, min(100.0, fraccion * 100))
        self.btn_cancelar.config(state=tk.NORMAL if ocupado else tk.DISABLED)

        # registro
        if version != self._log_visto:
            with self._lock:
                lineas = list(self._lineas)
            self.lista_log.delete(0, tk.END)
            for i, (texto, nivel) in enumerate(lineas):
                self.lista_log.insert(tk.END, texto)
                try:
                    self.lista_log.itemconfig(i, foreground=NIVEL_COLOR.get(nivel,
                                                                          COLOR_LOG_INFO))
                except Exception:
                    pass
            self.lista_log.see(tk.END)
            self._log_visto = version

        # panel de inicio (anillo y fichas)
        panel = self.paneles.get("inicio")
        if panel is not None and self.panel_actual == "inicio" and panel._construido:
            panel.actualizar(fraccion, estado, detalle, ocupado)

    # ==================================================================
    #  ciclo de vida
    # ==================================================================
    def leer_ultima_ruta(self):
        texto = persistencia.leer_ultima_ruta()
        if not texto:
            return ""
        return texto.splitlines()[0]

    def ejecutar(self):
        self.root.mainloop()

    def cerrar(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def _al_cerrar(self):
        from tkinter import messagebox
        if self.ocupado():
            if not messagebox.askyesno("Trabajo en curso",
                                       "Hay un respaldo en curso. Si sales se "
                                       "interrumpira. ¿Salir de todos modos?",
                                       parent=self.root):
                return
            self._evento_cancel.set()
        try:
            self.config.guardar()
        except Exception:
            pass
        try:
            utilidades.instalar_pedidor(None)
        except Exception:
            pass
        self.cerrar()


# compatibilidad con la version anterior del front
FronteHUD = Aplicacion


def iniciar_hud() -> None:
    """Arranca el front de escritorio (entry grafico de v6.0)."""
    config = configuracion.Configuracion.cargar()
    if not os.path.isabs(config.ruta_base_respaldos) or config.ruta_base_respaldos == "Respaldos":
        config.ruta_base_respaldos = constantes.RUTA_RESPALDOS
        config.guardar()
    gestor = estados.GestorEstados()
    motor_obj = motor.MotorRespaldo(config, gestor)
    Aplicacion(config, gestor, motor_obj).ejecutar()


if __name__ == "__main__":
    iniciar_hud()
