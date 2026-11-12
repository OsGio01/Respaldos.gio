#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modo red interna: servidor y cliente con TLS + HMAC + PIN (nucleo v6.2)."""
import os
import socket
import ssl
import time
from typing import Optional

from core import constantes, escaneo, fuentes, motor, progreso, seguridad, utilidades


# ==================================================================
#  Piezas del canal seguro (separadas para poder probarlas solas)
# ==================================================================
def _enviar_archivos(conn: socket.socket, archivos, config) -> None:
    """Envia la lista de archivos por un canal ya autenticado.

    archivos: lista de (ruta, nombre_relativo, tamano).
    """
    conn.settimeout(120)
    conn.sendall(constantes.ENC_TOTAL.pack(len(archivos)))
    prog = progreso.Progreso(len(archivos), sum(s for _, _, s in archivos), "Enviando",
                             silencioso=not config.mostrar_progreso)
    for ruta, rel, _ in archivos:
        try:
            f = open(ruta, "rb")
        except OSError:
            prog.archivo_listo()
            continue
        with f:
            real = os.fstat(f.fileno()).st_size
            nombre = rel.encode("utf-8")
            conn.sendall(constantes.ENC_ARCHIVO.pack(len(nombre), real) + nombre)
            if real:
                if conn.sendfile(f, count=real) != real:
                    raise ConnectionError(f"el archivo cambio mientras se enviaba: {rel}")
            prog.sumar_bytes(real)
        prog.archivo_listo()
        prog.mostrar()
    conn.sendall(constantes.ENC_ARCHIVO.pack(0, 0))
    prog.cerrar()


def _recibir_archivos(sock: socket.socket, destino, motor_obj, config, ip):
    """Recibe los archivos del canal autenticado y los guarda.

    Devuelve (carpeta, recibidos, bytes, errores).
    """
    carpeta = None
    recibidos = tam_total = 0
    errores_red = []
    inicio = time.time()
    try:
        total = constantes.ENC_TOTAL.unpack(
            seguridad._recibir_exacto(sock, constantes.ENC_TOTAL.size))[0]
        print(f"Recibiendo {total} archivos...")
        carpeta = motor.crear_carpeta_respaldo(destino, config.proteger_respaldos)
        prog = progreso.Progreso(total, 0, "Descargando",
                                  silencioso=not config.mostrar_progreso)
        buf = bytearray(max(256 * 1024, (config.tamano_buffer_mb or 8) * 1024 * 1024))
        vista = memoryview(buf)
        carpetas_ok = set()
        while True:
            largo, size = constantes.ENC_ARCHIVO.unpack(
                seguridad._recibir_exacto(sock, constantes.ENC_ARCHIVO.size))
            if largo == 0:
                break
            rel = seguridad._recibir_exacto(sock, largo).decode("utf-8", "replace")
            destino_archivo = seguridad._ruta_segura(carpeta, rel)
            guardado_ok = False
            f = None
            if destino_archivo:
                try:
                    d = os.path.dirname(destino_archivo)
                    if d not in carpetas_ok:
                        os.makedirs(d, exist_ok=True)
                        carpetas_ok.add(d)
                    f = open(destino_archivo, "wb")
                    guardado_ok = True
                except OSError as e:
                    errores_red.append((rel, seguridad.motivo_corto(e)))
                    f = None
                    guardado_ok = False
            else:
                errores_red.append((rel, "ruta no permitida (bloqueada)"))
            try:
                restante = size
                while restante:
                    n = sock.recv_into(vista[:min(len(buf), restante)])
                    if not n:
                        raise ConnectionError("el otro equipo cerro la conexion")
                    if f:
                        try:
                            f.write(vista[:n])
                        except OSError as e:
                            errores_red.append((rel, seguridad.motivo_corto(e)))
                            try:
                                f.close()
                            except OSError:
                                pass
                            f = None
                            guardado_ok = False
                    restante -= n
                    prog.sumar_bytes(n)
            finally:
                if f:
                    try:
                        f.close()
                    except OSError:
                        pass
            if guardado_ok:
                recibidos += 1
                tam_total += size
            prog.archivo_listo()
            prog.mostrar()
        prog.cerrar()
    finally:
        pass
    if errores_red:
        print(f"{utilidades.icono('⚠️ ', '[AVISO] ')}{len(errores_red)} archivo(s) del servidor NO se guardaron "
              f"(ruta no permitida o error de escritura); detalle en backup_info.json")
    motor_obj.finalizar(carpeta, "red_general", ip, recibidos, tam_total,
                        time.time() - inicio, errores_red, f"{recibidos} archivos")
    return carpeta, recibidos, tam_total, errores_red


