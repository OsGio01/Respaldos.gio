#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Front basico de terminal del programa Respaldos.Gio (v6.2).

Delega TODOS los pasos de negocio en el nucleo OOP (`core`); esta capa solo
presenta menus, pide datos y muestra salidas.
"""
import os
import platform

from core import constantes, configuracion, estados, escaneo, fuentes, motor, persistencia, progreso, red, utilidades, seguridad


def _onoff(valor: bool) -> str:
    return f"{utilidades.icono('✅', '[X]')} Activado" if valor else f"{utilidades.icono('❌', '[ ]')} Desactivado"


def menu_configuracion(config) -> None:
    try:
        while True:
            utilidades.limpiar_terminal()
            print(f"\n{utilidades.icono('⚙️ ', '')}CONFIGURACIÓN")
            print(f" 1. Compresión automática: {_onoff(config.comprimir_automatico)}")
            print(f" 2. Registrar rutas en .txt: {_onoff(config.registrar_rutas)}")
            print(f" 3. Barra de progreso: {_onoff(config.mostrar_progreso)}")
            print(f" 4. Guardar estado de respaldos: {_onoff(config.guardar_estado_respaldos)}")
            print(f" 5. Ajuste automático de hilos: {_onoff(config.auto_ajustar_hilos)}")
            print(f" 6. Hilos paralelos: {config.max_archivos_paralelos} ({'Auto' if config.auto_ajustar_hilos else 'Manual'})")
            print(f" 7. Nivel compresión (0-9): {config.nivel_compresion}")
            print(f" 8. Ruta base respaldos: {config.ruta_base_respaldos}")
            print(f" 9. Clave de red (HMAC): {'(configurada)' if config.red_clave else '(sin configurar)'}")
            print(f"10. Bind del servidor red: {config.red_bind_ip or '(preguntar)'}")
            print(f"11. TLS en modo red: {_onoff(config.red_usar_tls)}")
            print(f"12. Ruta de adb: {config.adb_path}")
            print(f"13. Verificar SHA-256 al reanudar: {_onoff(config.verificar_hash_al_reanudar)}")
            print(f"14. Proteger respaldos (solo tu usuario): {_onoff(config.proteger_respaldos)}")
            print("15. Guardar y volver")
            op = input("Opción: ").strip()

            cambio = False
            if op in ("1", "2", "3", "4", "5"):
                campo = ("comprimir_automatico", "registrar_rutas", "mostrar_progreso",
                         "guardar_estado_respaldos", "auto_ajustar_hilos")[int(op) - 1]
                setattr(config, campo, not getattr(config, campo))
                cambio = True
            elif op == "6":
                print("\nHILOS PARALELOS: cuántos archivos se copian a la vez.")
                print(f"   Recomendado: entre 4 y {constantes.MAX_WORKERS} (tu CPU tiene {os.cpu_count()} núcleos).")
                entrada = input("Número de hilos (1-64) o 'auto': ").strip().lower()
                if entrada == "auto":
                    config.auto_ajustar_hilos = True
                    config.max_archivos_paralelos = min(64, constantes.MAX_WORKERS)
                    cambio = True
                elif entrada.isdigit():
                    config.max_archivos_paralelos = max(1, min(64, int(entrada)))
                    config.auto_ajustar_hilos = False
                    cambio = True
            elif op == "7":
                print("\nNIVEL DE COMPRESIÓN: 0 = sin compresión (rápido) | 6 = equilibrio | 9 = máxima (lento)")
                entrada = input("Nuevo nivel (0-9): ").strip()
                if entrada.isdigit() and 0 <= int(entrada) <= 9:
                    config.nivel_compresion = int(entrada)
                    cambio = True
            elif op == "8":
                nueva = input("Nueva ruta base: ").strip()
                if nueva:
                    config.ruta_base_respaldos = utilidades.expandir_ruta(nueva)
                    cambio = True
            elif op == "9":
                nueva = input("Nueva clave de red (Enter para conservar): ").strip()
                if nueva:
                    if len(nueva) < constantes.RED_CLAVE_MIN:
                        print(f"La clave debe tener al menos {constantes.RED_CLAVE_MIN} caracteres.")
                        import time as _t
                        _t.sleep(1.5)
                    else:
                        config.red_clave = nueva
                        cambio = True
            elif op == "10":
                nueva = input("IP de bind (vacío = preguntar): ").strip()
                config.red_bind_ip = nueva
                cambio = True
            elif op == "11":
                config.red_usar_tls = not config.red_usar_tls
                cambio = True
            elif op == "12":
                nueva = input("Ruta a adb (ej. /usr/bin/adb o C:\\platform-tools\\adb.exe): ").strip()
                if nueva:
                    config.adb_path = nueva
                    cambio = True
            elif op in ("13", "14"):
                campo = "verificar_hash_al_reanudar" if op == "13" else "proteger_respaldos"
                setattr(config, campo, not getattr(config, campo))
                cambio = True
            elif op == "15":
                config.guardar()
                print("Configuración guardada")
                break
            else:
                print("Opción no válida")
                import time as _t
                _t.sleep(1)
                continue

            if cambio:
                try:
                    config.guardar()
                except OSError as e:
                    print(f"Aviso: no se pudo guardar config.json ({e})")
    except KeyboardInterrupt:
        try:
            config.guardar()
        except Exception:
            pass
        print("\nConfiguración guardada por interrupción.")


def menu_reanudar(gestor, motor_obj) -> None:
    pausados = gestor.pausados()
    if not pausados:
        print("No hay respaldos interrumpidos.")
        utilidades.pausa()
        return
    print(f"\n{utilidades.icono('🔄', '[REANUDAR]')} RESPALDOS INTERRUPIDOS")
    for i, e in enumerate(pausados, 1):
        print(f"{i}. {e.tipo} - {e.origen[:50]} - {len(gestor.leer_hechos(e.id))}/{e.total_archivos}")
    sel = input("Selecciona número (0 cancelar): ").strip()
    if not sel.isdigit() or not 1 <= int(sel) <= len(pausados):
        return
    motor_obj.reanudar(pausados[int(sel) - 1])
    utilidades.pausa()


def eliminar_respaldo(config) -> None:
    import os as _os
    from core import motor as _motor
    generados = persistencia.registro_nombres.todos()
    base = config.ruta_base_respaldos
    if not _os.path.exists(base):
        print(f"La carpeta {base} no existe.")
        utilidades.pausa()
        return
    respaldos = []
    for item in _os.listdir(base):
        if _motor._quitar_zip(item) in generados:
            full = _os.path.join(base, item)
            tam = _motor.contar_directorio(full)[1] if _os.path.isdir(full) else _os.path.getsize(full)
            respaldos.append((item, full, tam))
    if not respaldos:
        print("No hay respaldos generados por el programa en esta ruta "
              "(solo se pueden eliminar los que el propio sistema creó).")
        utilidades.pausa()
        return
    print(f"\n{utilidades.icono('🗑️ ', '[ELIMINAR] ')}RESPALDOS DISPONIBLES")
    for i, (nombre, _, tam) in enumerate(respaldos, 1):
        print(f"{i}. {nombre} ({utilidades.formatear_bytes(tam)})")
    sel = input("Número a eliminar (0 cancelar): ").strip()
    if not sel.isdigit() or not 1 <= int(sel) <= len(respaldos):
        if sel not in ("", "0"):
            print("Número inválido")
            utilidades.pausa()
        return
    nombre, full, _ = respaldos[int(sel) - 1]
    if input(f"¿Eliminar {nombre}? (sí/NO): ").strip().lower() not in ("si", "sí", "yes", "y", "s"):
        print("Cancelado")
        utilidades.pausa()
        return
    if _os.path.isdir(full):
        import shutil
        shutil.rmtree(full)
    else:
        _os.remove(full)
    persistencia.registro_nombres.quitar(_motor._quitar_zip(nombre))
    print(f"{utilidades.icono('✅', 'OK')} Eliminado: {nombre}")
    if _os.path.exists(constantes.RUTA_REGISTRO):
        sin_zip = _motor._quitar_zip(full)
        with open(constantes.RUTA_REGISTRO, "r", encoding="utf-8") as f:
            lineas = f.readlines()
        with open(constantes.RUTA_REGISTRO, "w", encoding="utf-8") as f:
            f.writelines(l for l in lineas if sin_zip not in l)
    utilidades.pausa()


def mostrar_registros() -> None:
    if not os.path.exists(constantes.RUTA_REGISTRO):
        print("No hay registros de respaldos.")
        utilidades.pausa()
        return
    with open(constantes.RUTA_REGISTRO, "r", encoding="utf-8") as f:
        lineas = f.readlines()
    print("\n" + "=" * 70)
    print(f"                     {utilidades.icono('📜', '')}REGISTROS DE RESPALDOS")
    print("=" * 70)
    print(f"Total: {len(lineas)}")
    for i, linea in enumerate(reversed(lineas[-10:]), 1):
        partes = linea.strip().split("|")
        if len(partes) >= 2:
            tipo = partes[2] if len(partes) > 2 else ""
            print(f"{i}. {partes[0][:19]} | {tipo.upper()} | {partes[1]}")
    print("=" * 70)
    utilidades.pausa()


def menu_principal() -> None:
    config = configuracion.Configuracion.cargar()
    if not os.path.isabs(config.ruta_base_respaldos) or config.ruta_base_respaldos == "Respaldos":
        config.ruta_base_respaldos = constantes.RUTA_RESPALDOS
        config.guardar()
    gestor = estados.GestorEstados()
    motor_obj = motor.MotorRespaldo(config, gestor)
    fuentes_disponibles = {
        "1": fuentes.FuenteCarpetasUsuario(),
        "2": fuentes.FuenteExtensiones(),
        "3": fuentes.FuenteDiscoExterno(),
        "4": fuentes.FuenteXampp(),
        "6": fuentes.FuenteMovil(),
    }
    entradas = [
        ("1", "📂", "Respaldo general (carpetas usuario)"),
        ("2", "🔤", "Respaldo por extensiones"),
        ("3", "💾", "Recuperar disco externo"),
        ("4", "🗄️ ", "Respaldo XAMPP/MYSQL"),
        ("5", "🔄", "Reanudar respaldo interrumpido"),
        ("6", "📱", "Respaldo movil (Android/iOS)"),
        ("7", "🌐", "Modo red interna"),
        ("8", "🗑️ ", "Eliminar respaldo seguro"),
        ("9", "📜", "Ver registros"),
        ("10", "⚙️ ", "Configuración"),
        ("11", "🚪", "Salir"),
    ]
    while True:
        try:
            utilidades.limpiar_terminal()
            print("\n" + "=" * 70)
            print("       SISTEMA DE RESPALDOS AVANZADO - TERMINAL PORTABLE")
            print("=" * 70)
            print(f"{platform.system()} | Version {constantes.VERSION_PROGRAMA} | "
                  f"Base: {config.ruta_base_respaldos}")
            ultima = persistencia.leer_ultima_ruta()
            if ultima:
                print(ultima.splitlines()[0])
            n_pausados = len(gestor.pausados())
            if n_pausados:
                print(f"{utilidades.icono('⏸️ ', '[PAUSA] ')}Respaldos interrumpidos: {n_pausados}")
            print("\nMENÚ:")
            for num, emoji, texto in entradas:
                print(f"{num:>2}) {emoji + ' ' if utilidades.UNICODE_SUPPORT else ''}{texto}")
            op = input("Opción: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nHasta pronto")
            try:
                config.guardar()
            except Exception:
                pass
            break
        except Exception as e:
            print(f"\n{utilidades.icono('⚠️ ', '[ERROR] ')}{seguridad.mensaje_error_amigable(e)}")
            utilidades.pausa()
            continue

        try:
            if op in fuentes_disponibles:
                fuentes.flujo_respaldo(fuentes_disponibles[op], config, motor_obj)
            elif op == "5":
                menu_reanudar(gestor, motor_obj)
            elif op == "7":
                red.modo_red(config, motor_obj)
            elif op == "8":
                eliminar_respaldo(config)
            elif op == "9":
                mostrar_registros()
            elif op == "10":
                menu_configuracion(config)
            elif op == "11":
                print("Hasta pronto")
                config.guardar()
                break
            elif op in ("1", "2", "3", "4", "6"):
                fuentes.flujo_respaldo(fuentes_disponibles[op], config, motor_obj)
            else:
                print("Opción no válida")
                import time as _t
                _t.sleep(1)
        except KeyboardInterrupt:
            print("\nOperación cancelada.")
            import time as _t
            _t.sleep(1)
        except Exception as e:
            print(f"\n{utilidades.icono('⚠️ ', '[ERROR] ')}{seguridad.mensaje_error_amigable(e)}")
            utilidades.pausa()


if __name__ == "__main__":
    menu_principal()
