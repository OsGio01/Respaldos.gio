# -*- coding: utf-8 -*-
"""Prueba E2E del modo red: TLS + HMAC + PIN y transferencia de archivos.

Levanta un servidor y un cliente reales sobre el loopback y comprueba que:
  - los archivos llegan completos y con el mismo contenido,
  - un cliente con la clave equivocada no se puede autenticar,
  - la derivacion de la clave es la misma en servidor y cliente.

Uso:  python Pruebas\\test_red_e2e.py
"""
import hashlib
import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from core import configuracion, constantes, estados, motor, red, seguridad

fallos = []


def comprobar(condicion, mensaje):
    if condicion:
        print(f"OK   {mensaje}")
    else:
        print(f"FAIL {mensaje}")
        fallos.append(mensaje)


def _config(clave, usar_tls=True):
    cfg = configuracion.Configuracion()
    cfg.red_clave = clave
    cfg.red_usar_tls = usar_tls
    cfg.mostrar_progreso = False
    cfg.proteger_respaldos = False
    cfg.tamano_buffer_mb = 1
    return cfg


def _archivos_de_prueba(origen):
    """Crea archivos de prueba y devuelve la lista (ruta, relativo, tamano)."""
    os.makedirs(os.path.join(origen, "Datos", "sub"), exist_ok=True)
    archivos = []
    contenidos = {
        os.path.join("Datos", "a.txt"): "contenido de a",
        os.path.join("Datos", "sub", "b.bin"): "x" * 5000,
        os.path.join("Datos", "con espacio.txt"): "espacios",
    }
    for relativo, contenido in contenidos.items():
        ruta = os.path.join(origen, relativo)
        modo = "wb" if isinstance(contenido, bytes) else "w"
        with open(ruta, modo) as f:
            f.write(contenido)
        archivos.append((ruta, relativo.replace("\\", "/"), os.path.getsize(ruta)))
    return archivos


def _huella_del_cert(base):
    """SHA-256 del DER del certificado (lo mismo que calcula _huella_cert)."""
    with open(os.path.join(base, "servidor_red.crt"), encoding="utf-8") as f:
        pem = f.read()
    der = ssl.PEM_cert_to_DER_cert(pem)
    return hashlib.sha256(der).hexdigest()


