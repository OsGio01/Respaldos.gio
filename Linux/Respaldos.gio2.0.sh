#!/bin/bash

clear
usuario=$(whoami)
comprimir_activado=true
ultima_carpeta=""

# Colores
VERDE="\e[32m"
ROJO="\e[31m"
AMARILLO="\e[33m"
CYAN="\e[36m"
RESET="\e[0m"

# -------------------------------
# Archivo log
# -------------------------------
log=""

# -------------------------------
# Función para leer rutas estándar del usuario
# -------------------------------
leer_ruta_usuario() {
    clave=$1
    archivo="$HOME/.config/user-dirs.dirs"
    if [[ -f "$archivo" ]]; then
        valor=$(grep "^$clave=" "$archivo" | head -n 1 | cut -d= -f2 | tr -d '"')
        valor="${valor/\$HOME/$HOME}"
        echo "$valor"
    else
        case "$clave" in
            XDG_DESKTOP_DIR) echo "$HOME/Desktop" ;;
            XDG_DOCUMENTS_DIR) echo "$HOME/Documents" ;;
            XDG_DOWNLOAD_DIR) echo "$HOME/Downloads" ;;
            XDG_MUSIC_DIR) echo "$HOME/Music" ;;
            XDG_PICTURES_DIR) echo "$HOME/Pictures" ;;
            XDG_VIDEOS_DIR) echo "$HOME/Videos" ;;
            *) echo "$HOME" ;;
        esac
    fi
}

