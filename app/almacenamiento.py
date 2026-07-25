"""Guardado de capturas en disco y registro append-only.

Estructura generada en la raiz del proyecto:

    capturas/
        2026-07-25_183042_LABLENS_DOC_a4vertical.jpg   <- documento enderezado
        originales/<mismo nombre>.jpg                  <- foto tal como salio de la camara
        registro.jsonl                                 <- una linea JSON por captura
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from .integraciones import Captura

RAIZ = Path(__file__).resolve().parent.parent
DIR_CAPTURAS = RAIZ / "capturas"
DIR_ORIGINALES = DIR_CAPTURAS / "originales"
DIR_DIAGNOSTICO = DIR_CAPTURAS / "diagnostico"
REGISTRO = DIR_CAPTURAS / "registro.jsonl"


def asegurar_directorios() -> None:
    DIR_ORIGINALES.mkdir(parents=True, exist_ok=True)
    DIR_DIAGNOSTICO.mkdir(parents=True, exist_ok=True)


def _nombre_archivo(momento: datetime, formato: str, sufijo: str) -> str:
    formato_limpio = formato.replace("_", "")
    return (
        f"{momento:%Y-%m-%d_%H%M%S}_LABLENS_DOC_{formato_limpio}_{sufijo}.jpg"
    )


def guardar_captura(
    jpeg_plano: bytes,
    jpeg_original: bytes,
    ancho: int,
    alto: int,
    formato: str,
    modo: str,
    quad: list[list[float]],
) -> Captura:
    """Escribe ambas imagenes, anota el registro y devuelve la Captura."""
    asegurar_directorios()
    momento = datetime.now()
    sufijo = uuid.uuid4().hex[:6]
    nombre = _nombre_archivo(momento, formato, sufijo)

    ruta = DIR_CAPTURAS / nombre
    ruta_original = DIR_ORIGINALES / nombre
    ruta.write_bytes(jpeg_plano)
    ruta_original.write_bytes(jpeg_original)

    captura = Captura(
        id=f"{momento:%Y%m%d%H%M%S}-{sufijo}",
        ruta=ruta,
        ruta_original=ruta_original,
        ancho=ancho,
        alto=alto,
        formato=formato,
        modo=modo,
        quad=quad,
        creado_en=momento.isoformat(timespec="seconds"),
    )

    with REGISTRO.open("a", encoding="utf-8") as archivo:
        archivo.write(json.dumps(captura.resumen(), ensure_ascii=False) + "\n")

    return captura


def listar_capturas(limite: int = 30) -> list[dict]:
    """Ultimas capturas registradas, de la mas reciente a la mas antigua."""
    if not REGISTRO.exists():
        return []
    lineas = REGISTRO.read_text(encoding="utf-8").splitlines()
    salida = []
    for linea in reversed(lineas):
        linea = linea.strip()
        if not linea:
            continue
        try:
            salida.append(json.loads(linea))
        except json.JSONDecodeError:
            continue
        if len(salida) >= limite:
            break
    return salida
