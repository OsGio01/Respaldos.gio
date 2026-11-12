# Pruebas

Pruebas de Respaldos.Gio v6.0. Viven en el repo para que cualquiera pueda
correrlas; todas usan rutas relativas (no dependen de dónde esté el proyecto).

## Correr todo

```powershell
python Pruebas\run_all_tests.py
```

Eso compila todo el código y corre las 12 pruebas del núcleo y los frentes.
Para incluir también los ejecutables (tardan más, abren ventanas):

```powershell
python Pruebas\run_all_tests.py --exe
```

## Qué hay aquí

| Script | Qué revisa |
|---|---|
| `smoke_core.py` | Configuración, estados, motor, seguridad, fuentes, persistencia |
| `e2e_core.py` | Respaldo completo de punta a punta sobre carpetas de prueba |
| `smoke_hud.py` / `smoke_hud2.py` | Que arranque el HUD y registre en el log |
| `smoke_movil.py` | Lógica del front móvil sin ventana |
| `test_terminal_front.py` | Menú de terminal: opciones y salida limpia |
| `smoke_fachada.py` | Que las fachadas (`Respaldos.py`, `RespaldosTkinter.py`) importen |
| `test_escritorio.py` | HUD completo: fuentes, progreso, tarjetas |
| `test_fase2.py` | Configuración: botón deslizante, control de hilos y burbujas ℹ️ |
| `test_fase3.py` | Front celular: menú hamburguesa, drawer y navegación |
| `test_ventana.py` | Que la ventana del escritorio abra con el tamano correcto |
| `tests_seguridad_rendimiento.py` | Suite de seguridad (17 pruebas) y rendimiento |
| `verif_iconos_exe.py` | Que los 3 exe lleven el icono HD (16 a 256 px) |
| `test_exe_terminal.py` | El exe de terminal arranca, muestra el menú y sale con código 0 |
| `test_exe_gui.py` | El exe de escritorio abre su ventana y cierra limpio |
| `test_exe_celular.py` | El exe celular abre una ventana tipo teléfono y cierra limpio |

## Notas

- Las pruebas que abren ventanas usan `root.update()` en bucle, no `mainloop`,
  para poder afirmar cosas y cerrar.
- Las pruebas del núcleo escriben en carpetas temporales y limpian al terminar.
- Si una prueba deja un `.exe` huérfano (PyInstaller onefile deja un hijo),
  ciérralo con `taskkill /F /IM Respaldos*.exe`.
- `tests_seguridad_rendimiento.py` viene de la auditoría del 27-10-2026 y fue
  portada del motor v5 al core OOP v6.0; ahora cubre también que la clave de
  red no viaje en el `config.json`.