# -------------------------------
# Función para detectar memorias externas
# -------------------------------
detectar_memorias() {
    puntos_montaje=()
    nombres_memorias=()
    for base in "/media/$usuario" "/run/media/$usuario"; do
        if [[ -d "$base" ]]; then
            for d in "$base"/*; do
                if [[ -d "$d" ]]; then
                    puntos_montaje+=("$d")
                    nombres_memorias+=("$(basename "$d")")
                fi
            done
        fi
    done
}

# -------------------------------
# Función para seleccionar destino
# -------------------------------
menu_destino() {
    echo "Selecciona donde quieres guardar los respaldos:"
    echo "0) Carpeta actual ($(pwd))"
    for i in "${!puntos_montaje[@]}"; do
        echo "$((i+1))) ${nombres_memorias[$i]} - ${puntos_montaje[$i]}"
    done
    echo "$(( ${#puntos_montaje[@]} + 1 )) ) Otra ruta manual"

    read -p "Ingresa el numero de opcion: " opcion
    if [[ "$opcion" =~ ^[0-9]+$ ]]; then
        if [[ "$opcion" -eq 0 ]]; then
            destino="$(pwd)"
            nombre_memoria=""
        elif [[ "$opcion" -ge 1 && "$opcion" -le ${#puntos_montaje[@]} ]]; then
            idx=$((opcion - 1))
            destino="${puntos_montaje[$idx]}"
            nombre_memoria="${nombres_memorias[$idx]}"
        elif [[ "$opcion" -eq $(( ${#puntos_montaje[@]} + 1 )) ]]; then
            read -p "Escribe la ruta manual: " ruta_manual
            destino=$(eval echo "$ruta_manual")
            if [[ ! -d "$destino" ]]; then
                mkdir -p "$destino" || { echo "No se pudo crear la ruta."; exit 1; }
            fi
            nombre_memoria=""
        else
            echo "Opcion invalida."
            exit 1
        fi
    else
        echo "Opcion invalida."
        exit 1
    fi
}

# -------------------------------
# Crear carpeta de respaldo
# -------------------------------
crear_carpeta_respaldo() {
    fecha=$(date +"%Y-%m-%d_%H-%M-%S")
    if [[ -n "$nombre_memoria" ]]; then
        carpeta_respaldo="$destino/Respaldo_${nombre_memoria}_$fecha"
    else
        carpeta_respaldo="$destino/Respaldo_$fecha"
    fi
    mkdir -p "$carpeta_respaldo" || { echo "Error creando carpeta de respaldo"; exit 1; }
    log="$carpeta_respaldo/log.txt"
    echo "Iniciando respaldo $fecha" > "$log"
    ultima_carpeta="$carpeta_respaldo"
}

# -------------------------------
# Función para registrar logs
# -------------------------------
log_info() {
    mensaje="$1"
    echo -e "$mensaje"
    echo "$mensaje" >> "$log"
}

# -------------------------------
# Respaldo general
# -------------------------------
respaldo_general() {
    carpetas=( 
        "$(leer_ruta_usuario XDG_DOCUMENTS_DIR)"
        "$(leer_ruta_usuario XDG_DOWNLOAD_DIR)"
        "$(leer_ruta_usuario XDG_DESKTOP_DIR)"
        "$(leer_ruta_usuario XDG_PICTURES_DIR)"
        "$(leer_ruta_usuario XDG_MUSIC_DIR)"
        "$(leer_ruta_usuario XDG_VIDEOS_DIR)"
    )
    for carpeta in "${carpetas[@]}"; do
        if [[ -d "$carpeta" ]]; then
            log_info "Respaldando $carpeta..."
            cp -r "$carpeta" "$carpeta_respaldo" 2>/dev/null && log_info "Respaldo exitoso de $carpeta" || log_info "Error al respaldar $carpeta"
        else
            log_info "No existe $carpeta, se omite."
        fi
    done
    $comprimir_activado && comprimir_respaldo
}

# -------------------------------
# Respaldo por extensiones
# -------------------------------
respaldo_extensiones() {
    extensiones=("pdf" "docx" "xlsx" "pptx" "txt" "jpg" "png" "mp4" "mp3" "zip" "rar")
    for ext in "${extensiones[@]}"; do
        mkdir -p "$carpeta_respaldo/$ext"
        find "$HOME" -type f -iname "*.$ext" 2>/dev/null | while read -r archivo; do
            cp "$archivo" "$carpeta_respaldo/$ext/" 2>/dev/null && log_info "Copiado: $archivo" || log_info "Error copiando: $archivo"
        done
    done
    $comprimir_activado && comprimir_respaldo
}

# -------------------------------
# Respaldar una unidad seleccionada
# -------------------------------
respaldar_unidad() {
    if [[ ${#puntos_montaje[@]} -eq 0 ]]; then
        log_info "No hay unidades externas conectadas."
        return
    fi

    echo "Selecciona la unidad a respaldar:"
    for i in "${!puntos_montaje[@]}"; do
        echo "$((i+1))) ${nombres_memorias[$i]} - ${puntos_montaje[$i]}"
    done
    read -p "Ingresa el numero de unidad: " opcion_unidad
    if [[ "$opcion_unidad" =~ ^[0-9]+$ ]] && [[ $opcion_unidad -ge 1 ]] && [[ $opcion_unidad -le ${#puntos_montaje[@]} ]]; then
        idx=$((opcion_unidad -1))
        destino_memoria="$carpeta_respaldo/Unidad_${nombres_memorias[$idx]}"
        mkdir -p "$destino_memoria"
        cp -r "${puntos_montaje[$idx]}"/* "$destino_memoria/" 2>/dev/null && log_info "Respaldado ${nombres_memorias[$idx]}" || log_info "Error respaldando ${nombres_memorias[$idx]}"
        $comprimir_activado && comprimir_respaldo
    else
        echo "Opcion invalida."
    fi
}

# -------------------------------
# Respaldo XAMPP
# -------------------------------
respaldo_xampp() {
    ruta="$HOME/xampp/htdocs"
    if [[ -d "$ruta" ]]; then
        cp -r "$ruta" "$carpeta_respaldo/htdocs" 2>/dev/null && log_info "Respaldo XAMPP completado" || log_info "Error respaldo XAMPP"
    else
        log_info "No existe carpeta XAMPP, se omite"
    fi
    $comprimir_activado && comprimir_respaldo
}

# -------------------------------
# Eliminar respaldos
# -------------------------------
eliminar_respaldos() {
    respaldos=("$destino"/Respaldo_*)
    if [[ ${#respaldos[@]} -eq 0 ]]; then
        log_info "No hay respaldos para eliminar."
        return
    fi

    echo "Respaldos disponibles:"
    for i in "${!respaldos[@]}"; do
        echo "$((i+1))) $(basename "${respaldos[$i]}")"
    done
    echo "a) Eliminar todos"

    read -p "Selecciona el respaldo a eliminar (numero) o 'a' para todos: " opcion
    if [[ "$opcion" == "a" ]]; then
        for r in "${respaldos[@]}"; do
            rm -rf "$r" && log_info "Eliminado $r" || log_info "Error eliminando $r"
        done
    elif [[ "$opcion" =~ ^[0-9]+$ ]] && [[ $opcion -ge 1 ]] && [[ $opcion -le ${#respaldos[@]} ]]; then
        idx=$((opcion-1))
        rm -rf "${respaldos[$idx]}" && log_info "Eliminado ${respaldos[$idx]}" || log_info "Error eliminando ${respaldos[$idx]}"
    else
        echo "Opción inválida."
    fi
}

# -------------------------------
# Comprimir respaldo
# -------------------------------
comprimir_respaldo() {
    if [[ -z "$ultima_carpeta" ]]; then
        log_info "No hay respaldo previo para comprimir."
        return
    fi
    zip_file="${ultima_carpeta}.zip"
    zip -r "$zip_file" "$ultima_carpeta" >/dev/null 2>&1 && log_info "Respaldo comprimido: $zip_file" || log_info "Error comprimiendo respaldo"
}

# -------------------------------
# Menú
# -------------------------------
mostrar_menu() {
    echo "====== MENÚ RESPALDOS ======"
    if $comprimir_activado; then
        estado="${VERDE}Activado ✅${RESET}"
    else
        estado="${ROJO}Desactivado ❌${RESET}"
    fi
    echo "1) Respaldo general"
    echo "2) Respaldo por extensiones"
    echo "3) Respaldar unidad externa (elige cual)"
    echo "4) Respaldo XAMPP"
    echo "5) Eliminar respaldos anteriores"
    echo "6) Comprimir ultimo respaldo"
    echo -e "7) Alternar compresion automatica [$estado]"
    echo "8) Salir"
    echo "==========================="
}

# -------------------------------
# Inicio
# -------------------------------
detectar_memorias
menu_destino
crear_carpeta_respaldo

while true; do
    clear
    mostrar_menu
    read -p "Selecciona opción: " opcion
    case $opcion in
        1) crear_carpeta_respaldo; respaldo_general ;;
        2) crear_carpeta_respaldo; respaldo_extensiones ;;
        3) crear_carpeta_respaldo; respaldar_unidad ;;
        4) crear_carpeta_respaldo; respaldo_xampp ;;
        5) eliminar_respaldos ;;
        6) comprimir_respaldo ;;
        7) 
            if $comprimir_activado; then
                comprimir_activado=false
                echo -e "${ROJO}Compresion automatica desactivada ❌${RESET}"
            else
                comprimir_activado=true
                echo -e "${VERDE}Compresion automatica activada ✅${RESET}"
            fi
            read -p "Presiona Enter para continuar..."
            ;;
        8) echo "Saliendo..."; exit 0 ;;
        *) echo "Opción inválida";;
    esac
    read -p "Presiona Enter para continuar..."
done