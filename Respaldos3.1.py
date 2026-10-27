import os
import shutil
import platform
from datetime import datetime
import zipfile
import json
import re
import time
import sys
import threading
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, asdict, field
from pathlib import Path
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess

# ============================================================================
# CONFIGURACIÓN MULTIPLATAFORMA ORIGINAL
# ============================================================================

def limpiar_terminal():
    """Limpia la terminal de forma multiplataforma"""
    os.system('cls' if platform.system() == "Windows" else 'clear')

def log_mensaje(carpeta_respaldo, mensaje):
    """Registra mensajes en el archivo log"""
    os.makedirs(carpeta_respaldo, exist_ok=True)
    log_path = os.path.join(carpeta_respaldo, "log.txt")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now()} - {mensaje}\n")
    print(mensaje)

def expandir_ruta(ruta):
    """Expande variables de entorno y rutas de usuario"""
    ruta_expandida = os.path.expandvars(ruta)
    ruta_expandida = os.path.expanduser(ruta_expandida)
    return os.path.normpath(ruta_expandida)

# ============================================================================
# CONFIGURACIÓN Y CONSTANTES
# ============================================================================

@dataclass
class EstadoRespaldo:
    """Estado de un respaldo en progreso o pausado"""
    id: str
    origen: str
    destino: str
    tipo: str
    total_archivos: int
    procesados: int = 0
    archivos_completados: List[str] = field(default_factory=list)
    archivos_pendientes: List[str] = field(default_factory=list)
    fecha_inicio: str = ""
    fecha_pausa: str = ""
    activo: bool = False

