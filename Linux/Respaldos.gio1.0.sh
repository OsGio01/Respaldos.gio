#!/bin/bash

clear
usuario=$(whoami)

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

menu_destino() {
    echo "Selecciona dónde quieres guardar los respaldos:"
    echo "0) Carpeta actual ($(pwd))"

    for i in "${!puntos_montaje[@]}"; do
        echo "$((i+1))) ${nombres_memorias[$i]} - ${puntos_montaje[$i]}"
    done
    echo "$(( ${#puntos_montaje[@]} + 1 )) ) Otra ruta manual"

    read -p "Ingresa el número de opción: " opcion

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
                echo "La ruta no existe, intentando crear..."
                mkdir -p "$destino" || { echo "No se pudo crear la ruta."; exit 1; }
            fi
            nombre_memoria=""
        else
            echo "Opción inválida."
            exit 1
        fi
    else
        echo "Opción inválida."
        exit 1
    fi
}

crear_carpeta_respaldo() {
    fecha=$(date +"%Y-%m-%d_%H-%M-%S")
    if [[ -n "$nombre_memoria" ]]; then
        carpeta="$destino/Respaldo_${nombre_memoria}_$fecha"
    else
        carpeta="$destino/Respaldo_$fecha"
    fi
    mkdir -p "$carpeta" || { echo "Error creando carpeta de respaldo"; exit 1; }
}

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
            echo "Respaldando $carpeta..."
            cp -r "$carpeta" "$carpeta_respaldo"
        else
            echo "No existe $carpeta, se omite."
        fi
    done
    echo "Respaldo general completado."
}

respaldo_extensiones() {
    extensiones=("pdf" "docx" "xlsx" "pptx" "txt" "jpg" "png" "mp4" "mp3" "zip" "rar")
    for ext in "${extensiones[@]}"; do
        mkdir -p "$carpeta_respaldo/$ext"
        find "$HOME" -type f -iname "*.$ext" 2>/dev/null | while read -r archivo; do
            cp "$archivo" "$carpeta_respaldo/$ext/"
        done
    done
    echo "Respaldo por extensiones finalizado."
}

respaldo_xampp() {
    ruta="$HOME/xampp/htdocs"
    if [[ -d "$ruta" ]]; then
        echo "Respaldando carpeta XAMPP..."
        cp -r "$ruta" "$carpeta_respaldo/htdocs"
        echo "Respaldo XAMPP completado."
    else
        echo "No existe la carpeta $ruta, se omite."
    fi
}

respaldo_memorias_usb() {
    if [[ ${#puntos_montaje[@]} -eq 0 ]]; then
        echo "No se detectaron memorias USB montadas."
        return
    fi

    echo "Memorias USB detectadas:"
    for i in "${!puntos_montaje[@]}"; do
        echo "$((i+1))) ${nombres_memorias[$i]} - ${puntos_montaje[$i]}"
    done

    read -p "Escribe los números de memorias a respaldar separados por espacios (ejemplo: 1 3): " seleccion

    # Convertir entrada en array
    IFS=' ' read -r -a indices <<< "$seleccion"

    for idx_str in "${indices[@]}"; do
        if [[ "$idx_str" =~ ^[0-9]+$ ]]; then
            idx=$((idx_str - 1))
            if [[ $idx -ge 0 && $idx -lt ${#puntos_montaje[@]} ]]; then
                origen="${puntos_montaje[$idx]}"
                nombre="${nombres_memorias[$idx]}"
                destino_memoria="$carpeta_respaldo/Memoria_${nombre}"
                echo "Respaldando $origen en $destino_memoria ..."
                mkdir -p "$destino_memoria"
                cp -r "$origen/"* "$destino_memoria/" 2>/dev/null
            else
                echo "Número $idx_str fuera de rango, se omite."
            fi
        else
            echo "'$idx_str' no es un número válido, se omite."
        fi
    done

    echo "Respaldo de memorias USB completado."
}

eliminar_respaldos() {
    respaldos=("$destino"/Respaldo_*)
    if [[ ${#respaldos[@]} -eq 0 ]]; then
        echo "No hay respaldos para eliminar."
        return
    fi
    echo "Respaldos disponibles:"
    for i in "${!respaldos[@]}"; do
        echo "$((i+1))) ${respaldos[$i]}"
    done
    read -p "Ingresa el número del respaldo a eliminar o 'todos': " sel
    if [[ "$sel" == "todos" ]]; then
        rm -rf "$destino"/Respaldo_*
        echo "Todos los respaldos eliminados."
    elif [[ "$sel" =~ ^[0-9]+$ ]]; then
        idx=$((sel - 1))
        if [[ $idx -ge 0 && $idx -lt ${#respaldos[@]} ]]; then
            rm -rf "${respaldos[$idx]}"
            echo "Eliminado respaldo: ${respaldos[$idx]}"
        else
            echo "Selección inválida."
        fi
    else
        echo "Entrada inválida."
    fi
}

mostrar_menu() {
    echo "====== MENÚ RESPALDOS ======"
    echo "1) Respaldo general"
    echo "2) Respaldo por extensiones"
    echo "3) Respaldar memorias USB montadas"
    echo "4) Respaldo carpeta XAMPP"
    echo "5) Eliminar respaldos anteriores"
    echo "6) Salir"
    echo "==========================="
}

# Inicio del script
detectar_memorias
menu_destino
crear_carpeta_respaldo
carpeta_respaldo="$carpeta"

while true; do
    clear
    mostrar_menu
    read -p "Selecciona una opción: " opcion_menu
    case $opcion_menu in
        1)
            respaldo_general
            read -p "Presiona Enter para continuar..."
            ;;
        2)
            respaldo_extensiones
            read -p "Presiona Enter para continuar..."
            ;;
        3)
            respaldo_memorias_usb
            read -p "Presiona Enter para continuar..."
            ;;
        4)
            respaldo_xampp
            read -p "Presiona Enter para continuar..."
            ;;
        5)
            eliminar_respaldos
            read -p "Presiona Enter para continuar..."
            ;;
        6)
            echo "Saliendo..."
            exit 0
            ;;
        *)
            echo "Opción inválida."
            read -p "Presiona Enter para continuar..."
            ;;
    esac
done