def _conectar_cliente(ip: str, puerto: int, config, clave: bytes,
                       ruta_pin: str = None) -> socket.socket:
    """Conecta al servidor: TLS, verificacion de huella (TOFU) y handshake."""
    sock = socket.create_connection((ip, puerto),
                                    timeout=constantes.NETWORK_TIMEOUT_AUTH)
    if config.red_usar_tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        sock = ctx.wrap_socket(sock, server_hostname=ip)
    if config.red_usar_tls:
        huella = seguridad._huella_cert(sock)
        if not huella:
            sock.close()
            raise ConnectionError("no se pudo obtener el certificado del servidor")
        if not seguridad._verificar_pin(ip, huella, ruta_pin):
            sock.close()
            raise ConnectionError("conexion abortada por verificacion de identidad")
    sock.settimeout(120)
    sock.sendall(constantes.MAGIA_RED)
    seguridad._handshake_cliente(sock, clave)
    return sock


def _autenticar_candidato(crudo: socket.socket, tls_ctx, clave: bytes):
    """Aplica TLS y autentica un socket ya aceptado. Devuelve el socket."""
    crudo.settimeout(constantes.NETWORK_TIMEOUT_SERVIDOR_AUTH)
    candidata = tls_ctx.wrap_socket(crudo, server_side=True) if tls_ctx is not None else crudo
    if seguridad._recibir_exacto(candidata, len(constantes.MAGIA_RED)) != constantes.MAGIA_RED:
        raise ConnectionError("protocolo o version distintos")
    seguridad._handshake_servidor(candidata, clave)
    return candidata


