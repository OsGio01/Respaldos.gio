#!/bin/bash
# Respaldos.Gio - atajo de doble clic para macOS.
# Finder ejecuta este archivo con Terminal; el script real es respaldos.sh.

cd "$(dirname "$0")" || exit 1
bash respaldos.sh "$@"

echo ""
printf "Presiona Enter para cerrar."
read -r _

