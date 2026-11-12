# Respaldos.gio

Un programa que te ayuda a respaldar tu PC cuando la quieras formatear.

Respaldos.gio copia tus carpetas a una carpeta de respaldo, comprime lo que conviene,
registra lo que hizo y —si algo se interrumpe— puede reanudar donde se quedó.
La versión 6.0 reescribió todo el programa alrededor de un **núcleo único** y lo
dispuso en **tres frentes**: terminal, escritorio y celular.

## Las tres versiones

| Versión | Cómo se arranca | Ejecutable |
|---|---|---|
| **Terminal** | `python Respaldos.py` | `Ejecutables/Respaldosterminal6.0/Respaldos.gio-Terminal6.0.exe` |
| **Escritorio (HUD)** | `python RespaldosTkinter.py` (o `python main.py`) | `Ejecutables/RespaldosInterface6.0/Respaldos.Gio6.0.exe` |
| **Celular** | `python RespaldosMovil.py` | `Ejecutables/Respaldoscelular6.0/RespaldosCelular6.0.exe` |

Los ejecutables son *onefile*: no necesitan instalación, pero la primera vez
descomprimen en una carpeta temporal, así que el arranque es un poco más lento.

### Terminal

Menú de texto con todas las opciones. Es la versión más completa para trabajar
en consola.

### Escritorio (HUD)

Ventana con paneles, barra de progreso, tarjetas de estado y **Configuración**
con botón deslizante, control de hilos y nivel de compresión. Cada control
tiene su ícono ℹ️ con una burbuja de ayuda.

### Celular

Ventana angosta (420 × 760) pensada para pantallas pequeñas. Todo el menú vive
detrás del botón **☰**, que abre un drawer con las mismas 11 opciones del
escritorio. La barra superior es compacta: estado resumido y la ruta de destino.

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
defensas de seguridad de la v6.0 (PBKDF2, TLS + HMAC + pinning, validación de
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

- Python 3.13
- Solo `tkinter`/`ttk` de la biblioteca estándar (no se usa `customtkinter`).
- `Pillow` y `PyInstaller` solo para generar los iconos HD y los ejecutables.

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
- `Ejecutables/` — los tres ejecutables 6.0 con su icono y su `config.json`.
- `IMG/` — `icono.png`, `interface.png` y los `.ico` multi-tamaño.
- `config.json`, `config/`, `rutas_respaldo.txt`, `lista_blanca.txt`,
  `lista_negra.txt` — configuración y registros del sistema.
- `Respaldos/` — respaldos generados.
- `ignorados/` — material que no se versiona (informes, pruebas antiguas).

## Generar los ejecutables

Cada ejecutable tiene su `.spec` en su carpeta dentro de `Ejecutables/`.
Para reconstruirlos hay que pasar `dist` y `build` de forma explícita (PyInstaller
los deja en el directorio de trabajo actual, no en el del `.spec`):

```powershell
python -m PyInstaller --noconfirm --clean --distpath Ejecutables\RespaldosInterface6.0\dist `
  --workpath Ejecutables\RespaldosInterface6.0\build `
  Ejecutables\RespaldosInterface6.0\Respaldos.Gio.spec
```

O, más cómodo, todo de corrido:

```powershell
python Ejecutables\construir_6.0.py
```

Ese script reconstruye los tres, deja cada `.exe` junto a su `.spec` y borra las
carpetas temporales de `build/`.

## Documentación

- `AGENTS.md` (dentro de `ignorados/`) — mapa rápido del proyecto para trabajar
  sobre él.
- `Pruebas/README.md` — qué prueba cada script y cómo correrlas.
- `ignorados/Informe_Auditoria_Respaldos_27-10-2026.md` — auditoría de
  seguridad y rendimiento.
- `ignorados/Pruebas/Cambios_2026-11-11.txt` — bitácora de los cambios de la
  versión 6.0.
- `ignorados/scripts_v5/LEEME.txt` — por qué se archivaron los scripts nativos
  v1.0/v2.0 de PowerShell y bash.
