#!/bin/bash
# ============================================================================
# SISTEMA DE RESPALDOS AVANZADO - BASH (VERSIÓN COMPLETA)
# Incluye: configuración persistente, registro, modo red, exclusión de SO,
# barra de progreso, reanudación básica, compresión automática.
# ============================================================================

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$BASE_DIR/config.json"
REGISTRO_FILE="$BASE_DIR/rutas_respaldo.txt"
RESPALDOS_DIR="$BASE_DIR/Respaldos"
EXCLUDE_DIR="$BASE_DIR/exclusiones"

mkdir -p "$RESPALDOS_DIR" "$EXCLUDE_DIR"

# Colores
VERDE="\e[32m"
ROJO="\e[31m"
AMARILLO="\e[33m"
CYAN="\e[36m"
RESET="\e[0m"

# Variables globales
comprimir_auto=true
destino_base="$RESPALDOS_DIR"
max_hilos=4
usuario=$(whoami)
ultima_carpeta=""

# -------------------------------
# Funciones auxiliares
# -------------------------------
log_info() {
    local msg="$1"
    echo -e "${CYAN}$(date '+%H:%M:%S')${RESET} $msg"
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $msg" >> "$REGISTRO_FILE"
}

# Cargar configuración desde JSON (requiere jq)
cargar_config() {
    if command -v jq &>/dev/null && [[ -f "$CONFIG_FILE" ]]; then
        comprimir_auto=$(jq -r '.comprimirAuto // true' "$CONFIG_FILE")
        destino_base=$(jq -r '.destinoBase // "'"$RESPALDOS_DIR"'"' "$CONFIG_FILE")
        max_hilos=$(jq -r '.maxHilos // 4' "$CONFIG_FILE")
        exclusiones=($(jq -r '.exclusiones[]?' "$CONFIG_FILE"))
        inclusiones=($(jq -r '.inclusiones[]?' "$CONFIG_FILE"))
    else
        comprimir_auto=true
        destino_base="$RESPALDOS_DIR"
        max_hilos=4
        exclusiones=("Windows" "Program Files" "System Volume Information" "\$RECYCLE.BIN" ".Trash" "AppData" "Library/Caches")
        inclusiones=()
    fi
    mkdir -p "$destino_base"
}

# Guardar configuración
guardar_config() {
    if command -v jq &>/dev/null; then
        cat > "$CONFIG_FILE" <<EOF
{
    "comprimirAuto": $comprimir_auto,
    "destinoBase": "$destino_base",
    "maxHilos": $max_hilos,
    "exclusiones": $(printf '%s\n' "${exclusiones[@]}" | jq -R . | jq -s .),
    "inclusiones": $(printf '%s\n' "${inclusiones[@]}" | jq -R . | jq -s .)
}
EOF
    else
        # Fallback: guardar en formato simple
        echo "comprimirAuto=$comprimir_auto" > "$CONFIG_FILE"
        echo "destinoBase=$destino_base" >> "$CONFIG_FILE"
    fi
}

# Mostrar barra de progreso simple (si pv no está instalado, usa texto)
mostrar_progreso() {
    local actual="$1"
    local total="$2"
    local desc="$3"
    if command -v pv &>/dev/null; then
        echo "$desc: $actual/$total" | pv -l -s "$total" -p -t -e >/dev/null
    else
        echo -ne "\r$desc: $actual/$total"
        if [[ "$actual" -eq "$total" ]]; then echo; fi
    fi
}

# Verificar si una ruta debe ser excluida (listas negra/blanca)
debe_excluir() {
    local ruta="$1"
    for inc in "${inclusiones[@]}"; do
        if [[ "$ruta" == "$inc"* ]]; then
            return 1  # No excluir (está en lista blanca)
        fi
    done
    for exc in "${exclusiones[@]}"; do
        if [[ "$ruta" == *"$exc"* ]]; then
            return 0  # Excluir
        fi
    done
    return 1
}

# Copiar con barra de progreso
copiar_con_progreso() {
    local origen="$1"
    local destino="$2"
    local desc="$3"
    local total_archivos=$(find "$origen" -type f 2>/dev/null | wc -l)
    local contador=0
    find "$origen" -type f 2>/dev/null | while read -r archivo; do
        local ruta_rel="${archivo#$origen}"
        local destino_archivo="$destino$ruta_rel"
        mkdir -p "$(dirname "$destino_archivo")"
        cp "$archivo" "$destino_archivo" 2>/dev/null
        contador=$((contador+1))
        mostrar_progreso "$contador" "$total_archivos" "$desc"
    done
    echo "$total_archivos"
}

