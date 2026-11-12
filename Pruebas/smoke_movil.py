# Prueba de Respaldos.Gio v6.1 (ver Pruebas/README.md)

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from core import Configuracion, GestorEstados, MotorRespaldo
from fronts.movil import FronteMovil

cfg = Configuracion()
g = GestorEstados()
m = MotorRespaldo(cfg, g)
f = FronteMovil(cfg, g, m)
f.log("Hola desde el front movil.", "ok")
f.log("Trabajo en progreso", "info")
f.set_estado("ejecutando", "Respaldos moviles")
print("ESTADO:", f.estado_actual())
print("LINEAS:", f.lineas())
f.set_estado("ok", "Listo")
print("ESTADO2:", f.estado_actual())
print("MOVIL SMOKE OK")
