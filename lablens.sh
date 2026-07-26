#!/usr/bin/env bash
# Arranque de LabLens en macOS y Linux.
#
#     bash lablens.sh            # prepara el entorno y arranca
#     bash lablens.sh --http     # las opciones pasan a servidor.py
#
# El trabajo real lo hace iniciar.py; esto solo encuentra un Python valido.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON=""
for candidato in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidato" >/dev/null 2>&1; then
        if "$candidato" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON="$candidato"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo ""
    echo "  No se encontro Python 3.10 o mas nuevo en este equipo."
    echo ""
    echo "  macOS:          brew install python@3.12"
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv"
    echo ""
    exit 1
fi

exec "$PYTHON" iniciar.py "$@"