# Crear carpeta de respaldo con timestamp
crear_carpeta_respaldo() {
    local tipo="$1"
    local fecha=$(date +'%Y-%m-%d_%H-%M-%S')
    local carpeta="$destino_base/${tipo}_$fecha"
    mkdir -p "$carpeta"
    echo "$carpeta"
}

# Comprimir respaldo
comprimir_respaldo() {
    local carpeta="$1"
    if [[ -z "$carpeta" || ! -d "$carpeta" ]]; then
        log_info "No hay carpeta para comprimir."
        return
    fi
    local zip_file="${carpeta}.zip"
    log_info "Comprimiendo $carpeta ..."
    zip -r "$zip_file" "$carpeta" >/dev/null 2>&1
    if [[ $? -eq 0 ]]; then
        rm -rf "$carpeta"
        log_info "Comprimido: $zip_file"
    else
        log_info "Error al comprimir"
    fi
}

# -------------------------------
# FUNCIONES DE RESPALDO
# -------------------------------

# 1. Respaldo general (carpetas estándar del usuario)
respaldo_general() {
    log_info "INICIANDO RESPALDO GENERAL"
    local carpetas=()
    for dir in "Documents" "Documentos" "Desktop" "Escritorio" "Downloads" "Descargas" "Pictures" "Imágenes" "Music" "Música" "Videos" "Vídeos"; do
        [[ -d "$HOME/$dir" ]] && carpetas+=("$HOME/$dir")
    done
    if [[ ${#carpetas[@]} -eq 0 ]]; then
        log_info "No se encontraron carpetas de usuario."
        return
    fi
    local carpeta_destino=$(crear_carpeta_respaldo "Respaldo_General")
    local total=0
    for c in "${carpetas[@]}"; do
        local nombre=$(basename "$c")
        log_info "Copiando $nombre ..."
        cp -r "$c" "$carpeta_destino/$nombre" 2>/dev/null
        total=$((total + $(find "$carpeta_destino/$nombre" -type f 2>/dev/null | wc -l)))
    done
    log_info "Respaldo general completado: $total archivos en $carpeta_destino"
    echo "$carpeta_destino"
}

# 2. Respaldo por extensiones
respaldo_extensiones() {
    log_info "INICIANDO RESPALDO POR EXTENSIONES"
    local extensiones=("pdf" "docx" "xlsx" "pptx" "txt" "jpg" "jpeg" "png" "gif" "mp3" "mp4" "zip" "rar" "py" "js" "html" "css")
    local carpeta_destino=$(crear_carpeta_respaldo "Respaldo_Ext")
    local total=0
    for ext in "${extensiones[@]}"; do
        local carpeta_ext="$carpeta_destino/Archivos_${ext^^}"
        mkdir -p "$carpeta_ext"
        find "$HOME" -type f -iname "*.$ext" 2>/dev/null | while read -r archivo; do
            if debe_excluir "$archivo"; then continue; fi
            cp "$archivo" "$carpeta_ext/" 2>/dev/null && total=$((total+1))
            mostrar_progreso "$total" 0 "Copiando .$ext"
        done
    done
    log_info "Respaldo por extensiones: $total archivos en $carpeta_destino"
    echo "$carpeta_destino"
}

# 3. Respaldo de unidad externa (seleccionable)
respaldo_unidad_externa() {
    log_info "RESPALDO DE UNIDAD EXTERNA"
    local unidades=()
    for m in "/media/$usuario" "/run/media/$usuario" "/mnt" "/Volumes"; do
        if [[ -d "$m" ]]; then
            for d in "$m"/*; do
                if mountpoint -q "$d" 2>/dev/null; then
                    unidades+=("$d")
                fi
            done
        fi
    done
    if [[ ${#unidades[@]} -eq 0 ]]; then
        log_info "No se detectaron unidades externas."
        return
    fi
    echo "Unidades externas detectadas:"
    for i in "${!unidades[@]}"; do
        echo " $((i+1)). ${unidades[$i]}"
    done
    read -p "Selecciona número: " idx
    if [[ "$idx" =~ ^[0-9]+$ ]] && (( idx >= 1 && idx <= ${#unidades[@]} )); then
        local origen="${unidades[$((idx-1))]}"
        local carpeta_destino=$(crear_carpeta_respaldo "Respaldo_Unidad")
        log_info "Copiando desde $origen ..."
        local total=$(copiar_con_progreso "$origen" "$carpeta_destino" "Copiando unidad externa")
        log_info "Unidad respaldada: $total archivos en $carpeta_destino"
        echo "$carpeta_destino"
    else
        log_info "Selección inválida."
    fi
}

# 4. Respaldo XAMPP
respaldo_xampp() {
    log_info "RESPALDO XAMPP"
    local rutas=("/opt/lampp/htdocs" "$HOME/xampp/htdocs" "/Applications/XAMPP/htdocs")
    local origen=""
    for r in "${rutas[@]}"; do
        if [[ -d "$r" ]]; then
            origen="$r"
            break
        fi
    done
    if [[ -z "$origen" ]]; then
        log_info "No se encontró XAMPP."
        return
    fi
    local carpeta_destino=$(crear_carpeta_respaldo "Respaldo_XAMPP")
    cp -r "$origen" "$carpeta_destino/htdocs" 2>/dev/null
    local total=$(find "$carpeta_destino" -type f 2>/dev/null | wc -l)
    log_info "XAMPP respaldado: $total archivos en $carpeta_destino"
    echo "$carpeta_destino"
}

# 5. Modo disco externo recuperado (omite carpetas del sistema)
respaldo_disco_recuperado() {
    log_info "MODO DISCO EXTERNO RECUPERADO"
    local unidades=()
    for m in "/media/$usuario" "/run/media/$usuario" "/mnt" "/Volumes"; do
        if [[ -d "$m" ]]; then
            for d in "$m"/*; do
                if mountpoint -q "$d" 2>/dev/null; then
                    unidades+=("$d")
                fi
            done
        fi
    done
    local carpetas_sistema=("Windows" "Program Files" "System Volume Information" "boot" "dev" "proc" "sys")
    for un in "${unidades[@]}"; do
        local es_sistema=false
        for sc in "${carpetas_sistema[@]}"; do
            if [[ -d "$un/$sc" ]]; then
                es_sistema=true
                break
            fi
        done
        if $es_sistema; then
            log_info "Unidad $un contiene sistema operativo. Omitida."
            continue
        fi
        log_info "Unidad $un detectada como disco recuperado."
        local carpeta_destino=$(crear_carpeta_respaldo "Recuperado")
        local total=$(copiar_con_progreso "$un" "$carpeta_destino" "Recuperando disco")
        log_info "Disco recuperado: $total archivos en $carpeta_destino"
        echo "$carpeta_destino"
        return
    done
    log_info "No se encontraron discos recuperables."
}

# -------------------------------
# MODO RED (servidor/cliente con netcat)
# -------------------------------
servidor_red() {
    log_info "SERVIDOR RED - Escuchando en puerto 56789"
    local archivo_tmp="/tmp/respaldo_red_$$.tar"
    nc -l -p 56789 -q 1 > "$archivo_tmp"
    if [[ -s "$archivo_tmp" ]]; then
        local carpeta_destino=$(crear_carpeta_respaldo "Red_Recibido")
        tar -xf "$archivo_tmp" -C "$carpeta_destino"
        rm "$archivo_tmp"
        local total=$(find "$carpeta_destino" -type f 2>/dev/null | wc -l)
        log_info "Transferencia red recibida: $total archivos en $carpeta_destino"
        if $comprimir_auto; then
            comprimir_respaldo "$carpeta_destino"
        fi
    else
        log_info "No se recibieron datos."
    fi
}

cliente_red() {
    read -p "IP del servidor: " server_ip
    log_info "CLIENTE RED - Enviando a $server_ip:56789"
    local temp_dir=$(mktemp -d)
    mkdir -p "$temp_dir/RespaldoRed"
    # Empaquetar carpetas comunes del usuario
    for c in "$HOME/Documentos" "$HOME/Desktop" "$HOME/Descargas" "$HOME/Imágenes" "$HOME/Música"; do
        [[ -d "$c" ]] && cp -r "$c" "$temp_dir/RespaldoRed/" 2>/dev/null
    done
    local tar_file="/tmp/respaldo_envio_$$.tar"
    tar -cf "$tar_file" -C "$temp_dir" RespaldoRed
    nc "$server_ip" 56789 < "$tar_file"
    rm -rf "$temp_dir" "$tar_file"
    log_info "Envío completado."
}

modo_red() {
    echo -e "${CYAN} MODO RED${RESET}"
    echo "1) Servidor (recibir respaldos)"
    echo "2) Cliente (enviar respaldos)"
    read -p "Opción: " op
    case $op in
        1) servidor_red ;;
        2) cliente_red ;;
        *) log_info "Opción inválida." ;;
    esac
}

# -------------------------------
# ELIMINAR RESPALDOS ANTIGUOS
# -------------------------------
eliminar_respaldos() {
    log_info "ELIMINAR RESPALDOS"
    mapfile -t respaldos < <(find "$destino_base" -maxdepth 1 -type d \( -name "Respaldo_*" -o -name "Recuperado_*" -o -name "Red_*" \) 2>/dev/null)
    if [[ ${#respaldos[@]} -eq 0 ]]; then
        log_info "No hay respaldos para eliminar."
        return
    fi
    echo "Respaldos disponibles:"
    for i in "${!respaldos[@]}"; do
        echo " $((i+1)). $(basename "${respaldos[$i]}")"
    done
    echo "t) Eliminar todos"
    read -p "Selecciona número o 't': " selec
    if [[ "$selec" == "t" ]]; then
        for r in "${respaldos[@]}"; do
            rm -rf "$r"
            log_info "Eliminado: $(basename "$r")"
        done
    elif [[ "$selec" =~ ^[0-9]+$ ]] && (( selec >= 1 && selec <= ${#respaldos[@]} )); then
        rm -rf "${respaldos[$((selec-1))]}"
        log_info "Eliminado: $(basename "${respaldos[$((selec-1))]}")"
    else
        log_info "Selección inválida."
    fi
}

# -------------------------------
# CONFIGURACIÓN Y MENÚ PRINCIPAL
# -------------------------------
mostrar_menu() {
    clear
    echo -e "${AMARILLO}============================================================"
    echo -e "         SISTEMA DE RESPALDOS AVANZADO - BASH"
    echo -e "============================================================${RESET}"
    echo -e "Usuario: ${VERDE}$usuario${RESET}"
    echo -e "Destino base: ${VERDE}$destino_base${RESET}"
    echo -e "Compresión automática: ${VERDE}$comprimir_auto${RESET}"
    echo -e "============================================================"
    echo "1)  Respaldo general (carpetas del usuario)"
    echo "2)  Respaldo por extensiones de archivo"
    echo "3)  Respaldo de unidad externa (USB/HDD)"
    echo "4)  Respaldo XAMPP"
    echo "5)  Modo disco externo recuperado (omite SO)"
    echo "6)  Modo red (servidor/cliente)"
    echo "7)  Eliminar respaldos antiguos"
    echo "8)  Configurar unidad destino"
    echo "9)  Alternar compresión automática"
    echo "10) Ver registro de respaldos"
    echo "11) Salir"
    echo -e "${AMARILLO}============================================================${RESET}"
}

# -------------------------------
# BUCLE PRINCIPAL
# -------------------------------
cargar_config
while true; do
    mostrar_menu
    read -p "Opción: " opcion
    ultima_carpeta=""
    case $opcion in
        1) ultima_carpeta=$(respaldo_general) ;;
        2) ultima_carpeta=$(respaldo_extensiones) ;;
        3) ultima_carpeta=$(respaldo_unidad_externa) ;;
        4) ultima_carpeta=$(respaldo_xampp) ;;
        5) ultima_carpeta=$(respaldo_disco_recuperado) ;;
        6) modo_red ;;
        7) eliminar_respaldos ;;
        8) 
            read -p "Nueva ruta base (ej. /media/usb o $HOME/Respaldos): " nueva
            if [[ -n "$nueva" ]]; then
                destino_base="$nueva"
                mkdir -p "$destino_base"
                guardar_config
                log_info "Destino cambiado a $destino_base"
            fi
            ;;
        9) 
            comprimir_auto=$([ "$comprimir_auto" = "true" ] && echo "false" || echo "true")
            guardar_config
            log_info "Compresión automática ahora: $comprimir_auto"
            ;;
        10) 
            if [[ -f "$REGISTRO_FILE" ]]; then
                less "$REGISTRO_FILE"
            else
                echo "No hay registro aún."
                read -p "Presiona ENTER..."
            fi
            ;;
        11) echo "Saliendo..."; exit 0 ;;
        *) echo "Opción inválida"; sleep 1 ;;
    esac
    if [[ -n "$ultima_carpeta" && "$comprimir_auto" == "true" ]]; then
        comprimir_respaldo "$ultima_carpeta"
    fi
    if [[ "$opcion" != "6" && "$opcion" != "10" && "$opcion" != "11" && -z "$ultima_carpeta" ]]; then
        read -p "Presiona ENTER para continuar..."
    fi
done