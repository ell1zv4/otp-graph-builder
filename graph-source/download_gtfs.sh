#!/bin/bash

set -e

API_KEY="TU_API_KEY_AQUI"

# Carpeta donde guardar los feeds
OUTPUT_DIR="./graph-source"
mkdir -p "$OUTPUT_DIR"

download_and_rename () {
  local url=$1
  local output_name=$2

  echo "⬇️ Descargando $output_name..."

  # Descarga a archivo temporal
  tmp_file=$(mktemp)

  curl -L \
    -H "apikey: $API_KEY" \
    "$url" \
    -o "$tmp_file"

  # Validar que es un zip (muy importante)
  if file "$tmp_file" | grep -q "Zip archive"; then
    mv "$tmp_file" "$OUTPUT_DIR/$output_name"
    echo "✅ Guardado como $output_name"
  else
    echo "❌ ERROR: $output_name no es un ZIP válido"
    rm "$tmp_file"
    exit 1
  fi
}

# ===== DESCARGAS =====

download_and_rename "https://nap.transportes.gob.es/api/Fichero/download/1130" "1130.zip"
download_and_rename "https://nap.transportes.gob.es/api/Fichero/download/1262" "1262.zip"
download_and_rename "https://nap.transportes.gob.es/api/Fichero/download/1267" "1267.zip"

echo "🎉 Todos los GTFS descargados correctamente"
