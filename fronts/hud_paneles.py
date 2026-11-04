#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paneles del front de escritorio (Respaldos.Gio v6.0).

Cada panel es una vista del area de contenido. La logica de negocio vive en
`core` y las operaciones sin presentacion en `fronts.acciones`; aqui solo se
construyen widgets y se piden datos al usuario.
"""
import os
import time
import tkinter as tk
from tkinter import filedialog

from core import configuracion, constantes, utilidades
from fronts import acciones
from fronts.tema import (
    COLOR_ACCENTO, COLOR_ACCENTO_FIN, COLOR_ARCO, COLOR_ARCO_OK, COLOR_BORDE,
    COLOR_FONDO, COLOR_LOG_ERROR, COLOR_LOG_INFO, COLOR_LOG_OK, COLOR_LOG_WARN,
    COLOR_PANEL, COLOR_PANEL_2, COLOR_SUBTEXTO, COLOR_TEXTO, ANCHO_ARCO, MARGEN_ARCO,
)


# ==========================================================================
#  utilidades de dibujo
# ==========================================================================
def tarjeta(parent, padx=0, pady=0):
    """Marco con fondo de panel y borde suave."""
    f = tk.Frame(parent, bg=COLOR_PANEL, highlightbackground=COLOR_BORDE, highlightthickness=1)
    f.pack(fill="x", padx=padx, pady=pady)
    return f


def etiqueta(parent, texto, tam=10, negrita=False, color=None, bg=None):
    return tk.Label(parent, text=texto, bg=bg or COLOR_PANEL, fg=color or COLOR_TEXTO,
                    font=("Segoe UI", tam, "bold" if negrita else "normal"), anchor="w")


def boton(parent, texto, comando, primario=True, ancho=None):
    fondo = COLOR_ACCENTO if primario else COLOR_PANEL_2
    b = tk.Button(parent, text=texto, command=comando, bg=fondo,
                  fg="#ffffff" if primario else COLOR_TEXTO,
                  activebackground=COLOR_ACCENTO_FIN if primario else COLOR_BORDE,
                  activeforeground="#ffffff" if primario else COLOR_TEXTO,
                  relief="flat", cursor="hand2", font=("Segoe UI", 10, "bold"),
                  padx=16, pady=7)
    if ancho:
        b.config(width=ancho)
    return b


class MarcoScroll(tk.Frame):
    """Contenido con barra de desplazamiento vertical."""

    def __init__(self, master, bg=None):
        super().__init__(master, bg=bg or COLOR_FONDO)
        self.canvas = tk.Canvas(self, bg=bg or COLOR_FONDO, highlightthickness=0)
        self.barra = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.interior = tk.Frame(self.canvas, bg=bg or COLOR_FONDO)
        self._win = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")
        self.canvas.configure(yscrollcommand=self.barra.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.barra.pack(side="right", fill="y")
        self.interior.bind("<Configure>",
                           lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._win, width=e.width))
        self.canvas.bind("<MouseWheel>", self._rueda)
        self.interior.bind("<MouseWheel>", self._rueda)

    def _rueda(self, evento):
        delta = -1 if evento.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")


class Interruptor(tk.Canvas):
    """Boton deslizante ON/OFF (toggle switch)."""

    ANCHO, ALTO = 48, 26

    def __init__(self, master, variable, on_cambio=None):
        super().__init__(master, width=self.ANCHO, height=self.ALTO, bg=COLOR_PANEL,
                         highlightthickness=0, cursor="hand2")
        self.variable = variable
        self.on_cambio = on_cambio
        self.bind("<Button-1>", self._alternar)
        self._dibujar()

    def _alternar(self, _evento=None):
        self.variable.set(0 if self.variable.get() else 1)
        self._dibujar()
        if self.on_cambio:
            self.on_cambio(bool(self.variable.get()))

    def refrescar(self):
        self._dibujar()

    def _dibujar(self):
        self.delete("all")
        activo = bool(self.variable.get())
        color = COLOR_ACCENTO if activo else "#334155"
        a, h = 13, self.ALTO
        # rectangulo redondeado
        self.create_rectangle(a, 0, self.ANCHO - a, h, fill=color, outline="")
        self.create_oval(0, 0, 2 * a, h, fill=color, outline="")
        self.create_oval(self.ANCHO - 2 * a, 0, self.ANCHO, h, fill=color, outline="")
        # perilla
        kx = (self.ANCHO - 24) if activo else 2
        self.create_oval(kx, 3, kx + 20, h - 3, fill="#ffffff", outline="")


class Burbuja(tk.Canvas):
    """Icono (i) que al pasar el raton muestra una burbuja con el significado.

    Click izquierdo fija la burbuja (para leerla con calma); otro click la
    cierra. Se destruye sola si muere el widget que la contiene.
    """

    def __init__(self, master, texto, ancho=340, bg=None, **kw):
        super().__init__(master, width=17, height=17, bg=bg or COLOR_PANEL,
                         highlightthickness=0, cursor="question_arrow", **kw)
        self.texto = texto or ""
        self.ancho = ancho
        self._ventana = None
        self._fijada = False
        self.create_oval(1, 1, 16, 16, outline=COLOR_ACCENTO, width=1)
        self.create_text(8.5, 9, text="i", fill=COLOR_ACCENTO,
                         font=("Segoe UI", 9, "bold"))
        self.bind("<Enter>", self._al_entrar)
        self.bind("<Leave>", self._al_salir)
        self.bind("<Button-1>", self._al_pulsar)
        self.bind("<Destroy>", self._al_destruir)

    # ---------------------------------------------------------- eventos
    def _al_entrar(self, _evento=None):
        if not self._fijada:
            self.mostrar()

    def _al_salir(self, _evento=None):
        if not self._fijada:
            self.ocultar()

    def _al_pulsar(self, _evento=None):
        self._fijada = not self._fijada
        self.mostrar() if self._fijada else self.ocultar()

    def _al_destruir(self, evento):
        if evento.widget is self:
            self._fijada = False
            self.ocultar()

    # ---------------------------------------------------------- burbuja
    def mostrar(self):
        if self._ventana is not None or not self.texto:
            return
        try:
            top = tk.Toplevel(self)
            top.overrideredirect(True)
            top.attributes("-topmost", True)
            marco = tk.Frame(top, bg=COLOR_BORDE)
            marco.pack(fill="both", expand=True, padx=1, pady=1)
            tk.Label(marco, text=self.texto, bg=COLOR_PANEL_2, fg=COLOR_TEXTO,
                     font=("Segoe UI", 9), justify="left", anchor="w",
                     wraplength=self.ancho).pack(fill="both", expand=True,
                                                 padx=10, pady=8)
            top.update_idletasks()
            x = self.winfo_rootx() - 6
            y = self.winfo_rooty() + self.winfo_height() + 7
            ancho_px, alto_px = top.winfo_reqwidth(), top.winfo_reqheight()
            max_x = self.winfo_screenwidth() - ancho_px - 6
            max_y = self.winfo_screenheight() - alto_px - 6
            x = max(6, min(x, max_x))
            if y > max_y:  # no cabe abajo: se coloca arriba del icono
                y = max(6, self.winfo_rooty() - alto_px - 7)
            top.geometry(f"+{x}+{y}")
            self._ventana = top
        except Exception:
            self._ventana = None

    def ocultar(self):
        top, self._ventana = self._ventana, None
        if top is not None:
            try:
                top.destroy()
            except Exception:
                pass


# ==========================================================================
#  panel base
# ==========================================================================
class Panel:
    clave = ""
    titulo = ""
    descripcion = ""

    def __init__(self, app, contenedor):
        self.app = app
        self._contenedor = contenedor
        self.frame = tk.Frame(contenedor, bg=COLOR_FONDO)
        self._construido = False

    # ---------------------------------------------------------------- vistas
    def mostrar(self):
        if not self._construido:
            self.construir()
            self._construido = True
        self.frame.pack(fill="both", expand=True)
        self.al_mostrar()

    def ocultar(self):
        self.frame.pack_forget()

    def _cabecera(self, parent):
        c = tk.Frame(parent, bg=COLOR_FONDO)
        c.pack(fill="x", pady=(0, 12))
        tk.Label(c, text=self.titulo, bg=COLOR_FONDO, fg=COLOR_TEXTO,
                 font=("Segoe UI", 17, "bold"), anchor="w").pack(anchor="w")
        if self.descripcion:
            tk.Label(c, text=self.descripcion, bg=COLOR_FONDO, fg=COLOR_SUBTEXTO,
                     font=("Segoe UI", 10), anchor="w").pack(anchor="w")
        return c

    def construir(self):
        raise NotImplementedError

    def al_mostrar(self):
        pass


# ==========================================================================
#  INICIO
# ==========================================================================
class PanelInicio(Panel):
    clave = "inicio"
    titulo = "Inicio"
    descripcion = "Estado general del sistema de respaldos."

    def construir(self):
        self._cabecera(self.frame)
        fila = tk.Frame(self.frame, bg=COLOR_FONDO)
        fila.pack(fill="both", expand=True)

        # --- izquierda: anillo + boton
        izq = tk.Frame(fila, bg=COLOR_FONDO)
        izq.pack(side="left", fill="y", padx=(0, 28))
        self.arco = tk.Canvas(izq, bg=COLOR_FONDO, width=ANCHO_ARCO, height=ANCHO_ARCO,
                              highlightthickness=0)
        self.arco.pack(pady=(4, 10))
        self.boton = boton(izq, "INICIAR RESPALDO", self._al_pulsar, primario=True)
        self.boton.pack(fill="x")
        self.boton_cancelar = boton(izq, "CANCELAR", self._cancelar, primario=False)
        self.boton_cancelar.pack(fill="x", pady=(8, 0))
        self.boton_cancelar.pack_forget()

        # --- derecha: fichas de informacion
        der = tk.Frame(fila, bg=COLOR_FONDO)
        der.pack(side="left", fill="both", expand=True)

        self.ficha_estado = self._ficha(der, "ESTADO")
        self.lbl_estado = self._valor(self.ficha_estado, "Listo para respaldar.")
        self.lbl_detalle = self._valor(self.ficha_estado, "", COLOR_LOG_INFO, tam=9)

        self.ficha_destino = self._ficha(der, "DESTINO DE RESPALDOS")
        self.lbl_destino = self._valor(self.ficha_destino, "", COLOR_LOG_INFO, tam=9)

        self.ficha_ultima = self._ficha(der, "ULTIMO RESPALDO")
        self.lbl_ultima = self._valor(self.ficha_ultima, "Sin registros.", COLOR_LOG_INFO, tam=9)

        self.ficha_pausa = self._ficha(der, "RESPALDOS INTERRUMPIDOS")
        self.lbl_pausa = self._valor(self.ficha_pausa, "Ninguno.", COLOR_LOG_INFO, tam=9)

        self._dibujar_arco(0.0)

    def _ficha(self, parent, titulo):
        f = tarjeta(parent, pady=6)
        tk.Label(f, text=titulo, bg=COLOR_PANEL, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=12, pady=(8, 0))
        return f

    def _valor(self, parent, texto, color=None, tam=10):
        l = tk.Label(parent, text=texto, bg=COLOR_PANEL, fg=color or COLOR_TEXTO,
                     font=("Segoe UI", tam), anchor="w", justify="left")
        l.pack(fill="x", padx=12, pady=(2, 8))
        return l

    # ------------------------------------------------------------- progreso
    def _dibujar_arco(self, frac):
        c = self.arco
        c.delete("all")
        x0, y0 = MARGEN_ARCO, MARGEN_ARCO
        x1, y1 = ANCHO_ARCO - MARGEN_ARCO, ANCHO_ARCO - MARGEN_ARCO
        c.create_oval(x0, y0, x1, y1, outline=COLOR_BORDE, width=2)
        f = max(0.0, min(1.0, frac))
        color = COLOR_ARCO_OK if f >= 1 else COLOR_ARCO
        c.create_arc(x0, y0, x1, y1, start=270, extent=f * 360, style="arc",
                     outline=color, width=10)
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2 - 6, text=f"{int(f * 100)}%",
                      fill=COLOR_TEXTO, font=("Segoe UI", 26, "bold"))
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2 + 26, text="completado",
                      fill=COLOR_SUBTEXTO, font=("Segoe UI", 9))

    def actualizar(self, frac, estado, detalle, ocupado):
        self._dibujar_arco(frac)
        self.lbl_estado.config(text=detalle or estado)
        # las fichas leen disco: se refrescan como maximo una vez por segundo
        ahora = time.monotonic()
        if ahora - getattr(self, "_fichas_en", 0.0) >= 1.0:
            self._fichas_en = ahora
            try:
                self.lbl_destino.config(text=self.app.config.ruta_base_respaldos)
                ultima = self.app.leer_ultima_ruta()
                self.lbl_ultima.config(text=ultima or "Sin registros.")
                n = len(self.app.gestor.pausados())
                self.lbl_pausa.config(text="Ninguno." if not n else
                                      f"{n} respaldo(s) reanudables.")
            except Exception:
                pass
        self.boton.config(state=tk.DISABLED if ocupado else tk.NORMAL,
                          text="RESPALDO EN CURSO..." if ocupado else self._texto_boton(estado))
        if ocupado:
            self.boton_cancelar.pack(fill="x", pady=(8, 0))
        else:
            self.boton_cancelar.pack_forget()

    def _texto_boton(self, estado):
        if estado == "pausado":
            return "REANUDAR ULTIMO"
        if estado == "ok":
            return "NUEVO RESPALDO"
        if estado in ("error", "warn"):
            return "REINTENTAR"
        return "INICIAR RESPALDO"

    def _al_pulsar(self):
        self.app.iniciar_respaldo_general()

    def _cancelar(self):
        self.app.cancelar_respaldo()


# ==========================================================================
#  FUENTES DE RESPALDO (general, extensiones, disco externo, xampp, movil)
# ==========================================================================
class PanelFuente(Panel):
    def __init__(self, app, contenedor, clave, titulo, descripcion, fuente):
        super().__init__(app, contenedor)
        self.clave = clave
        self.titulo = titulo
        self.descripcion = descripcion
        self.fuente = fuente
        self._opciones = []
        self._detectando = False

    def construir(self):
        self._cabecera(self.frame)
        cuerpo = tk.Frame(self.frame, bg=COLOR_FONDO)
        cuerpo.pack(fill="both", expand=True)

        # --- selector de opciones
        if self.fuente.requiere_seleccion:
            caja = tarjeta(cuerpo, pady=(0, 10))
            tk.Label(caja, text="OPCIONES DISPONIBLES", bg=COLOR_PANEL, fg=COLOR_SUBTEXTO,
                     font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=12,
                                                                    pady=(8, 0))
            controles = tk.Frame(caja, bg=COLOR_PANEL)
            controles.pack(fill="x", padx=12, pady=(4, 4))
            self.lbl_detect = tk.Label(controles, text="Detectando...", bg=COLOR_PANEL,
                                       fg=COLOR_LOG_INFO, font=("Segoe UI", 9))
            self.lbl_detect.pack(side="left")
            self.btn_todos = boton(controles, "Todos", self._marcar_todos, primario=False)
            self.btn_todos.pack(side="right", padx=(6, 0))
            self.btn_ninguno = boton(controles, "Ninguno", self._marcar_ninguno, primario=False)
            self.btn_ninguno.pack(side="right")

            lista = tk.Frame(caja, bg=COLOR_PANEL)
            lista.pack(fill="both", expand=True, padx=12, pady=(0, 12))
            self.lista = tk.Listbox(lista, bg=COLOR_PANEL_2, fg=COLOR_TEXTO,
                                    selectbackground=COLOR_ACCENTO, selectforeground="#ffffff",
                                    highlightthickness=0, height=8, font=("Segoe UI", 9),
                                    selectmode=tk.EXTENDED if self.fuente.multiple else tk.BROWSE)
            scroll = tk.Scrollbar(lista, orient="vertical", command=self.lista.yview)
            self.lista.configure(yscrollcommand=scroll.set)
            self.lista.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            if not self.fuente.multiple:
                self.btn_todos.config(state=tk.DISABLED)
                self.btn_ninguno.config(state=tk.DISABLED)
        else:
            caja = tarjeta(cuerpo, pady=(0, 10))
            tk.Label(caja,
                     text="Se respaldaran todos los archivos de las extensiones configuradas "
                          "en el escaner del programa.",
                     bg=COLOR_PANEL, fg=COLOR_LOG_INFO, font=("Segoe UI", 9),
                     anchor="w", justify="left", wraplength=700).pack(
                fill="x", padx=14, pady=12)

        # --- destino
        dest = tarjeta(cuerpo, pady=(0, 10))
        tk.Label(dest, text="CARPETA DESTINO", bg=COLOR_PANEL, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=12,
                                                                pady=(8, 0))
        fila = tk.Frame(dest, bg=COLOR_PANEL)
        fila.pack(fill="x", padx=12, pady=(4, 12))
        self.entry_destino = tk.Entry(fila, bg=COLOR_PANEL_2, fg=COLOR_TEXTO, insertbackground=COLOR_TEXTO,
                                      relief="flat", font=("Segoe UI", 9))
        self.entry_destino.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry_destino.insert(0, self.app.config.ruta_base_respaldos)
        boton(fila, "Examinar...", self._examinar, primario=False).pack(side="right", padx=(8, 0))

        # --- accion
        acciones_f = tk.Frame(self.frame, bg=COLOR_FONDO)
        acciones_f.pack(fill="x", pady=(4, 0))
        self.btn_iniciar = boton(acciones_f, "INICIAR RESPALDO", self._iniciar, primario=True)
        self.btn_iniciar.pack(side="left")

    # ------------------------------------------------------------- acciones
    def al_mostrar(self):
        if self.fuente.requiere_seleccion and not self._opciones and not self._detectando:
            self._detectar()

    def _detectar(self):
        self._detectando = True
        if hasattr(self, "lbl_detect"):
            self.lbl_detect.config(text="Detectando...", fg=COLOR_LOG_INFO)
        self.app.ejecutar_trabajo(f"detectar::{self.clave}", self._worker_detectar)

    def _worker_detectar(self):
        try:
            opciones = self.fuente.detectar()
            error = None
        except Exception as e:
            opciones, error = [], str(e)
        self.app.programar(lambda: self._fin_detectar(opciones, error))

    def _fin_detectar(self, opciones, error):
        self._detectando = False
        self._opciones = opciones
        if not hasattr(self, "lista"):
            return
        self.lista.delete(0, tk.END)
        if error:
            self.lbl_detect.config(text=f"Error al detectar: {error}", fg=COLOR_LOG_ERROR)
            return
        if not opciones:
            self.lbl_detect.config(text=self.fuente.sin_opciones, fg=COLOR_LOG_WARN)
            return
        self.lbl_detect.config(text=f"{len(opciones)} opcion(es) encontradas.",
                               fg=COLOR_LOG_OK)
        for o in opciones:
            self.lista.insert(tk.END, o.texto)
        if self.fuente.multiple:
            self.lista.select_set(0, tk.END)

    def _marcar_todos(self):
        self.lista.select_set(0, tk.END)

    def _marcar_ninguno(self):
        self.lista.selection_clear(0, tk.END)

    def _examinar(self):
        ruta = filedialog.askdirectory(title="Selecciona la carpeta destino",
                                       initialdir=self.entry_destino.get() or "")
        if ruta:
            self.entry_destino.delete(0, tk.END)
            self.entry_destino.insert(0, ruta)

    def _iniciar(self):
        if self.app.ocupado():
            self.app.log("Ya hay un trabajo en curso; esperalo o cancelalo.", "warn")
            return
        seleccion = []
        if self.fuente.requiere_seleccion:
            if not self._opciones:
                self.app.log("Todavia no hay opciones detectadas.", "warn")
                return
            indices = self.lista.curselection()
            if not indices:
                self.app.log("Selecciona al menos una opcion.", "warn")
                return
            seleccion = [self._opciones[i] for i in indices]
        destino = self.entry_destino.get().strip() or self.app.config.ruta_base_respaldos
        self.app.iniciar_fuente(self.fuente, seleccion, destino, origen=self.titulo)


# ==========================================================================
#  REANUDAR
# ==========================================================================
class PanelReanudar(Panel):
    clave = "reanudar"
    titulo = "Reanudar respaldo"
    descripcion = "Continua un respaldo que quedo interrumpido sin perder lo copiado."

    def construir(self):
        self._cabecera(self.frame)
        caja = tarjeta(self.frame)
        tk.Label(caja, text="RESPALDOS INTERRUMPIDOS", bg=COLOR_PANEL, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=12,
                                                                pady=(8, 0))
        self.lbl_vacio = tk.Label(caja, text="Cargando...", bg=COLOR_PANEL,
                                  fg=COLOR_LOG_INFO, font=("Segoe UI", 10), anchor="w")
        self.lbl_vacio.pack(fill="x", padx=14, pady=6)
        cont = tk.Frame(caja, bg=COLOR_PANEL)
        cont.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.lista = tk.Listbox(cont, bg=COLOR_PANEL_2, fg=COLOR_TEXTO,
                                selectbackground=COLOR_ACCENTO, selectforeground="#ffffff",
                                highlightthickness=0, height=10, font=("Segoe UI", 9))
        scroll = tk.Scrollbar(cont, orient="vertical", command=self.lista.yview)
        self.lista.configure(yscrollcommand=scroll.set)
        self.lista.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        fila = tk.Frame(self.frame, bg=COLOR_FONDO)
        fila.pack(fill="x", pady=(12, 0))
        boton(fila, "REANUDAR SELECCIONADO", self._reanudar, primario=True).pack(side="left")
        boton(fila, "Actualizar", self.al_mostrar, primario=False).pack(side="left", padx=(10, 0))

    def al_mostrar(self):
        self.app.programar(self._refrescar)

    def _refrescar(self):
        self._items = acciones.listar_pausados(self.app.gestor)
        self.lista.delete(0, tk.END)
        for it in self._items:
            self.lista.insert(tk.END, acciones.detalle_pausado(it))
        if self._items:
            self.lbl_vacio.config(text=f"{len(self._items)} respaldo(s) esperando.",
                                  fg=COLOR_LOG_OK)
            self.lista.selection_set(0)
        else:
            self.lbl_vacio.config(text="No hay respaldos interrumpidos.", fg=COLOR_LOG_INFO)

    def _reanudar(self):
        if self.app.ocupado():
            self.app.log("Ya hay un trabajo en curso.", "warn")
            return
        sel = self.lista.curselection()
        if not sel or not getattr(self, "_items", None):
            self.app.log("Selecciona un respaldo para reanudar.", "warn")
            return
        self.app.iniciar_reanudar(self._items[sel[0]]["estado"])


# ==========================================================================
#  MODO RED
# ==========================================================================
class PanelRed(Panel):
    clave = "red"
    titulo = "Modo red interna"
    descripcion = "Envia o recibe respaldos entre equipos de tu red (TLS + HMAC + PIN)."

    def construir(self):
        self._cabecera(self.frame)
        fila = tk.Frame(self.frame, bg=COLOR_FONDO)
        fila.pack(fill="both", expand=True)

        self._tarjeta_opcion(
            fila, "SERVIDOR",
            "Escanea tus carpetas de usuario y espera a que un cliente se autentique "
            "para enviarselas cifradas.",
            "INICIAR SERVIDOR", lambda: self.app.iniciar_red("servidor"))
        self._tarjeta_opcion(
            fila, "CLIENTE",
            "Conecta a un servidor de tu red y descarga el respaldo que este tiene "
            "listo para ti.",
            "CONECTAR COMO CLIENTE", lambda: self.app.iniciar_red("cliente"))

        nota = tk.Frame(self.frame, bg=COLOR_FONDO)
        nota.pack(fill="x", pady=(16, 0))
        tk.Label(nota,
                 text="La clave de red, la IP y las confirmaciones se piden en ventanas "
                      "emergentes durante la operacion.",
                 bg=COLOR_FONDO, fg=COLOR_SUBTEXTO, font=("Segoe UI", 9),
                 anchor="w", justify="left").pack(anchor="w")

    def _tarjeta_opcion(self, parent, titulo, texto, accion_texto, accion):
        c = tk.Frame(parent, bg=COLOR_PANEL, highlightbackground=COLOR_BORDE,
                     highlightthickness=1)
        c.pack(side="left", fill="both", expand=True, padx=(0, 12))
        tk.Label(c, text=titulo, bg=COLOR_PANEL, fg=COLOR_ACCENTO, font=("Segoe UI", 13, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(18, 6))
        tk.Label(c, text=texto, bg=COLOR_PANEL, fg=COLOR_LOG_INFO, font=("Segoe UI", 10),
                 anchor="w", justify="left", wraplength=380).pack(fill="x", padx=18)
        boton(c, accion_texto, accion, primario=True).pack(anchor="w", padx=18, pady=(18, 20))


# ==========================================================================
#  ELIMINAR
# ==========================================================================
class PanelEliminar(Panel):
    clave = "eliminar"
    titulo = "Eliminar respaldo"
    descripcion = "Borra respaldos que genero el propio programa (los ajenos no se tocan)."

    def construir(self):
        self._cabecera(self.frame)
        caja = tarjeta(self.frame)
        tk.Label(caja, text="RESPALDOS GENERADOS", bg=COLOR_PANEL, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=12,
                                                                pady=(8, 0))
        self.lbl_vacio = tk.Label(caja, text="Cargando...", bg=COLOR_PANEL,
                                  fg=COLOR_LOG_INFO, font=("Segoe UI", 10), anchor="w")
        self.lbl_vacio.pack(fill="x", padx=14, pady=6)
        cont = tk.Frame(caja, bg=COLOR_PANEL)
        cont.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.lista = tk.Listbox(cont, bg=COLOR_PANEL_2, fg=COLOR_TEXTO,
                                selectbackground="#ef4444", selectforeground="#ffffff",
                                highlightthickness=0, height=10, font=("Segoe UI", 9))
        scroll = tk.Scrollbar(cont, orient="vertical", command=self.lista.yview)
        self.lista.configure(yscrollcommand=scroll.set)
        self.lista.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        fila = tk.Frame(self.frame, bg=COLOR_FONDO)
        fila.pack(fill="x", pady=(12, 0))
        self.btn_eliminar = boton(fila, "ELIMINAR SELECCIONADO", self._eliminar, primario=False)
        self.btn_eliminar.pack(side="left")
        boton(fila, "Actualizar", self.al_mostrar, primario=False).pack(side="left",
                                                                       padx=(10, 0))

    def al_mostrar(self):
        self.app.programar(self._refrescar)

    def _refrescar(self):
        self._items, error = acciones.listar_respaldos(self.app.config)
        self.lista.delete(0, tk.END)
        for nombre, _ruta, tam in self._items:
            self.lista.insert(tk.END, f"{nombre}   ({utilidades.formatear_bytes(tam)})")
        if error and not self._items:
            self.lbl_vacio.config(text=error, fg=COLOR_LOG_WARN)
        elif self._items:
            self.lbl_vacio.config(text=f"{len(self._items)} respaldo(s) disponibles.",
                                  fg=COLOR_LOG_OK)
            self.lista.selection_set(0)
        else:
            self.lbl_vacio.config(text="No hay respaldos.", fg=COLOR_LOG_INFO)

    def _eliminar(self):
        sel = self.lista.curselection()
        if not sel or not getattr(self, "_items", None):
            self.app.log("Selecciona un respaldo para eliminar.", "warn")
            return
        nombre, ruta, _tam = self._items[sel[0]]
        from tkinter import messagebox
        if not messagebox.askyesno("Confirmar eliminacion",
                                   f"Se borrara permanentemente:\n\n{nombre}\n\n"
                                   "Esta accion no se puede deshacer.",
                                   parent=self.app.root):
            return
        try:
            acciones.eliminar_respaldo(nombre, ruta)
        except OSError as e:
            self.app.log(f"No se pudo eliminar: {e}", "error")
            return
        self.app.log(f"Eliminado: {nombre}", "ok")
        self._refrescar()


# ==========================================================================
#  REGISTROS
# ==========================================================================
class PanelRegistros(Panel):
    clave = "registros"
    titulo = "Registros de respaldos"
    descripcion = "Historial de respaldos guardados en rutas_respaldo.txt."

    def construir(self):
        self._cabecera(self.frame)
        caja = tarjeta(self.frame)
        top = tk.Frame(caja, bg=COLOR_PANEL)
        top.pack(fill="x", padx=12, pady=(10, 6))
        self.lbl_total = tk.Label(top, text="", bg=COLOR_PANEL, fg=COLOR_LOG_INFO,
                                  font=("Segoe UI", 9), anchor="w")
        self.lbl_total.pack(side="left")
        boton(top, "Actualizar", self.al_mostrar, primario=False).pack(side="right")

        cont = tk.Frame(caja, bg=COLOR_PANEL)
        cont.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.texto = tk.Text(cont, bg=COLOR_PANEL_2, fg=COLOR_TEXTO, relief="flat",
                             font=("Consolas", 9), wrap="none", height=14,
                             state=tk.DISABLED)
        scroll_y = tk.Scrollbar(cont, orient="vertical", command=self.texto.yview)
        scroll_x = tk.Scrollbar(cont, orient="horizontal", command=self.texto.xview)
        self.texto.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.texto.pack(side="left", fill="both", expand=True)
        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x")

    def al_mostrar(self):
        self.app.programar(self._refrescar)

    def _refrescar(self):
        total, lineas = acciones.leer_registros()
        self.lbl_total.config(text="Sin registros." if not total else
                              f"Total: {total} registro(s)")
        self.texto.config(state=tk.NORMAL)
        self.texto.delete("1.0", tk.END)
        if not lineas:
            self.texto.insert(tk.END, "No hay registros de respaldos.")
        else:
            for i, linea in enumerate(reversed(lineas[-40:]), 1):
                self.texto.insert(tk.END, f"{i:>3}. {acciones.resumen_registro(linea)}\n")
        self.texto.config(state=tk.DISABLED)


# ==========================================================================
#  CONFIGURACION
# ==========================================================================
INTERRUPTORES = [
    ("comprimir_automatico", "Compresion automatica"),
    ("registrar_rutas", "Registrar rutas en .txt"),
    ("mostrar_progreso", "Barra de progreso en terminal"),
    ("guardar_estado_respaldos", "Guardar estado de respaldos"),
    ("auto_ajustar_hilos", "Ajuste automatico de hilos"),
    ("red_usar_tls", "TLS en modo red"),
    ("verificar_hash_al_reanudar", "Verificar SHA-256 al reanudar"),
    ("proteger_respaldos", "Proteger respaldos (solo tu usuario)"),
]

CAMPOS_TEXTO = [
    ("ruta_base_respaldos", "Ruta base de respaldos", True),
    ("red_clave", "Clave de red (HMAC)", False),
    ("red_bind_ip", "IP de bind del servidor", False),
    ("adb_path", "Ruta de adb", False),
]

# Significado de cada control, tal como se explica en el menu de terminal.
NUCLEOS = os.cpu_count() or "?"
AYUDAS = {
    "comprimir_automatico": (
        "Al terminar un respaldo lo guarda comprimido en un solo archivo .zip "
        "para que ocupe menos espacio. Desactivalo si prefieres la carpeta tal cual."),
    "registrar_rutas": (
        "Anota la fecha, el tipo y el destino de cada respaldo en el archivo "
        "rutas_respaldo.txt, para que siempre tengas el historial a la mano."),
    "mostrar_progreso": (
        "Muestra la barra de progreso en la terminal mientras corre un respaldo."),
    "guardar_estado_respaldos": (
        "Guarda el avance de cada respaldo para poder reanudarlo mas adelante "
        "si se interrumpe (corte de luz, error o cierre inesperado)."),
    "auto_ajustar_hilos": (
        "Calcula solo cuantos hilos usar segun los nucleos de tu CPU. Si lo "
        "activas, el control manual de hilos queda bloqueado."),
    "red_usar_tls": (
        "Cifra la conexion del modo red con TLS. Recomendado activado: sin TLS "
        "los datos viajan sin cifrar por la red."),
    "verificar_hash_al_reanudar": (
        "Al reanudar un respaldo interrumpido verifica con SHA-256 que lo "
        "copiado antes no este danado antes de seguir."),
    "proteger_respaldos": (
        "Restringe los permisos de los respaldos para que solo tu usuario pueda "
        "leerlos (carpeta 0700, archivos 0600)."),
    "hilos": (
        f"Cuantos archivos se copian al mismo tiempo. Mas hilos = mas rapido, "
        f"pero gasta mas CPU y memoria. Recomendado: entre 4 y {NUCLEOS} "
        "(tu CPU tiene ese numero de nucleos)."),
    "auto": (
        "Deja que el programa elija los hilos ideales segun tu CPU. "
        "Es lo mas sencillo y lo recomendado."),
    "nivel": (
        "Que tan comprime los respaldos: 0 = sin compresion (lo mas rapido), "
        "6 = equilibrio (recomendado), 9 = compresion maxima (el archivo queda "
        "mas chico pero tarda mas)."),
    "ruta_base_respaldos": (
        "Carpeta donde se guardan todos los respaldos. Puedes escribir la ruta "
        "a mano o elegirla con 'Examinar'."),
    "red_clave": (
        "Contraseña que usan los equipos para autenticarse entre si en el modo "
        f"red (HMAC). Minimo {constantes.RED_CLAVE_MIN} caracteres; se guarda "
        "enmascarada y nunca se muestra completa por defecto."),
    "red_bind_ip": (
        "Direccion IP en la que escucha el servidor de red. Dejala vacia para "
        "que el programa te la pregunte cada vez."),
    "adb_path": (
        "Ruta al programa 'adb' (Android Debug Bridge) que se usa para los "
        "respaldos moviles. Ejemplo: C:\\platform-tools\\adb.exe"),
}


class PanelConfig(Panel):
    clave = "config"
    titulo = "Configuracion"
    descripcion = "Ajustes del programa. Los cambios se guardan solos."

    def construir(self):
        self._cabecera(self.frame)
        self.scroll = MarcoScroll(self.frame)
        self.scroll.pack(fill="both", expand=True)
        cont = self.scroll.interior

        # --- interruptores
        caja = tarjeta(cont, pady=(0, 10))
        tk.Label(caja, text="OPCIONES ACTIVADAS / DESACTIVADAS", bg=COLOR_PANEL,
                 fg=COLOR_SUBTEXTO, font=("Segoe UI", 8, "bold"), anchor="w").pack(
            fill="x", padx=14, pady=(10, 4))
        self._vars_bool = {}
        for campo, texto in INTERRUPTORES:
            self._fila_interruptor(caja, campo, texto)

        # --- hilos
        caja2 = tarjeta(cont, pady=(0, 10))
        cab_h = tk.Frame(caja2, bg=COLOR_PANEL)
        cab_h.pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(cab_h, text="HILOS PARALELOS", bg=COLOR_PANEL, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
        Burbuja(cab_h, AYUDAS["hilos"]).pack(side="left", padx=(7, 0))
        tk.Label(caja2,
                 text="Cuantos archivos se copian al mismo tiempo.",
                 bg=COLOR_PANEL, fg=COLOR_LOG_INFO, font=("Segoe UI", 9), anchor="w").pack(
            fill="x", padx=14)
        fila_h = tk.Frame(caja2, bg=COLOR_PANEL)
        fila_h.pack(fill="x", padx=14, pady=(6, 4))
        self.var_hilos = tk.IntVar(value=self.app.config.max_archivos_paralelos)
        self.scale_hilos = tk.Scale(fila_h, from_=1, to=64, orient="horizontal",
                                    variable=self.var_hilos, length=320, showvalue=True,
                                    bg=COLOR_PANEL, fg=COLOR_TEXTO, highlightthickness=0,
                                    troughcolor=COLOR_PANEL_2, activebackground=COLOR_ACCENTO,
                                    font=("Segoe UI", 9), command=self._cambio_hilos)
        self.scale_hilos.pack(side="left")
        self.var_auto = tk.IntVar(value=1 if self.app.config.auto_ajustar_hilos else 0)
        tk.Checkbutton(fila_h, text="Auto (recomendado)", variable=self.var_auto,
                       bg=COLOR_PANEL, fg=COLOR_TEXTO, selectcolor=COLOR_PANEL_2,
                       activebackground=COLOR_PANEL, activeforeground=COLOR_TEXTO,
                       font=("Segoe UI", 9), command=self._cambio_auto).pack(
            side="left", padx=(16, 0))
        Burbuja(fila_h, AYUDAS["auto"]).pack(side="left", padx=(7, 0))
        self.lbl_cpus = tk.Label(caja2, text=f"Tu CPU: {os.cpu_count() or '?'} nucleos",
                                 bg=COLOR_PANEL, fg=COLOR_SUBTEXTO, font=("Segoe UI", 9),
                                 anchor="w")
        self.lbl_cpus.pack(fill="x", padx=14, pady=(0, 10))

        # --- nivel de compresion
        caja3 = tarjeta(cont, pady=(0, 10))
        cab_n = tk.Frame(caja3, bg=COLOR_PANEL)
        cab_n.pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(cab_n, text="NIVEL DE COMPRESION (0-9)", bg=COLOR_PANEL, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
        Burbuja(cab_n, AYUDAS["nivel"]).pack(side="left", padx=(7, 0))
        self.lbl_nivel_txt = tk.Label(caja3, text="", bg=COLOR_PANEL, fg=COLOR_LOG_INFO,
                                      font=("Segoe UI", 9), anchor="w")
        self.lbl_nivel_txt.pack(fill="x", padx=14)
        fila_n = tk.Frame(caja3, bg=COLOR_PANEL)
        fila_n.pack(fill="x", padx=14, pady=(6, 10))
        self.var_nivel = tk.IntVar(value=self.app.config.nivel_compresion)
        tk.Scale(fila_n, from_=0, to=9, orient="horizontal", variable=self.var_nivel,
                 length=320, showvalue=True, bg=COLOR_PANEL, fg=COLOR_TEXTO,
                 highlightthickness=0, troughcolor=COLOR_PANEL_2,
                 activebackground=COLOR_ACCENTO, font=("Segoe UI", 9),
                 command=self._cambio_nivel).pack(side="left")
        self._actualizar_texto_nivel()

        # --- campos de texto
        caja4 = tarjeta(cont, pady=(0, 10))
        tk.Label(caja4, text="RUTAS Y CLAVES", bg=COLOR_PANEL, fg=COLOR_SUBTEXTO,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=14,
                                                                pady=(10, 4))
        self._vars_texto = {}
        for campo, texto, con_examinar in CAMPOS_TEXTO:
            self._fila_texto(caja4, campo, texto, con_examinar)

        # --- pie
        pie = tk.Frame(cont, bg=COLOR_FONDO)
        pie.pack(fill="x", pady=(4, 16))
        boton(pie, "GUARDAR TODO", self._guardar, primario=True).pack(side="left")
        boton(pie, "Restaurar valores por defecto", self._restaurar,
              primario=False).pack(side="left", padx=(10, 0))

    # --------------------------------------------------------------- filas
    def _fila_interruptor(self, parent, campo, texto):
        f = tk.Frame(parent, bg=COLOR_PANEL)
        f.pack(fill="x", padx=14, pady=3)
        tk.Label(f, text=texto, bg=COLOR_PANEL, fg=COLOR_TEXTO, font=("Segoe UI", 10),
                 anchor="w").pack(side="left")
        Burbuja(f, AYUDAS.get(campo, "")).pack(side="left", padx=(7, 0))
        var = tk.IntVar(value=1 if getattr(self.app.config, campo) else 0)
        self._vars_bool[campo] = var
        lbl = tk.Label(f, text="", bg=COLOR_PANEL, fg=COLOR_LOG_INFO,
                       font=("Segoe UI", 9, "bold"), width=11, anchor="e")
        lbl.pack(side="right")
        sw = Interruptor(f, var, on_cambio=lambda v, c=campo: self._cambio_bool(c, v))
        sw.pack(side="right", padx=(0, 10))
        lbl.config(text="ACTIVADO" if var.get() else "DESACTIVADO")
        setattr(self, f"lbl_{campo}", lbl)

    def _fila_texto(self, parent, campo, texto, con_examinar):
        f = tk.Frame(parent, bg=COLOR_PANEL)
        f.pack(fill="x", padx=14, pady=5)
        cab = tk.Frame(f, bg=COLOR_PANEL)
        cab.pack(fill="x")
        tk.Label(cab, text=texto, bg=COLOR_PANEL, fg=COLOR_TEXTO, font=("Segoe UI", 10),
                 anchor="w").pack(side="left")
        Burbuja(cab, AYUDAS.get(campo, "")).pack(side="left", padx=(7, 0))
        fila = tk.Frame(f, bg=COLOR_PANEL)
        fila.pack(fill="x", pady=(3, 0))
        e = tk.Entry(fila, bg=COLOR_PANEL_2, fg=COLOR_TEXTO, insertbackground=COLOR_TEXTO,
                     relief="flat", font=("Segoe UI", 9))
        e.insert(0, getattr(self.app.config, campo) or "")
        e.pack(side="left", fill="x", expand=True, ipady=5)
        e.bind("<FocusOut>", lambda ev, c=campo, ent=e: self._guardar_campo(c, ent.get()))
        e.bind("<Return>", lambda ev, c=campo, ent=e: self._guardar_campo(c, ent.get()))
        if con_examinar:
            boton(fila, "Examinar...", lambda ent=e: self._examinar(ent),
                  primario=False).pack(side="right", padx=(8, 0))
        self._vars_texto[campo] = e

    def _examinar(self, entry):
        ruta = filedialog.askdirectory(title="Selecciona la carpeta base",
                                       initialdir=entry.get() or "")
        if ruta:
            entry.delete(0, tk.END)
            entry.insert(0, ruta)
            self._guardar_campo("ruta_base_respaldos", ruta)

    # ----------------------------------------------------------- cambios
    def _cambio_bool(self, campo, valor):
        setattr(self.app.config, campo, bool(valor))
        lbl = getattr(self, f"lbl_{campo}", None)
        if lbl:
            lbl.config(text="ACTIVADO" if valor else "DESACTIVADO")
        self._guardar()

    def _cambio_hilos(self, _valor):
        self.app.config.max_archivos_paralelos = max(1, min(64, int(self.var_hilos.get())))
        self._guardar()

    def _cambio_auto(self):
        self.app.config.auto_ajustar_hilos = bool(self.var_auto.get())
        self.scale_hilos.config(state=tk.DISABLED if self.var_auto.get() else tk.NORMAL)
        self._guardar()

    def _cambio_nivel(self, _valor):
        self.app.config.nivel_compresion = max(0, min(9, int(self.var_nivel.get())))
        self._actualizar_texto_nivel()
        self._guardar()

    def _actualizar_texto_nivel(self):
        n = int(self.var_nivel.get())
        if n == 0:
            txt = "0 = sin compresion (lo mas rapido)"
        elif n <= 3:
            txt = f"{n} = compresion ligera (rapido)"
        elif n <= 6:
            txt = f"{n} = equilibrio (recomendado)"
        elif n <= 8:
            txt = f"{n} = compresion fuerte (lento)"
        else:
            txt = "9 = compresion maxima (lo mas lento)"
        self.lbl_nivel_txt.config(text=txt)

    def _guardar_campo(self, campo, valor):
        valor = (valor or "").strip()
        if campo == "red_clave" and valor and len(valor) < constantes.RED_CLAVE_MIN:
            self.app.log(f"La clave de red debe tener al menos {constantes.RED_CLAVE_MIN} "
                         "caracteres.", "error")
            return
        actual = getattr(self.app.config, campo) or ""
        if valor == actual:
            return
        if campo == "ruta_base_respaldos" and valor:
            valor = utilidades.expandir_ruta(valor)
        setattr(self.app.config, campo, valor)
        self._guardar()

    def _guardar(self):
        try:
            self.app.config.guardar()
        except OSError as e:
            self.app.log(f"No se pudo guardar config.json ({e})", "error")

    def _restaurar(self):
        from tkinter import messagebox
        if not messagebox.askyesno("Restaurar valores",
                                   "Se restauran todos los ajustes a sus valores "
                                   "por defecto. ¿Continuar?",
                                   parent=self.app.root):
            return
        base = configuracion.Configuracion()
        for campo, _ in INTERRUPTORES:
            setattr(self.app.config, campo, getattr(base, campo))
        self.app.config.nivel_compresion = base.nivel_compresion
        self.app.config.max_archivos_paralelos = base.max_archivos_paralelos
        self.app.config.auto_ajustar_hilos = base.auto_ajustar_hilos
        self.app.config.adb_path = base.adb_path
        self.app.config.red_usar_tls = base.red_usar_tls
        self.app.config.verificar_hash_al_reanudar = base.verificar_hash_al_reanudar
        self.app.config.proteger_respaldos = base.proteger_respaldos
        self._guardar()
        self.app.log("Valores por defecto restaurados.", "ok")
        self._reconstruir()

    def _reconstruir(self):
        """Vuelve a dibujar el panel con los valores actuales de la config."""
        try:
            self.frame.destroy()
        except Exception:
            pass
        self.frame = tk.Frame(self._contenedor, bg=COLOR_FONDO)
        self._construido = False
        if self.app.panel_actual == self.clave:
            self.mostrar()
