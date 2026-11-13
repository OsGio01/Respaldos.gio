#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seguridad: permisos, hashes, errores amigables, clave de red, TLS y PIN (nucleo v6.2)."""
import hashlib
import hmac
import os
import platform
import socket
import ssl
import subprocess
from typing import Optional

from core import constantes, persistencia

try:
    import psutil
except ImportError:
    psutil = None  # en Termux y sistemas minimos puede no estar disponible


def _sid_usuario_actual() -> str:
    """SID del usuario actual en formato de texto (S-1-5-21-...). Vacio si falla."""
    import ctypes
    from ctypes import wintypes as wt

    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]

    TOKEN_QUERY = 0x0008
    TokenUser = 1

    advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD,
                                          ctypes.POINTER(wt.HANDLE)]
    advapi32.OpenProcessToken.restype = wt.BOOL
    advapi32.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int,
                                             ctypes.c_void_p, wt.DWORD,
                                             ctypes.POINTER(wt.DWORD)]
    advapi32.GetTokenInformation.restype = wt.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                                 ctypes.POINTER(wt.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wt.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wt.HANDLE

    token = wt.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY,
                                     ctypes.byref(token)):
        return ""
    try:
        tam = wt.DWORD()
        advapi32.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(tam))
        if not tam.value:
            return ""
        buf = ctypes.create_string_buffer(tam.value)
        if not advapi32.GetTokenInformation(token, TokenUser, buf, tam,
                                            ctypes.byref(tam)):
            return ""
        usuario = SID_AND_ATTRIBUTES.from_buffer_copy(buf.raw)
        ptr = wt.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(usuario.Sid, ctypes.byref(ptr)):
            return ""
        try:
            return ptr.value or ""
        finally:
            kernel32.LocalFree(ptr)
    finally:
        kernel32.CloseHandle(token)


def _aplicar_acl_windows(ruta: str) -> bool:
    """Deja el archivo solo para el usuario actual usando la API de Windows.

    Equivale a `icacls ruta /inheritance:r /grant:r <usuario>:F` pero sin
    lanzar un proceso externo (eso congelaba la interfaz en cada guardado).
    Devuelve False si no se pudo, para que el llamador use el respaldo.
    """
    import ctypes
    from ctypes import wintypes as wt

    sid = _sid_usuario_actual()
    if not sid:
        return False

    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32

    # D:P = DACL protegida (sin herencia), A = allow, FA = acceso total
    sddl = f"D:P(A;;FA;;;{sid})"

    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wt.LPCWSTR, wt.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wt.DWORD)]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wt.BOOL
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int)]
    advapi32.GetSecurityDescriptorDacl.restype = wt.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wt.LPCWSTR, ctypes.c_int, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p]
    advapi32.SetNamedSecurityInfoW.restype = wt.DWORD
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            ctypes.create_unicode_buffer(sddl), 1, ctypes.byref(descriptor), None):
        return False
    try:
        dacl = ctypes.c_void_p()
        presente = ctypes.c_int()
        por_defecto = ctypes.c_int()
        # GetSecurityDescriptorDacl(pSecurityDescriptor, pDaclPresent, pDacl, pDaclDefaulted)
        if not advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(presente),
                                                  ctypes.byref(dacl),
                                                  ctypes.byref(por_defecto)):
            return False
        SE_FILE_OBJECT = 1
        DACL_SECURITY_INFORMATION = 0x00000004
        PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
        flags = DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION
        ok = advapi32.SetNamedSecurityInfoW(ruta, SE_FILE_OBJECT, flags, None, None,
                                             dacl if presente.value else None,
                                             None) == 0
    finally:
        kernel32.LocalFree(descriptor)

    if ok and not _sigue_legible(ruta):
        # Nunca dejar al usuario sin acceso a su propio archivo.
        try:
            usuario = os.environ.get("USERNAME", "")
            if usuario:
                subprocess.run(
                    ["icacls", ruta, "/inheritance:r", "/grant:r", f"{usuario}:F"],
                    capture_output=True, timeout=5,
                )
        except Exception:
            pass
        return False
    return ok


def _sigue_legible(ruta: str) -> bool:
    """Comprueba que el archivo sigue siendo legible tras cambiar la ACL."""
    if not os.path.exists(ruta):
        return True
    try:
        with open(ruta, "rb") as f:
            f.read(1)
        return True
    except OSError:
        return False


