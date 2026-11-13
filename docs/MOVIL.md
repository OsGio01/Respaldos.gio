# Respaldos.Gio en Android e iOS

Este documento explica **qué se puede y qué no se puede** hacer con este
código en móvil, y qué hace falta para llevar el programa al teléfono.

## Resumen

| | Estado | Por qué |
|---|---|---|
| **Android (Termux)** | Funciona el front de **Terminal** | Python disponible; el GUI no porque no hay tkinter |
| **Android (app nativa)** | Pendiente | Requiere otra app (Kivy/Flutter/Tauri) que reusar el núcleo |
| **iOS** | **Fuera de alcance de este código** | No hay Python con tkinter en App Store, ni acceso al sistema de archivos del usuario |

## Por qué el ejecutable de celular se descartó como producto

`fronts/movil.py` es una ventana angosta (420 × 760) con menú hamburguesa. Se
construía como `RespaldosCelular6.2.exe` en Windows. **Eso no es una app de
Android ni de iOS**: es un `.exe` de Windows con forma de teléfono.

Se conserva el código como **plantilla** para la app nativa (ver abajo), pero
ya no se compila ni se distribuye. El spec
`Ejecutables/Respaldoscelular6.2/RespaldosCelular.spec` se queda como
referencia y dice explícitamente que es plantilla.

### Lo que bloquea a Android/iOS

- **Sin tkinter.** En Android (Termux) y iOS no existe tkinter. La interfaz
  gráfica tiene que ser nativa o con un framework multiplataforma.
- **Acceso a archivos.** En Android el almacenamiento compartido está en
  `/sdcard` y necesita permiso (`termux-setup-storage`); en iOS la app vive
  en su sandbox y **no puede leer las carpetas del usuario** sin copia
  explícita.
- **Firmado y distribuido.** Android necesita un APK firmado; iOS, un IPA con
  cuenta de desarrollador. Eso es otro ciclo de build, no un `pyinstaller`.

## Lo que sí funciona hoy: Android con Termux

```bash
# En Termux (de la F-Droid)
pkg install python python-tk git
# Si quieres el almacenamiento del telefono:
termux-setup-storage

# Copia el proyecto y ejecuta:
python3 Respaldos.pyz
```

El front de **Terminal** funciona completo: respaldos, reanudar, eliminar,
modo red, configuración. Funciona porque:

1. `fronts/__init__.py` usa imports perezosos, así que el terminal **no
   arrastra `tkinter`** (esto se arregló en la v6.2; antes el programa no
   arrancaba en Linux sin `python3-tk`).
2. `core/plataforma.py` detecta Android (`PREFIX` con `com.termux` o
   `ANDROID_ROOT`) y `core/escaneo.py` usa las carpetas de `/sdcard`
   (DCIM, Download, Documents, Movies, Music, Pictures).

## Qué expone el núcleo para una app nativa

Una app móvil no debe reimplementar la lógica de respaldos: debe **llamar al
núcleo**. Estas son las piezas públicas:

| Módulo | Qué ofrece |
|---|---|
| `core.motor.MotorRespaldo` | `ejecutar(plan, destino)`, `reanudar(estado)`, `finalizar(...)` |
| `core.fuentes` | Fuentes de respaldo (general, extensiones, disco, XAMPP, móvil) y `Plan` |
| `core.escaneo.Escaner` | Recorre carpetas aplicando whitelist/blacklist |
| `core.progreso.Progreso` | Progreso y cancelación (`cancelar` es un `threading.Event`) |
| `core.estados.GestorEstados` | Estado de respaldos interrumpidos (reanudar) |
| `core.seguridad` | Rutas seguras, hashes, permisos, clave de red |
| `core.configuracion.Configuracion` | Ajustes (cargar/guardar) |
| `core.plataforma` | Detección de SO y carpetas del usuario |

El flujo que usaría la app nativa:

```python
from core import configuracion, estados, motor, fuentes, escaneo, progreso

config = configuracion.Configuracion.cargar()
gestor = estados.GestorEstados()
motor_obj = motor.MotorRespaldo(config, gestor)

fuente = fuentes.FuenteCarpetasUsuario()
seleccion = fuente.detectar()                    # lista de Opcion
plan = fuente.construir_plan(seleccion, escaneo.Escaner())

pro = progreso.Progreso(len(plan.archivos), 0, "Respaldando", silencioso=True)
motor_obj.ejecutar(plan, destino, progreso_obj=pro)
```

El `progreso_obj` es un objeto con `fraccion()`, `archivos` y
`bytes_copiados`: la app móvil lo lee desde su hilo de UI y lo muestra en una
barra. Para cancelar, se pasa `cancelar=threading.Event()`.

## Qué falta para la app nativa

1. **Interfaz propia** (Kivy, Flutter, React Native, Tauri mobile) en lugar
   de tkinter.
2. **Permisos de almacenamiento** en Android: `MANAGE_EXTERNAL_STORAGE` o el
   modelo de almacenamiento por Android (`Storage Access Framework`).
3. **Permisos en iOS**: la app solo ve su sandbox; para leer fotos o
   documentos hay que usar `PHPicker` / `UIDocumentPicker`.
4. **Firmado y publicación**: APK firmado, IPA con cuenta de Apple.
5. **Adaptar `fronts/movil.py`**: sirve de maqueta del diseño (menú
   hamburguesa, tarjetas, barra de progreso), pero los widgets hay que
   reescribirlos en el framework elegido.

## Nota sobre el modo red

El modo red (TLS + HMAC + pinning) funciona igual en cualquier plataforma
porque es código puro de `core/red.py` y `core/seguridad.py`. Si la app
nativa quiere esa función, la puede usar tal cual (con `cryptography` como
dependencia).
