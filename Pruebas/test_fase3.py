#!/usr/bin/env python3
# Prueba de Respaldos.Gio v6.2 (ver Pruebas/README.md)
"""Prueba Fase 3: front celular con menu hamburguesa (v6.2)."""

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import os
import sys
import time


from core import Configuracion, GestorEstados, MotorRespaldo, fuentes, escaneo
from core.fuentes import Fuente, Opcion, Plan
from fronts.movil import AplicacionMovil
from fronts.hud import NAVEGACION

import tempfile

# --- fuentes de prueba chicas --------------------------------------------
raiz = tempfile.mkdtemp(prefix="movil_fuente_")
for i in range(4):
    with open(os.path.join(raiz, f"archivo{i}.txt"), "w", encoding="utf-8") as f:
        f.write("hola" * 500)

destino = tempfile.mkdtemp(prefix="movil_destino_")


class FuentePrueba(Fuente):
    tipo = "general"
    titulo = "PRUEBA"
    emoji = ("", "[PRUEBA]")
    multiple = True

    def detectar(self):
        return [Opcion(os.path.basename(raiz), raiz)]

    def construir_plan(self, seleccion, escaner):
        archivos = []
        for o in seleccion:
            base = os.path.basename(o.ruta)
            for ruta, rel, size in escaner.recorrer(o.ruta):
                archivos.append((ruta, os.path.join(base, rel), size))
        return Plan(self.tipo, o.ruta, archivos,
                    f"{len(seleccion)} carpetas", escaner.omitidas)


cfg = Configuracion()
cfg.ruta_base_respaldos = destino
gestor = GestorEstados()
motor_obj = MotorRespaldo(cfg, gestor)
app = AplicacionMovil(cfg, gestor, motor_obj)

fallos = []


def pump(segundos):
    fin = time.time() + segundos
    while time.time() < fin:
        app.root.update()
        time.sleep(0.02)


def comprobar(cond, texto):
    print(("OK   " if cond else "FAIL ") + texto)
    if not cond:
        fallos.append(texto)


class _Toque:
    """Toque falso para probar el cierre por toque fuera del menu."""

    def __init__(self, widget, x, y):
        self.widget = widget
        self.x_root = x
        self.y_root = y


# --- 1) ventana celular ---------------------------------------------------
pump(0.5)
ancho = app.root.winfo_width()
alto = app.root.winfo_height()
comprobar(ancho == 420, f"ancho de la ventana = {ancho} (esperado 420)")
comprobar(alto == 760, f"alto de la ventana = {alto} (esperado 760)")
min_ancho = app.root.winfo_reqwidth() or 0
comprobar(app.root.winfo_geometry().split("x")[0] == "420",
          f"geometria {app.root.winfo_geometry()}")

# --- 2) boton hamburguesa abre/cierra el drawer --------------------------
comprobar(not app._menu_abierto, "el menu empieza cerrado")
app.btn_menu.event_generate("<Button-1>")
pump(0.3)
comprobar(app._menu_abierto, "el boton ☰ abre el menu")
comprobar(app.drawer.winfo_ismapped(), "el drawer se muestra (overlay)")
app.cerrar_menu()
pump(0.3)
comprobar(not app._menu_abierto and not app.drawer.winfo_ismapped(),
          "el cierre oculta el drawer")

# --- 3) toque fuera / dentro ---------------------------------------------
app.abrir_menu()
pump(0.2)
dx = app.drawer.winfo_rootx() + 5
dy = app.drawer.winfo_rooty() + 5
app._al_tocar_ventana(_Toque(app.root, dx, dy))
pump(0.2)
comprobar(app._menu_abierto, "tocar DENTRO del menu no lo cierra")
fuera_x = app.drawer.winfo_rootx() + app.drawer.winfo_width() + 40
app._al_tocar_ventana(_Toque(app.root, fuera_x, dy))
pump(0.2)
comprobar(not app._menu_abierto, "tocar FUERA del menu lo cierra")