def _restringir_permisos(ruta: str, es_carpeta: bool = False) -> None:
    """Deja el archivo/carpeta accesible solo por el usuario actual.

    POSIX: chmod 0700 si es carpeta, 0600 si es archivo (para directorios hay
    que mantener el bit de ejecucion, si no no se puede entrar).
    Windows: ACL protegida con acceso total solo para el usuario, aplicada con
    la API del sistema (rapida). Si eso falla, se intenta con icacls.
    Silencioso si falla.
    """
    if os.name == "nt":
        try:
            if _aplicar_acl_windows(ruta):
                return
        except Exception:
            pass
        # respaldo: icacls (lento, solo si la API no estuvo disponible)
        try:
            usuario = os.environ.get("USERNAME", "")
            if usuario:
                subprocess.run(
                    ["icacls", ruta, "/inheritance:r", "/grant:r", f"{usuario}:F"],
                    capture_output=True, timeout=5,
                )
        except Exception:
            pass
        return
    try:
        os.chmod(ruta, 0o700 if es_carpeta else 0o600)
    except OSError:
        pass


def _sha256_archivo(ruta: str, buffer_size: int = 1024 * 1024) -> str:
    """SHA-256 de un archivo sin cargarlo completo en memoria."""
    h = hashlib.sha256()
    with open(ruta, "rb", buffering=0) as f:
        while True:
            bloque = f.read(buffer_size)
            if not bloque:
                break
            h.update(bloque)
    return h.hexdigest()


def _es_disco_lleno(e: BaseException) -> bool:
    # Windows tiene dos codigos para disco lleno: 112 (ERROR_DISK_FULL)
    # y 39 (ERROR_HANDLE_DISK_FULL, al escribir sobre un handle abierto).
    if not isinstance(e, OSError):
        return False
    if e.errno == 28:  # errno.ENOSPC
        return True
    we = getattr(e, "winerror", None)
    return we in (39, 112)


def motivo_corto(e: BaseException) -> str:
    if isinstance(e, PermissionError):
        return "sin permisos"
    if isinstance(e, FileNotFoundError):
        return "ya no existe"
    if _es_disco_lleno(e):
        return "disco de destino lleno"
    return str(e)[:80]


def mensaje_error_amigable(e: Exception) -> str:
    if isinstance(e, PermissionError):
        return ("No se pudo completar la operacion porque no hay permisos suficientes para acceder a algunos "
                "archivos o carpetas. Intenta ejecutar el programa como administrador o revisa los permisos.")
    if isinstance(e, FileNotFoundError):
        return ("No se pudo completar la operacion porque una de las rutas ya no existe. Verifica que el disco, "
                "USB o carpeta siga conectado y disponible.")
    if _es_disco_lleno(e):
        return "No hay suficiente espacio en el disco de destino. Libera espacio o elige otra ubicacion."
    if isinstance(e, (ConnectionError, socket.timeout, socket.gaierror)):
        return "Se perdio la conexion de red durante la transferencia. Verifica que ambos equipos sigan en la misma red."
    return f"Ocurrio un problema inesperado ({e}). Si habia un respaldo en curso quedo pausado y puede reanudarse desde el menu."


def _recibir_exacto(sock: socket.socket, n: int) -> bytes:
    datos = bytearray()
    while len(datos) < n:
        trozo = sock.recv(n - len(datos))
        if not trozo:
            raise ConnectionError("el otro equipo cerro la conexion")
        datos += trozo
    return bytes(datos)


def _ruta_segura(carpeta: str, rel: str) -> Optional[str]:
    """Devuelve la ruta destino o None si es insegura (SEG-05)."""
    try:
        if "\x00" in rel:
            return None
        base = os.path.realpath(os.path.abspath(carpeta))
        destino = os.path.realpath(os.path.abspath(os.path.join(base, rel.replace("/", os.sep))))
        if destino == base or os.path.commonpath((base, destino)) != base:
            return None
        return destino
    except (ValueError, OSError):
        return None


def _enmascarar(clave: str) -> str:
    """Nunca se imprime la clave completa."""
    return "ninguna" if not clave else "…" + clave[-4:]


def _detectar_ip_local() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def ruta_clave_red(ruta_config: str = None) -> str:
    """Ruta del archivo protegido donde vive la clave de red.

    El config.json se versiona, asi que la clave no debe viajar ahi: vive en
    <carpeta del config>/config/clave_red.key, con permisos solo del usuario.
    """
    base = os.path.dirname(os.path.abspath(ruta_config or constantes.RUTA_CONFIG))
    return os.path.join(base, "config", "clave_red.key")


