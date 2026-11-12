# -*- coding: utf-8 -*-
"""Suite de pruebas de seguridad y rendimiento de Respaldos.Gio (v6.1).

Portada del core OOP (antes apuntaba a Respaldos5.0.py). Valida:
  - verificar_hash_al_reanudar default == False
  - ausencia de MD5 en el codigo activo
  - _ruta_segura bloquea traversal y bytes nulos
  - _enmascarar no revela la clave completa
  - _clave_red_bytes determinista y de 32 bytes (PBKDF2)
  - handshake HMAC: clave correcta acepta, incorrecta rechaza
  - motivo_corto clasifica errores
  - constantes de protocolo correctas
  - tamano_buffer_mb se usa en el buffer de red
  - la clave de red NO viaja en el config.json (vive en un archivo protegido)
  - la clave de red respeta el minimo de longitud (SEG-03)

Uso:  python Pruebas\\tests_seguridad_rendimiento.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from core import configuracion, constantes, seguridad

Configuracion = configuracion.Configuracion
_ruta_segura = seguridad._ruta_segura
_enmascarar = seguridad._enmascarar
_clave_red_bytes = seguridad._clave_red_bytes
_handshake_servidor = seguridad._handshake_servidor
_handshake_cliente = seguridad._handshake_cliente
_restringir_permisos = seguridad._restringir_permisos
motivo_corto = seguridad.motivo_corto
MAGIA_RED = constantes.MAGIA_RED
ENC_TOTAL = constantes.ENC_TOTAL
ENC_ARCHIVO = constantes.ENC_ARCHIVO
NETWORK_PORT = constantes.NETWORK_PORT


class TestSeguridad(unittest.TestCase):
    """Pruebas de seguridad del nucleo v6.1."""

    def test_verificar_hash_al_reanudar_default_false(self):
        """Default False para evitar I/O duplicado en respaldos grandes."""
        cfg = Configuracion()
        self.assertFalse(cfg.verificar_hash_al_reanudar, "default debe ser False")

    def test_ruta_segura_ruta_valida(self):
        with tempfile.TemporaryDirectory() as d:
            destino = _ruta_segura(d, "subcarpeta/archivo.txt")
            self.assertIsNotNone(destino)
            base = os.path.realpath(d)
            self.assertTrue(destino == base or destino.startswith(base + os.sep))

    def test_ruta_segura_traversal_rechazado(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(_ruta_segura(d, "../../etc/passwd"))
            self.assertIsNone(_ruta_segura(d, ".." + os.sep + ".." + os.sep + "etc" + os.sep + "passwd"))

    def test_ruta_segura_byte_nulo_rechazado(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(_ruta_segura(d, "archivo\x00.txt"))

    def test_enmascarar_no_revela_clave_completa(self):
        clave = "miClaveSecreta1234567890"
        enm = _enmascarar(clave)
        self.assertNotIn(clave, enm, "la clave completa no debe aparecer enmascarada")
        self.assertTrue(enm.endswith(clave[-4:]), "debe mostrar los ultimos 4 caracteres")
        self.assertEqual(_enmascarar(""), "ninguna", "clave vacia debe mostrar 'ninguna'")

    def test_clave_red_bytes_determinista_y_longitud(self):
        class Cfg:
            red_clave = "clave_de_prueba_1234567890"
        k1 = _clave_red_bytes(Cfg)
        k2 = _clave_red_bytes(Cfg)
        self.assertEqual(len(k1), 32, "PBKDF2 debe producir 32 bytes")
        self.assertEqual(k1, k2, "debe ser determinista para la misma clave")

    def _par_sockets(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        return srv, port

    def test_handshake_clave_correcta_aceptada(self):
        srv, port = self._par_sockets()
        cfg_ok = type("Cfg", (), {"red_clave": "clave_red_handshake_ok_12345"})()
        clave = _clave_red_bytes(cfg_ok)
        resultado = {}

        def servidor():
            conn = None
            try:
                conn, _ = srv.accept()
                conn.settimeout(5)
                _handshake_servidor(conn, clave)
                resultado["servidor"] = "ok"
            except Exception as e:
                resultado["servidor"] = "fail:" + type(e).__name__
            finally:
                try:
                    if conn:
                        conn.close()
                    srv.close()
                except OSError:
                    pass

        hilo = threading.Thread(target=servidor, daemon=True)
        hilo.start()
        time.sleep(0.25)
        cli = socket.create_connection(("127.0.0.1", port), timeout=5)
        cli.settimeout(5)
        try:
            _handshake_cliente(cli, clave)
            resultado["cliente"] = "ok"
        except Exception as e:
            resultado["cliente"] = "fail:" + type(e).__name__
        finally:
            try:
                cli.close()
            except OSError:
                pass
        hilo.join(10)
        self.assertEqual(resultado.get("servidor"), "ok")
        self.assertEqual(resultado.get("cliente"), "ok")

    def test_handshake_clave_incorrecta_rechazada(self):
        srv, port = self._par_sockets()
        cfg_ok = type("Cfg", (), {"red_clave": "clave_red_handshake_ok_12345"})()
        cfg_mal = type("Cfg", (), {"red_clave": "clave_red_handshake_mal_xyz987"})()
        clave_ok = _clave_red_bytes(cfg_ok)
        clave_mal = _clave_red_bytes(cfg_mal)
        resultado = {}

        def servidor():
            conn = None
            try:
                conn, _ = srv.accept()
                conn.settimeout(5)
                _handshake_servidor(conn, clave_ok)
                resultado["servidor"] = "ok (deberia fallar)"
            except Exception as e:
                resultado["servidor"] = "rechazado:" + type(e).__name__
            finally:
                try:
                    if conn:
                        conn.close()
                    srv.close()
                except OSError:
                    pass

        hilo = threading.Thread(target=servidor, daemon=True)
        hilo.start()
        time.sleep(0.25)
        cli = socket.create_connection(("127.0.0.1", port), timeout=5)
        cli.settimeout(5)
        try:
            _handshake_cliente(cli, clave_mal)
            resultado["cliente"] = "aceptada (ERROR de seguridad)"
        except Exception as e:
            resultado["cliente"] = "rechazada:" + type(e).__name__
        finally:
            try:
                cli.close()
            except OSError:
                pass
        hilo.join(10)
        self.assertEqual(resultado.get("servidor"), "rechazado:ConnectionError")
        self.assertIn("rechazada", resultado.get("cliente", ""))

    def test_motivo_corto_clasifica_errores(self):
        self.assertEqual(motivo_corto(PermissionError("x")), "sin permisos")
        self.assertEqual(motivo_corto(FileNotFoundError("x")), "ya no existe")
        self.assertIsInstance(motivo_corto(OSError("fallo generico")), str)

    def test_constantes_protocolo_presentes(self):
        self.assertEqual(MAGIA_RED, b"RGIO1")
        self.assertEqual(ENC_TOTAL.size, 8)
        self.assertEqual(ENC_ARCHIVO.size, 10)
        self.assertEqual(NETWORK_PORT, 56789)


class TestClaveRed(unittest.TestCase):
    """La clave de red no debe viajar en el config.json (ese archivo se versiona)."""

    def test_guardar_saca_la_clave_del_json(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "config.json")
            cfg = Configuracion()
            cfg.red_clave = "clave_secreta_de_prueba_1234"
            cfg.guardar(ruta)
            with open(ruta, encoding="utf-8") as f:
                datos = json.load(f)
            self.assertEqual(datos.get("red_clave"), "", "la clave quedo en el config")
            protegida = seguridad.ruta_clave_red(ruta)
            self.assertTrue(os.path.exists(protegida), "no se creo el archivo protegido")
            with open(protegida, encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), "clave_secreta_de_prueba_1234")

    def test_cargar_recupera_la_clave_protegida(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "config.json")
            cfg = Configuracion()
            cfg.red_clave = "clave_secreta_de_prueba_1234"
            cfg.guardar(ruta)
            otra = Configuracion.cargar(ruta)
            self.assertEqual(otra.red_clave, "clave_secreta_de_prueba_1234")

    def test_limpiar_la_clave_borra_el_archivo(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "config.json")
            cfg = Configuracion()
            cfg.red_clave = "clave_secreta_de_prueba_1234"
            cfg.guardar(ruta)
            cfg.borrar_clave_red(ruta)
            protegida = seguridad.ruta_clave_red(ruta)
            self.assertFalse(os.path.exists(protegida), "el archivo protegido quedo con la clave")
            self.assertEqual(Configuracion.cargar(ruta).red_clave, "")

    def test_guardar_sin_clave_no_borra_la_guardada(self):
        """Un guardado que no lleva clave no debe borrar la que ya existe."""
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "config.json")
            cfg = Configuracion()
            cfg.red_clave = "clave_secreta_de_prueba_1234"
            cfg.guardar(ruta)
            otra = Configuracion()          # config nueva, sin clave
            otra.guardar(ruta)
            protegida = seguridad.ruta_clave_red(ruta)
            self.assertTrue(os.path.exists(protegida), "se borro la clave sin querer")
            self.assertEqual(Configuracion.cargar(ruta).red_clave, "clave_secreta_de_prueba_1234")

    def test_clave_corta_se_rechaza(self):
        """SEG-03: la clave de red necesita al menos RED_CLAVE_MIN caracteres."""
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "config.json")
            cfg = Configuracion()
            cfg.red_clave = "corta"
            cfg.guardar(ruta)
            protegida = seguridad.ruta_clave_red(ruta)
            self.assertFalse(os.path.exists(protegida), "se guardo una clave demasiado corta")
            self.assertEqual(Configuracion.cargar(ruta).red_clave, "")


class TestRendimiento(unittest.TestCase):
    """Pruebas de rendimiento del motor."""

    def test_no_md5_en_codigo_activo(self):
        activos = []
        for carpeta in ("core", "fronts"):
            for f in os.listdir(os.path.join(RAIZ, carpeta)):
                if f.endswith(".py"):
                    activos.append(os.path.join(RAIZ, carpeta, f))
        for f in ("Respaldos.py", "RespaldosTkinter.py", "RespaldosMovil.py", "main.py"):
            activos.append(os.path.join(RAIZ, f))
        self.assertTrue(activos, "no se encontro codigo activo que revisar")
        for p in activos:
            with open(p, encoding="utf-8") as f:
                contenido = f.read()
            self.assertNotIn("hashlib.md5(", contenido, "MD5 hallado en " + p)

    def test_tamano_buffer_mb_usado_en_red(self):
        p = os.path.join(RAIZ, "core", "red.py")
        with open(p, encoding="utf-8") as f:
            contenido = f.read()
        self.assertIn("tamano_buffer_mb", contenido)
        self.assertIn("bytearray(max(256 * 1024", contenido)

    def test_tamano_buffer_mb_usado_en_motor(self):
        p = os.path.join(RAIZ, "core", "motor.py")
        with open(p, encoding="utf-8") as f:
            contenido = f.read()
        self.assertIn("tamano_buffer_mb", contenido)


class TestPermisos(unittest.TestCase):
    """Los permisos no pueden depender de lanzar un proceso externo.

    Antes se usaba `icacls` en cada guardado: eso congelaba la interfaz del
    escritorio y del celular al mover un control. Ahora se aplica la ACL con
    la API de Windows directamente.
    """

    def test_restringir_permisos_no_lanza_subprocesos(self):
        original = seguridad.subprocess.run

        def prohibido(*args, **kwargs):
            raise AssertionError("se lanzo un subproceso: " + str(args))

        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "config.json")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write("{}")
            seguridad.subprocess.run = prohibido
            try:
                seguridad._restringir_permisos(ruta)
                seguridad._restringir_permisos(d, es_carpeta=True)
            finally:
                seguridad.subprocess.run = original

    def test_guardar_config_no_lanza_subprocesos(self):
        original = seguridad.subprocess.run

        def prohibido(*args, **kwargs):
            raise AssertionError("se lanzo un subproceso: " + str(args))

        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "config.json")
            seguridad.subprocess.run = prohibido
            try:
                cfg = Configuracion()
                for _ in range(20):
                    cfg.guardar(ruta)
            finally:
                seguridad.subprocess.run = original

    def test_el_archivo_sigue_legible(self):
        """Aplicar los permisos no puede dejar al usuario sin acceso."""
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "config.json")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write("hola")
            seguridad._restringir_permisos(ruta)
            with open(ruta, encoding="utf-8") as f:
                self.assertEqual(f.read(), "hola", "el archivo quedo ilegible")

    def test_guardar_config_es_rapido(self):
        """Guardar el config no debe tardar (se hace en cada cambio de la UI)."""
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "config.json")
            cfg = Configuracion()
            inicio = time.time()
            for _ in range(50):
                cfg.guardar(ruta)
            total = time.time() - inicio
            self.assertLess(total, 5.0,
                            f"50 guardados tardaron {total:.2f}s (deberia ser instantaneo)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
