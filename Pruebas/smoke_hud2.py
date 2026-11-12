# Prueba de Respaldos.Gio v6.2 (ver Pruebas/README.md)

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
f.log("Respaldo completado: 3 copiados.", "ok")
f.log("Error: algo", "error")
f.log("Listo", "info")
f._set_estado("ejecutando", "Respaldo de 2 carpeta(s) / 10 archivos.")
f._refrescar()
f._set_estado("ok", "Respaldo completado: 3 copiados, 1 duplicados, 0 errores.")
f._refrescar()
f._set_estado("idle", "Listo para respaldar.")
f._refrescar()
f._set_estado("error", "Fallo")
f._refrescar()
f.cerrar()
print("HUD SMOKE OK")
