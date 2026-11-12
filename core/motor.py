#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Motor de respaldo: ejecuta, reanuda y finaliza respaldos (nucleo v6.2)."""
import os
import shutil
import time
import zipfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from core import constantes, escaneo, seguridad, estados as _estados, persistencia, progreso, utilidades

try:
    import psutil
except ImportError:
    psutil = None


def _quitar_zip(nombre: str) -> str:
    return nombre[:-4] if nombre.lower().endswith(".zip") else nombre


def crear_carpeta_respaldo(base: str, proteger: bool = True) -> str:
    usuario, equipo = utilidades.obtener_usuario_equipo()
    nombre = utilidades.sanitizar_nombre(f"{usuario}_{equipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    carpeta = os.path.join(base, nombre)
    contador = 1
    while os.path.exists(carpeta) or os.path.exists(carpeta + ".zip"):
        carpeta = os.path.join(base, f"{nombre}_{contador}")
        contador += 1
    os.makedirs(carpeta, exist_ok=True)
    if proteger:
        seguridad._restringir_permisos(carpeta, es_carpeta=True)
    persistencia.registro_nombres.agregar(os.path.basename(carpeta))
    return carpeta


def comprimir_respaldo(carpeta: str, nivel: int = 6, proteger: bool = False):
    zip_path = carpeta + ".zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=nivel) as zf:
            for raiz, _, archivos in os.walk(carpeta):
                for nombre in archivos:
                    completa = os.path.join(raiz, nombre)
                    ya_comprimido = os.path.splitext(nombre)[1].lower() in escaneo.EXT_YA_COMPRIMIDAS
                    tipo = zipfile.ZIP_STORED if (ya_comprimido or nivel == 0) else zipfile.ZIP_DEFLATED
                    zf.write(completa, os.path.relpath(completa, carpeta))
        shutil.rmtree(carpeta)
        if proteger:
            seguridad._restringir_permisos(zip_path)
        return zip_path
    except Exception as e:
        return None


def registrar_respaldo(ruta: str, tipo: str, detalles: str, config) -> None:
    if config.registrar_rutas:
        with open(constantes.RUTA_REGISTRO, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}|{ruta}|{tipo}|{detalles}\n")


def generar_metadatos_respaldo(origen, destino, tipo, total_archivos, tam_total, duracion, estado, config, info: Dict, extra: Optional[Dict] = None) -> Dict:
    primer_origen = origen.split(" + ")[0] if isinstance(origen, str) else str(origen)
    meta = {
        "fecha_ejecucion": datetime.now().isoformat(),
        "usuario": info["usuario"], "equipo": info["equipo"],
        "sistema_operativo": info["sistema"], "arquitectura": info["arquitectura"],
        "cpu_logico": info["cpu_logico"], "cpu_fisico": info["cpu_fisico"],
        "cpu_uso_inicial": info["cpu_uso"],
        "memoria_total_bytes": info["memoria_total"],
        "memoria_disponible_inicial_bytes": info["memoria_disponible"],
        "origen": origen, "destino": destino,
        "disco_origen": obtener_info_disco(primer_origen),
        "disco_destino": obtener_info_disco(destino),
        "tipo_respaldo": tipo,
        "total_archivos": total_archivos,
        "tamano_total_bytes": tam_total,
        "tamano_total_human": utilidades.formatear_bytes(tam_total),
        "duracion_segundos": round(duracion, 2),
        "estado_final": estado,
        "version_programa": constantes.VERSION_PROGRAMA,
        "configuracion": {
            "comprimir_automatico": config.comprimir_automatico,
            "nivel_compresion": config.nivel_compresion,
            "max_archivos_paralelos": config.max_archivos_paralelos,
            "auto_ajustar_hilos": config.auto_ajustar_hilos,
            "ruta_base_respaldos": config.ruta_base_respaldos,
        },
    }
    if extra:
        meta.update(extra)
    return meta


def guardar_metadatos_respaldo(destino: str, metadatos: Dict) -> None:
    try:
        import json as _json
        with open(os.path.join(destino, "backup_info.json"), "w", encoding="utf-8") as f:
            _json.dump(metadatos, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(utilidades.icono("⚠️ ", "[AVISO] ") + "Error guardando metadata:", e)


def contar_directorio(carpeta: str) -> Tuple[int, int]:
    n = 0
    tam = 0
    for raiz, _, archivos in os.walk(carpeta):
        for a in archivos:
            try:
                tam += os.path.getsize(os.path.join(raiz, a))
                n += 1
            except OSError:
                pass
    return n, tam


def obtener_info_sistema() -> Dict:
    import platform as _platform
    usuario, equipo = utilidades.obtener_usuario_equipo()
    memoria_total = memoria_disponible = None
    cpu_uso = None
    cpu_logico = os.cpu_count() or 1
    if psutil:
        try:
            mem = psutil.virtual_memory()
            memoria_total, memoria_disponible = mem.total, mem.available
            cpu_uso = psutil.cpu_percent(interval=0.2)
            cpu_logico = psutil.cpu_count(logical=True) or cpu_logico
        except Exception:
            pass
    return {
        "usuario": usuario, "equipo": equipo,
        "sistema": f"{_platform.system()} {_platform.release()}",
        "arquitectura": _platform.architecture()[0],
        "cpu_logico": cpu_logico, "cpu_fisico": None, "cpu_uso": cpu_uso,
        "memoria_total": memoria_total, "memoria_disponible": memoria_disponible,
    }


def obtener_info_disco(ruta: str) -> Dict:
    datos = {"ruta": ruta, "total_bytes": None, "free_bytes": None, "percent": None}
    try:
        uso = shutil.disk_usage(ruta)
        datos.update({"total_bytes": uso.total, "free_bytes": uso.free,
                      "percent": round(uso.used * 100 / uso.total, 1) if uso.total else None})
    except Exception:
        pass
    return datos


def calcular_hilos_optimos(config) -> int:
    max_threads = min(64, config.max_archivos_paralelos or constantes.MAX_WORKERS)
    if not getattr(config, "auto_ajustar_hilos", True) or not psutil:
        return max_threads
    try:
        cpu_pct = psutil.cpu_percent(interval=None)
        mem_pct = psutil.virtual_memory().percent
        nucleos = psutil.cpu_count(logical=True) or (os.cpu_count() or 1)
        base = max(1, int(nucleos * 0.8))
        valor = base // 2 if (cpu_pct > 70 or mem_pct > 80) else base
        return max(1, min(max_threads, valor))
    except Exception:
        return max_threads


def imprimir_resumen_sistema(info: Dict, origen: Optional[str] = None, destino: Optional[str] = None) -> None:
    print("\n" + "=" * 70)
    print(f"{utilidades.icono('💻', '[SYS]')} Equipo: {info['equipo']} | Usuario: {info['usuario']}")
    print(f"Sistema operativo: {info['sistema']} | Arquitectura: {info['arquitectura']}")
    if info["cpu_fisico"]:
        print(f"CPU: {info['cpu_fisico']} fisicos / {info['cpu_logico']} logicos | Uso inicial: {info['cpu_uso'] or 0:.1f}%")
    else:
        print(f"CPU: {info['cpu_logico']} hilos | Uso inicial: {info['cpu_uso'] or 0:.1f}%")
    print(f"RAM instalada: {utilidades.formatear_bytes(info['memoria_total'])} | Disponible: {utilidades.formatear_bytes(info['memoria_disponible'])}")
    for etiqueta, ruta in (("Origen", origen), ("Destino", destino)):
        if ruta:
            d = obtener_info_disco(ruta)
            usado = f"{d['percent']:.0f}% usado" if d["percent"] is not None else "N/A"
            print(f"{etiqueta}: {ruta}\n  Disco libre: {utilidades.formatear_bytes(d['free_bytes'])} ({usado})")
    print(f"Version Respaldos.Gio: {constantes.VERSION_PROGRAMA}")
    print("=" * 70)


class MotorRespaldo:
    def __init__(self, config, gestor):
        self.config = config
        self.gestor = gestor

    def ejecutar(self, plan, base_destino: str, progreso_obj=None, cancelar=None):
        carpeta = crear_carpeta_respaldo(base_destino, self.config.proteger_respaldos)
        estado = None
        if self.config.guardar_estado_respaldos:
            total_bytes = sum(s for _, _, s in plan.archivos)
            estado = self.gestor.crear_estado(plan.origen_txt, carpeta, plan.tipo, len(plan.archivos), total_bytes)
            self.gestor.escribir_manifiesto(estado.id, plan.archivos)
        return self._correr(plan.archivos, carpeta, plan.tipo, plan.origen_txt, estado, "Copiando",
                             plan.detalle, plan.omitidas, progreso_obj=progreso_obj, cancelar=cancelar)

    def reanudar(self, estado, progreso_obj=None, cancelar=None):
        if not os.path.exists(self.gestor.ruta_manifiesto(estado.id)):
            print("Este respaldo viene de una version anterior y no tiene la lista de archivos necesaria "
                  "para reanudarlo con exactitud. Se descarta el aviso (lo ya copiado sigue en su carpeta).")
            self.gestor.completar(estado.id)
            return None
        if not os.path.isdir(estado.destino):
            print("La carpeta de ese respaldo ya no existe (¿se movio, se comprobo o se borro?). Se descarta el aviso.")
            self.gestor.completar(estado.id)
            return None

        hechos = self.gestor.leer_hechos(estado.id)
        rapida = not self.config.verificar_hash_al_reanudar
        modo = "tamano" if rapida else "SHA-256"
        pendientes = []
        revalidadas = 0
        for origen, rel, size in self.gestor.leer_manifiesto(estado.id):
            if not seguridad.rel_es_segura(rel):
                continue
            if rel in hechos:
                sha_esperado = hechos[rel]
                try:
                    destino_rel = os.path.join(estado.destino, rel)
                    if os.stat(destino_rel).st_size == size and (
                            rapida or (sha_esperado is not None and seguridad._sha256_archivo(destino_rel) == sha_esperado)):
                        revalidadas += 1
                        continue
                except OSError:
                    pass
            pendientes.append((origen, rel, size))
        if not pendientes:
            print(f"No hay archivos pendientes. {revalidadas} archivo(s) verificados por {modo}; el respaldo ya estaba completo.")
            self.gestor.completar(estado.id)
            return None
        self.gestor.reanudar(estado.id)
        return self._correr(pendientes, estado.destino, estado.tipo, estado.origen, estado, "Reanudando",
                            total_archivos=estado.total_archivos, progreso_obj=progreso_obj, cancelar=cancelar)

    def _correr(self, items, carpeta, tipo, origen_txt, estado, descripcion, detalle="", omitidas=(),
                total_archivos=None, progreso_obj=None, cancelar=None):
        items = list(items)
        cfg = self.config
        total_bytes = sum(s for _, _, s in items)
        info = obtener_info_sistema()
        ruta_origen_valida = origen_txt if os.path.isdir(origen_txt) else None
        imprimir_resumen_sistema(info, ruta_origen_valida, carpeta)
        try:
            libre = shutil.disk_usage(carpeta).free
            if libre < total_bytes:
                print(f"{utilidades.icono('⚠️ ', '[AVISO] ')}Espacio libre en el destino ({utilidades.formatear_bytes(libre)}) "
                      f"menor a lo que se va a copiar ({utilidades.formatear_bytes(total_bytes)}).")
        except OSError:
            pass
        hilos = calcular_hilos_optimos(cfg)
        print(f"{utilidades.icono('⚙️ ', '[CPU] ')}Usando {hilos} hilos")
        pro = progreso_obj or progreso.Progreso(len(items), total_bytes, descripcion, silencioso=not cfg.mostrar_progreso)
        monitor = progreso.MonitorRecursos(lambda: pro.bytes_copiados) if psutil else None
        hechos = None
        if estado:
            hechos = _estados.RegistroHechos(self.gestor.ruta_hechos(estado.id))
        copiador = progreso.CopiadorParalelo(carpeta, pro, monitor,
                                            hechos=hechos,
                                            calcular_hash=cfg.verificar_hash_al_reanudar,
                                            buffer_size=max(256 * 1024, (cfg.tamano_buffer_mb or 8) * 1024 * 1024),
                                            cancelar=cancelar)
        if monitor:
            monitor.start()
        inicio = time.time()
        try:
            res = copiador.copiar(items, hilos)
            if copiador.cancelado:
                return None
        except KeyboardInterrupt:
            print()
            if estado:
                self.gestor.pausar(estado.id)
                print(f"{utilidades.icono('⏸️ ', '[PAUSA] ')}Respaldo interrumpido. Podras reanudar desde el menu.")
            else:
                print("Respaldo interrumpido (no se guardo el estado, asi que no se puede reanudar).")
            return None
        except Exception:
            if estado:
                self.gestor.pausar(estado.id)
            raise
        finally:
            if monitor:
                monitor.stop()
            if hechos:
                hechos.cerrar()
        duracion = time.time() - inicio
        pro.cerrar()
        if estado:
            self.gestor.completar(estado.id)
        print(f"{utilidades.icono('✅', 'OK')} Copiados: {res.copiados} | Duplicados: {res.duplicados} | Errores: {len(res.errores)}")
        if res.errores:
            print(f"{utilidades.icono('⚠️ ', '[ERR] ')}No se pudieron copiar {len(res.errores)} archivo(s):")
            for rel, motivo in res.errores[:10]:
                print(f"   - {rel}: {motivo}")
            if len(res.errores) > 10:
                print(f"   ... y {len(res.errores) - 10} mas (detalle en backup_info.json)")
        if omitidas:
            print(f"{utilidades.icono('⚠️ ', '[AVISO] ')}{len(omitidas)} carpeta(s) no se pudieron leer (permisos u otro motivo); "
                  f"el detalle esta en backup_info.json")
        resumen = (detalle + ", " if detalle else "") + f"{res.copiados} archivos"
        self.finalizar(carpeta, tipo, origen_txt, total_archivos if total_archivos is not None else len(items),
                       res.bytes_copiados, duracion, res.errores, resumen, omitidas, info)
        return res

    def finalizar(self, carpeta, tipo, origen_txt, total_archivos, tam, duracion, errores, detalle,
                  omitidas=(), info=None):
        cfg = self.config
        info = info or obtener_info_sistema()
        extra = {"errores": [{"archivo": r, "motivo": m} for r, m in errores[:200]],
                 "carpetas_omitidas": [{"ruta": r, "motivo": m} for r, m in list(omitidas)[:200]]}
        meta = generar_metadatos_respaldo(origen_txt, carpeta, tipo, total_archivos, tam, duracion,
                                        "completado" if not errores else "con_errores", cfg, info, extra)
        guardar_metadatos_respaldo(carpeta, meta)
        registrar_respaldo(carpeta, tipo, detalle, cfg)
        persistencia.guardar_ultima_ruta(carpeta, tipo)
        if cfg.comprimir_automatico:
            comprimir_respaldo(carpeta, cfg.nivel_compresion, cfg.proteger_respaldos)
