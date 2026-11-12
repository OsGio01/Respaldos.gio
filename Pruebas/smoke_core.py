# Prueba de Respaldos.Gio v6.1 (ver Pruebas/README.md)

import os
import sys

# Raiz del proyecto: este archivo vive en <raiz>/Pruebas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import os, json, tempfile
from core import Configuracion, GestorEstados, MotorRespaldo, seguridad, progreso, fuentes, persistencia, utilidades, escaneo, constantes, red, motor, estados, configuracion
from core import progreso as progreso_mod
from core.fuentes import Plan, Opcion, Fuente, FuenteExtensiones, flujo_respaldo, pedir_seleccion, pedir_destino

TMP = r"C:\Users\Oscar\AppData\Local\Temp\respaldos_test"
os.makedirs(TMP, exist_ok=True)

cfg = Configuracion()
cfg.ruta_base_respaldos = TMP
cfg.nivel_compresion = 4
cfg.max_archivos_paralelos = 5
cfg.guardar(os.path.join(TMP, "test_cfg.json"))
cfg2 = Configuracion.cargar(os.path.join(TMP, "test_cfg.json"))
assert cfg2.nivel_compresion == 4, cfg2
assert cfg2.max_archivos_paralelos == 5
assert cfg2.ruta_base_respaldos == TMP
print("CONFIG OK")

c3 = Configuracion()
c3.red_clave = "abc"
c3.guardar(os.path.join(TMP, "test_cfg2.json"))
c3b = Configuracion.cargar(os.path.join(TMP, "test_cfg2.json"))
assert c3b.red_clave == "", c3b.red_clave
print("CONFIG VALIDACION OK")

g = GestorEstados(os.path.join(TMP, "test_estados.json"))
e = g.crear_estado(os.path.join(TMP, "origen"), os.path.join(TMP, "destino"), "general", 3, 100)
assert e.activo
g.pausar(e.id)
assert not g.estados[e.id].activo
g.reanudar(e.id)
assert g.estados[e.id].activo
g.completar(e.id)
assert e.id not in g.estados
print("ESTADOS OK")

assert seguridad.rel_es_segura("a/b.txt")
assert not seguridad.rel_es_segura("../escape.txt")
assert not seguridad.rel_es_segura("/abs.txt")
assert not seguridad.rel_es_segura("C:/x.txt")
print("SEGURIDAD OK")

p = progreso_mod.Progreso(2, 2000, "Test", silencioso=True)
p.sumar_bytes(1000)
p.archivo_listo()
p.mostrar(forzar=True)
p.cerrar()
print("PROGRESO OK")

opts = [Opcion("uno", "C:/uno"), Opcion("dos", "C:/dos")]
assert len(opts) == 2
assert callable(pedir_seleccion) and callable(pedir_destino)
print("FUENTES OK")

m = MotorRespaldo(cfg, GestorEstados(os.path.join(TMP, "test_estados2.json")))
meta = motor.generar_metadatos_respaldo(os.path.join(TMP, "o"), os.path.join(TMP, "d"), "general", 1, 10, 1.5, "completado", cfg, {"usuario": "u", "equipo": "e", "sistema": "s", "arquitectura": "x", "cpu_logico": 2, "cpu_fisico": None, "cpu_uso": 1.0, "memoria_total": 1, "memoria_disponible": 1}, {"errores": [{"archivo": "a", "motivo": "b"}]})
from core import constantes
assert meta["version_programa"] == constantes.VERSION_PROGRAMA
print("METADATA OK")

assert callable(red.servidor_red) and callable(red.cliente_red) and callable(red.modo_red)
assert callable(seguridad._intentar_tls_servidor) and callable(seguridad._handshake_servidor) and callable(seguridad._handshake_cliente)
print("RED OK")

print("TODO OK")
