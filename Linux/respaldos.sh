#!/bin/bash
# Respaldos.Gio - version minima de terminal (sin Python).
# Respaldo general, reanudar y eliminar. Sin modo red, sin deduplicacion por
# hash, sin extensiones y sin interfaz grafica: es la version portatil para
# equipos donde no hay Python instalado.
#
# Los scripts de Linux (Linux/respaldos.sh) y macOS (macOS/respaldos.sh) son
# casi iguales a windows/Respaldos.gio.ps1: si cambias uno, cambia los otros.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_FILE="$SCRIPT_DIR/respaldos.conf"
STATE_FILE="$SCRIPT_DIR/respaldos.estado"
FUENTES_FILE="$SCRIPT_DIR/respaldos.fuentes.tmp"

VERDE="\033[32m"
AMARILLO="\033[33m"
ROJO="\033[31m"
CIAN="\033[36m"
GRIS="\033[90m"
RESET="\033[0m"

titulo() { printf "\n${CIAN}=== %s ===${RESET}\n" "$1"; }
info()   { printf "%s\n" "$1"; }
aviso()  { printf "${AMARILLO}%s${RESET}\n" "$1"; }
error()  { printf "${ROJO}%s${RESET}\n" "$1"; }

# ---------------------------------------------------------------- configuracion
leer_destino() {
    local destino="$SCRIPT_DIR/Respaldos"
    if [ -f "$CONF_FILE" ]; then
        while IFS= read -r linea; do
            case "$linea" in
                DESTINO=*) destino="${linea#DESTINO=}" ;;
            esac
        done < "$CONF_FILE"
    fi
    printf "%s" "$destino"
}

guardar_destino() {
    printf '# Respaldos.Gio - configuracion minima\nDESTINO=%s\n' "$1" > "$CONF_FILE"
}

# ---------------------------------------------------------------- carpetas
_agregar() {
    if [ -n "${2:-}" ] && [ -d "$2" ]; then
        printf "%s|%s\n" "$1" "$2"
    fi
}

_xdg() {
    local valor
    valor="$(grep "^$1=" "$HOME/.config/user-dirs.dirs" 2>/dev/null | head -n 1 | cut -d= -f2- | tr -d '"')"
    valor="${valor//\$HOME/$HOME}"
    printf "%s" "$valor"
}

# Imprime una linea por carpeta: "Etiqueta|ruta"
# Si esta definida RESPALDOS_GIO_FUENTES se usa esa lista en lugar de detectar
# las carpetas del usuario. Formato: "Etiqueta|ruta;Etiqueta|ruta"
carpetas_usuario() {
    if [ -n "${RESPALDOS_GIO_FUENTES:-}" ]; then
        printf '%s\n' "$RESPALDOS_GIO_FUENTES" | tr ';' '\n'
        return 0
    fi
    local base="$HOME"
    if [ -f "$HOME/.config/user-dirs.dirs" ]; then
        _agregar "Documentos" "$(_xdg XDG_DOCUMENTS_DIR)"
        _agregar "Escritorio" "$(_xdg XDG_DESKTOP_DIR)"
        _agregar "Descargas" "$(_xdg XDG_DOWNLOAD_DIR)"
        _agregar "Imagenes" "$(_xdg XDG_PICTURES_DIR)"
        _agregar "Musica" "$(_xdg XDG_MUSIC_DIR)"
        _agregar "Videos" "$(_xdg XDG_VIDEOS_DIR)"
    else
        _agregar "Documentos" "$base/Documents"
        _agregar "Escritorio" "$base/Desktop"
        _agregar "Descargas" "$base/Downloads"
        _agregar "Imagenes" "$base/Pictures"
        _agregar "Musica" "$base/Music"
        _agregar "Videos" "$base/Videos"
    fi
}

# ---------------------------------------------------------------- estado
leer_carpeta_estado() { grep -m1 '^CARPETA=' "$STATE_FILE" 2>/dev/null | cut -d= -f2-; }
leer_fuentes_estado() { grep '^FUENTE=' "$STATE_FILE" 2>/dev/null | cut -d= -f2-; }

