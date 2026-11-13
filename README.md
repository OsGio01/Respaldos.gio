# Respaldos.gio

Un programa que te ayuda a respaldar tu PC cuando la quieras formatear.

Respaldos.gio copia tus carpetas a una carpeta de respaldo, comprime lo que conviene,
registra lo que hizo y —si algo se interrumpe— puede reanudar donde se quedó.
La versión 6.0 reescribió todo el programa alrededor de un **núcleo único** y lo
dispuso en **tres frentes**: terminal, escritorio y celular.

## Un archivo para todos los sistemas

La forma mas simple de usar el programa es el **archivo universal**:

```
Respaldos.pyz
```

Es un solo archivo que corre en **Windows, Linux y macOS** con cualquier
Python 3.8 o superior, y **trae las imagenes dentro** (el logo del escritorio
y el de la terminal). Al abrirlo pregunta que frente quieres usar.

| Sistema | Cómo se arranca |
|---|---|
| Windows | `python Respaldos.pyz` |
| Linux / macOS | `./Respaldos.pyz` (o `python3 Respaldos.pyz`) |

No necesita PyInstaller ni compilar nada. En Linux y macOS hay que darle
permiso una vez: `chmod +x Respaldos.pyz`.

Para ver por que el programa no arranca en otra maquina:

```
python Respaldos.py --diagnostico
```

## Los tres frentes

| Versión | Cómo se arranca | Qué necesita |
|---|---|---|
| **Terminal** | `python Respaldos.py` | nada mas (no usa tkinter) |
| **Escritorio (HUD)** | `python RespaldosTkinter.py` (o `python main.py`) | `python3-tk` |
| **Celular** | *plantilla, no se distribuye* | ver `docs/MOVIL.md` |

### Terminal

Menu de texto con todas las opciones. Es la version mas completa para trabajar
en consola y **funciona en cualquier sistema con Python**, sin dependencias
de interfaz grafica (importante en Android/Termux y en servidores).

### Escritorio (HUD)

Ventana con paneles, barra de progreso, tarjetas de estado y **Configuracion**
con boton deslizante, control de hilos y nivel de compresion. Cada control
tiene su icono con una burbuja de ayuda.

En Linux y macOS necesita `python3-tk` (`sudo apt install python3-tk`).
Si falta, el programa avisa y sigue funcionando en terminal.

### Celular

La ventana angosta (420 x 760) con menu hamburguesa **quedo como plantilla**
para la app nativa de Android e iOS: un `.exe` de Windows con forma de
telefono no es una app movil. El codigo se conserva en `fronts/movil.py` y lo
que hace falta para la app esta en `docs/MOVIL.md`.

## Ejecutables nativos (sin Python instalado)

Si quieres que el programa corra **sin tener Python**, hay un binario por
sistema operativo. PyInstaller no cruza sistemas: el `.exe` de Windows no
abre en Linux (sin Wine).

| Sistema | Donde queda | Como se compila |
|---|---|---|
| Windows | `Ejecutables/windows/` | `python Ejecutables\construir.py` |
| Linux | `Ejecutables/linux/` | `python3 Ejecutables/construir.py` |
| macOS | `Ejecutables/macos/` | `python3 Ejecutables/construir.py` |

Los tres se compilan en su propio sistema. La guia completa (requisitos,
comandos y que hacer si falla) esta en **`Linux/COMPILAR-LINUX-MAC.txt`**.

Cada binario lleva las imagenes **dentro**, asi que el logo se ve aunque el
archivo se copie a otra carpeta.

## Versión mínima de terminal (sin Python)

Para equipos donde no hay Python instalado (o donde solo quieres una terminal
limpia) hay una versión **mínima**, escrita en el lenguaje nativo de cada
sistema y sin dependencias:

