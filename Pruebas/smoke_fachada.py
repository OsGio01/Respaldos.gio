# Prueba de Respaldos.Gio v6.2 (ver Pruebas/README.md)

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import Respaldos
import RespaldosTkinter
print("FACHADA IMPORT OK")
