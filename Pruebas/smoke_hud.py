# Prueba de Respaldos.Gio v6.0 (ver Pruebas/README.md)

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from core import Configuracion, GestorEstados, MotorRespaldo
from fronts.hud import FronteHUD

cfg = Configuracion()
g = GestorEstados()
m = MotorRespaldo(cfg, g)
f = FronteHUD(cfg, g, m)
print("HUD INSTANCIA OK")
f.cerrar()