| Sistema | Script | Cómo se arranca |
|---|---|---|
| Windows | `windows/Respaldos.gio.bat` → `Respaldos.gio.ps1` | doble clic en el `.bat` |
| Linux | `Linux/respaldos.sh` | `bash Linux/respaldos.sh` |
| macOS | `macOS/respaldos.sh` o `macOS/Respaldos.gio.command` | doble clic en el `.command` |

Menu de texto con cuatro opciones: **respaldo general**, **reanudar**,
**eliminar** y **salir**.

- **Respaldo general**: copia tus carpetas (Documentos, Escritorio, Descargas,
  Imágenes, Música y Videos) a `<destino>/Respaldo_<fecha>/` y opcionalmente
  lo comprime en `.zip`.
- **Reanudar**: si se interrumpió, continúa solo con lo que faltaba.
- **Eliminar**: borra un respaldo anterior (pide escribir `BORRAR`).

El destino se recuerda en `respaldos.conf` y el estado de la copia en
`respaldos.estado`, junto al script. Para respaldar carpetas concretas sin
tocar las del usuario, define `RESPALDOS_GIO_FUENTES` con el formato
`Etiqueta|ruta;Etiqueta|ruta`.

**Lo que no hace** (eso vive solo en el núcleo Python con todas sus
protecciones): modo red, deduplicación por hash, respaldo por extensiones,
XAMPP/MySQL, disco externo, listas blanca/negra y configuración avanzada. Estos
scripts se mantienen **por separado** del núcleo, así que no heredan las
defensas de seguridad de la v6.2 (PBKDF2, TLS + HMAC + pinning, validación de
rutas, permisos 0700/0600). Para respaldos importantes, usa el núcleo.

## Arquitectura

```
core/     Núcleo OOP: motor, seguridad, escaneo, fuentes, progreso, red,
          persistencia, estados y configuración. Aquí vive TODA la lógica.
fronts/   Los tres frentes (terminal, HUD, celular). Solo presentan: leen del
          núcleo y mandan acciones. No repiten lógica de respaldos.
```

- `Respaldos.py`, `RespaldosTkinter.py`, `main.py` y `RespaldosMovil.py` son
  fachadas: arrancan el frente correspondiente del núcleo.
- `fronts/tema.py` define los tokens de ancho para que los paneles se adapten
  a la ventana angosta del celular.

## Donde se guardan los datos

El programa **no guarda sus datos junto al ejecutable** sino en la carpeta de
datos del sistema, porque un `.pyz` o un ejecutable pueden estar en una
carpeta de solo lectura (`/usr/share`, `C:\Program Files`):