# --- 4) el drawer tiene las 11 opciones -----------------------------------
claves = [c for c, _t in NAVEGACION if not c.startswith("_")]
etiquetas = {}
for lbl in app.drawer.winfo_children():
    pass


def etiquetas_drawer():
    encontradas = {}

    def buscar(w):
        for hijo in w.winfo_children():
            if hijo.winfo_class() == "Label":
                txt = str(hijo.cget("text"))
                for c, t in NAVEGACION:
                    if not c.startswith("_") and t == txt:
                        encontradas[c] = hijo
            buscar(hijo)

    buscar(app.drawer)
    return encontradas


etiquetas = etiquetas_drawer()
comprobar(len(etiquetas) == 11,
          f"el drawer lista las 11 opciones ({len(etiquetas)} encontradas)")

# --- 5) cada opcion navega desde el drawer y lo cierra --------------------
paneles = ["inicio", "general", "extensiones", "disco_externo", "xampp",
           "movil", "reanudar", "red", "eliminar", "registros", "config"]
for p in paneles:
    app.abrir_menu()
    pump(0.1)
    lbl = etiquetas.get(p)
    if lbl is None:
        comprobar(False, f"opcion {p} presente en el drawer")
        continue
    lbl.event_generate("<Button-1>")
    pump(0.6)
    comprobar(app.panel_actual == p, f"clic en {p} navega al panel")
    comprobar(not app._menu_abierto, f"navegar desde {p} cierra el menu")
    comprobar(app.paneles[p]._construido, f"panel {p} se construye")

# --- 6) ningun panel se desborda del ancho celular ------------------------
ANCHO_LIBRE = 396  # 420 - padx 12*2 del cuerpo
for clave in paneles:
    app.navegar(clave)
    pump(0.4)
    req = app.paneles[clave].frame.winfo_reqwidth()
    comprobar(req <= ANCHO_LIBRE,
              f"panel {clave} cabe ({req} <= {ANCHO_LIBRE} px)")

# --- 7) respaldo real desde el panel --------------------------------------
app.navegar("general")
pump(0.3)
fuente = FuentePrueba()
seleccion = fuente.detectar()
app.log("Prueba de respaldo iniciada.", "accion")
app._arrancar(lambda: app._worker_fuente(fuente, seleccion, destino, "Prueba"),
              "Iniciando prueba...")
espera = time.time() + 60
while app.ocupado() and time.time() < espera:
    app.root.update()
    time.sleep(0.03)
pump(1.0)
estado = app.estado_actual()
comprobar(estado["estado"] == "ok", f"respaldo real ok ({estado['estado']})")
archivos = sum(len(fs) for _raiz, _dirs, fs in os.walk(destino))
zips = [f for _r, _d, fs in os.walk(destino) for f in fs
        if f.lower().endswith(".zip")]
comprobar(archivos >= 4 or zips,
          f"archivos copiados (directos={archivos}, zips={len(zips)})")

# --- 8) panel config funcional --------------------------------------------
app.navegar("config")
pump(0.6)
panel_cfg = app.paneles["config"]
antes = cfg.registrar_rutas
panel_cfg._cambio_bool("registrar_rutas", not antes)
pump(0.3)
comprobar(cfg.registrar_rutas != antes, "interruptor de config cambia")
cfg.registrar_rutas = antes
panel_cfg.var_hilos.set(12)
panel_cfg._cambio_hilos(12)
pump(0.2)
comprobar(cfg.max_archivos_paralelos == 12, "slider de hilos funciona (12)")
panel_cfg.var_hilos.set(8)
panel_cfg._cambio_hilos(8)

# --- 9) cierre limpio ------------------------------------------------------
app._al_cerrar()
pump(0.3)
try:
    cerrada = not app.root.winfo_exists()
except Exception:
    cerrada = True
comprobar(cerrada, "la ventana cierra limpio")

print()
print("FALLOS:", len(fallos))
for f_ in fallos:
    print("  -", f_)
print("RESULTADO:", "TODOS OK" if not fallos else "HAY FALLOS")
sys.exit(1 if fallos else 0)
