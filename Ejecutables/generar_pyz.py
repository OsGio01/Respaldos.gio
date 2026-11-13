#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera el ejecutable universal Respaldos.pyz (nucleo v6.2).

Un .pyz (Python zipapp) es UN SOLO archivo que corre en Windows, Linux y macOS
con cualquier Python 3.8 o superior. Lleva dentro el codigo y las imagenes
(IMG/interface.png para el escritorio e IMG/icono.png para la terminal).

Uso:
    python Ejecutables\\zipapp.py
    python Ejecutables\\zipapp.py --salida otro.pyz

Notas:
  - No requiere PyInstaller: se arma con zipapp de la libreria estandar.
  - El shebang es "/usr/bin/env python3", asi que en Linux y macOS se puede
    ejecutar directamente (./Respaldos.pyz) si tiene permiso de ejecucion.
    En Windows se abre con: python Respaldos.pyz
  - El .pyz NO incluye los .exe: esos se compilan por separado con
    construir.py (un binario por sistema operativo).
"""
import io
import os
import shutil
import sys
import tempfile
import zipapp

RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
IMAGENES = ("interface.png", "icono.png", "interface.ico", "icono.ico")

# NUNCA se empaqueta esto dentro del .pyz:
#  - clave_red.key: es el secreto de la clave de red. Si viaja dentro del
#    archivo, cualquiera que lo reciba tiene la clave de la red.
#  - config.json y las listas: son configuracion de la maquina de origen.
EXCLUIDOS = {"clave_red.key", "config.json", "blacklist.json", "whitelist.json",
             "estados_respaldo.json", "respaldos_generados.json",
             "ultimo_respaldo.txt", "rutas_respaldo.txt", "servidores_conocidos.json"}

LANZADOR = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Respaldos.Gio - lanzador del archivo universal (.pyz).

Al abrirlo pregunta que frente quieres usar:
  1) Terminal   - menus de texto (no necesita tkinter)
  2) Escritorio - ventana grafica (necesita python3-tk)
"""
import os
import sys

# El .pyz se ejecuta desde un ZIP: los modulos se cargan con zipimport.
# Se agrega la raiz del .pyz al path para que 'from core import ...' funcione.
_RAIZ = os.path.dirname(os.path.abspath(__file__))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)


def elegir_frente():
    print("")
    print("  RESPALDOS.GIO")
    print("  1) Terminal    (menus de texto)")
    print("  2) Escritorio  (ventana grafica)")
    print("  3) Salir")
    try:
        op = input("Opcion: ").strip()
    except (EOFError, KeyboardInterrupt):
        op = "3"
    return op


def main():
    op = elegir_frente()
    if op == "1":
        from fronts.terminal import menu_principal
        menu_principal()
    elif op == "2":
        try:
            import tkinter  # noqa: F401
        except ImportError:
            print("")
            print("  Falta python3-tk: la ventana grafica no se puede abrir.")
            print("  En Debian/Ubuntu: sudo apt install python3-tk")
            print("  En Fedora: sudo dnf install python3-tkinter")
            print("  Puedes usar el front de Terminal (opcion 1).")
            return 1
        from fronts.hud import iniciar_hud
        iniciar_hud()
    elif op == "3":
        print("Hasta pronto.")
        return 0
    else:
        print("Opcion no valida.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def preparar_escenario(destino):
    """Copia al escenario lo que va dentro del .pyz."""
    # Paquetes del nucleo y los fronts.
    for paquete in ("core", "fronts"):
        origen = os.path.join(RAIZ, paquete)
        destino_paquete = os.path.join(destino, paquete)
        shutil.copytree(
            origen, destino_paquete,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        # Se borran los archivos de datos del usuario: dentro del .pyz no
        # debe quedar la clave de red ni la configuracion de otra maquina.
        for raiz, _dirs, archivos in os.walk(destino_paquete):
            for archivo in archivos:
                if archivo in EXCLUIDOS:
                    os.remove(os.path.join(raiz, archivo))
        # La carpeta de estados (manifiestos de respaldos) tampoco va.
        estados = os.path.join(destino_paquete, "estados")
        if os.path.isdir(estados):
            shutil.rmtree(estados, ignore_errors=True)
    # Las fachadas (puntos de entrada).
    for nombre in ("Respaldos.py", "RespaldosTkinter.py", "main.py"):
        origen = os.path.join(RAIZ, nombre)
        if os.path.exists(origen):
            shutil.copy2(origen, os.path.join(destino, nombre))
    # Las imagenes (las dos que pidió el usuario).
    origen_img = os.path.join(RAIZ, "IMG")
    destino_img = os.path.join(destino, "IMG")
    os.makedirs(destino_img, exist_ok=True)
    for nombre in IMAGENES:
        origen = os.path.join(origen_img, nombre)
        if os.path.exists(origen):
            shutil.copy2(origen, os.path.join(destino_img, nombre))
        else:
            print(f"  AVISO: no se encontro IMG/{nombre}")
    # El lanzador.
    io.open(os.path.join(destino, "__main__.py"), "w", encoding="utf-8", newline="\n").write(LANZADOR)


def construir(destino_final):
    print("Preparando el contenido del .pyz...")
    escenario = tempfile.mkdtemp(prefix="gio_zipapp_")
    try:
        preparar_escenario(escenario)

        if os.path.exists(destino_final):
            os.remove(destino_final)
        zipapp.create_archive(
            escenario,
            target=destino_final,
            interpreter="/usr/bin/env python3",
            compressed=True,
        )
    finally:
        shutil.rmtree(escenario, ignore_errors=True)

    tam = os.path.getsize(destino_final)
    print(f"  OK {os.path.relpath(destino_final, RAIZ)}: {tam:,} bytes")

    # Verificacion: el .pyz se abre y trae las imagenes.
    import zipfile
    with zipfile.ZipFile(destino_final) as z:
        nombres = z.namelist()
    img = [n for n in nombres if n.startswith("IMG/") and not n.endswith("/")]
    print(f"  imagenes dentro: {sorted(img)}")
    faltan = [f"IMG/{n}" for n in IMAGENES if f"IMG/{n}" not in img]
    if faltan:
        print(f"  FALLO: faltan {faltan}")
        return False

    # El secreto de la clave de red NO debe estar dentro.
    secretos = [n for n in nombres if "clave_red" in n]
    if secretos:
        print(f"  FALLO: el .pyz trae {secretos} (la clave de red no debe viajar dentro)")
        return False
    print("  verificado: sin clave de red dentro")
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    destino = os.path.join(RAIZ, args[0] if args else "Respaldos.pyz")
    print(f"Generando {os.path.relpath(destino, RAIZ)}...")
    return 0 if construir(destino) else 1


if __name__ == "__main__":
    sys.exit(main())
