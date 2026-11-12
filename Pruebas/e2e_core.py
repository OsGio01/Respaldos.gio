# Prueba de Respaldos.Gio v6.0 (ver Pruebas/README.md)

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import os, tempfile
from core import Configuracion, GestorEstados, MotorRespaldo
from core.fuentes import Plan

base = tempfile.mkdtemp()
src = os.path.join(base, "src")
os.makedirs(src)
with open(os.path.join(src, "hola.txt"), "w") as f:
    f.write("hola mundo")
with open(os.path.join(src, "datos.bin"), "wb") as f:
    f.write(b"x" * 1000)
plan = Plan("general", src, [(os.path.join(src, "hola.txt"), "hola.txt", 9), (os.path.join(src, "datos.bin"), "datos.bin", 1000)], "test")
cfg = Configuracion()
cfg.ruta_base_respaldos = base
cfg.comprimir_automatico = False
cfg.guardar_estado_respaldos = False
cfg.registrar_rutas = False
m = MotorRespaldo(cfg, GestorEstados())
res = m.ejecutar(plan, base)
print("RESULT", res)
assert res is not None and res.copiados == 2 and len(res.errores) == 0
print("E2E OK")
