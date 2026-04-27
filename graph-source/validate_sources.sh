#!/usr/bin/env bash
set -e

echo "=============================="
echo "🔍 VALIDANDO DESCARGAS"
echo "=============================="

cd graph-source

echo ""
echo "📦 LISTADO DE ARCHIVOS:"
ls -lh

echo ""
echo "=============================="
echo "📄 VALIDACIÓN DE ARCHIVOS BASE"
echo "=============================="

for f in *.zip; do
  echo ""
  echo "➡️  ZIP: $f"

  if [ ! -s "$f" ]; then
    echo "❌ ERROR: archivo vacío"
    exit 1
  fi

  size=$(stat -c%s "$f")
  echo "📏 Tamaño: $size bytes"

  if [ "$size" -lt 5000 ]; then
    echo "❌ ERROR: ZIP demasiado pequeño → probable descarga rota"
    exit 1
  fi

  echo "📦 Contenido del ZIP:"
  unzip -l "$f" | head -20

  if ! unzip -l "$f" | grep -q "stops.txt"; then
    echo "❌ ERROR: no contiene stops.txt → NO es GTFS válido"
    exit 1
  fi

  echo "✅ GTFS OK básico"
done

echo ""
echo "=============================="
echo "🗺️ VALIDACIÓN OSM"
echo "=============================="

for f in *.pbf *.osm.pbf; do
  if [ -f "$f" ]; then
    echo ""
    echo "➡️ OSM: $f"

    size=$(stat -c%s "$f")
    echo "📏 Tamaño: $size bytes"

    if [ "$size" -lt 1000000 ]; then
      echo "❌ ERROR: OSM demasiado pequeño → probablemente corrupto"
      exit 1
    fi

    file "$f"
    echo "✅ OSM OK básico"
  fi
done

echo ""
echo "=============================="
echo "🎯 RESULTADO FINAL"
echo "=============================="

echo "✅ Todo parece descargado correctamente"
echo "⚠️ Esto NO valida routing, solo integridad de archivos"