def _leer_clave_red(ruta_config: str = None) -> str:
    """Lee la clave de red del archivo protegido. Vacio si no existe."""
    try:
        with open(ruta_clave_red(ruta_config), "r", encoding="utf-8") as f:
            clave = f.read().strip()
    except OSError:
        return ""
    return clave if len(clave) >= constantes.RED_CLAVE_MIN else ""


def _guardar_clave_red(clave: str, ruta_config: str = None) -> bool:
    """Guarda la clave de red en el archivo protegido (0600 / solo el usuario).

    Con clave vacia o demasiado corta no toca nada: borrar la clave es una
    accion explicita (_borrar_clave_red).
    """
    ruta = ruta_clave_red(ruta_config)
    clave = (clave or "").strip()
    if len(clave) < constantes.RED_CLAVE_MIN:
        return False
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(clave)
    except OSError:
        return False
    _restringir_permisos(ruta)
    return True


def _borrar_clave_red(ruta_config: str = None) -> bool:
    """Borra el archivo protegido con la clave de red."""
    ruta = ruta_clave_red(ruta_config)
    try:
        if os.path.exists(ruta):
            os.remove(ruta)
        return True
    except OSError:
        return False


def _clave_red_desde_texto(texto: str) -> bytes:
    """Deriva la clave de red a partir de una frase.

    OJO: servidor y cliente TIENEN que usar exactamente esta misma
    derivacion, o el handshake nunca coincidiria.
    """
    return hashlib.pbkdf2_hmac("sha256", (texto or "").encode("utf-8"),
                               b"Respaldos.Gio", 100_000, dklen=32)


def _clave_red_bytes(config) -> bytes:
    import secrets
    if not config.red_clave:
        config.red_clave = secrets.token_hex(32)
        try:
            config.guardar()
        except OSError:
            pass
    return _clave_red_desde_texto(config.red_clave)


def _binding_tls(sock: socket.socket) -> bytes:
    """Material ligado a la sesion TLS."""
    try:
        binding = sock.get_channel_binding("tls-server-end-point")
    except (AttributeError, ValueError, OSError):
        return b""
    if not binding and not constantes.BINDING_TLS_SIN_SOPORTE and hasattr(sock, "getpeercert"):
        constantes.BINDING_TLS_SIN_SOPORTE = True
        print("Aviso: este Python/OpenSSL no expone 'tls-server-end-point'. El HMAC sigue autenticando la clave, pero no queda ligado al certificado del servidor.")
    return binding or b""


def _handshake_servidor(conn: socket.socket, clave: bytes) -> None:
    binding = _binding_tls(conn)
    for _ in range(constantes.MAX_INTENTOS_AUTH):
        import secrets
        nonce = secrets.token_bytes(32)
        try:
            conn.sendall(nonce)
            resp = _recibir_exacto(conn, 32)
        except (ConnectionError, OSError):
            raise ConnectionError("conexion cerrada durante autenticacion")
        import hmac as _hmac
        esperado = _hmac.new(clave, nonce + binding, hashlib.sha256).digest()
        if hmac.compare_digest(resp, esperado):
            conn.sendall(b"OK")
            return
        try:
            conn.sendall(b"NO")
        except OSError:
            pass
    raise ConnectionError("demasiados intentos fallidos")


def _handshake_cliente(sock: socket.socket, clave: bytes) -> None:
    import secrets
    nonce = _recibir_exacto(sock, 32)
    binding = _binding_tls(sock)
    import hmac as _hmac
    resp = _hmac.new(clave, nonce + binding, hashlib.sha256).digest()
    sock.sendall(resp)
    r = _recibir_exacto(sock, 2)
    if r != b"OK":
        raise ConnectionError("el servidor rechazo la autenticacion (clave incorrecta)")