@dataclass
class Configuracion:
    """Configuración persistente del sistema"""
    comprimir_automatico: bool = True
    registrar_rutas: bool = True
    mostrar_progreso: bool = True
    nivel_compresion: int = 6
    max_archivos_paralelos: int = 4
    tamano_buffer_mb: int = 8
    guardar_estado_respaldos: bool = True
    
    @classmethod
    def cargar(cls, ruta="config.json"):
        """Carga la configuración desde archivo JSON"""
        config_default = cls()
        if os.path.exists(ruta):
            try:
                with open(ruta, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                    return cls(**datos)
            except:
                pass
        return config_default
    
    def guardar(self, ruta="config.json"):
        """Guarda la configuración en archivo JSON"""
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

# ============================================================================
# GESTOR DE ESTADOS DE RESPALDO
# ============================================================================

class GestorEstados:
    """Gestiona los estados de respaldo para reanudación"""
    
    def __init__(self, archivo_estados="estados_respaldo.json"):
        self.archivo_estados = archivo_estados
        self.estados = self.cargar_estados()
    
    def cargar_estados(self) -> Dict[str, EstadoRespaldo]:
        """Carga los estados desde archivo JSON"""
        if os.path.exists(self.archivo_estados):
            try:
                with open(self.archivo_estados, 'r', encoding='utf-8') as f:
                    datos = json.load(f)
                    estados = {}
                    for id_respaldo, datos_estado in datos.items():
                        estado = EstadoRespaldo(**datos_estado)
                        estados[id_respaldo] = estado
                    return estados
            except Exception as e:
                print(f"⚠️ Error cargando estados: {e}")
        return {}
    
    def guardar_estados(self):
        """Guarda los estados en archivo JSON"""
        try:
            datos = {id_respaldo: asdict(estado) for id_respaldo, estado in self.estados.items()}
            with open(self.archivo_estados, 'w', encoding='utf-8') as f:
                json.dump(datos, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Error guardando estados: {e}")
    
    def crear_estado(self, origen: str, destino: str, tipo: str, total_archivos: int) -> EstadoRespaldo:
        """Crea un nuevo estado de respaldo"""
        id_respaldo = f"{tipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(origen.encode()).hexdigest()[:8]}"
        
        estado = EstadoRespaldo(
            id=id_respaldo,
            origen=origen,
            destino=destino,
            tipo=tipo,
            total_archivos=total_archivos,
            fecha_inicio=datetime.now().isoformat(),
            activo=True
        )
        
        self.estados[id_respaldo] = estado
        self.guardar_estados()
        return estado
    
    def pausar_respaldo(self, id_respaldo: str, archivos_completados: List[str], archivos_pendientes: List[str]):
        """Pausa un respaldo en curso"""
        if id_respaldo in self.estados:
            estado = self.estados[id_respaldo]
            estado.activo = False
            estado.fecha_pausa = datetime.now().isoformat()
            estado.archivos_completados = archivos_completados
            estado.archivos_pendientes = archivos_pendientes
            estado.procesados = len(archivos_completados)
            self.guardar_estados()
    
    def reanudar_respaldo(self, id_respaldo: str) -> Optional[EstadoRespaldo]:
        """Reanuda un respaldo pausado"""
        if id_respaldo in self.estados:
            estado = self.estados[id_respaldo]
            estado.activo = True
            estado.fecha_pausa = ""
            self.guardar_estados()
            return estado
        return None
    
    def completar_respaldo(self, id_respaldo: str):
        """Marca un respaldo como completado y lo elimina del registro"""
        if id_respaldo in self.estados:
            del self.estados[id_respaldo]
            self.guardar_estados()
    
    def obtener_respaldos_pausados(self) -> List[EstadoRespaldo]:
        """Obtiene todos los respaldos pausados"""
        return [estado for estado in self.estados.values() if not estado.activo]

# ============================================================================
# BARRA DE PROGRESO
# ============================================================================

class BarraProgreso:
    """Implementa una barra de progreso visual para consola"""
    
    def __init__(self, total: int, descripcion: str = "Progreso", ancho: int = 50):
        self.total = total
        self.descripcion = descripcion
        self.ancho = ancho
        self.completado = 0
        self.inicio_tiempo = time.time()
    
    def actualizar(self, incremento: int = 1):
        """Actualiza el progreso y muestra la barra"""
        self.completado += incremento
        porcentaje = self.completado / self.total if self.total > 0 else 0
        
        tiempo_transcurrido = time.time() - self.inicio_tiempo
        if porcentaje > 0:
            tiempo_total_estimado = tiempo_transcurrido / porcentaje
            tiempo_restante = tiempo_total_estimado - tiempo_transcurrido
        else:
            tiempo_restante = 0
        
        barras_llenas = int(self.ancho * porcentaje)
        barra = '█' * barras_llenas + '░' * (self.ancho - barras_llenas)
        
        if tiempo_restante > 60:
            tiempo_str = f"{tiempo_restante/60:.1f} min"
        else:
            tiempo_str = f"{tiempo_restante:.0f} seg"
        
        sys.stdout.write(f"\r{self.descripcion}: |{barra}| {porcentaje:.1%} ({self.completado}/{self.total}) "
                        f"Tiempo restante: ~{tiempo_str}")
        sys.stdout.flush()
    
    def completar(self):
        """Marca la barra como completada"""
        self.actualizar(0)
        tiempo_total = time.time() - self.inicio_tiempo
        print(f"\n✅ Completado en {tiempo_total:.1f} segundos")

# ============================================================================
# DETECCIÓN DE UNIDADES EXTERNAS (MULTIPLATAFORMA)
# ============================================================================

def detectar_unidades_externas():
    """Detecta unidades externas conectadas (USB, discos duros externos)"""
    sistema = platform.system()
    unidades = []
    
    try:
        if sistema == "Windows":
            # Método para Windows
            import ctypes
            import string
            
            # Obtener todas las unidades lógicas
            drives = []
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append(letter + ":\\")
                bitmask >>= 1
            
            # Filtrar unidades externas (no C:)
            for drive in drives:
                if drive != "C:\\":
                    try:
                        # Verificar si es unidad extraíble
                        tipo_unidad = ctypes.windll.kernel32.GetDriveTypeW(drive)
                        # DRIVE_REMOVABLE = 2, DRIVE_FIXED = 3 (pero externo), DRIVE_REMOTE = 4
                        if tipo_unidad in [2, 3, 4]:
                            # Obtener información del disco
                            total_bytes = ctypes.c_ulonglong()
                            free_bytes = ctypes.c_ulonglong()
                            
                            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                                ctypes.c_wchar_p(drive),
                                None,
                                ctypes.pointer(total_bytes),
                                ctypes.pointer(free_bytes)
                            )
                            
                            total_gb = total_bytes.value / (1024**3)
                            libre_gb = free_bytes.value / (1024**3)
                            
                            # Obtener nombre del volumen
                            nombre_volumen = ctypes.create_unicode_buffer(1024)
                            ctypes.windll.kernel32.GetVolumeInformationW(
                                ctypes.c_wchar_p(drive),
                                nombre_volumen,
                                ctypes.sizeof(nombre_volumen),
                                None, None, None, None, 0
                            )
                            
                            nombre = nombre_volumen.value if nombre_volumen.value else "Sin Nombre"
                            
                            unidades.append({
                                'letra': drive,
                                'nombre': nombre,
                                'capacidad_gb': round(total_gb, 2),
                                'libre_gb': round(libre_gb, 2),
                                'tipo': 'USB' if tipo_unidad == 2 else 'Disco Externo'
                            })
                    except:
                        continue
        
        elif sistema == "Darwin":  # macOS
            # Método para macOS
            try:
                # Usar diskutil para listar discos
                resultado = subprocess.run(['diskutil', 'list'], 
                                        capture_output=True, 
                                        text=True,
                                        encoding='utf-8')
                
                lines = resultado.stdout.split('\n')
                current_disk = None
                
                for line in lines:
                    if '/dev/disk' in line and 'external' in line.lower():
                        disk_info = line.split()
                        if len(disk_info) > 0:
                            disk_id = disk_info[0]
                            
                            # Obtener información del disco
                            info_cmd = ['diskutil', 'info', disk_id]
                            info_result = subprocess.run(info_cmd, 
                                                        capture_output=True, 
                                                        text=True,
                                                        encoding='utf-8')
                            
                            info_lines = info_result.stdout.split('\n')
                            mount_point = ""
                            nombre = ""
                            capacidad = 0
                            
                            for info_line in info_lines:
                                if 'Mount Point:' in info_line:
                                    mount_point = info_line.split(':')[1].strip()
                                elif 'Volume Name:' in info_line:
                                    nombre = info_line.split(':')[1].strip()
                                elif 'Volume Size:' in info_line:
                                    size_str = info_line.split(':')[1].strip()
                                    # Convertir a GB
                                    if 'GB' in size_str:
                                        capacidad = float(size_str.replace('GB', '').replace(',', '').strip())
                                    elif 'MB' in size_str:
                                        capacidad = float(size_str.replace('MB', '').replace(',', '').strip()) / 1024
                                    elif 'TB' in size_str:
                                        capacidad = float(size_str.replace('TB', '').replace(',', '').strip()) * 1024
                            
                            if mount_point and mount_point != 'Not applicable':
                                # Obtener espacio libre
                                if os.path.exists(mount_point):
                                    stat = os.statvfs(mount_point)
                                    libre_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
                                    
                                    unidades.append({
                                        'letra': mount_point,
                                        'nombre': nombre if nombre else "Sin Nombre",
                                        'capacidad_gb': round(capacidad, 2),
                                        'libre_gb': round(libre_gb, 2),
                                        'tipo': 'Externo'
                                    })
            except:
                # Fallback manual para macOS
                posibles_rutas = ['/Volumes']
                for ruta_base in posibles_rutas:
                    if os.path.exists(ruta_base):
                        for item in os.listdir(ruta_base):
                            ruta_completa = os.path.join(ruta_base, item)
                            if os.path.ismount(ruta_completa) and item != 'Macintosh HD':
                                try:
                                    stat = os.statvfs(ruta_completa)
                                    total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
                                    libre_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
                                    
                                    unidades.append({
                                        'letra': ruta_completa,
                                        'nombre': item,
                                        'capacidad_gb': round(total_gb, 2),
                                        'libre_gb': round(libre_gb, 2),
                                        'tipo': 'Externo'
                                    })
                                except:
                                    continue
        
        else:  # Linux
            # Método para Linux
            posibles_rutas = ['/media', '/mnt', '/run/media']
            
            for ruta_base in posibles_rutas:
                if os.path.exists(ruta_base):
                    # Buscar en subdirectorios
                    for root, dirs, _ in os.walk(ruta_base):
                        for dir_name in dirs:
                            ruta_completa = os.path.join(root, dir_name)
                            try:
                                # Verificar si es punto de montaje
                                if os.path.ismount(ruta_completa):
                                    stat = os.statvfs(ruta_completa)
                                    total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
                                    libre_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
                                    
                                    unidades.append({
                                        'letra': ruta_completa,
                                        'nombre': dir_name,
                                        'capacidad_gb': round(total_gb, 2),
                                        'libre_gb': round(libre_gb, 2),
                                        'tipo': 'Externo'
                                    })
                            except:
                                continue
            
            # También buscar en /dev/disk/by-id para discos USB
            try:
                if os.path.exists('/dev/disk/by-id'):
                    for link in os.listdir('/dev/disk/by-id'):
                        if 'usb' in link.lower():
                            real_path = os.path.realpath(os.path.join('/dev/disk/by-id', link))
                            # Encontrar punto de montaje
                            with open('/proc/mounts', 'r') as f:
                                for line in f:
                                    if real_path in line:
                                        mount_point = line.split()[1]
                                        stat = os.statvfs(mount_point)
                                        total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
                                        libre_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
                                        
                                        unidades.append({
                                            'letra': mount_point,
                                            'nombre': link.split('-')[1] if '-' in link else link,
                                            'capacidad_gb': round(total_gb, 2),
                                            'libre_gb': round(libre_gb, 2),
                                            'tipo': 'USB'
                                        })
                                        break
            except:
                pass
    
    except Exception as e:
        print(f"⚠️ Error detectando unidades externas: {e}")
    
    # Eliminar duplicados
    unidades_unicas = []
    vistas = set()
    for unidad in unidades:
        if unidad['letra'] not in vistas:
            vistas.add(unidad['letra'])
            unidades_unicas.append(unidad)
    
    return unidades_unicas

def formatear_tamano(gb: float) -> str:
    """Formatea el tamaño en GB a una cadena legible"""
    if gb >= 1000:
        return f"{gb/1024:.1f} TB"
    elif gb >= 1:
        return f"{gb:.1f} GB"
    else:
        mb = gb * 1024
        return f"{mb:.0f} MB"

# ============================================================================
# RESPALDO DE UNIDADES EXTERNAS
# ============================================================================

def respaldo_unidad_externa(carpeta_respaldo: str, config: Configuracion, gestor_estados: GestorEstados):
    """Realiza respaldo de una unidad externa seleccionada"""
    
    print("\n" + "="*70)
    print("                 💾 RESPALDO DE UNIDADES EXTERNAS")
    print("="*70)
    
    # Detectar unidades externas
    print("\n🔍 Detectando unidades externas conectadas...")
    unidades = detectar_unidades_externas()
    
    if not unidades:
        print("\n❌ No se detectaron unidades externas conectadas.")
        print("   💡 Conecta una unidad USB o disco duro externo y vuelve a intentar.")
        input("\n⏎ Presiona ENTER para continuar...")
        return
    
    # Mostrar unidades detectadas
    print("\n" + "="*70)
    print(" 📋 UNIDADES EXTERNAS DETECTADAS")
    print("="*70)
    print("\n#  | Tipo          | Nombre              | Capacidad  | Libre      | Ruta")
    print("-"*80)
    
    for i, unidad in enumerate(unidades, 1):
        tipo = unidad['tipo'].ljust(12)
        nombre = (unidad['nombre'][:18] + '..') if len(unidad['nombre']) > 20 else unidad['nombre'].ljust(20)
        capacidad = formatear_tamano(unidad['capacidad_gb']).rjust(10)
        libre = formatear_tamano(unidad['libre_gb']).rjust(10)
        ruta = unidad['letra']
        
        print(f"{i:2} | {tipo} | {nombre} | {capacidad} | {libre} | {ruta}")
    
    print("="*80)
    
    # Seleccionar unidad
    try:
        seleccion = input("\n🎯 Selecciona el número de la unidad a respaldar (0 para cancelar): ").strip()
        
        if seleccion == "0":
            print("❌ Operación cancelada.")
            return
        
        idx = int(seleccion) - 1
        if 0 <= idx < len(unidades):
            unidad_seleccionada = unidades[idx]
            
            print(f"\n✅ Unidad seleccionada:")
            print(f"   📝 Nombre: {unidad_seleccionada['nombre']}")
            print(f"   🔌 Tipo: {unidad_seleccionada['tipo']}")
            print(f"   💾 Capacidad total: {formatear_tamano(unidad_seleccionada['capacidad_gb'])}")
            print(f"   📊 Espacio libre: {formatear_tamano(unidad_seleccionada['libre_gb'])}")
            print(f"   📍 Ruta: {unidad_seleccionada['letra']}")
            
            # Verificar si la unidad existe y es accesible
            if not os.path.exists(unidad_seleccionada['letra']):
                print(f"\n❌ Error: La unidad '{unidad_seleccionada['letra']}' no está accesible.")
                input("\n⏎ Presiona ENTER para continuar...")
                return
            
            # Verificar espacio suficiente en destino
            stat_unidad = os.statvfs(unidad_seleccionada['letra'])
            usado_gb = (stat_unidad.f_blocks - stat_unidad.f_bavail) * stat_unidad.f_frsize / (1024**3)
            
            print(f"\n📊 Estadísticas de la unidad:")
            print(f"   🔍 Tamaño a respaldar (aproximado): {formatear_tamano(usado_gb)}")
            
            # Confirmar respaldo
            confirmar = input("\n⚠️  ¿Estás seguro de respaldar esta unidad? (sí/NO): ").strip().lower()
            
            if confirmar not in ['si', 'sí', 'yes', 'y']:
                print("❌ Respaldo cancelado.")
                return
            
            # Realizar respaldo
            print(f"\n🔄 Iniciando respaldo de '{unidad_seleccionada['nombre']}'...")
            
            # Crear subcarpeta para el respaldo
            nombre_unidad_safe = re.sub(r'[^\w\s-]', '', unidad_seleccionada['nombre']).strip().replace(' ', '_')
            carpeta_destino = os.path.join(carpeta_respaldo, f"Unidad_{nombre_unidad_safe}")
            os.makedirs(carpeta_destino, exist_ok=True)
            
            # Contar archivos
            print("🔍 Contando archivos...")
            archivos_a_respaldar = []
            total_archivos = 0
            total_tamano = 0
            
            for root, _, files in os.walk(unidad_seleccionada['letra']):
                # Saltar carpetas del sistema
                if any(x in root for x in ['$RECYCLE.BIN', 'System Volume Information', '.Trash', '.Spotlight']):
                    continue
                
                for file in files:
                    ruta_completa = os.path.join(root, file)
                    try:
                        tamano = os.path.getsize(ruta_completa)
                        archivos_a_respaldar.append((ruta_completa, tamano))
                        total_archivos += 1
                        total_tamano += tamano
                    except:
                        continue
            
            if total_archivos == 0:
                print("⚠️  No se encontraron archivos para respaldar en la unidad.")
                input("\n⏎ Presiona ENTER para continuar...")
                return
            
            print(f"📊 Total de archivos a respaldar: {total_archivos:,}")
            print(f"📊 Tamaño total: {formatear_tamano(total_tamano/(1024**3))}")
            
            # Crear estado de respaldo
            estado_respaldo = None
            if config.guardar_estado_respaldos:
                estado_respaldo = gestor_estados.crear_estado(
                    origen=unidad_seleccionada['letra'],
                    destino=carpeta_destino,
                    tipo="unidad_externa",
                    total_archivos=total_archivos
                )
                print(f"📝 Estado de respaldo guardado (ID: {estado_respaldo.id[:8]}...)")
            
            # Crear barra de progreso
            barra = BarraProgreso(total_archivos, "Copiando archivos") if config.mostrar_progreso else None
            
            # Copiar archivos
            archivos_copiados = 0
            archivos_error = 0
            tamano_copiado = 0
            
            for ruta_origen, tamano in archivos_a_respaldar:
                try:
                    # Calcular ruta relativa
                    ruta_relativa = os.path.relpath(ruta_origen, unidad_seleccionada['letra'])
                    ruta_destino = os.path.join(carpeta_destino, ruta_relativa)
                    
                    # Crear directorios necesarios
                    os.makedirs(os.path.dirname(ruta_destino), exist_ok=True)
                    
                    # Copiar archivo
                    shutil.copy2(ruta_origen, ruta_destino)
                    
                    archivos_copiados += 1
                    tamano_copiado += tamano
                    
                    if barra:
                        barra.actualizar()
                    
                    # Actualizar estado si existe
                    if estado_respaldo:
                        estado_respaldo.procesados = archivos_copiados
                        if archivos_copiados % 100 == 0:  # Guardar cada 100 archivos
                            gestor_estados.guardar_estados()
                            
                except PermissionError:
                    print(f"\n⚠️  Permiso denegado: {os.path.basename(ruta_origen)}")
                    archivos_error += 1
                    if barra:
                        barra.actualizar()
                except Exception as e:
                    print(f"\n❌ Error copiando {os.path.basename(ruta_origen)}: {e}")
                    archivos_error += 1
                    if barra:
                        barra.actualizar()
            
            if barra:
                barra.completar()
            
            # Completar estado
            if estado_respaldo:
                gestor_estados.completar_respaldo(estado_respaldo.id)
            
            # Mostrar resumen
            print("\n" + "="*70)
            print(" 📊 RESUMEN DEL RESPALDO DE UNIDAD EXTERNA")
            print("="*70)
            print(f"✅ Unidad respaldada: {unidad_seleccionada['nombre']}")
            print(f"✅ Archivos copiados: {archivos_copiados:,} de {total_archivos:,}")
            print(f"✅ Tamaño respaldado: {formatear_tamano(tamano_copiado/(1024**3))}")
            print(f"❌ Archivos con error: {archivos_error}")
            print(f"💾 Carpeta de respaldo: {carpeta_destino}")
            print("="*70)
            
            # Crear archivo de información
            info_respaldo = {
                'fecha_respaldo': datetime.now().isoformat(),
                'unidad_origen': unidad_seleccionada,
                'carpeta_destino': carpeta_destino,
                'estadisticas': {
                    'archivos_copiados': archivos_copiados,
                    'archivos_error': archivos_error,
                    'tamano_total_gb': tamano_copiado/(1024**3)
                }
            }
            
            with open(os.path.join(carpeta_destino, "info_respaldo.json"), 'w', encoding='utf-8') as f:
                json.dump(info_respaldo, f, indent=2, ensure_ascii=False)
            
            # Registrar en archivo de rutas
            if config.registrar_rutas:
                with open("rutas_respaldo.txt", "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now().isoformat()}|{carpeta_destino}|unidad_externa|{unidad_seleccionada['nombre']}|{archivos_copiados} archivos\n")
            
        else:
            print(f"❌ Número fuera de rango. Selecciona entre 1 y {len(unidades)}")
            
    except ValueError:
        print("❌ Entrada inválida. Debe ser un número.")
    except Exception as e:
        print(f"❌ Error durante el respaldo: {e}")
    
    input("\n⏎ Presiona ENTER para continuar...")

# ============================================================================
# REANUDAR RESPALDO INTERRUMPIDO
# ============================================================================

def reanudar_respaldo_interrumpido(config: Configuracion, gestor_estados: GestorEstados):
    """Reanuda un respaldo que fue interrumpido"""
    
    print("\n" + "="*70)
    print("                 🔄 REANUDAR RESPALDO INTERRUMPIDO")
    print("="*70)
    
    # Obtener respaldos pausados
    respaldos_pausados = gestor_estados.obtener_respaldos_pausados()
    
    if not respaldos_pausados:
        print("\n📭 No hay respaldos interrumpidos para reanudar.")
        input("\n⏎ Presiona ENTER para continuar...")
        return
    
    # Mostrar respaldos pausados
    print(f"\n📋 Respaldos interrumpidos disponibles: {len(respaldos_pausados)}")
    print("="*70)
    
    for i, estado in enumerate(respaldos_pausados, 1):
        fecha_pausa = datetime.fromisoformat(estado.fecha_pausa).strftime("%d/%m/%Y %H:%M") if estado.fecha_pausa else "Desconocida"
        porcentaje = (estado.procesados / estado.total_archivos * 100) if estado.total_archivos > 0 else 0
        
        print(f"\n{i:2d}. [{estado.tipo.upper()}]")
        print(f"    📍 Origen: {estado.origen}")
        print(f"    🎯 Destino: {estado.destino}")
        print(f"    📊 Progreso: {estado.procesados:,} de {estado.total_archivos:,} archivos ({porcentaje:.1f}%)")
        print(f"    ⏸️  Pausado el: {fecha_pausa}")
        print(f"    🆔 ID: {estado.id[:12]}...")
    
    print("\n" + "="*70)
    
    try:
        seleccion = input("\n🎯 Selecciona el número del respaldo a reanudar (0 para cancelar): ").strip()
        
        if seleccion == "0":
            print("❌ Operación cancelada.")
            return
        
        idx = int(seleccion) - 1
        if 0 <= idx < len(respaldos_pausados):
            estado = respaldos_pausados[idx]
            
            print(f"\n🔄 Preparando para reanudar respaldo...")
            print(f"   📍 Origen: {estado.origen}")
            print(f"   🎯 Destino: {estado.destino}")
            print(f"   📊 Progreso anterior: {estado.procesados:,} de {estado.total_archivos:,} archivos")
            
            # Verificar que los archivos aún existen
            if not os.path.exists(estado.origen):
                print(f"\n❌ Error: El origen '{estado.origen}' ya no existe.")
                gestor_estados.completar_respaldo(estado.id)  # Eliminar estado
                input("\n⏎ Presiona ENTER para continuar...")
                return
            
            if not os.path.exists(estado.destino):
                print(f"⚠️  La carpeta de destino no existe. Creando...")
                os.makedirs(estado.destino, exist_ok=True)
            
            # Confirmar reanudación
            confirmar = input("\n⚠️  ¿Reanudar este respaldo? (sí/NO): ").strip().lower()
            
            if confirmar not in ['si', 'sí', 'yes', 'y']:
                print("❌ Reanudación cancelada.")
                return
            
            # Reanudar estado
            estado_reanudado = gestor_estados.reanudar_respaldo(estado.id)
            if not estado_reanudado:
                print("❌ Error al reanudar el estado del respaldo.")
                return
            
            print(f"\n🔄 Reanudando respaldo...")
            
            # Para simplificar, vamos a re-contar los archivos pendientes
            # En una implementación completa, usaríamos la lista de archivos_pendientes guardada
            
            print("🔍 Re-analizando archivos pendientes...")
            
            # Contar archivos totales en origen
            archivos_totales = []
            for root, _, files in os.walk(estado.origen):
                for file in files:
                    ruta_completa = os.path.join(root, file)
                    archivos_totales.append(ruta_completa)
            
            # Contar archivos ya copiados en destino
            archivos_copiados = []
            if os.path.exists(estado.destino):
                for root, _, files in os.walk(estado.destino):
                    for file in files:
                        # Reconstruir ruta de origen equivalente
                        rel_path = os.path.relpath(os.path.join(root, file), estado.destino)
                        ruta_origen_equivalente = os.path.join(estado.origen, rel_path)
                        if os.path.exists(ruta_origen_equivalente):
                            archivos_copiados.append(ruta_origen_equivalente)
            
            # Determinar archivos pendientes
            archivos_pendientes = [archivo for archivo in archivos_totales 
                                if archivo not in archivos_copiados]
            
            total_pendientes = len(archivos_pendientes)
            print(f"📊 Archivos pendientes: {total_pendientes:,}")
            
            if total_pendientes == 0:
                print("✅ Todos los archivos ya estaban respaldados.")
                gestor_estados.completar_respaldo(estado.id)
                input("\n⏎ Presiona ENTER para continuar...")
                return
            
            # Crear barra de progreso
            barra = BarraProgreso(total_pendientes, "Reanudando respaldo") if config.mostrar_progreso else None
            
            # Copiar archivos pendientes
            copiados_nuevos = 0
            errores_nuevos = 0
            
            for ruta_origen in archivos_pendientes:
                try:
                    # Calcular ruta relativa
                    ruta_relativa = os.path.relpath(ruta_origen, estado.origen)
                    ruta_destino = os.path.join(estado.destino, ruta_relativa)
                    
                    # Crear directorios necesarios
                    os.makedirs(os.path.dirname(ruta_destino), exist_ok=True)
                    
                    # Copiar archivo
                    shutil.copy2(ruta_origen, ruta_destino)
                    
                    copiados_nuevos += 1
                    
                    if barra:
                        barra.actualizar()
                    
                    # Actualizar estado
                    estado_reanudado.procesados += 1
                    if copiados_nuevos % 100 == 0:
                        gestor_estados.guardar_estados()
                        
                except Exception as e:
                    print(f"\n❌ Error copiando {os.path.basename(ruta_origen)}: {e}")
                    errores_nuevos += 1
                    if barra:
                        barra.actualizar()
            
            if barra:
                barra.completar()
            
            # Completar respaldo
            gestor_estados.completar_respaldo(estado.id)
            
            # Mostrar resumen
            print("\n" + "="*70)
            print(" 📊 RESUMEN DE REANUDACIÓN")
            print("="*70)
            print(f"✅ Respaldo reanudado exitosamente")
            print(f"✅ Archivos nuevos copiados: {copiados_nuevos:,}")
            print(f"✅ Archivos totales en destino: {len(archivos_copiados) + copiados_nuevos:,}")
            print(f"❌ Errores durante reanudación: {errores_nuevos}")
            print(f"💾 Carpeta de respaldo: {estado.destino}")
            print("="*70)
            
        else:
            print(f"❌ Número fuera de rango. Selecciona entre 1 y {len(respaldos_pausados)}")
            
    except ValueError:
        print("❌ Entrada inválida. Debe ser un número.")
    except Exception as e:
        print(f"❌ Error durante la reanudación: {e}")
    
    input("\n⏎ Presiona ENTER para continuar...")

# ============================================================================
# RESPALDO POR EXTENSIONES MEJORADO - SOLO CREA CARPETAS ENCONTRADAS
# ============================================================================

def respaldo_por_extensiones(carpeta_respaldo: str, config: Configuracion):
    """Realiza respaldo por extensiones, creando carpetas SOLO para extensiones encontradas"""
    
    print("🔄 Preparando respaldo por extensiones...")
    
    home = os.path.expanduser("~")
    
    # Extensiones a buscar (lista completa para búsqueda)
    extensiones_busqueda = [
        # Documentos
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "rtf",
        "odt", "ods", "odp",
        # Imágenes
        "jpg", "jpeg", "png", "gif", "bmp", "tiff", "svg", "webp",
        # Multimedia
        "mp3", "wav", "flac", "mp4", "avi", "mkv", "mov", "wmv",
        # Archivos
        "zip", "rar", "7z", "tar", "gz",
        # Desarrollo
        "py", "js", "html", "css", "java", "cpp", "c", "h", "cs", "php",
        "json", "xml", "sql", "md", "yml", "yaml", "rb", "go", "rs",
        "swift", "kt", "dart", "sh", "bat", "ps1", "ts", "jsx", "tsx"
    ]
    
    print("🔍 Buscando archivos por extensiones...")
    
    # Primero: buscar qué extensiones existen y contar archivos
    extensiones_encontradas = {}  # {extensión: [rutas de archivos]}
    archivos_encontrados = 0
    
    # Crear un conjunto para búsqueda rápida
    extensiones_set = set(f".{ext.lower()}" for ext in extensiones_busqueda)
    
    # Escanear y recolectar archivos
    for root, _, files in os.walk(home):
        # Saltar rutas bloqueadas del sistema
        if any(bloq in root for bloq in ['AppData', 'ProgramData', 'Windows', 'System32', '.cache', '.local']):
            continue
        
        for file in files:
            # Obtener extensión del archivo
            _, extension = os.path.splitext(file)
            extension_lower = extension.lower()
            
            # Verificar si la extensión está en nuestra lista
            if extension_lower in extensiones_set:
                ruta_origen = os.path.join(root, file)
                
                # Agregar a la lista de extensiones encontradas
                if extension_lower not in extensiones_encontradas:
                    extensiones_encontradas[extension_lower] = []
                
                extensiones_encontradas[extension_lower].append(ruta_origen)
                archivos_encontrados += 1
    
    # Mostrar estadísticas de lo encontrado
    print(f"\n📊 ARCHIVOS ENCONTRADOS POR EXTENSIÓN:")
    for ext in sorted(extensiones_encontradas.keys()):
        cantidad = len(extensiones_encontradas[ext])
        print(f"  • {ext[1:].upper()}: {cantidad} archivos")
    
    if archivos_encontrados == 0:
        print("\n⚠️ No se encontraron archivos con las extensiones especificadas.")
        return
    
    print(f"\n📈 Total de archivos a respaldar: {archivos_encontrados}")
    
    # Preguntar al usuario si quiere continuar
    continuar = input("\n¿Deseas continuar con el respaldo? (sí/NO): ").strip().lower()
    if continuar not in ['si', 'sí', 'yes', 'y']:
        print("❌ Respaldo cancelado.")
        return
    
    # Crear barra de progreso si está activada
    barra = BarraProgreso(archivos_encontrados, "Respaldo por extensiones") if config.mostrar_progreso else None
    
    # Crear carpetas SOLO para las extensiones encontradas y copiar archivos
    print("\n📁 Creando carpetas y respaldando archivos...")
    
    archivos_copiados = 0
    archivos_omitidos = 0
    archivos_error = 0
    
    for ext, rutas_archivos in extensiones_encontradas.items():
        # Crear carpeta solo si hay archivos de esta extensión
        nombre_ext = ext[1:].upper()  # Quitar el punto y poner en mayúsculas
        destino_ext = os.path.join(carpeta_respaldo, f"Archivos_{nombre_ext}")
        os.makedirs(destino_ext, exist_ok=True)
        
        print(f"\n  📂 Copiando archivos {ext} ({len(rutas_archivos)} archivos)...")
        
        for ruta_origen in rutas_archivos:
            nombre_archivo = os.path.basename(ruta_origen)
            ruta_destino = os.path.join(destino_ext, nombre_archivo)
            
            try:
                # Manejar archivos duplicados
                contador = 1
                base, extension_archivo = os.path.splitext(nombre_archivo)
                
                while os.path.exists(ruta_destino):
                    # Verificar si son el mismo archivo
                    try:
                        if os.path.getsize(ruta_origen) == os.path.getsize(ruta_destino):
                            # Verificar contenido
                            with open(ruta_origen, 'rb') as f1, open(ruta_destino, 'rb') as f2:
                                if f1.read() == f2.read():
                                    archivos_omitidos += 1
                                    if config.mostrar_progreso:
                                        barra.actualizar()
                                    break
                    except:
                        pass
                    
                    # Crear nuevo nombre
                    nuevo_nombre = f"{base}_{contador}{extension_archivo}"
                    ruta_destino = os.path.join(destino_ext, nuevo_nombre)
                    contador += 1
                
                else:  # Solo copiar si no se rompió el ciclo por archivo duplicado
                    shutil.copy2(ruta_origen, ruta_destino)
                    archivos_copiados += 1
                    
                    if config.mostrar_progreso:
                        barra.actualizar()
                        
            except PermissionError:
                print(f"    ⚠️ Permiso denegado: {nombre_archivo}")
                archivos_error += 1
                if config.mostrar_progreso:
                    barra.actualizar()
            except Exception as e:
                print(f"    ❌ Error copiando {nombre_archivo}: {e}")
                archivos_error += 1
                if config.mostrar_progreso:
                    barra.actualizar()
    
    if config.mostrar_progreso:
        barra.completar()
    
    # Mostrar resumen
    print("\n" + "="*60)
    print("📊 RESUMEN DEL RESPALDO POR EXTENSIONES")
    print("="*60)
    print(f"✅ Carpetas creadas: {len(extensiones_encontradas)}")
    print(f"✅ Archivos copiados exitosamente: {archivos_copiados}")
    print(f"⚠️ Archivos omitidos (duplicados): {archivos_omitidos}")
    print(f"❌ Archivos con error: {archivos_error}")
    print(f"💾 Carpeta de respaldo: {carpeta_respaldo}")
    print("="*60)
    
    # Registrar ruta si está activado
    if config.registrar_rutas:
        with open("rutas_respaldo.txt", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}|{carpeta_respaldo}|extensiones|{len(extensiones_encontradas)} carpetas|{archivos_copiados} archivos\n")

# ============================================================================
# RESPALDO XAMPP/MYSQL
# ============================================================================

def buscar_xampp_mysql():
    """Busca instalaciones de XAMPP y MySQL"""
    sistema = platform.system()
    rutas_encontradas = []
    
    if sistema == "Windows":
        # Buscar XAMPP
        posibles_rutas = [
            "C:\\xampp",
            "D:\\xampp", 
            "C:\\Program Files\\xampp",
            "C:\\Program Files (x86)\\xampp"
        ]
        
        for ruta in posibles_rutas:
            if os.path.exists(ruta):
                rutas_encontradas.append(("XAMPP", ruta))
        
        # Buscar MySQL
        mysql_rutas = [
            "C:\\Program Files\\MySQL",
            "C:\\Program Files (x86)\\MySQL",
            "C:\\xampp\\mysql"
        ]
        
        for ruta in mysql_rutas:
            if os.path.exists(ruta):
                rutas_encontradas.append(("MySQL", ruta))
    
    elif sistema == "Darwin":  # macOS
        posibles_rutas = [
            "/Applications/XAMPP",
            "/Applications/xampp",
            "/usr/local/mysql",
            "/Applications/MAMP"
        ]
        
        for ruta in posibles_rutas:
            if os.path.exists(ruta):
                nombre = "XAMPP" if "xampp" in ruta.lower() else "MySQL" if "mysql" in ruta.lower() else "MAMP"
                rutas_encontradas.append((nombre, ruta))
    
    else:  # Linux
        posibles_rutas = [
            "/opt/lampp",
            "/var/www/html",
            "/usr/local/mysql",
            "/var/lib/mysql"
        ]
        
        for ruta in posibles_rutas:
            if os.path.exists(ruta):
                nombre = "XAMPP" if "lampp" in ruta else "MySQL" if "mysql" in ruta else "Apache"
                rutas_encontradas.append((nombre, ruta))
    
    return rutas_encontradas

def respaldo_xampp_mysql(carpeta_respaldo: str, config: Configuracion):
    """Realiza respaldo de XAMPP/MySQL"""
    
    print("🔍 Buscando instalaciones de XAMPP/MySQL...")
    instalaciones = buscar_xampp_mysql()
    
    if not instalaciones:
        print("❌ No se encontraron instalaciones de XAMPP o MySQL.")
        print("💡 Sugerencias:")
        print("   • Asegúrate de tener XAMPP o MySQL instalado")
        print("   • Puedes agregar la ruta manualmente a la lista blanca")
        return
    
    print("📍 Instalaciones encontradas:")
    for i, (nombre, ruta) in enumerate(instalaciones, 1):
        print(f"  {i}) {nombre}: {ruta}")
    
    # Seleccionar qué respaldar
    print("\n¿Qué deseas respaldar?")
    print("  1) Todas las instalaciones")
    print("  2) Seleccionar específicas")
    
    opcion = input("Selecciona una opción (1-2): ").strip()
    
    if opcion == "1":
        seleccionadas = instalaciones
    elif opcion == "2":
        print("\nEscribe los números separados por espacios (ej: 1 3):")
        indices = input("> ").strip().split()
        seleccionadas = []
        for idx in indices:
            if idx.isdigit():
                i = int(idx) - 1
                if 0 <= i < len(instalaciones):
                    seleccionadas.append(instalaciones[i])
    else:
        print("❌ Opción no válida.")
        return
    
    # Contar archivos totales
    print("\n📊 Contando archivos...")
    total_archivos = 0
    for nombre, ruta in seleccionadas:
        for root, _, files in os.walk(ruta):
            total_archivos += len(files)
    
    if total_archivos == 0:
        print("⚠️ No se encontraron archivos para respaldar.")
        return
    
    # Crear barra de progreso
    barra = BarraProgreso(total_archivos, "Respaldo XAMPP/MySQL") if config.mostrar_progreso else None
    
    # Realizar respaldo
    archivos_copiados = 0
    archivos_error = 0
    
    for nombre, ruta in seleccionadas:
        print(f"\n🔄 Respaldando {nombre} desde: {ruta}")
        
        destino = os.path.join(carpeta_respaldo, nombre)
        os.makedirs(destino, exist_ok=True)
        
        for root, _, files in os.walk(ruta):
            # Saltar algunas carpetas innecesarias
            if any(skip in root for skip in ['cache', 'temp', 'tmp', 'logs', 'backup']):
                continue
            
            for file in files:
                ruta_origen = os.path.join(root, file)
                rel_path = os.path.relpath(root, ruta)
                destino_dir = os.path.join(destino, rel_path)
                
                os.makedirs(destino_dir, exist_ok=True)
                ruta_destino = os.path.join(destino_dir, file)
                
                try:
                    # Para archivos de base de datos, verificar que no estén en uso
                    if file.endswith(('.ibd', '.myd', '.myi', '.frm')):
                        try:
                            shutil.copy2(ruta_origen, ruta_destino)
                            archivos_copiados += 1
                        except PermissionError:
                            print(f"  ⚠️ Archivo de BD en uso: {file}")
                            archivos_error += 1
                            continue
                    else:
                        shutil.copy2(ruta_origen, ruta_destino)
                        archivos_copiados += 1
                    
                    if barra:
                        barra.actualizar()
                        
                except PermissionError:
                    print(f"  ⚠️ Permiso denegado: {file}")
                    archivos_error += 1
                    if barra:
                        barra.actualizar()
                except Exception as e:
                    print(f"  ❌ Error: {file} - {e}")
                    archivos_error += 1
                    if barra:
                        barra.actualizar()
    
    if barra:
        barra.completar()
    
    # Mostrar resumen
    print("\n" + "="*60)
    print("📊 RESUMEN DEL RESPALDO XAMPP/MYSQL")
    print("="*60)
    print(f"✅ Instalaciones respaldadas: {len(seleccionadas)}")
    print(f"✅ Archivos copiados exitosamente: {archivos_copiados}")
    print(f"❌ Archivos con error: {archivos_error}")
    print(f"💾 Carpeta de respaldo: {carpeta_respaldo}")
    print("="*60)
    
    # Registrar ruta si está activado
    if config.registrar_rutas:
        with open("rutas_respaldo.txt", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}|{carpeta_respaldo}|xampp_mysql|{len(seleccionadas)} instalaciones|{archivos_copiados} archivos\n")

# ============================================================================
# VER REGISTROS (MEJORADA - SE CIERRA CON ENTER)
# ============================================================================

def mostrar_registros():
    """Muestra los registros de respaldos y espera Enter para continuar"""
    
    if not os.path.exists("rutas_respaldo.txt"):
        print("📭 No hay registros de respaldos.")
        input("\n⏎ Presiona ENTER para continuar...")
        return
    
    try:
        with open("rutas_respaldo.txt", "r", encoding="utf-8") as f:
            lineas = f.readlines()
        
        if not lineas:
            print("📭 No hay registros de respaldos.")
            input("\n⏎ Presiona ENTER para continuar...")
            return
        
        print("\n" + "="*70)
        print("                     📜 REGISTROS DE RESPALDOS")
        print("="*70)
        print(f"\nTotal de respaldos registrados: {len(lineas)}")
        print("\nÚltimos 10 respaldos:")
        print("-"*70)
        
        # Mostrar los últimos 10 registros
        for i, linea in enumerate(reversed(lineas[-10:]), 1):
            partes = linea.strip().split("|")
            if len(partes) >= 3:
                fecha_str = partes[0]
                ruta = partes[1]
                tipo = partes[2]
                
                try:
                    fecha_obj = datetime.fromisoformat(fecha_str)
                    fecha_formateada = fecha_obj.strftime("%d/%m/%Y %H:%M")
                except:
                    fecha_formateada = fecha_str
                
                # Mostrar ruta abreviada si es muy larga
                if len(ruta) > 50:
                    ruta_display = "..." + ruta[-47:]
                else:
                    ruta_display = ruta
                
                print(f"\n{i:2d}. [{fecha_formateada}]")
                print(f"    Tipo: {tipo.upper()}")
                print(f"    Ruta: {ruta_display}")
                
                # Mostrar detalles adicionales si existen
                if len(partes) > 3:
                    detalles = " | ".join(partes[3:])
                    print(f"    Detalles: {detalles}")
        
        print("\n" + "="*70)
        print("Archivo completo: rutas_respaldo.txt")
        
    except Exception as e:
        print(f"❌ Error al leer los registros: {e}")
    
    input("\n⏎ Presiona ENTER para continuar...")

# ============================================================================
# ELIMINACIÓN RESTRINGIDA DE RESPALDOS
# ============================================================================

def eliminar_respaldo_seguro(destino_base: str):
    """Elimina solo respaldos generados por el programa"""
    
    # Patrón de nombres de respaldo
    patron_respaldo = re.compile(r'^Respaldo_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(\.zip)?$')
    
    if not os.path.exists(destino_base):
        print("❌ El directorio de respaldos no existe.")
        input("\n⏎ Presiona ENTER para continuar...")
        return
    
    # Listar solo respaldos válidos
    respaldos_validos = []
    for item in os.listdir(destino_base):
        ruta_completa = os.path.join(destino_base, item)
        
        # Verificar patrón
        if not patron_respaldo.match(item):
            continue
        
        # Calcular tamaño
        try:
            if os.path.isdir(ruta_completa):
                total = 0
                for root, _, files in os.walk(ruta_completa):
                    for f in files:
                        total += os.path.getsize(os.path.join(root, f))
                if total < 1024*1024:
                    tamano = f"{total/1024:.1f} KB"
                elif total < 1024*1024*1024:
                    tamano = f"{total/(1024*1024):.1f} MB"
                else:
                    tamano = f"{total/(1024*1024*1024):.2f} GB"
                tipo = "📁 Carpeta"
            else:  # Es archivo zip
                tamano = f"{os.path.getsize(ruta_completa)/(1024*1024):.1f} MB"
                tipo = "📦 ZIP"
            
            # Extraer fecha del nombre
            fecha_match = re.search(r'(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})', item)
            if fecha_match:
                fecha = f"{fecha_match.group(1)} {fecha_match.group(2).replace('-', ':')}"
            else:
                fecha = "Fecha desconocida"
            
            respaldos_validos.append((item, ruta_completa, tipo, tamano, fecha))
            
        except Exception as e:
            print(f"⚠️ Error al procesar {item}: {e}")
    
    if not respaldos_validos:
        print("📭 No hay respaldos generados por el programa para eliminar.")
        input("\n⏎ Presiona ENTER para continuar...")
        return
    
    # Mostrar respaldos
    print("\n" + "="*70)
    print("              🗑️ ELIMINAR RESPALDOS (SOLO GENERADOS POR EL PROGRAMA)")
    print("="*70)
    
    for i, (nombre, ruta, tipo, tamano, fecha) in enumerate(respaldos_validos, 1):
        # Acortar nombre si es muy largo
        if len(nombre) > 40:
            nombre_display = nombre[:37] + "..."
        else:
            nombre_display = nombre
        
        print(f"\n{i:2d}. {nombre_display}")
        print(f"    {tipo} | {tamano} | {fecha}")
    
    print("\n" + "="*70)
    print("  📝 NOTA: Solo se muestran respaldos con el formato 'Respaldo_AAAA-MM-DD_HH-MM-SS'")
    print("="*70)
    
    # Selección
    try:
        seleccion = input("\nSelecciona el número del respaldo a eliminar (0 para cancelar): ").strip()
        
        if seleccion == "0":
            print("❌ Operación cancelada.")
            return
        
        idx = int(seleccion) - 1
        if 0 <= idx < len(respaldos_validos):
            nombre, ruta, tipo, tamano, fecha = respaldos_validos[idx]
            
            # Confirmación adicional
            print(f"\n⚠️  ATENCIÓN: Estás por eliminar:")
            print(f"   • Nombre: {nombre}")
            print(f"   • Tipo: {tipo}")
            print(f"   • Tamaño: {tamano}")
            print(f"   • Fecha: {fecha}")
            
            confirmacion = input("\n¿Estás SEGURO de que quieres eliminar este respaldo? (sí/NO): ").strip().lower()
            
            if confirmacion in ['si', 'sí', 'yes', 'y']:
                try:
                    if os.path.isdir(ruta):
                        shutil.rmtree(ruta)
                    else:
                        os.remove(ruta)
                    print(f"✅ Respaldo eliminado: {nombre}")
                    
                    # Actualizar registro de rutas
                    actualizar_registro_eliminacion(ruta)
                    
                except Exception as e:
                    print(f"❌ Error al eliminar: {e}")
            else:
                print("❌ Operación cancelada.")
        else:
            print("❌ Número fuera de rango.")
            
    except ValueError:
        print("❌ Entrada inválida. Debe ser un número.")
    
    input("\n⏎ Presiona ENTER para continuar...")

def actualizar_registro_eliminacion(ruta_eliminada: str):
    """Actualiza el archivo de registro cuando se elimina un respaldo"""
    if not os.path.exists("rutas_respaldo.txt"):
        return
    
    try:
        with open("rutas_respaldo.txt", "r", encoding="utf-8") as f:
            lineas = f.readlines()
        
        # Filtrar la ruta eliminada
        nuevas_lineas = []
        for linea in lineas:
            partes = linea.strip().split("|")
            if len(partes) >= 2 and partes[1] != ruta_eliminada:
                nuevas_lineas.append(linea)
        
        with open("rutas_respaldo.txt", "w", encoding="utf-8") as f:
            f.writelines(nuevas_lineas)
            
    except Exception as e:
        print(f"⚠️ Error al actualizar registro: {e}")

# ============================================================================
# NUEVA FUNCIÓN: RESPALDO GENERAL DE CARPETAS (COPIA COMPLETA)
# ============================================================================

def obtener_carpetas_usuario():
    """Devuelve una lista de carpetas comunes del usuario según el SO"""
    sistema = platform.system()
    home = os.path.expanduser("~")
    carpetas = []

    if sistema == "Windows":
        # Carpetas típicas de Windows
        carpetas = [
            os.path.join(home, "Documents"),
            os.path.join(home, "Music"),
            os.path.join(home, "Pictures"),
            os.path.join(home, "Videos"),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Desktop"),
            os.path.join(home, "Favorites"),
            os.path.join(home, "Contacts"),
            os.path.join(home, "Links"),
            os.path.join(home, "Saved Games"),
            os.path.join(home, "Searches"),
        ]
    elif sistema == "Darwin":  # macOS
        carpetas = [
            os.path.join(home, "Documents"),
            os.path.join(home, "Music"),
            os.path.join(home, "Pictures"),
            os.path.join(home, "Movies"),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Desktop"),
            os.path.join(home, "Library"),
        ]
    else:  # Linux
        carpetas = [
            os.path.join(home, "Documentos"),
            os.path.join(home, "Música"),
            os.path.join(home, "Imágenes"),
            os.path.join(home, "Vídeos"),
            os.path.join(home, "Descargas"),
            os.path.join(home, "Escritorio"),
            os.path.join(home, "Public"),
            os.path.join(home, "Plantillas"),
        ]
        # También incluir versiones en inglés por si acaso
        carpetas.extend([
            os.path.join(home, "Documents"),
            os.path.join(home, "Music"),
            os.path.join(home, "Pictures"),
            os.path.join(home, "Videos"),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Desktop"),
        ])
    
    # Filtrar solo las que existen
    carpetas_existentes = [c for c in carpetas if os.path.exists(c)]
    return carpetas_existentes

def respaldo_general_archivos(config: Configuracion, gestor_estados: GestorEstados):
    """Realiza copia de seguridad de carpetas completas seleccionadas por el usuario"""
    
    print("\n" + "="*70)
    print("                 📂 RESPALDO GENERAL (CARPETAS COMPLETAS)")
    print("="*70)
    
    # 1. Obtener carpetas comunes del usuario
    carpetas_usuario = obtener_carpetas_usuario()
    
    print("\n📁 Carpetas comunes encontradas:")
    for i, carpeta in enumerate(carpetas_usuario, 1):
        nombre = os.path.basename(carpeta)
        print(f"  {i}. {nombre} -> {carpeta}")
    
    print("\n➕ También puedes añadir rutas personalizadas.")
    
    # 2. Selección de carpetas a respaldar
    carpetas_a_respaldar = []
    
    while True:
        print("\n🎯 Opciones:")
        print("   • Escribe el número de una carpeta para agregarla")
        print("   • Escribe una ruta personalizada directamente")
        print("   • Escribe 'ok' cuando hayas terminado de seleccionar")
        print("   • Escribe '0' para cancelar")
        
        entrada = input("➤ ").strip()
        
        if entrada == "0":
            print("❌ Operación cancelada.")
            return
        elif entrada.lower() == "ok":
            if not carpetas_a_respaldar:
                print("⚠️ No has seleccionado ninguna carpeta. Introduce al menos una.")
                continue
            break
        else:
            # Verificar si es un número (carpeta de la lista)
            if entrada.isdigit():
                idx = int(entrada) - 1
                if 0 <= idx < len(carpetas_usuario):
                    carpeta = carpetas_usuario[idx]
                    if carpeta not in carpetas_a_respaldar:
                        carpetas_a_respaldar.append(carpeta)
                        print(f"✅ Agregada: {carpeta}")
                    else:
                        print("⚠️ Ya está en la lista.")
                else:
                    print("❌ Número fuera de rango.")
            else:
                # Ruta personalizada
                ruta = expandir_ruta(entrada)
                if os.path.exists(ruta):
                    if ruta not in carpetas_a_respaldar:
                        carpetas_a_respaldar.append(ruta)
                        print(f"✅ Agregada: {ruta}")
                    else:
                        print("⚠️ Ya está en la lista.")
                else:
                    print(f"❌ La ruta no existe: {ruta}")
    
    # 3. Mostrar resumen de carpetas seleccionadas
    print("\n📋 Carpetas a respaldar:")
    for carpeta in carpetas_a_respaldar:
        print(f"   • {carpeta}")
    
    # 4. Solicitar destino
    destino_base = input("\n📁 Ruta para guardar el respaldo (Enter para 'Respaldos'): ").strip()
    if not destino_base:
        destino_base = "Respaldos"
    destino_base = expandir_ruta(destino_base)
    
    # Crear carpeta con timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    carpeta_destino = os.path.join(destino_base, f"Respaldo_General_{timestamp}")
    os.makedirs(carpeta_destino, exist_ok=True)
    print(f"✅ Carpeta de destino creada: {carpeta_destino}")
    
    # 5. Contar archivos totales para la barra de progreso
    print("\n🔍 Contando archivos a copiar...")
    total_archivos = 0
    archivos_info = []  # Lista de (ruta_origen, ruta_destino)
    
    for origen in carpetas_a_respaldar:
        for root, _, files in os.walk(origen):
            for file in files:
                ruta_origen = os.path.join(root, file)
                # Ruta relativa respecto a la carpeta origen
                rel_path = os.path.relpath(ruta_origen, origen)
                # Construir ruta destino manteniendo estructura
                ruta_destino = os.path.join(carpeta_destino, os.path.basename(origen), rel_path)
                archivos_info.append((ruta_origen, ruta_destino))
                total_archivos += 1
    
    if total_archivos == 0:
        print("⚠️ No se encontraron archivos para copiar.")
        input("\n⏎ Presiona ENTER para continuar...")
        return
    
    print(f"📊 Total de archivos a copiar: {total_archivos:,}")
    
    # 6. Crear estado de respaldo (opcional)
    estado_respaldo = None
    if config.guardar_estado_respaldos:
        estado_respaldo = gestor_estados.crear_estado(
            origen=" + ".join(carpetas_a_respaldar),
            destino=carpeta_destino,
            tipo="general",
            total_archivos=total_archivos
        )
        print(f"📝 Estado de respaldo guardado (ID: {estado_respaldo.id[:8]}...)")
    
    # 7. Barra de progreso
    barra = BarraProgreso(total_archivos, "Copiando archivos") if config.mostrar_progreso else None
    
    # 8. Copiar archivos
    archivos_copiados = 0
    archivos_error = 0
    
    for ruta_origen, ruta_destino in archivos_info:
        try:
            # Crear directorio de destino si no existe
            os.makedirs(os.path.dirname(ruta_destino), exist_ok=True)
            
            # Copiar archivo preservando metadatos
            shutil.copy2(ruta_origen, ruta_destino)
            
            archivos_copiados += 1
            
            if barra:
                barra.actualizar()
            
            # Actualizar estado cada 100 archivos
            if estado_respaldo and archivos_copiados % 100 == 0:
                estado_respaldo.procesados = archivos_copiados
                gestor_estados.guardar_estados()
                
        except PermissionError:
            print(f"\n⚠️ Permiso denegado: {ruta_origen}")
            archivos_error += 1
            if barra:
                barra.actualizar()
        except Exception as e:
            print(f"\n❌ Error copiando {ruta_origen}: {e}")
            archivos_error += 1
            if barra:
                barra.actualizar()
    
    if barra:
        barra.completar()
    
    # 9. Finalizar estado
    if estado_respaldo:
        gestor_estados.completar_respaldo(estado_respaldo.id)
    
    # 10. Resumen final
    print("\n" + "="*70)
    print("📊 RESUMEN DEL RESPALDO GENERAL")
    print("="*70)
    print(f"✅ Carpetas respaldadas: {len(carpetas_a_respaldar)}")
    print(f"✅ Archivos copiados: {archivos_copiados:,} de {total_archivos:,}")
    print(f"❌ Archivos con error: {archivos_error}")
    print(f"💾 Carpeta de respaldo: {carpeta_destino}")
    print("="*70)
    
    # 11. Registrar en archivo de rutas
    if config.registrar_rutas:
        with open("rutas_respaldo.txt", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}|{carpeta_destino}|general|{len(carpetas_a_respaldar)} carpetas|{archivos_copiados} archivos\n")
    
    # 12. Preguntar si comprimir (si la opción automática no está activada)
    if not config.comprimir_automatico:
        comprimir = input("\n¿Deseas comprimir el respaldo en ZIP? (sí/NO): ").strip().lower()
        if comprimir in ['si', 'sí', 'yes', 'y']:
            comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    else:
        # Si compresión automática está activada, comprimir directamente
        comprimir_respaldo(carpeta_destino, config.nivel_compresion)
    
    input("\n⏎ Presiona ENTER para continuar...")

# ============================================================================
# FUNCIONES AUXILIARES PARA COMPRESIÓN Y CREACIÓN DE CARPETAS
# ============================================================================

def crear_carpeta_respaldo(destino_base: str) -> str:
    """Crea una carpeta de respaldo con nombre único"""
    fecha = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    carpeta_respaldo = os.path.join(destino_base, f"Respaldo_{fecha}")
    os.makedirs(carpeta_respaldo, exist_ok=True)
    return carpeta_respaldo

def comprimir_respaldo(carpeta_respaldo: str, nivel_compresion: int = 6):
    """Comprime el respaldo en archivo ZIP"""
    zip_file = f"{carpeta_respaldo}.zip"
    try:
        with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED, compresslevel=nivel_compresion) as zf:
            for root, _, files in os.walk(carpeta_respaldo):
                for file in files:
                    ruta_completa = os.path.join(root, file)
                    zf.write(ruta_completa, os.path.relpath(ruta_completa, carpeta_respaldo))
        print(f"✅ Respaldo comprimido: {zip_file}")
        
        # Eliminar carpeta original
        try:
            shutil.rmtree(carpeta_respaldo)
            print(f"🗑️ Carpeta original eliminada: {carpeta_respaldo}")
        except:
            print(f"⚠️ No se pudo eliminar la carpeta original: {carpeta_respaldo}")
            
    except Exception as e:
        print(f"❌ Error al comprimir: {e}")

