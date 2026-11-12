# Prueba de Respaldos.Gio v6.2 (ver Pruebas/README.md)

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import os, sys, time, tempfile, tkinter as tk

from core import Configuracion, GestorEstados, MotorRespaldo
from fronts.hud import Aplicacion
from fronts.hud_paneles import AYUDAS, Burbuja

destino = tempfile.mkdtemp(prefix="fase2_destino_")
cfg = Configuracion()
cfg.ruta_base_respaldos = destino
gestor = GestorEstados()
motor_obj = MotorRespaldo(cfg, gestor)
app = Aplicacion(cfg, gestor, motor_obj)

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


# --- 1) el panel de config construye sus burbujas -----------------------
app.navegar("config")
pump(0.8)
panel = app.paneles["config"]

burbujas = []


def buscar_burbujas(widget):
    for hijo in widget.winfo_children():
        if isinstance(hijo, Burbuja):
            burbujas.append(hijo)
        buscar_burbujas(hijo)


buscar_burbujas(panel.frame)
comprobar(len(burbujas) >= 15, f"hay burbujas en config ({len(burbujas)} >= 15)")

# --- 2) cada control tiene su burbuja con texto ------------------------
vacias = [b for b in burbujas if not b.texto.strip()]
comprobar(not vacias, "ninguna burbuja esta vacia")

# los 8 interruptores
campos = [c for c, _ in __import__("fronts.hud_paneles", fromlist=["INTERRUPTORES"]).INTERRUPTORES]
sin_ayuda = [c for c in campos if c not in AYUDAS]
comprobar(not sin_ayuda, f"los 8 interruptores tienen ayuda ({sin_ayuda})")

# --- 3) la burbuja emerge al pasar el raton y se cierra ----------------
b0 = burbujas[0]
b0.mostrar()
pump(0.3)
comprobar(b0._ventana is not None, "la burbuja emerge")
if b0._ventana is not None:
    textos = []
    def recoger(w):
        for h in w.winfo_children():
            if isinstance(h, tk.Label):
                textos.append(h.cget("text"))
            recoger(h)
    recoger(b0._ventana)
    comprobar(any(len(t) > 40 for t in textos),
              f"la burbuja muestra la explicacion ({max((len(t) for t in textos), default=0)} chars)")
    # la ventana flota sin borde y arriba de todo
    comprobar(str(b0._ventana.attributes("-topmost")) in ("1", "True"),
              "la burbuja queda encima de la ventana")
b0.ocultar()
pump(0.3)
comprobar(b0._ventana is None, "la burbuja se cierra")

# --- 4) click fija la burbuja -----------------------------------------
b0._al_pulsar()
pump(0.3)
comprobar(b0._fijada and b0._ventana is not None, "el click fija la burbuja")
b0._al_pulsar()
pump(0.3)
comprobar(not b0._fijada and b0._ventana is None, "el segundo click la libera")

# --- 5) los controles siguen funcionando -------------------------------
antes = cfg.registrar_rutas
panel._cambio_bool("registrar_rutas", not antes)
pump(0.2)
comprobar(cfg.registrar_rutas != antes, "interruptor ON/OFF")
cfg.registrar_rutas = antes

panel.var_hilos.set(24)
panel._cambio_hilos(24)
pump(0.2)
comprobar(cfg.max_archivos_paralelos == 24, "slider de hilos (24)")

panel.var_nivel.set(3)
panel._cambio_nivel(3)
pump(0.2)
comprobar(cfg.nivel_compresion == 3, "slider de compresion (3)")
comprobar("ligera" in panel.lbl_nivel_txt.cget("text"),
          f"texto guia del nivel ({panel.lbl_nivel_txt.cget('text')})")

# el auto bloquea/desbloquea el slider de hilos
panel.var_auto.set(1)
panel._cambio_auto()
pump(0.2)
comprobar(panel.scale_hilos.cget("state") == tk.DISABLED, "auto bloquea el slider")
panel.var_auto.set(0)
panel._cambio_auto()
pump(0.2)
comprobar(panel.scale_hilos.cget("state") == tk.NORMAL, "manual desbloquea el slider")

# --- 6) los textos de ayuda estan en espanol neutro --------------------
malos = [k for k, v in AYUDAS.items() if len(v) < 30]
comprobar(not malos, f"todas las ayudas tienen texto ({malos})")

# --- 7) reconstruir el panel no deja burbujas huerfanas ---------------
panel._reconstruir()
pump(0.5)
burbujas2 = []
def buscar2(w):
    for h in w.winfo_children():
        if isinstance(h, Burbuja):
            burbujas2.append(h)
        buscar2(h)
buscar2(panel.frame)
comprobar(len(burbujas2) >= 15, f"tras reconstruir siguen ({len(burbujas2)} >= 15)")

app.cerrar()

print()
print("FALLOS:", len(fallos))
for f_ in fallos:
    print("  -", f_)
print("RESULTADO:", "TODOS OK" if not fallos else "HAY FALLOS")
sys.exit(0 if not fallos else 1)