# Reescribe el estado conservando las copias ya hechas.
escribir_estado() {
    local carpeta="$1"
    {
        printf '# Respaldos.Gio - estado de reanudacion\n'
        printf 'CARPETA=%s\n' "$carpeta"
        grep '^FUENTE=' "$STATE_FILE" 2>/dev/null || true
        grep '^COPIA=' "$STATE_FILE" 2>/dev/null || true
    } > "$STATE_FILE.tmp"
    mv "$STATE_FILE.tmp" "$STATE_FILE"
}

agregar_copia() {
    printf 'COPIA=%s\n' "$1" >> "$STATE_FILE"
}

ya_copiada() {
    grep -Fxq "COPIA=$1" "$STATE_FILE" 2>/dev/null
}

# ---------------------------------------------------------------- copia
copiar_arbol() {
    local destino_carpeta="$1"
    local total=0 hechos=0
    local fuente etiqueta raiz origen rel clave destino

    # 1) contar lo que falta
    while IFS= read -r fuente; do
        [ -z "$fuente" ] && continue
        etiqueta="${fuente%%|*}"
        raiz="${fuente#*|}"
        [ -d "$raiz" ] || continue
        while IFS= read -r -d '' origen; do
            rel="${origen#"$raiz"/}"
            clave="$etiqueta/$rel"
            ya_copiada "$clave" && continue
            total=$((total + 1))
        done < <(find "$raiz" -type f -print0 2>/dev/null)
    done < "$FUENTES_FILE"

    if [ "$total" -eq 0 ]; then
        info "No hay archivos pendientes por copiar."
        return 0
    fi
    info "Archivos a copiar: $total"

    # 2) copiar
    while IFS= read -r fuente; do
        [ -z "$fuente" ] && continue
        etiqueta="${fuente%%|*}"
        raiz="${fuente#*|}"
        [ -d "$raiz" ] || continue
        while IFS= read -r -d '' origen; do
            rel="${origen#"$raiz"/}"
            clave="$etiqueta/$rel"
            ya_copiada "$clave" && continue
            destino="$destino_carpeta/$etiqueta/$rel"
            mkdir -p "$(dirname "$destino")"
            cp -p "$origen" "$destino" 2>/dev/null || cp "$origen" "$destino"
            agregar_copia "$clave"
            hechos=$((hechos + 1))
            if [ $((hechos % 25)) -eq 0 ] || [ "$hechos" -eq "$total" ]; then
                printf "${GRIS}  %s/%s archivos${RESET}\n" "$hechos" "$total"
            fi
        done < <(find "$raiz" -type f -print0 2>/dev/null)
    done < "$FUENTES_FILE"
}

comprimir_respaldo() {
    local carpeta="$1"
    if ! command -v zip >/dev/null 2>&1; then
        aviso "No hay herramienta zip; se deja la carpeta sin comprimir."
        return 0
    fi
    info "Comprimiendo en $(basename "$carpeta").zip ..."
    if (cd "$(dirname "$carpeta")" && zip -qr "$(basename "$carpeta").zip" "$(basename "$carpeta")" 2>/dev/null); then
        rm -rf "$carpeta"
        info "Listo: $carpeta.zip"
    else
        aviso "No se pudo comprimir; se deja la carpeta sin comprimir."
    fi
}

# ---------------------------------------------------------------- acciones
respaldo_general() {
    titulo "Respaldo general"
    local destino respuesta compactar sello carpeta
    destino="$(leer_destino)"
    info "Destino actual: $destino"
    printf "Destino (Enter para usar el actual): "
    read -r respuesta
    if [ -n "$respuesta" ]; then
        destino="$respuesta"
    fi
    mkdir -p "$destino"
    guardar_destino "$destino"

    Carpetas-Usuario-Archivo
    if [ ! -s "$FUENTES_FILE" ]; then
        error "No se encontraron carpetas de usuario."
        return 0
    fi
    info "Carpetas a respaldar:"
    while IFS= read -r linea; do
        [ -z "$linea" ] && continue
        info "  - ${linea%%|*} : ${linea#*|}"
    done < "$FUENTES_FILE"

    printf "¿Comprimir en .zip al terminar? (s/n): "
    read -r compactar

    sello="$(date +%Y%m%d-%H%M%S)"
    carpeta="$destino/Respaldo_$sello"
    mkdir -p "$carpeta"

    {
        printf '# Respaldos.Gio - estado de reanudacion\n'
        printf 'CARPETA=%s\n' "$(basename "$carpeta")"
        sed 's/^/FUENTE=/' "$FUENTES_FILE"
    } > "$STATE_FILE"

    copiar_arbol "$carpeta"
    escribir_estado "$(basename "$carpeta")"
    rm -f "$STATE_FILE"
    info "Respaldo terminado en $carpeta"
    if [ "$compactar" = "s" ] || [ "$compactar" = "S" ]; then
        comprimir_respaldo "$carpeta"
    fi
}