def _servidor_en_hilo(puerto_ready, archivos, cfg, clave, tls_ctx, error_servidor):
    """Servidor: espera una conexion, la autentica y envia los archivos."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(20)
    puerto_ready.append(srv.getsockname()[1])
    try:
        crudo, _ = srv.accept()
        conn = red._autenticar_candidato(crudo, tls_ctx, clave)
        red._enviar_archivos(conn, archivos, cfg)
        conn.close()
    except Exception as e:  # el servidor puede fallar en la prueba del cliente malo
        error_servidor.append(e)
    finally:
        try:
            srv.close()
        except OSError:
            pass


def _prueba_transferencia():
    print("== Transferencia completa (TLS + HMAC + PIN) ==")
    base = tempfile.mkdtemp(prefix="gio_red_")
    certs = os.path.join(base, "certs")
    origen = os.path.join(base, "origen")
    destino = os.path.join(base, "destino")
    os.makedirs(certs, exist_ok=True)
    os.makedirs(destino, exist_ok=True)

    clave_txt = "clave_secreta_de_red_1234"
    cfg = _config(clave_txt)
    clave = seguridad._clave_red_bytes(cfg)

    tls_ctx = seguridad._intentar_tls_servidor(certs)
    usar_tls = tls_ctx is not None
    if not usar_tls:
        print("     (sin 'cryptography': la prueba va sin TLS)")
    cfg.red_usar_tls = usar_tls

    archivos = _archivos_de_prueba(origen)

    # el pin se guarda antes para que no pida confirmacion por consola
    pin = os.path.join(base, "servidores_conocidos.json")
    if usar_tls:
        with open(pin, "w", encoding="utf-8") as f:
            f.write('{"127.0.0.1": "%s"}' % _huella_del_cert(certs))

    puerto_ready = []
    error_servidor = []
    hilo = threading.Thread(target=_servidor_en_hilo,
                             args=(puerto_ready, archivos, cfg, clave, tls_ctx, error_servidor),
                             daemon=True)
    hilo.start()
    for _ in range(50):
        if puerto_ready:
            break
        time.sleep(0.1)
    comprobar(bool(puerto_ready), "el servidor levanto en un puerto libre")
    if not puerto_ready:
        shutil.rmtree(base, ignore_errors=True)
        return

    gestor = estados.GestorEstados()
    motor_obj = motor.MotorRespaldo(cfg, gestor)
    sock = red._conectar_cliente("127.0.0.1", puerto_ready[0], cfg, clave, pin)
    carpeta, recibidos, tam_total, errores = red._recibir_archivos(
        sock, destino, motor_obj, cfg, "127.0.0.1")
    sock.close()
    hilo.join(20)

    comprobar(recibidos == len(archivos),
              f"se recibieron {recibidos} de {len(archivos)} archivos")
    comprobar(not errores, f"sin errores al guardar ({errores})")
    comprobar(bool(carpeta), "el motor entrego la carpeta del respaldo")

    # al finalizar, el motor comprime la carpeta: se revisa el zip o la carpeta
    import zipfile
    zip_path = (carpeta or "") + ".zip"
    contenido = {}
    if carpeta and os.path.isdir(carpeta):
        for raiz, _dirs, archivos in os.walk(carpeta):
            for nombre in archivos:
                completa = os.path.join(raiz, nombre)
                rel = os.path.relpath(completa, carpeta).replace("\\", "/")
                with open(completa, "rb") as f:
                    contenido[rel] = f.read()
        comprobar(True, "la carpeta del respaldo existe con los archivos")
    elif os.path.isfile(zip_path):
        with zipfile.ZipFile(zip_path) as zf:
            for nombre in zf.namelist():
                contenido[nombre.replace("\\", "/")] = zf.read(nombre)
        comprobar(True, "el respaldo quedo comprimido en .zip con los archivos")
    else:
        comprobar(False, "no se encontro la carpeta ni el zip del respaldo")

    esperado = b"contenido de a"
    comprobar(contenido.get("Datos/a.txt") == esperado, "el archivo de texto llego integro")
    comprobar(contenido.get("Datos/sub/b.bin") == b"x" * 5000, "el archivo binario llego integro")
    comprobar("Datos/con espacio.txt" in contenido, "llego el archivo con espacios en el nombre")

    shutil.rmtree(base, ignore_errors=True)


def _prueba_clave_mala():
    print("== Cliente con clave incorrecta ==")
    base = tempfile.mkdtemp(prefix="gio_red_mala_")
    certs = os.path.join(base, "certs")
    origen = os.path.join(base, "origen")
    os.makedirs(certs, exist_ok=True)

    cfg = _config("clave_correcta_del_servidor_1")
    clave = seguridad._clave_red_bytes(cfg)
    tls_ctx = seguridad._intentar_tls_servidor(certs)
    usar_tls = tls_ctx is not None
    cfg.red_usar_tls = usar_tls

    archivos = _archivos_de_prueba(origen)
    puerto_ready = []
    error_servidor = []
    hilo = threading.Thread(target=_servidor_en_hilo,
                             args=(puerto_ready, archivos, cfg, clave, tls_ctx, error_servidor),
                             daemon=True)
    hilo.start()
    for _ in range(50):
        if puerto_ready:
            break
        time.sleep(0.1)
    if not puerto_ready:
        comprobar(False, "el servidor levanto en un puerto libre")
        shutil.rmtree(base, ignore_errors=True)
        return

    pin = os.path.join(base, "servidores_conocidos.json")
    if usar_tls:
        with open(pin, "w", encoding="utf-8") as f:
            f.write('{"127.0.0.1": "%s"}' % _huella_del_cert(certs))

    clave_mala = seguridad._clave_red_desde_texto("clave_equivocada_9999")
    rechazado = False
    try:
        sock = red._conectar_cliente("127.0.0.1", puerto_ready[0], cfg, clave_mala, pin)
        sock.close()
    except ConnectionError:
        rechazado = True
    except OSError:
        rechazado = True
    comprobar(rechazado, "el servidor rechazo al cliente con clave incorrecta")
    hilo.join(20)
    shutil.rmtree(base, ignore_errors=True)


def _prueba_derivacion():
    print("== Derivacion de la clave ==")
    texto = "la_misma_frase_1234"
    clave = seguridad._clave_red_desde_texto(texto)
    comprobar(len(clave) == 32, "la clave derivada mide 32 bytes")
    comprobar(clave == seguridad._clave_red_desde_texto(texto), "es determinista")

    class Cfg:
        red_clave = texto
    comprobar(clave == seguridad._clave_red_bytes(Cfg),
              "servidor y cliente derivan la MISMA clave (PBKDF2)")


def main():
    _prueba_derivacion()
    _prueba_transferencia()
    _prueba_clave_mala()
    print()
    if fallos:
        print(f"FALLOS: {len(fallos)}")
        for f in fallos:
            print("  -", f)
        return 1
    print("RESULTADO: TODOS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