def _intentar_tls_servidor(ruta_base: str = None):
    """Prepara el contexto TLS del servidor (certificado autofirmado).

    ruta_base permite usar otra carpeta (por ejemplo una temporal en las
    pruebas) en vez de la carpeta de la aplicacion.
    """
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime as _dt
    except ImportError:
        return None
    base = ruta_base or constantes.RUTA_APP
    cert_path = os.path.join(base, "servidor_red.crt")
    key_path = os.path.join(base, "servidor_red.key")
    if not (os.path.exists(cert_path) and os.path.exists(key_path)):
        for p in (cert_path, key_path):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            import secrets as _s
            import datetime as _dt2
            from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
            from cryptography import x509 as _x509
            from cryptography.x509.oid import NameOID as _NameOID
            from cryptography.hazmat.primitives import hashes as _hashes, serialization as _serialization
            key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = issuer = _x509.Name([_x509.NameAttribute(_NameOID.COMMON_NAME, u"Respaldos.Gio")])
            cert = (_x509.CertificateBuilder()
                    .subject_name(subject).issuer_name(issuer)
                    .public_key(key.public_key())
                    .serial_number(_x509.random_serial_number())
                    .not_valid_before(_dt2.datetime.utcnow())
                    .not_valid_after(_dt2.datetime.utcnow() + _dt2.timedelta(days=3650))
                    .sign(key, _hashes.SHA256()))
            with open(key_path, "wb") as f:
                f.write(key.private_bytes(encoding=_serialization.Encoding.PEM, format=_serialization.PrivateFormat.TraditionalOpenSSL, encryption_algorithm=_serialization.NoEncryption()))
            with open(cert_path, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
            _restringir_permisos(key_path)
        except Exception:
            return None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        return ctx
    except Exception:
        return None


def ajustar_prioridad_proceso(reducir: bool) -> None:
    if not psutil:
        return
    try:
        proceso = psutil.Process(os.getpid())
        if platform.system() == "Windows":
            clase = "BELOW_NORMAL_PRIORITY_CLASS" if reducir else "NORMAL_PRIORITY_CLASS"
            if hasattr(psutil, clase):
                proceso.nice(getattr(psutil, clase))
        else:
            proceso.nice(10 if reducir else 0)
    except Exception:
        pass


def _adb_disponible(config=None) -> Optional[str]:
    ruta = (config.adb_path if config and config.adb_path else "adb") or "adb"
    if os.path.isabs(ruta) and os.path.exists(ruta):
        return ruta
    from shutil import which
    return which(ruta)


def rel_es_segura(rel: str) -> bool:
    """SEG-04: una ruta relativa de respaldo nunca debe salir de la carpeta destino."""
    import re as _re
    if not rel or "\x00" in rel or rel.startswith(("/", "\\")) or os.path.isabs(rel):
        return False
    if _re.match(r"^[A-Za-z]:", rel):
        return False
    return ".." not in _re.split(r"[\\/]", rel)


def _huella_cert(sock: socket.socket) -> Optional[str]:
    """SHA-256 del certificado DER del servidor, o None si no se obtuvo."""
    try:
        der = sock.getpeercert(binary_form=True)
        if not der:
            return None
        return hashlib.sha256(der).hexdigest()
    except Exception:
        return None


def _verificar_pin(ip: str, huella: str, ruta_pin: str = None) -> bool:
    """TOFU: primera vez pide confirmacion; si cambia, alerta y exige confirmacion.

    ruta_pin permite usar otro archivo (por ejemplo una temporal en las
    pruebas) en vez del archivo de la aplicacion.
    """
    ruta = ruta_pin or constantes.RUTA_PINNING
    datos = persistencia.cargar_json(ruta, {})
    if not isinstance(datos, dict):
        datos = {}
    conocida = datos.get(ip)
    if conocida is None:
        print(f"\nServidor nuevo: {ip}")
        print("Huella del certificado (SHA-256):")
        print(f"  {huella}")
        resp = input("¿Confiar en este servidor y recordarlo? (s/N): ").strip().lower()
        if resp not in ("s", "si", "sí", "y", "yes"):
            return False
        datos[ip] = huella
        try:
            persistencia.guardar_json(ruta, datos)
            _restringir_permisos(ruta)
        except OSError:
            pass
        return True
    if hmac.compare_digest(conocida, huella):
        return True
    print(f"\n¡ALERTA! La huella del certificado de {ip} CAMBIÓ.")
    print(f"  Esperada: {conocida}")
    print(f"  Recibida: {huella}")
    print("Esto puede indicar un MITM, una reinstalacion legitima o rotacion de certificado.")
    resp = input("¿Actualizar la huella guardada? (s/N): ").strip().lower()
    if resp not in ("s", "si", "sí", "y", "yes"):
        return False
    datos[ip] = huella
    try:
        persistencia.guardar_json(ruta, datos)
    except OSError:
        pass
    return True