| Sistema | Carpeta de datos |
|---|---|
| Windows | `%APPDATA%\Respaldos.Gio\` |
| Linux | `~/.config/respaldos.gio/` (o `$XDG_CONFIG_HOME/respaldos.gio/`) |
| macOS | `~/Library/Application Support/Respaldos.Gio/` |

Ahi van `config.json`, la lista blanca/negra, la clave de red, los estados de
los respaldos interrumpidos, los respaldos y el registro.

Para meter todo en otro lado (por ejemplo un USB), define la variable de
entorno `RESPALDOS_GIO_DATA` antes de arrancar:

```
RESPALDOS_GIO_DATA=/mnt/USB/Respaldos python3 Respaldos.pyz
```

La primera vez, si encuentra un `config.json` junto al programa (de una
version anterior), lo copia a la carpeta de datos para que no se pierdan los
ajustes.

## Seguridad

- Clave de red derivada con **PBKDF2-HMAC-SHA256 (100,000 iteraciones)**.
- Transferencias con **TLS** (`server-end-point`), **handshake HMAC** con nonce
  y **pinning TOFU** (`servidores_conocidos.json`).
- La **clave de red no viaja en el `config.json`** (ese archivo se versiona):
  vive en `config/clave_red.key`, con permisos solo para tu usuario. Si usas el
  modo red entre dos equipos, copia ese archivo a los dos.
  Ojo: los permisos por usuario dependen del sistema de archivos (NTFS los
  soporta; exFAT no tiene ACLs, así que en un disco exFAT la protección real
  es que el archivo no se versiona).
- Validación de rutas contra escape de directorio y contención física del
  destino (`SEG-04`, `SEG-05`).
- Respaldos protegidos con permisos restrictivos (`0700` carpetas, `0600` zips).
- SHA-256 para verificar el estado y reanudar sin repetir trabajo.

## Requisitos

- Python 3.8 o superior (se recomienda 3.13).
- El front de **terminal** no necesita nada mas.
- El front de **escritorio** necesita `tkinter`:
  - Debian/Ubuntu: `sudo apt install python3-tk`
  - Fedora: `sudo dnf install python3-tkinter`
  - macOS: el Python de python.org ya lo trae; el de Apple (`/usr/bin/python3`)
    no, usa `brew install python-tk`.
- `Pillow`, `PyInstaller`, `psutil` y `cryptography` solo para compilar los
  ejecutables y las funciones opcional (iconos, TLS del modo red).

## Pruebas

Las pruebas viven en `Pruebas/` y usan rutas relativas (funcionan en cualquier
copia del proyecto):

```powershell
python Pruebas\run_all_tests.py          # núcleo y frentes (12 pruebas)
python Pruebas\run_all_tests.py --exe    # además los 3 ejecutables
```

## Estructura de carpetas

- `core/` — núcleo OOP del programa.
- `fronts/` — terminal, HUD y celular.
- `Pruebas/` — pruebas del núcleo, de los frentes y de los ejecutables.
- `windows/`, `Linux/`, `macOS/` — versión mínima de terminal, sin Python.
- `Ejecutables/` — los specs (`Respaldos.Gio.spec`, `Respaldos.Gio-Terminal.spec`,
  `RespaldosCelular.spec`), los generadores (`construir.py` para el binario
  del sistema actual, `generar_pyz.py` para el archivo universal) y los
  binarios en `windows/`, `linux/` o `macos/`.
- `docs/MOVIL.md` — que falta para la app nativa de Android e iOS.
- `IMG/` — `icono.png`, `interface.png` y los `.ico` multi-tamaño.
- `config.json`, `config/`, `rutas_respaldo.txt`, `lista_blanca.txt`,
  `lista_negra.txt` — configuración y registros del sistema.
- `Respaldos/` — respaldos generados.
- `ignorados/` — material que no se versiona (informes, pruebas antiguas).

## Generar los ejecutables

Cada ejecutable tiene su `.spec` en su carpeta dentro de `Ejecutables/`.
PyInstaller **no cruza sistemas operativos**: el binario que se compila es del
sistema donde se compila, y sale en `Ejecutables/<sistema>/`.

En Windows:

```powershell
python Ejecutables\construir.py
```

En Linux y macOS:

```bash
python3 Ejecutables/construir.py
```

Los specs se ajustan solos: el icono (`.ico` en Windows, `.png` en Linux,
`.icns` en macOS) y la extension del binario. Las imagenes van **dentro** del
ejecutable, asi que el logo se ve aunque copies el archivo a otra carpeta.

El archivo universal se genera aparte:

```bash
python Ejecutables/generar_pyz.py
```

La guia paso a paso para compilar en Linux y macOS (requisitos, comandos y
que hacer si falla) esta en `Linux/COMPILAR-LINUX-MAC.txt`.

## Documentación

- `AGENTS.md` (dentro de `ignorados/`) — mapa rápido del proyecto para trabajar
  sobre él.
- `Pruebas/README.md` — qué prueba cada script y cómo correrlas.
- `ignorados/Informe_Auditoria_Respaldos_27-10-2026.md` — auditoría de
  seguridad y rendimiento.
- `ignorados/Pruebas/Cambios_2026-11-11.txt` — bitácora de los cambios de la
  versión 6.2.
- `ignorados/scripts_v5/LEEME.txt` — por qué se archivaron los scripts nativos
  v1.0/v2.0 de PowerShell y bash.