Carpetas-Usuario-Archivo() {
    : > "$FUENTES_FILE"
    while IFS= read -r linea; do
        [ -z "$linea" ] && continue
        printf "%s\n" "$linea" >> "$FUENTES_FILE"
    done <<< "$(carpetas_usuario)"
}

reanudar_respaldo() {
    titulo "Reanudar respaldo interrumpido"
    local carpeta_destino destino carpeta compactar
    if [ ! -f "$STATE_FILE" ]; then
        aviso "No hay ningún respaldo interrumpido."
        return 0
    fi
    carpeta_destino="$(leer_carpeta_estado)"
    if [ -z "$carpeta_destino" ]; then
        aviso "No hay ningún respaldo interrumpido."
        return 0
    fi
    destino="$(leer_destino)"
    carpeta="$destino/$carpeta_destino"
    if [ ! -d "$carpeta" ]; then
        aviso "La carpeta del respaldo ya no existe."
        return 0
    fi

    info "Respaldo: $carpeta_destino"
    info "Archivos ya copiados: $(grep -c '^COPIA=' "$STATE_FILE" 2>/dev/null || echo 0)"

    printf "¿Comprimir en .zip al terminar? (s/n): "
    read -r compactar

    grep '^FUENTE=' "$STATE_FILE" | cut -d= -f2- > "$FUENTES_FILE"
    copiar_arbol "$carpeta"
    escribir_estado "$carpeta_destino"
    rm -f "$STATE_FILE"
    rm -f "$FUENTES_FILE"
    info "Respaldo terminado en $carpeta"
    if [ "$compactar" = "s" ] || [ "$compactar" = "S" ]; then
        comprimir_respaldo "$carpeta"
    fi
}

eliminar_respaldo() {
    titulo "Eliminar respaldo"
    local destino opcion objetivo confirmacion i
    destino="$(leer_destino)"
    if [ ! -d "$destino" ]; then
        aviso "No hay respaldos en $destino"
        return 0
    fi
    local lista
    lista="$(find "$destino" -maxdepth 1 -type d -name 'Respaldo_*' 2>/dev/null | sort -r)"
    if [ -z "$lista" ]; then
        aviso "No hay respaldos en $destino"
        return 0
    fi
    info "Respaldos disponibles:"
    i=1
    while IFS= read -r carpeta; do
        [ -z "$carpeta" ] && continue
        info "  $i) $(basename "$carpeta")"
        i=$((i + 1))
    done <<< "$lista"

    printf "Número del respaldo a eliminar (0 para salir): "
    read -r opcion
    case "$opcion" in
        ''|*[!0-9]*) aviso "Opción no válida."; return 0 ;;
    esac
    if [ "$opcion" -lt 1 ]; then
        info "Cancelado."
        return 0
    fi
    objetivo="$(printf '%s\n' "$lista" | sed -n "${opcion}p")"
    if [ -z "$objetivo" ]; then
        aviso "Opción no válida."
        return 0
    fi
    aviso "Se va a eliminar: $objetivo"
    printf "Escribe BORRAR para confirmar: "
    read -r confirmacion
    if [ "$confirmacion" != "BORRAR" ]; then
        info "Cancelado."
        return 0
    fi
    rm -rf "$objetivo"
    rm -f "$objetivo.zip"
    info "Eliminado."
}

# ---------------------------------------------------------------- menu
menu() {
    local opcion
    while true; do
        printf "\n${VERDE}  RESPALDOS.GIO - versión mínima de terminal${RESET}\n"
        printf "  1) Respaldo general\n"
        printf "  2) Reanudar respaldo interrumpido\n"
        printf "  3) Eliminar respaldo\n"
        printf "  4) Salir\n"
        printf "Opción: "
        read -r opcion
        case "$opcion" in
            1) respaldo_general ;;
            2) reanudar_respaldo ;;
            3) eliminar_respaldo ;;
            4) break ;;
            *) aviso "Opción no válida." ;;
        esac
    done
}

menu
info "Hasta pronto."