# ============================================================================
# MENÚ PRINCIPAL COMPLETO (MODIFICADO)
# ============================================================================

def menu_principal():
    """Menú principal del sistema de respaldos"""
    
    # Cargar configuración
    config = Configuracion.cargar()
    
    # Inicializar gestor de estados
    gestor_estados = GestorEstados()
    
    while True:
        limpiar_terminal()
        
        print("\n" + "="*70)
        print("                 🗂️ SISTEMA DE RESPALDOS AVANZADO")
        print("="*70)
        
        # Información del sistema
        print(f"💻 Sistema: {platform.system()} {platform.release()}")
        print(f"👤 Usuario: {os.path.expanduser('~').split(os.sep)[-1]}")
        print(f"📅 Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Mostrar respaldos pendientes si existen
        respaldos_pendientes = len(gestor_estados.obtener_respaldos_pausados())
        if respaldos_pendientes > 0:
            print(f"⏸️  Respaldos interrumpidos: {respaldos_pendientes}")
        
        # Estado de configuraciones
        print(f"\n⚙️  CONFIGURACIÓN:")
        print(f"   📝 Registrar rutas: {'✅ Activado' if config.registrar_rutas else '❌ Desactivado'}")
        print(f"   📊 Barra de progreso: {'✅ Activada' if config.mostrar_progreso else '❌ Desactivada'}")
        print(f"   📦 Compresión automática: {'✅ Activada' if config.comprimir_automatico else '❌ Desactivada'}")
        print(f"   💾 Guardar estado respaldos: {'✅ Activado' if config.guardar_estado_respaldos else '❌ Desactivado'}")
        
        print("\n" + "="*70)
        print("📋 MENÚ PRINCIPAL:")
        print(" 1) 📂 Respaldo general (carpetas completas: Documentos, Música, etc.)")
        print(" 2) 🔤 Respaldo por extensiones (documentos, código, multimedia)")
        print(" 3) 💾 Respaldo de unidades externas (copia de archivos)")
        print(" 4) 🗄️ Respaldo XAMPP/MySQL")
        print(" 5) 🔄 Reanudar respaldo interrumpido")
        print(" 6) ⚙️ Configuración del sistema")
        print(" 7) 📜 Ver registros de respaldos")
        print(" 8) 🗑️ Eliminar respaldo (solo generados por el programa)")
        print(" 9) 🚪 Salir")
        print("="*70)
        
        opcion = input("\n🎯 Selecciona una opción (1-9): ").strip()
        
        if opcion == "1":
            respaldo_general_archivos(config, gestor_estados)
        
        elif opcion == "2":
            destino = input("\n📁 Ruta para guardar respaldo (Enter para 'Respaldos'): ").strip()
            if not destino:
                destino = "Respaldos"
            destino = expandir_ruta(destino)
            
            carpeta_respaldo = crear_carpeta_respaldo(destino)
            respaldo_por_extensiones(carpeta_respaldo, config)
            
            if config.comprimir_automatico:
                comprimir_respaldo(carpeta_respaldo, config.nivel_compresion)
            
            input("\n⏎ Presiona ENTER para continuar...")
        
        elif opcion == "3":
            destino = input("\n📁 Ruta para guardar respaldo (Enter para 'Respaldos'): ").strip()
            if not destino:
                destino = "Respaldos"
            destino = expandir_ruta(destino)
            
            carpeta_respaldo = crear_carpeta_respaldo(destino)
            respaldo_unidad_externa(carpeta_respaldo, config, gestor_estados)
            
            if config.comprimir_automatico:
                comprimir_respaldo(carpeta_respaldo, config.nivel_compresion)
        
        elif opcion == "4":
            destino = input("\n📁 Ruta para guardar respaldo (Enter para 'Respaldos'): ").strip()
            if not destino:
                destino = "Respaldos"
            destino = expandir_ruta(destino)
            
            carpeta_respaldo = crear_carpeta_respaldo(destino)
            respaldo_xampp_mysql(carpeta_respaldo, config)
            
            if config.comprimir_automatico:
                comprimir_respaldo(carpeta_respaldo, config.nivel_compresion)
            
            input("\n⏎ Presiona ENTER para continuar...")
        
        elif opcion == "5":
            reanudar_respaldo_interrumpido(config, gestor_estados)
        
        elif opcion == "6":
            menu_configuracion(config)
        
        elif opcion == "7":
            mostrar_registros()
        
        elif opcion == "8":
            destino_base = input("\n📁 Ruta base de respaldos (Enter para 'Respaldos'): ").strip()
            if not destino_base:
                destino_base = "Respaldos"
            destino_base = expandir_ruta(destino_base)
            eliminar_respaldo_seguro(destino_base)
        
        elif opcion == "9":
            print("\n👋 ¡Hasta pronto!")
            config.guardar()
            gestor_estados.guardar_estados()
            break
        
        else:
            print("❌ Opción no válida. Intenta de nuevo.")
            time.sleep(1)

def menu_configuracion(config: Configuracion):
    """Menú de configuración del sistema"""
    
    while True:
        limpiar_terminal()
        print("\n" + "="*50)
        print("          ⚙️ CONFIGURACIÓN DEL SISTEMA")
        print("="*50)
        
        print(f"\n1) Registrar rutas en archivo: {'✅ Activado' if config.registrar_rutas else '❌ Desactivado'}")
        print(f"2) Mostrar barra de progreso: {'✅ Activada' if config.mostrar_progreso else '❌ Desactivada'}")
        print(f"3) Compresión automática: {'✅ Activada' if config.comprimir_automatico else '❌ Desactivada'}")
        print(f"4) Guardar estado de respaldos: {'✅ Activado' if config.guardar_estado_respaldos else '❌ Desactivado'}")
        print(f"5) Nivel de compresión: {config.nivel_compresion}/9")
        print("6) Guardar y volver")
        print("="*50)
        
        opcion = input("\nSelecciona opción a cambiar (1-6): ").strip()
        
        if opcion == "1":
            config.registrar_rutas = not config.registrar_rutas
            estado = "Activado" if config.registrar_rutas else "Desactivado"
            print(f"✓ Registrar rutas: {estado}")
            time.sleep(1)
        
        elif opcion == "2":
            config.mostrar_progreso = not config.mostrar_progreso
            estado = "Activada" if config.mostrar_progreso else "Desactivada"
            print(f"✓ Barra de progreso: {estado}")
            time.sleep(1)
        
        elif opcion == "3":
            config.comprimir_automatico = not config.comprimir_automatico
            estado = "Activada" if config.comprimir_automatico else "Desactivada"
            print(f"✓ Compresión automática: {estado}")
            time.sleep(1)
        
        elif opcion == "4":
            config.guardar_estado_respaldos = not config.guardar_estado_respaldos
            estado = "Activado" if config.guardar_estado_respaldos else "Desactivado"
            print(f"✓ Guardar estado respaldos: {estado}")
            time.sleep(1)
        
        elif opcion == "5":
            try:
                nivel = int(input("Nivel de compresión (0-9, 0=sin compresión, 9=máxima): "))
                if 0 <= nivel <= 9:
                    config.nivel_compresion = nivel
                    print(f"✓ Nivel de compresión establecido a {nivel}")
                else:
                    print("❌ El nivel debe estar entre 0 y 9")
            except ValueError:
                print("❌ Entrada inválida")
            time.sleep(1)
        
        elif opcion == "6":
            config.guardar()
            print("✅ Configuración guardada")
            break
        
        else:
            print("❌ Opción no válida")
            time.sleep(1)

# ============================================================================
# INICIO DEL PROGRAMA
# ============================================================================

def iniciar_programa():
    """Función principal de inicio del programa"""
    
    try:
        # Crear directorios necesarios
        os.makedirs("Respaldos", exist_ok=True)
        
        # Verificar archivos de configuración
        if not os.path.exists("config.json"):
            config = Configuracion()
            config.guardar()
            print("✅ Archivo de configuración creado")
        
        # Mostrar banner
        limpiar_terminal()
        print("\n" + "="*70)
        print("                 SISTEMA DE RESPALDOS AVANZADO")
        print("="*70)
        print("✅ Restricción de eliminación activada")
        print("✅ Barra de progreso disponible")
        print("✅ Registro de rutas en archivo")
        print("✅ Respaldos por extensión (solo carpetas necesarias)")
        print("✅ Respaldo XAMPP/MySQL disponible")
        print("✅ Detección de unidades externas (Windows/macOS/Linux)")
        print("✅ Sistema de reanudación de respaldos interrumpidos")
        print("✅ Respaldo general de carpetas (Documentos, Música, etc.)")
        print("="*70)
        time.sleep(2)
        
        # Iniciar menú principal
        menu_principal()
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Programa interrumpido por el usuario")
    
    except Exception as e:
        print(f"\n💥 Error crítico: {e}")
        print("Por favor, contacta al soporte técnico.")
        input("\nPresiona ENTER para salir...")

# ============================================================================
# EJECUCIÓN
# ============================================================================

if __name__ == "__main__":
    iniciar_programa()