def servidor_red(config) -> None:
    print(f"\n{utilidades.icono('🌐', '[RED]')} MODO SERVIDOR")
    escaner = escaneo.Escaner()
    archivos = []
    for c in escaneo.obtener_carpetas_usuario():
        print(f"{utilidades.icono('🔍', '[SCAN]')} Escaneando {c}...")
        base = os.path.basename(c)
        for ruta, rel, size in escaner.recorrer(c):
            archivos.append((ruta, base + "/" + rel.replace(os.sep, "/"), size))
    print(f"{len(archivos)} archivos listos para enviar.")

    clave = seguridad._clave_red_bytes(config)
    print(f"Clave de red configurada: {seguridad._enmascarar(config.red_clave)}")
    if utilidades.pedir("¿Mostrar la clave completa en pantalla para copiarla? (s/N): ").strip().lower() in ("s", "si", "sí", "y", "yes"):
        print(f"Clave de red (compártela con el cliente): {config.red_clave}")

    bind_ip = config.red_bind_ip or ""
    if not bind_ip:
        ip_local = seguridad._detectar_ip_local()
        sugerida = ip_local or "0.0.0.0"
        entrada = utilidades.pedir(f"IP a exponer [Enter = {sugerida}]: ").strip()
        bind_ip = entrada or sugerida
    if bind_ip == "0.0.0.0":
        resp = utilidades.pedir("Vas a exponer el servidor en TODAS las interfaces. ¿Continuar? (s/N): ").strip().lower()
        if resp not in ("s", "si", "sí", "y", "yes"):
            ip_local = seguridad._detectar_ip_local()
            if ip_local:
                print(f"Usando IP local: {ip_local}")
                bind_ip = ip_local
            else:
                print("Cancelado.")
                return

    if not config.red_usar_tls:
        print("AVISO: TLS está desactivado. Los archivos viajan SIN CIFRAR por la red.")
        if utilidades.pedir("¿Continuar sin TLS? (s/N): ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
            return

    tls_ctx = seguridad._intentar_tls_servidor() if config.red_usar_tls else None
    if config.red_usar_tls and tls_ctx is None:
        print("Aviso: TLS no disponible (falta 'cryptography' o fallo al generar cert).")
        print("El HMAC evita accesos no autorizados, pero el tráfico viaja en claro.")
        if utilidades.pedir("¿Continuar sin TLS? (s/N): ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
            return

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((bind_ip, constantes.NETWORK_PORT))
        srv.listen(8)
        srv.settimeout(5.0)
        print(f"Esperando cliente en {bind_ip}:{constantes.NETWORK_PORT}...")
        limite = time.monotonic() + constantes.NETWORK_ESPERA_SERVIDOR
        conn = None
        fallos_por_ip = {}
        while conn is None:
            if time.monotonic() > limite:
                print("Tiempo de espera agotado sin un cliente autenticado. Servidor cerrado.")
                return
            try:
                crudo, addr = srv.accept()
            except OSError:
                continue
            ip_origen = addr[0]
            try:
                conn = _autenticar_candidato(crudo, tls_ctx, clave)
            except (ssl.SSLError, ConnectionError, OSError) as e:
                fallos_por_ip[ip_origen] = fallos_por_ip.get(ip_origen, 0) + 1
                print(f"Conexion de {ip_origen} descartada ({type(e).__name__}); sigo esperando...")
                if fallos_por_ip[ip_origen] >= constantes.MAX_FALLOS_POR_IP:
                    print(f"IP {ip_origen} bloqueada tras {constantes.MAX_FALLOS_POR_IP} intentos fallidos.")
                try:
                    crudo.close()
                except OSError:
                    pass
        with conn:
            print(f"Cliente autenticado desde {addr[0]}")
            _enviar_archivos(conn, archivos, config)
    finally:
        srv.close()
    print(f"{utilidades.icono('✅', 'OK')} Transferencia completada.")


def cliente_red(config, motor_obj) -> None:
    ip = utilidades.pedir("IP del servidor: ").strip()
    if not ip:
        return
    clave_txt = utilidades.pedir(f"Clave de red (Enter = usar la guardada: {seguridad._enmascarar(config.red_clave)}): ").strip()
    if not clave_txt:
        clave_txt = config.red_clave
    if not clave_txt:
        print("Se requiere la clave de red para autenticarse.")
        return
    # La derivacion tiene que ser EXACTAMENTE la misma que usa el servidor.
    clave = seguridad._clave_red_desde_texto(clave_txt)
    if not config.red_usar_tls:
        print("AVISO: TLS está desactivado. Todo lo que recibas viaja SIN CIFRAR por la red.")
        if utilidades.pedir("¿Continuar sin TLS? (s/N): ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
            return

    destino = fuentes.pedir_destino(config)
    try:
        sock = _conectar_cliente(ip, constantes.NETWORK_PORT, config, clave)
    except ssl.SSLError as e:
        print(f"Error TLS: {e}")
        print("Se aborta la conexión. Desactiva 'red_usar_tls' en configuración si quieres ir en claro.")
        return
    except ConnectionError as e:
        print(f"Conexión abortada: {e}")
        return
    except OSError as e:
        print(f"No se pudo conectar con {ip}: {e}")
        return

    try:
        carpeta, recibidos, tam_total, errores_red = _recibir_archivos(
            sock, destino, motor_obj, config, ip)
        print(f"{utilidades.icono('✅', 'OK')} Respaldo remoto completado en {carpeta}")
    finally:
        sock.close()


def modo_red(config, motor_obj) -> None:
    print(f"\n{utilidades.icono('🌐', '[RED]')} MODO RED")
    print("1. Actuar como SERVIDOR")
    print("2. Actuar como CLIENTE")
    print("3. Cancelar")
    op = utilidades.pedir("Selecciona: ").strip()
    if op == "1":
        servidor_red(config)
    elif op == "2":
        cliente_red(config, motor_obj)
    elif op == "3":
        return
    else:
        print("Opción inválida")
    utilidades.pausa()
