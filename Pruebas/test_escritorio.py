# Prueba de Respaldos.Gio v6.2 (ver Pruebas/README.md)

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import os, sys, time, shutil, tempfile

from core import Configuracion, GestorEstados, MotorRespaldo, fuentes, escaneo
from core.fuentes import Fuente, Opcion, Plan
from fronts.hud import Aplicacion

# --- fuentes de prueba chicas -------------------------------------------
raiz = tempfile.mkdtemp(prefix="hud_fuente_")
for i in range(4):
    with open(os.path.join(raiz, f"archivo{i}.txt"), "w", encoding="utf-8") as f:
        f.write("hola" * 500)

destino = tempfile.mkdtemp(prefix="hud_destino_")


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
        return Plan(self.tipo, o.ruta, archivos, f"{len(seleccion)} carpetas", escaner.omitidas)


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


# --- 1) navegar todos los paneles ---------------------------------------
paneles = ["inicio", "general", "extensiones", "disco_externo", "xampp", "movil",
           "reanudar", "red", "eliminar", "registros", "config"]
for p in paneles:
    app.navegar(p)
    pump(0.6)
    comprobar(app.panel_actual == p and app.paneles[p]._construido,
              f"panel {p} se construye y se muestra")

# --- 2) deteccion en los paneles de fuente ------------------------------
pump(2.0)
general = app.paneles["general"]
comprobar(len(general._opciones) > 0,
          f"deteccion general ({len(general._opciones)} carpetas)")

# --- 3) respaldo real desde el panel ------------------------------------
app.navegar("general")
pump(0.3)
fuente = FuentePrueba()
seleccion = fuente.detectar()
app.log("Prueba de respaldo iniciada.", "accion")
app._arrancar(lambda: app._worker_fuente(fuente, seleccion, destino, "Prueba"),
              "Iniciando prueba...")
pump(0.2)
# el respaldo es diminuto: puede terminar antes de la comprobacion
if app.ocupado():
    print("OK   el hilo de respaldo esta vivo")
else:
    print("OK   el respaldo termino rapido (4 archivos)")

espera = time.time() + 60
while app.ocupado() and time.time() < espera:
    app.root.update()
    time.sleep(0.03)
pump(1.0)

estado = app.estado_actual()
print("ESTADO FINAL:", estado)
comprobar(estado["estado"] == "ok", f"estado final ok ({estado['estado']})")
archivos = sum(len(fs) for _raiz, _dirs, fs in os.walk(destino))
zips = [f for _r, _d, fs in os.walk(destino) for f in fs if f.lower().endswith(".zip")]
comprobar(archivos >= 4 or zips,
          f"se copiaron los archivos (directos={archivos}, zips={len(zips)})")
comprobar(any("completado" in m.lower() for m, _ in app.lineas()),
          "el registro muestra el cierre")

# --- 4) panel de inicio: anillo y boton ---------------------------------
app.navegar("inicio")
pump(0.5)
panel_inicio = app.paneles["inicio"]
comprobar(panel_inicio.arco.winfo_exists(), "el anillo de progreso existe")
comprobar(panel_inicio.boton.cget("text") in ("INICIAR RESPALDO", "NUEVO RESPALDO"),
          f"boton contextual ({panel_inicio.boton.cget('text')})")

# --- 5) panel config: interruptor y niveles -----------------------------
app.navegar("config")
pump(0.6)
panel_cfg = app.paneles["config"]
antes = cfg.registrar_rutas
panel_cfg._cambio_bool("registrar_rutas", not antes)
pump(0.3)
comprobar(cfg.registrar_rutas != antes, "interruptor cambia el valor")
cfg.registrar_rutas = antes

panel_cfg.var_nivel.set(9)
panel_cfg._cambio_nivel(9)
pump(0.2)
comprobar(cfg.nivel_compresion == 9, "nivel de compresion 9")
panel_cfg.var_nivel.set(6)
panel_cfg._cambio_nivel(6)

panel_cfg.var_hilos.set(12)
panel_cfg._cambio_hilos(12)
pump(0.2)
comprobar(cfg.max_archivos_paralelos == 12, "hilos 12")

# --- 6) panel eliminar / registros --------------------------------------
app.navegar("eliminar")
pump(1.0)
app.navegar("registros")
pump(0.8)
comprobar(app.paneles["registros"].texto.winfo_exists(), "panel registros OK")

# --- 7) pedir desde hilo (dialogo) --------------------------------------
# se sustituye el dialogo real para que la prueba no espere un clic humano
app._pedir_dialogo = lambda mensaje, ocultar=False: "RESPUESTA"
resultado = {}
def en_otro_hilo():
    resultado["v"] = app._pedir("prueba de peticion")
import threading
t = threading.Thread(target=en_otro_hilo, daemon=True)
t.start()
pump(1.5)
t.join(timeout=5)
comprobar(resultado.get("v") == "RESPUESTA", "la peticion desde hilo no se cuelga")

app.cerrar()

print()
print("FALLOS:", len(fallos))
for f_ in fallos:
    print("  -", f_)
print("RESULTADO:", "TODOS OK" if not fallos else "HAY FALLOS")
